#!/bin/zsh

set -euo pipefail

APP_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
DATA_DIR="${2:-$HOME/Library/Application Support/xiangzhongjing}"
MODE="${3:-}"
DB_PATH="$DATA_DIR/xiangzhongjing.db"
BASELINE_PATH="$APP_DIR/deployment-baseline.json"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
PORT="${XIANGZHONGJING_PORT:-$(sed -n 's/^PORT=//p' "$APP_DIR/.env" 2>/dev/null | tail -1 | tr -d '\r')}"
PORT="${PORT:-8860}"

fail() {
  print -u2 "验收失败：$1"
  exit 1
}

[[ -f "$DB_PATH" ]] || fail "缺少数据库 $DB_PATH"
[[ -f "$BASELINE_PATH" ]] || fail "缺少 deployment-baseline.json"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="$(command -v python3 || true)"
[[ -n "$PYTHON_BIN" ]] || fail "未找到 Python 3"

APP_DIR="$APP_DIR" DATA_DIR="$DATA_DIR" DB_PATH="$DB_PATH" BASELINE_PATH="$BASELINE_PATH" "$PYTHON_BIN" - <<'PY'
import hashlib
import json
import os
import sqlite3
from pathlib import Path

db_path = Path(os.environ["DB_PATH"])
data_dir = Path(os.environ["DATA_DIR"])
app_dir = Path(os.environ["APP_DIR"]).resolve()
baseline = json.loads(Path(os.environ["BASELINE_PATH"]).read_text(encoding="utf-8"))

connection = sqlite3.connect(db_path)
connection.row_factory = sqlite3.Row
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
assert integrity == "ok", f"SQLite integrity_check={integrity}"

counts = {}
for table in baseline["table_counts"]:
    counts[table] = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
assert counts == baseline["table_counts"], f"表计数不一致：{counts}"

state = json.loads(connection.execute("SELECT state_json FROM app_state WHERE id = 1").fetchone()[0])
state_counts = {
    "projects": len(state.get("projects", [])),
    "diary_entries": len(state.get("diaryEntries", [])),
    "inspiration_draws": len(state.get("inspirationDraws", [])),
    "versions": len(state.get("versions", [])),
}
assert state_counts == baseline["state_counts"], f"工作区计数不一致：{state_counts}"

published = connection.execute(
    "SELECT version FROM style_skill_versions WHERE status = 'published' ORDER BY id DESC LIMIT 1"
).fetchone()
assert published and published[0] == baseline["published_skill_version"], "发布 Skill 版本不一致"

ready_quotes = connection.execute(
    "SELECT COUNT(*) FROM book_citations WHERE material_type='direct_quote' AND quality_status='valid'"
).fetchone()[0]
assert ready_quotes == baseline["generation_ready_quotes"], f"可生成直引数量不一致：{ready_quotes}"

for row in connection.execute("SELECT name, source, dir_path FROM skills"):
    expected_root = app_dir / ("product_skills" if row["source"] == "builtin" else "custom_skills")
    path = Path(row["dir_path"]).resolve()
    assert expected_root in path.parents or path == expected_root, f"Skill 路径未迁移：{row['name']}"
    assert (path / "SKILL.md").is_file(), f"Skill 文件缺失：{row['name']}"

actual_assets = {}
for asset_root_name in ("media", "source_documents"):
    asset_root = data_dir / asset_root_name
    if not asset_root.exists():
        continue
    for path in sorted(item for item in asset_root.rglob("*") if item.is_file()):
        relative = str(path.relative_to(data_dir))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        actual_assets[relative] = digest
expected_assets = baseline.get("asset_sha256", baseline.get("media_sha256", {}))
assert actual_assets == expected_assets, "媒体或阅读资料文件缺失、内容不一致"
connection.close()
print(json.dumps({
    "database": "ok",
    "projects": state_counts["projects"],
    "published_skill": baseline["published_skill_version"],
    "generation_ready_quotes": ready_quotes,
    "asset_files": len(actual_assets),
}, ensure_ascii=False))
PY

if [[ "$MODE" != "--offline" ]]; then
  for PATHNAME in \
    "/api/xiangzhongjing/health" \
    "/xiangzhongjing-demo" \
    "/xiangzhongjing-prd"; do
    curl -fsS --max-time 5 "http://127.0.0.1:$PORT$PATHNAME" >/dev/null \
      || fail "页面或接口不可访问：$PATHNAME"
  done
fi

print "验收通过：源码、数据库、Skill、书库和媒体资产一致。"
