"""Create a consistent local backup without exposing API keys."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DATA_DIR


def main() -> int:
    output_dir = Path.cwd() / "backups"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"xiangzhongjing-backup-{stamp}.zip"
    database = DATA_DIR / "xiangzhongjing.db"
    with tempfile.TemporaryDirectory() as tmpdir:
        stage = Path(tmpdir)
        if database.exists():
            source = sqlite3.connect(database)
            destination = sqlite3.connect(stage / "xiangzhongjing.db")
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
        media = DATA_DIR / "media"
        if media.exists():
            shutil.copytree(media, stage / "media")
        (stage / "backup.json").write_text(
            json.dumps(
                {
                    "format": "xiangzhongjing-backup-v1",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "contains_api_keys": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in stage.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(stage))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
