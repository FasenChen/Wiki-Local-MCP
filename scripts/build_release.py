"""Build a distributable ZIP from the committed, public source snapshot."""

from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from confluence_mcp.settings_file import parse_env


def _is_private_or_runtime(name: str) -> bool:
    path = PurePosixPath(name)
    parts = {part.casefold() for part in path.parts}
    basename = path.name.casefold()
    if parts & {".git", ".venv", ".superpowers", "__pycache__", ".pytest_cache", "dist", "build"}:
        return True
    if basename.startswith(".env") and name != ".env.example":
        return True
    return basename.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".log"))


def build_release(output: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=zip", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or any(_is_private_or_runtime(name) for name in names):
            raise ValueError("The committed snapshot contains private or runtime files.")
        if not {".env.example", "setup.bat", "setup.command"}.issubset(names):
            raise ValueError("The committed snapshot is missing the template or setup scripts.")
        template = source.read(".env.example")
        for line in template.decode("utf-8-sig").splitlines():
            candidate = line.lstrip()
            if candidate.startswith("#"):
                candidate = candidate[1:].lstrip()
                key, separator, _ = candidate.removeprefix("export ").partition("=")
                if not separator or key.strip() != "ATLASSIAN_CONFLUENCE_PAT":
                    continue
            if parse_env(candidate).get("ATLASSIAN_CONFLUENCE_PAT", "").strip():
                raise ValueError("The configuration template must not contain a PAT.")

        with zipfile.ZipFile(result, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename in {"setup.bat", "setup.command"}:
                    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                    if info.filename == "setup.bat":
                        data = data.replace(b"\n", b"\r\n")
                    else:
                        info.create_system = 3
                        info.external_attr = (0o100755 << 16) | (info.external_attr & 0xFFFF)
                target.writestr(info, data)
            env_info = zipfile.ZipInfo(".env")
            env_info.create_system = 3
            env_info.external_attr = 0o100600 << 16
            target.writestr(env_info, template)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(result.getvalue())


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_release.py <new-zip-path>", file=sys.stderr)
        return 2
    try:
        build_release(Path(sys.argv[1]))
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"Release build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release ZIP created: {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
