import getpass
import importlib
import os
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from confluence_mcp.settings_file import load_env_file


VALID_CONFIG = (
    "ATLASSIAN_CONFLUENCE_URL=https://wiki.example.invalid/confluence\n"
    "ATLASSIAN_CONFLUENCE_PAT=sample-secret\n"
)


def installer():
    return importlib.import_module("scripts.install")


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "Wiki 安装 folder"
    root.mkdir()
    (root / ".env.example").write_text(
        "ATLASSIAN_CONFLUENCE_URL=\nATLASSIAN_CONFLUENCE_PAT=\n", encoding="utf-8"
    )
    (root / "constraints.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "")
    return root


def test_console_setup_creates_config_without_echoing_pat(project, monkeypatch, capsys):
    install = installer()
    monkeypatch.setattr("builtins.input", lambda prompt: "https://wiki.example.invalid/confluence")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "#sample==")
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **k: pytest.fail("editor opened"))

    assert install.ensure_configuration(project)
    values = load_env_file(project / ".env")
    assert values["ATLASSIAN_CONFLUENCE_URL"] == "https://wiki.example.invalid/confluence"
    assert values["ATLASSIAN_CONFLUENCE_PAT"] == "#sample=="
    captured = capsys.readouterr()
    assert "#sample==" not in captured.out + captured.err


def test_console_setup_enter_retains_existing_configuration(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    original = (VALID_CONFIG + "CONFLUENCE_ENABLE_WRITES=true\nPRIVATE_OPTION=keep\n").encode()
    path.write_bytes(original)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompts.append(prompt) or "")

    assert install.ensure_configuration(project)
    assert path.read_bytes() == original
    assert len(prompts) == 2 and all("已配置" in prompt for prompt in prompts)
    assert "sample-secret" not in repr(prompts) + capsys.readouterr().out


def test_console_edit_preserves_other_settings_and_replaces_duplicate_pat(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    original = ("# user comment\r\n" + VALID_CONFIG.replace("\n", "\r\n") +
                "export ATLASSIAN_CONFLUENCE_PAT=old-token\r\n"
                "CONFLUENCE_ENABLE_WRITES=true\r\nCONFLUENCE_WRITE_SPACES=OPS\r\n"
                "ATLASSIAN_CONFLUENCE_CA_BUNDLE=C:/certs/ca.pem\r\nPRIVATE_OPTION=keep\r\n")
    path.write_bytes(original.encode("utf-8-sig"))
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "#new-token==")
    monkeypatch.setattr(install.subprocess, "Popen", lambda *a, **k: pytest.fail("editor opened"))

    assert install.ensure_configuration(project, edit=True)
    result = path.read_bytes()
    assert result.startswith(b"\xef\xbb\xbf") and b"\r\n" in result
    assert b"# user comment\r\n" in result and b"PRIVATE_OPTION=keep\r\n" in result
    assert b"CONFLUENCE_ENABLE_WRITES=true\r\n" in result and b"CONFLUENCE_WRITE_SPACES=OPS\r\n" in result
    assert b"ATLASSIAN_CONFLUENCE_CA_BUNDLE=C:/certs/ca.pem\r\n" in result
    assert b"old-token" not in result and b"sample-secret" not in result
    assert load_env_file(path)["ATLASSIAN_CONFLUENCE_PAT"] == "#new-token=="
    captured = capsys.readouterr()
    assert "#new-token==" not in captured.out + captured.err


def test_console_setup_refuses_password_input_when_echo_cannot_be_disabled(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    def cannot_hide(prompt):
        warnings.warn("input might be visible", getpass.GetPassWarning)
        return "sample-secret"

    monkeypatch.setattr(getpass, "getpass", cannot_hide)
    assert not install.ensure_configuration(project)
    assert path.read_bytes() == original
    captured = capsys.readouterr()
    assert "sample-secret" not in captured.out + captured.err


def test_missing_pat_stops_without_overwriting_or_exposing_values(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    original = "ATLASSIAN_CONFLUENCE_URL=\nATLASSIAN_CONFLUENCE_PAT=\nPRIVATE=sample-secret\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: "https://wiki.example.invalid/confluence")
    assert not install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == original
    assert "sample-secret" not in capsys.readouterr().out


def test_edit_retains_configuration_when_both_inputs_are_blank(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    monkeypatch.setattr(install, "PROJECT_ROOT", project)
    monkeypatch.setattr(sys, "argv", ["install.py", "--edit"])
    assert install.main() == 0
    assert path.read_text(encoding="utf-8") == VALID_CONFIG
    output = capsys.readouterr().out
    assert "已保留现有配置" in output
    assert "已更新 .env" not in output
    assert "sample-secret" not in output


def test_interrupted_input_is_reported_without_overwriting(project, monkeypatch, capsys):
    install = installer()
    path = project / ".env"
    original = VALID_CONFIG
    path.write_text(original, encoding="utf-8")

    def interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(getpass, "getpass", interrupt)
    assert not install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == original
    assert capsys.readouterr().err


@pytest.mark.parametrize("failed_step", ["permissions", "replace"])
def test_config_write_failure_preserves_original_and_removes_temp_file(project, monkeypatch, capsys, failed_step):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "replacement-token")

    def fail(*args):
        if failed_step == "permissions":
            assert args[1].read_bytes() == b""
        raise OSError("save unavailable")

    if failed_step == "permissions":
        monkeypatch.setattr(install, "_copy_config_permissions", fail)
    else:
        monkeypatch.setattr(install.os, "replace", fail)
    assert not install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == VALID_CONFIG
    assert set(project.glob(".env.*")) == {project / ".env.example"}
    assert "replacement-token" not in capsys.readouterr().err


def test_external_config_edit_during_prompt_is_not_overwritten(project, monkeypatch):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    external = VALID_CONFIG + "CONFLUENCE_WRITE_SPACES=OPS\n"

    def edit_during_prompt(prompt):
        path.write_text(external, encoding="utf-8")
        return "replacement-token"

    monkeypatch.setattr(getpass, "getpass", edit_during_prompt)
    assert not install.ensure_configuration(project)
    assert path.read_text(encoding="utf-8") == external


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file ACLs")
@pytest.mark.parametrize("protected", [False, True])
def test_console_update_preserves_existing_windows_acl(project, monkeypatch, protected):
    install = installer()
    path = project / ".env"
    path.write_text(VALID_CONFIG, encoding="utf-8")

    def icacls(*args):
        result = subprocess.run(
            ["icacls.exe", str(path), *args], capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    if protected:
        icacls("/inheritance:d")
    before = icacls()
    assert (b"(I)" not in before) is protected
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "replacement-token")
    assert install.ensure_configuration(project)
    assert icacls() == before


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
