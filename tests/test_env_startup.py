import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from confluence_mcp import settings_file


@pytest.fixture
def project_process(tmp_path):
    def run(config_text):
        run_dir = Path(tempfile.mkdtemp(prefix="project-env-", dir=tmp_path))
        project = run_dir / "project"
        source_root = project / "src"
        shutil.copytree(
            Path(settings_file.__file__).resolve().parent,
            source_root / "confluence_mcp",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*", "*.db*", "*.log"),
        )
        config_path = project / ".env"
        if config_text is not None:
            config_path.write_text(config_text, encoding="utf-8")

        other_cwd = run_dir / "other"
        other_cwd.mkdir()
        (other_cwd / ".env").write_text("CONFLUENCE_ENABLE_WRITES=true\n", encoding="utf-8")
        legacy_file = run_dir / "legacy.env"
        legacy_file.write_text("CONFLUENCE_ENABLE_WRITES=true\n", encoding="utf-8")

        env = os.environ.copy()
        env.pop("ATLASSIAN_CONFLUENCE_PAT", None)
        env.update({
            "CONFLUENCE_MCP_ENV_FILE": str(legacy_file),
            "CONFLUENCE_ENABLE_WRITES": "true",
            "PYTHONPATH": str(source_root),
            "PYTHONIOENCODING": "utf-8",
        })
        program = (
            "import asyncio, json, sys\n"
            "from pathlib import Path\n"
            "from confluence_mcp import server\n"
            "tools = sorted(t.name for t in asyncio.run(server.mcp.list_tools()))\n"
            "before = server.writes_enabled()\n"
            "Path(sys.argv[1]).write_text('CONFLUENCE_ENABLE_WRITES=' + "
            "('false' if before else 'true'), encoding='utf-8')\n"
            "print(json.dumps({'tools': tools, 'enabled_after_change': server.writes_enabled()}))\n"
        )
        return subprocess.run(
            [sys.executable, "-c", program, str(config_path)],
            cwd=other_cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    return run


@pytest.mark.parametrize("enabled", [False, True])
def test_startup_uses_project_env_from_unrelated_cwd(project_process, enabled):
    result = project_process(f"CONFLUENCE_ENABLE_WRITES={str(enabled).lower()}\n")
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert ("create_page" in actual["tools"]) is enabled
    assert actual["enabled_after_change"] is enabled


def test_missing_project_env_cannot_use_inherited_write_flag(project_process):
    result = project_process(None)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert "create_page" not in actual["tools"]
    assert actual["enabled_after_change"] is False


@pytest.mark.parametrize("file_pat", [None, "file#token=="])
def test_pat_is_read_only_from_project_file_in_a_fresh_process(tmp_path, file_pat):
    project = tmp_path / "project"
    source_root = project / "src"
    shutil.copytree(
        Path(settings_file.__file__).resolve().parent,
        source_root / "confluence_mcp",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*"),
    )
    config = "ATLASSIAN_CONFLUENCE_URL=https://wiki.example.invalid/confluence\n"
    if file_pat is not None:
        config += f"ATLASSIAN_CONFLUENCE_PAT={file_pat}\n"
    (project / ".env").write_text(config, encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("ATLASSIAN_CONFLUENCE_PAT=cwd-token\n", encoding="utf-8")
    legacy = tmp_path / "legacy.env"
    legacy.write_text("ATLASSIAN_CONFLUENCE_PAT=legacy-token\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "ATLASSIAN_CONFLUENCE_PAT": "process-token",
        "CONFLUENCE_MCP_ENV_FILE": str(legacy),
        "PYTHONPATH": str(source_root),
    })
    program = (
        "import json, sys, types\n"
        "keyring = types.ModuleType('keyring')\n"
        "keyring.get_password = lambda *_: 'stored-token'\n"
        "sys.modules['keyring'] = keyring\n"
        "from confluence_mcp.client import ConfluenceConfigurationError, ConfluenceSettings\n"
        "try:\n"
        "    settings = ConfluenceSettings.from_environment()\n"
        "    result = {'file_token': settings.pat == 'file#token==', 'missing': False}\n"
        "except ConfluenceConfigurationError:\n"
        "    result = {'file_token': False, 'missing': True}\n"
        "print(json.dumps(result))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=other,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"file_token": file_pat is not None, "missing": file_pat is None}
