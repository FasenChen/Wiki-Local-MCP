import importlib
import subprocess
import zipfile
from pathlib import Path

import pytest


def git(root, *args):
    return subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={root / 'no-hooks'}", *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "release 项目 folder"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".env.example").write_text(
        "ATLASSIAN_CONFLUENCE_URL=\nATLASSIAN_CONFLUENCE_PAT=\n", encoding="utf-8"
    )
    (root / "setup.bat").write_bytes(b"@echo off\necho safe\n")
    (root / "setup.command").write_bytes(b"#!/bin/sh\r\necho safe\r\n")
    (root / "README.md").write_text("public\n", encoding="utf-8")
    (root / "MCP_SETUP.template.md").write_text("public Agent template\n", encoding="utf-8")
    git(root, "add", ".env.example", "setup.bat", "setup.command", "README.md", "MCP_SETUP.template.md")
    git(root, "update-index", "--chmod=+x", "setup.command")
    git(root, "commit", "-qm", "test snapshot")
    return root


def builder(repo, monkeypatch):
    module = importlib.import_module("scripts.build_release")
    monkeypatch.setattr(module, "PROJECT_ROOT", repo)
    return module


def test_release_uses_committed_template_and_excludes_private_files(repo, tmp_path, monkeypatch):
    (repo / ".env").write_text("PRIVATE_SENTINEL", encoding="utf-8")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "secret.txt").write_text("PRIVATE_SENTINEL", encoding="utf-8")
    (repo / "queue.sqlite3").write_text("PRIVATE_SENTINEL", encoding="utf-8")
    (repo / "audit.log").write_text("PRIVATE_SENTINEL", encoding="utf-8")
    (repo / "MCP_SETUP.md").write_text("PRIVATE_SENTINEL", encoding="utf-8")
    output = tmp_path / "release.zip"
    builder(repo, monkeypatch).build_release(output)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert archive.read(".env") == archive.read(".env.example")
        assert archive.read("MCP_SETUP.template.md").decode("utf-8").splitlines() == ["public Agent template"]
        assert all(b"PRIVATE_SENTINEL" not in archive.read(name) for name in names if not name.endswith("/"))
        assert not any(name.startswith(".venv/") or name.endswith((".sqlite3", ".log")) for name in names)
        assert archive.getinfo("setup.command").external_attr >> 16 & 0o111
        assert b"\r" not in archive.read("setup.command")
        assert b"\r\n" in archive.read("setup.bat")
        assert b"\n" not in archive.read("setup.bat").replace(b"\r\n", b"")


def test_release_requires_agent_template(repo, tmp_path, monkeypatch):
    git(repo, "rm", "MCP_SETUP.template.md")
    git(repo, "commit", "-qm", "missing template")
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError, match="missing"):
        builder(repo, monkeypatch).build_release(output)
    assert not output.exists()


def test_nonempty_template_pat_is_rejected_without_exposing_it(repo, tmp_path, monkeypatch):
    (repo / ".env.example").write_text("ATLASSIAN_CONFLUENCE_PAT=sample-secret\n", encoding="utf-8")
    git(repo, "add", ".env.example")
    git(repo, "commit", "-qm", "bad template")
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError) as caught:
        builder(repo, monkeypatch).build_release(output)
    assert "sample-secret" not in str(caught.value)
    assert not output.exists()


def test_template_cannot_hide_a_pat_behind_a_later_empty_assignment(repo, tmp_path, monkeypatch):
    (repo / ".env.example").write_text(
        "ATLASSIAN_CONFLUENCE_PAT=sample-secret\nATLASSIAN_CONFLUENCE_PAT=\n", encoding="utf-8"
    )
    git(repo, "add", ".env.example")
    git(repo, "commit", "-qm", "duplicate token")
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError) as caught:
        builder(repo, monkeypatch).build_release(output)
    assert "sample-secret" not in str(caught.value)
    assert not output.exists()


def test_commented_template_pat_is_not_included_in_release(repo, tmp_path, monkeypatch):
    (repo / ".env.example").write_text(
        "# ATLASSIAN_CONFLUENCE_PAT=sample-secret\nATLASSIAN_CONFLUENCE_PAT=\n", encoding="utf-8"
    )
    git(repo, "add", ".env.example")
    git(repo, "commit", "-qm", "commented token")
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError) as caught:
        builder(repo, monkeypatch).build_release(output)
    assert "sample-secret" not in str(caught.value)
    assert not output.exists()


def test_template_can_label_the_pat_without_assigning_it(repo, tmp_path, monkeypatch):
    (repo / ".env.example").write_text(
        "# ATLASSIAN_CONFLUENCE_PAT\nATLASSIAN_CONFLUENCE_PAT=\n", encoding="utf-8"
    )
    git(repo, "add", ".env.example")
    git(repo, "commit", "-qm", "token label")
    output = tmp_path / "release.zip"
    builder(repo, monkeypatch).build_release(output)
    assert output.exists()


def test_existing_release_is_not_overwritten(repo, tmp_path, monkeypatch):
    output = tmp_path / "release.zip"
    output.write_bytes(b"existing content")
    with pytest.raises(FileExistsError):
        builder(repo, monkeypatch).build_release(output)
    assert output.read_bytes() == b"existing content"


@pytest.mark.parametrize("name", [".env", "MCP_SETUP.md", "queue.sqlite3", "audit.log", ".venv/data.txt"])
def test_tracked_private_or_runtime_file_is_rejected(repo, tmp_path, monkeypatch, name):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("PRIVATE_SENTINEL", encoding="utf-8")
    git(repo, "add", "-f", name)
    git(repo, "commit", "-qm", "unsafe snapshot")
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError):
        builder(repo, monkeypatch).build_release(output)
    assert not output.exists()
