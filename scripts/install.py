"""Prepare the local environment and check the configured Wiki connection."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from string import Template

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from confluence_mcp.settings_file import parse_env


def _env_literal(key: str, value: str) -> str:
    if "\n" not in value and "\r" not in value:
        for candidate in (value, f'"{value}"', f"'{value}'"):
            if parse_env(f"{key}={candidate}").get(key) == value:
                return candidate
    raise ValueError("配置值无法安全保存到 .env，请手动编辑。")


def _copy_config_permissions(source: Path, destination: Path) -> None:
    if os.name != "nt":
        os.chmod(destination, source.stat().st_mode & 0o777)
        return

    import ctypes
    from ctypes import wintypes

    security = ctypes.WinDLL("advapi32", use_last_error=True)
    get_security = security.GetNamedSecurityInfoW
    get_security.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security.restype = wintypes.DWORD
    get_control = security.GetSecurityDescriptorControl
    get_control.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    get_control.restype = wintypes.BOOL
    set_security = security.SetNamedSecurityInfoW
    set_security.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    set_security.restype = wintypes.DWORD
    free = ctypes.WinDLL("kernel32").LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p

    file_object = 1
    dacl_information = 0x4
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    error = get_security(
        str(source), file_object, dacl_information, None, None,
        ctypes.byref(dacl), None, ctypes.byref(descriptor),
    )
    if error:
        raise ctypes.WinError(error)
    try:
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Keep the original DACL and its inheritance setting before writing the PAT.
        inheritance = 0x80000000 if control.value & 0x1000 else 0x20000000
        error = set_security(
            str(destination), file_object, dacl_information | inheritance, None, None, dacl, None,
        )
        if error:
            raise ctypes.WinError(error)
    finally:
        free(descriptor)


def _save_configuration(path: Path, original: bytes, changes: dict[str, str]) -> None:
    text = original.decode("utf-8-sig")
    literals = {key: _env_literal(key, value) for key, value in changes.items()}
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        prefix, separator, _ = line.partition("=")
        key = prefix.strip()
        if key.startswith("export "):
            key = key[len("export "):].lstrip()
        if separator and not key.startswith("#") and key in literals:
            ending = line[len(line.rstrip("\r\n")) :]
            line = f"{prefix}={literals[key]}{ending}"
            seen.add(key)
        lines.append(line)
    result = "".join(lines)
    newline = "\r\n" if "\r\n" in text else "\n"
    for key in literals:
        if key in seen:
            continue
        if result and not result.endswith(("\n", "\r")):
            result += newline
        result += f"{key}={literals[key]}{newline}"
    data = result.encode("utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".env.", delete=False) as handle:
            temporary = Path(handle.name)
        _copy_config_permissions(path, temporary)
        temporary.write_bytes(data)
        if path.read_bytes() != original:
            raise ValueError("配置文件在输入期间发生变化，请重新运行安装。")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ensure_configuration(root: Path, *, edit: bool = False) -> bool:
    path = (root / ".env").resolve()
    if not path.exists():
        try:
            template = (root / ".env.example").read_text(encoding="utf-8-sig")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(template)
        except FileExistsError:
            pass
        except (OSError, ValueError):
            print("无法创建配置文件，请检查 .env.example 和目录权限。", file=sys.stderr)
            return False

    try:
        original = path.read_bytes()
        values = parse_env(original.decode("utf-8-sig"))
        url = values.get("ATLASSIAN_CONFLUENCE_URL", "").strip()
        pat = values.get("ATLASSIAN_CONFLUENCE_PAT", "").strip()
        print("====== 更新配置 ======" if edit else "====== Wiki 连接配置 ======", flush=True)
        new_url = input("Wiki 地址（已配置，回车保留）：" if url else "Wiki 地址（必填）：").strip() or url
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            new_pat = getpass.getpass(
                "PAT（已配置，回车保留；输入不显示）：" if pat else "PAT（必填，输入不显示）："
            ).strip() or pat
        if not new_url or not new_pat:
            print("缺少地址或 PAT，未修改配置。", file=sys.stderr)
            return False
        changes = {}
        if new_url != url:
            changes["ATLASSIAN_CONFLUENCE_URL"] = new_url
        if new_pat != pat:
            changes["ATLASSIAN_CONFLUENCE_PAT"] = new_pat
        if changes:
            _save_configuration(path, original, changes)
            print("已更新 .env。")
        else:
            print("已保留现有配置。")
        return True
    except getpass.GetPassWarning:
        print("当前终端无法隐藏 PAT 输入，请在系统终端中重新运行。", file=sys.stderr)
    except (OSError, UnicodeError, ValueError, EOFError, KeyboardInterrupt):
        print("无法读取、输入或保存配置，请检查 .env 和项目目录。", file=sys.stderr)
    return False


def _write_agent_setup(root: Path, venv_python: Path) -> Path:
    command = str(venv_python.absolute())
    config = {"mcpServers": {"wiki-local-mcp": {
        "type": "stdio", "command": command, "args": ["-m", "confluence_mcp.server"],
    }}}
    template = Template((root / "MCP_SETUP.template.md").read_text(encoding="utf-8"))
    document = template.substitute(
        SYSTEM={"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(sys.platform, sys.platform),
        PROJECT_DIR=json.dumps(str(root.resolve()), ensure_ascii=False),
        MCP_CONFIG=json.dumps(config, ensure_ascii=False, indent=2),
        PYTHON_COMMAND=json.dumps(command, ensure_ascii=False),
    )
    output = root / "MCP_SETUP.md"
    output.write_text(document, encoding="utf-8", newline="\n")
    return output


def run_install(root: Path) -> int:
    if sys.version_info < (3, 10):
        print("需要 Python 3.10 或更高版本。", file=sys.stderr)
        return 1
    if not ensure_configuration(root):
        return 1

    print("\n====== 环境配置 ======", flush=True)
    child_env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "ATLASSIAN_CONFLUENCE_PAT"):
        child_env.pop(name, None)

    venv = root / ".venv"
    venv_python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not venv.exists():
        print("正在创建虚拟环境，请稍候...", flush=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv)], cwd=root, check=True, env=child_env,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            )
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
        message = "安装依赖中，首次安装可能需要几分钟，请稍候..." if label == "安装依赖" else f"{label}..."
        print(message, flush=True)
        quiet = label in {"检查 pip", "安装依赖"}
        try:
            subprocess.run(
                command, cwd=root, check=True, env=child_env,
                stdout=subprocess.DEVNULL if quiet else None,
                stderr=subprocess.STDOUT if quiet else None,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            if label == "检查 pip":
                print("检查 pip 失败，.venv 可能不完整；请检查或尝试较短路径，脚本不会删除 .venv。", file=sys.stderr)
            elif isinstance(exc, subprocess.CalledProcessError):
                print(f"{label}失败（退出码 {exc.returncode}）。", file=sys.stderr)
            else:
                print(f"{label}无法启动，请检查 Python 和项目路径。", file=sys.stderr)
            return 1
        print(f"{label}完成。")
    try:
        document = _write_agent_setup(root, venv_python)
    except (OSError, ValueError, KeyError):
        print("无法生成 Agent 接入文档，请检查 MCP_SETUP.template.md 和目录权限。", file=sys.stderr)
        return 1
    print(f"请将 {document} 发给 Agent 完成 MCP 配置。")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--edit"]:
        if ensure_configuration(PROJECT_ROOT, edit=True):
            print("配置处理完成，请重启 MCP；可重新运行安装检查。")
            return 0
        return 1
    if sys.argv[1:]:
        print("Usage: install.py [--edit]", file=sys.stderr)
        return 2
    return run_install(PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
