import json

import pytest

from confluence_mcp import writes
from confluence_mcp.client import ConfluenceConfigurationError


def test_process_env_cannot_enable_writes(config_values, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    assert writes.writes_enabled() is False


def test_process_env_cannot_bypass_space_whitelist(config_values, monkeypatch):
    config_values.update({
        "CONFLUENCE_ENABLE_WRITES": "true",
        "CONFLUENCE_WRITE_SPACES": "OPS",
    })
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    writes.ensure_write_allowed("OPS")
    with pytest.raises(ConfluenceConfigurationError):
        writes.ensure_write_allowed("QA")


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", " true "])
def test_writes_enabled_accepts_truthy_values(monkeypatch, value, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", value)

    assert writes.writes_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no"])
def test_writes_enabled_rejects_falsy_values(monkeypatch, value, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", value)

    assert writes.writes_enabled() is False


def test_ensure_write_allowed_rejects_when_disabled(monkeypatch, config_values):
    monkeypatch.delitem(config_values, "CONFLUENCE_ENABLE_WRITES", raising=False)

    with pytest.raises(ConfluenceConfigurationError, match="CONFLUENCE_ENABLE_WRITES"):
        writes.ensure_write_allowed("OPS")


def test_whitelist_allows_listed_space(monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setitem(config_values, "CONFLUENCE_WRITE_SPACES", "OPS, QA")

    writes.ensure_write_allowed("OPS")
    writes.ensure_write_allowed("QA")


def test_whitelist_rejects_unlisted_space(monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setitem(config_values, "CONFLUENCE_WRITE_SPACES", "OPS,QA")

    with pytest.raises(ConfluenceConfigurationError, match="not in CONFLUENCE_WRITE_SPACES"):
        writes.ensure_write_allowed("DEV")


def test_whitelist_is_case_sensitive(monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setitem(config_values, "CONFLUENCE_WRITE_SPACES", "OPS")

    with pytest.raises(ConfluenceConfigurationError):
        writes.ensure_write_allowed("ops")


def test_empty_whitelist_allows_every_space(monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setitem(config_values, "CONFLUENCE_WRITE_SPACES", "  ,  ")

    writes.ensure_write_allowed("ANY")


def test_audit_write_appends_one_json_line(monkeypatch, tmp_path):
    log = tmp_path / "audit.log"
    monkeypatch.setattr(writes, "AUDIT_PATH", log)

    writes.audit_write(
        "create_page",
        page_id="42",
        space_key="OPS",
        version_before=None,
        version_after=1,
        result="created",
    )

    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["action"] == "create_page"
    assert record["page_id"] == "42"
    assert record["space_key"] == "OPS"
    assert record["version_before"] is None
    assert record["version_after"] == 1
    assert record["result"] == "created"
    assert record["ts"]


def test_audit_write_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "audit.log"
    blocker.mkdir()
    monkeypatch.setattr(writes, "AUDIT_PATH", blocker)

    writes.audit_write(
        "add_comment",
        page_id="42",
        space_key="OPS",
        version_before=None,
        version_after=None,
        result="created",
    )
