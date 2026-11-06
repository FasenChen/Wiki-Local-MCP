import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


VALID_CONFIG = (
    "ATLASSIAN_CONFLUENCE_URL=https://wiki.example.invalid/confluence\n"
    "ATLASSIAN_CONFLUENCE_PAT=sample-secret\n"
)


def installer():
    return importlib.import_module("scripts.install")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Wiki 安装 folder"
    root.mkdir()
    (root / ".env.example").write_text(
        "ATLASSIAN_CONFLUENCE_URL=\nATLASSIAN_CONFLUENCE_PAT=\n", encoding="utf-8"
    )
    (root / "constraints.txt").write_text("", encoding="utf-8")
    return root


def test_missing_configuration_opens_editor_and_uses_saved_values(project, monkeypatch, capsys):
    install = installer()
    opened = []

    def edit(command, **kwargs):
        opened.append(command)
        (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")

    monkeypatch.setattr(install.subprocess, "Popen", edit)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert install.ensure_configuration(project)
    assert (project / ".env").read_text(encoding="utf-8") == VALID_CONFIG
    assert str(project / ".env") in opened[0]
    assert "sample-secret" not in repr(opened)
    assert "sample-secret" not in capsys.readouterr().out


def test_existing_valid_configuration_is_not_changed_or_opened(project, monkeypatch):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected editor"))
    assert install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == VALID_CONFIG


def test_unsaved_configuration_stops_without_overwriting_or_exposing_values(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    original = "ATLASSIAN_CONFLUENCE_URL=\nATLASSIAN_CONFLUENCE_PAT=\nPRIVATE=sample-secret\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert not install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == original
    assert "sample-secret" not in capsys.readouterr().out


def test_user_can_reopen_valid_configuration_to_update_pat(project, monkeypatch):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    updated = VALID_CONFIG.replace("sample-secret", "new-example-token")
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **k: path.write_text(updated, encoding="utf-8"))
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert install.ensure_configuration(project, edit=True)
    assert path.read_text(encoding="utf-8") == updated


def test_missing_editor_is_reported_without_overwriting(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    original = "ATLASSIAN_CONFLUENCE_URL=\nATLASSIAN_CONFLUENCE_PAT=\n"
    path.write_text(original, encoding="utf-8")

    def fail(*args, **kwargs):
        raise FileNotFoundError("editor unavailable")

    monkeypatch.setattr(install.subprocess, "Popen", fail)
    assert not install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == original
    assert capsys.readouterr().err


def test_installer_imports_without_installed_dependencies(project):
    script = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    code = f"import runpy; runpy.run_path({str(script)!r}, run_name='installer_import')"
    result = subprocess.run(
        [sys.executable, "-S", "-c", code], cwd=project, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("platform", "venv_parts"), [
    ("win32", ("Scripts", "python.exe")),
    ("darwin", ("bin", "python")),
])
def test_install_runs_steps_in_isolated_project_with_platform_python(
    project, monkeypatch, capsys, platform, venv_parts
):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    fake_sys = SimpleNamespace(
        version_info=sys.version_info, executable=sys.executable, platform=platform, stderr=sys.stderr
    )
    monkeypatch.setattr(install, "sys", fake_sys)
    monkeypatch.setenv("PYTHONPATH", "other-project")
    monkeypatch.setenv("PYTHONHOME", "other-python")
    calls = []
    venv_python = project / ".venv" / Path(*venv_parts)

    def run(command, *, cwd, check, env):
        calls.append((command, cwd, env))
        if command[1:3] == ["-m", "venv"]:
            venv_python.parent.mkdir(parents=True)
            venv_python.touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install.subprocess, "run", run)
    assert install.run_install(project) == 0
    assert calls[0][0][1:3] == ["-m", "venv"]
    assert calls[1][0] == [str(venv_python), "-m", "pip", "--version"]
    assert calls[2][0] == [
        str(venv_python), "-m", "pip", "install", "-c", str(project / "constraints.txt"), "-e", str(project)
    ]
    assert calls[3][0][:2] == [str(venv_python), "-c"]
    assert calls[4][0] == [str(venv_python), "-m", "confluence_mcp.healthcheck"]
    assert all(cwd == project for _, cwd, _ in calls)
    assert all("PYTHONPATH" not in env and "PYTHONHOME" not in env for _, _, env in calls)
    assert "sample-secret" not in capsys.readouterr().out


def test_invalid_existing_venv_is_not_deleted(project, monkeypatch):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    venv = project / ".venv"
    venv.mkdir()
    marker = venv / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **k: pytest.fail("unexpected subprocess"))
    assert install.run_install(project) == 1
    assert marker.read_text(encoding="utf-8") == "keep"


def test_venv_creation_failure_preserves_partial_data_and_mentions_shorter_path(project, monkeypatch, capsys):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    marker = project / ".venv" / "keep.txt"

    def fail(command, *, cwd, check, env):
        marker.parent.mkdir()
        marker.write_text("keep", encoding="utf-8")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(install.subprocess, "run", fail)
    assert install.run_install(project) == 1
    assert marker.read_text(encoding="utf-8") == "keep"
    assert "较短路径" in capsys.readouterr().err


def test_broken_pip_reports_path_guidance_without_deleting_venv(project, monkeypatch, capsys):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    parts = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    venv_python = project / ".venv" / Path(*parts)
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()

    def fail(command, *, cwd, check, env):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(install.subprocess, "run", fail)
    assert install.run_install(project) == 1
    assert venv_python.exists()
    assert "较短路径" in capsys.readouterr().err


def test_existing_valid_venv_is_reused(project, monkeypatch):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    parts = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    venv_python = project / ".venv" / Path(*parts)
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    marker = project / ".venv" / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    calls = []

    def run(command, *, cwd, check, env):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install.subprocess, "run", run)
    assert install.run_install(project) == 0
    assert not any(command[1:3] == ["-m", "venv"] for command in calls)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_dependency_install_failure_stops_before_network_check(project, monkeypatch, capsys):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    parts = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    venv_python = project / ".venv" / Path(*parts)
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    calls = []

    def run(command, *, cwd, check, env):
        calls.append(command)
        if "install" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install.subprocess, "run", run)
    assert install.run_install(project) == 1
    assert not any("confluence_mcp.healthcheck" in command for command in calls)
    assert venv_python.exists()
    assert "sample-secret" not in capsys.readouterr().err


@pytest.mark.parametrize("failed_step", ["local_tools", "wiki_auth"])
def test_failed_checks_stop_install_and_report_failure(project, monkeypatch, capsys, failed_step):
    install = installer()
    (project / ".env").write_text(VALID_CONFIG, encoding="utf-8")
    parts = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    venv_python = project / ".venv" / Path(*parts)
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    calls = []

    def run(command, *, cwd, check, env):
        calls.append(command)
        is_local = len(command) > 1 and command[1] == "-c"
        is_auth = "confluence_mcp.healthcheck" in command
        if (failed_step == "local_tools" and is_local) or (failed_step == "wiki_auth" and is_auth):
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install.subprocess, "run", run)
    assert install.run_install(project) == 1
    if failed_step == "local_tools":
        assert not any("confluence_mcp.healthcheck" in command for command in calls)
    assert "sample-secret" not in capsys.readouterr().err


def test_old_python_stops_before_changing_configuration(project, monkeypatch):
    install = installer()
    fake_sys = SimpleNamespace(
        version_info=(3, 9), executable=sys.executable, platform=sys.platform, stderr=sys.stderr
    )
    monkeypatch.setattr(install, "sys", fake_sys)
    assert install.run_install(project) == 1
    assert not (project / ".env").exists()
