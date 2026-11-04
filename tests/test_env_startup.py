import asyncio
import importlib
import os

import confluence_mcp
from confluence_mcp import server, settings_file


def test_env_file_enables_writes_at_startup(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CONFLUENCE_ENABLE_WRITES=true # enable writes\n"
        "CONFLUENCE_WRITE_SPACES=OPS # approved space\n",
        encoding="utf-8",
    )
    # Setting then deleting makes monkeypatch restore both variables after the test.
    for name in ("CONFLUENCE_ENABLE_WRITES", "CONFLUENCE_WRITE_SPACES"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv(settings_file.ENV_FILE_VAR, str(env_file))
    try:
        # Re-running the package __init__ is the real startup path that loads .env.
        importlib.reload(confluence_mcp)
        module = importlib.reload(server)
        assert "create_page" in {t.name for t in asyncio.run(module.mcp.list_tools())}
        assert os.environ["CONFLUENCE_WRITE_SPACES"] == "OPS"
    finally:
        monkeypatch.undo()
        importlib.reload(server)
