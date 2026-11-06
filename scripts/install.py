"""Prepare the local environment and check the configured Wiki connection."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from confluence_mcp.settings_file import load_env_file


def _configuration_ready(path: Path) -> bool:
    try:
        values = load_env_file(path)
    except (OSError, ValueError):
        return False
    return bool(values.get("ATLASSIAN_CONFLUENCE_URL", "").strip()) and bool(
        values.get("ATLASSIAN_CONFLUENCE_PAT", "").strip()
    )


def ensure_configuration(root: Path, *, edit: bool = False) -> bool:
    path = root / ".env"
    if not path.exists():
        try:
            template = (root / ".env.example").read_text(encoding="utf-8-sig")
            with path.open("x", encoding="utf-8", newline="\n") as output:
                output.write(template)
        except FileExistsError:
            pass
        except (OSError, ValueError):
            print("无法创建配置文件，请检查 .env.example 和目录权限。", file=sys.stderr)
            return False

    if edit or not _configuration_ready(path):
        print("请在打开的 .env 中填写 Wiki 地址和 PAT，保存原文件后返回此窗口。")
        command = ["notepad.exe", str(path)] if sys.platform == "win32" else ["open", "-t", str(path)]
        try:
            subprocess.Popen(command)
            input("保存后按 Enter 继续：")
        except (OSError, EOFError, KeyboardInterrupt):
            print("无法打开或确认配置文件，请检查文本编辑器。", file=sys.stderr)
            return False

    if not _configuration_ready(path):
        print("配置未保存或缺少地址/PAT，请检查项目根目录的 .env。", file=sys.stderr)
        return False
    return True


def run_install(root: Path) -> int:
    if sys.version_info < (3, 10):
        print("需要 Python 3.10 或更高版本。", file=sys.stderr)
        return 1
    if not ensure_configuration(root):
        return 1

    child_env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "ATLASSIAN_CONFLUENCE_PAT"):
        child_env.pop(name, None)

    venv = root / ".venv"
    venv_python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not venv.exists():
        try:
            subprocess.run([sys.executable, "-m", "venv", str(venv)], cwd=root, check=True, env=child_env)
        except (OSError, subprocess.CalledProcessError):
            print("创建虚拟环境失败，请检查 Python 或尝试较短路径；现有 .venv 未自动删除。", file=sys.stderr)
            return 1
    if not venv_python.is_file():
        print("现有虚拟环境不可用；请检查项目目录中的 .venv。", file=sys.stderr)
        return 1

    local_check = (
        "import asyncio\n"
        "from confluence_mcp.server import mcp\n"
        "names = {tool.name for tool in asyncio.run(mcp.list_tools())}\n"
        "assert {'search_pages', 'get_page', 'get_page_by_title'} <= names, 'Required MCP tools are unavailable'\n"
    )
    steps = (
        ("检查 pip", [str(venv_python), "-m", "pip", "--version"]),
        ("安装依赖", [str(venv_python), "-m", "pip", "install", "-c", str(root / "constraints.txt"), "-e", str(root)]),
        ("检查 MCP 工具", [str(venv_python), "-c", local_check]),
        ("检查 Wiki 认证", [str(venv_python), "-m", "confluence_mcp.healthcheck"]),
    )
    for label, command in steps:
        print(f"{label}...", flush=True)
        try:
            subprocess.run(command, cwd=root, check=True, env=child_env)
        except (OSError, subprocess.CalledProcessError) as exc:
            if label == "检查 pip":
                print("检查 pip 失败，.venv 可能不完整；请检查或尝试较短路径，脚本不会删除 .venv。", file=sys.stderr)
            elif isinstance(exc, subprocess.CalledProcessError):
                print(f"{label}失败（退出码 {exc.returncode}）。", file=sys.stderr)
            else:
                print(f"{label}无法启动，请检查 Python 和项目路径。", file=sys.stderr)
            return 1
        print(f"{label}完成。")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--edit"]:
        if ensure_configuration(PROJECT_ROOT, edit=True):
            print("已读取 .env；如有修改，请确认已保存，再重启 MCP。可重新运行安装检查。")
            return 0
        return 1
    if sys.argv[1:]:
        print("Usage: install.py [--edit]", file=sys.stderr)
        return 2
    return run_install(PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
