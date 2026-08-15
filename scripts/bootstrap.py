"""Cross-platform Community Beta bootstrapper."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="安装并启动匣中镜 Community Beta")
    parser.add_argument("--start", action="store_true", help="安装完成后立即启动 Web 应用")
    parser.add_argument("--skip-tests", action="store_true", help="跳过安装后的核心测试")
    args = parser.parse_args()

    if sys.version_info < (3, 9):
        raise SystemExit("匣中镜需要 Python 3.9 或更高版本")
    if not VENV_DIR.exists():
        print("[1/4] 创建隔离环境 .venv")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    python = str(venv_python())
    print("[2/4] 安装依赖")
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-r", "requirements.txt"])
    env_path = ROOT / ".env"
    if not env_path.exists():
        shutil.copyfile(ROOT / ".env.example", env_path)
        print("[3/4] 已创建 .env，请在设置页或文件中填写模型 API Key")
    else:
        print("[3/4] 保留现有 .env")
    if not args.skip_tests:
        print("[4/4] 验证空白安装核心契约")
        run([python, "-m", "unittest", "tests.test_creator_memory_service", "tests.test_modular_architecture_contract"])
    else:
        print("[4/4] 已跳过测试")

    print("\n安装完成：")
    print("  macOS/Linux: .venv/bin/python main.py")
    print(r"  Windows:     .venv\Scripts\python.exe main.py")
    print("  访问地址:    http://127.0.0.1:8860/xiangzhongjing-demo")
    if args.start:
        os.chdir(ROOT)
        os.execv(python, [python, "main.py"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
