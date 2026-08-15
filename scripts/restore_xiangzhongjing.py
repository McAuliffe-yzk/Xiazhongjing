"""Restore a trusted Xiangzhongjing backup into the local data directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DATA_DIR


def _safe_members(archive: zipfile.ZipFile) -> None:
    for member in archive.infolist():
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"备份包含非法路径：{member.filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description="恢复匣中镜本地备份")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--yes", action="store_true", help="确认覆盖当前本地数据")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("恢复会覆盖当前数据库和媒体。确认已停止服务后，加 --yes 执行。")
    if not args.backup.is_file():
        raise SystemExit("备份文件不存在")
    with tempfile.TemporaryDirectory() as tmpdir:
        stage = Path(tmpdir)
        with zipfile.ZipFile(args.backup) as archive:
            _safe_members(archive)
            archive.extractall(stage)
        manifest_path = stage / "backup.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != "xiangzhongjing-backup-v1":
            raise SystemExit("不是受支持的匣中镜备份")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        database = stage / "xiangzhongjing.db"
        if database.exists():
            shutil.copy2(database, DATA_DIR / "xiangzhongjing.db")
        media = stage / "media"
        if media.exists():
            target_media = DATA_DIR / "media"
            if target_media.exists():
                shutil.rmtree(target_media)
            shutil.copytree(media, target_media)
    print(f"已恢复到 {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
