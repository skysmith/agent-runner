from pathlib import Path

from agent_runner.executable_utils import extend_path_with_user_bins, resolve_executable_path


def test_resolve_executable_path_checks_codex_app_bundle_when_path_lookup_fails(monkeypatch) -> None:
    codex_bundle_dir = Path("/Applications/Codex.app/Contents/Resources")
    monkeypatch.setattr("agent_runner.executable_utils.shutil.which", lambda command: None)
    monkeypatch.setattr("agent_runner.executable_utils._COMMON_USER_BIN_DIRS", (codex_bundle_dir,))
    monkeypatch.setattr(
        "agent_runner.executable_utils._is_executable",
        lambda path: path == codex_bundle_dir / "codex",
    )

    resolved = resolve_executable_path("codex")

    assert resolved == str(codex_bundle_dir / "codex")


def test_extend_path_with_user_bins_includes_codex_bundle_when_present(monkeypatch) -> None:
    codex_bundle_dir = Path("/Applications/Codex.app/Contents/Resources")
    monkeypatch.setattr("agent_runner.executable_utils._COMMON_USER_BIN_DIRS", (codex_bundle_dir,))
    monkeypatch.setattr(Path, "exists", lambda self: self == codex_bundle_dir)

    updated = extend_path_with_user_bins("/usr/bin:/bin")

    assert updated.split(":") == ["/usr/bin", "/bin", str(codex_bundle_dir)]
