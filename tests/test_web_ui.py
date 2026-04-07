from agent_runner.web_ui import render_error_page, render_web_app


def test_render_web_app_locks_mobile_zoom() -> None:
    html = render_web_app()

    assert "maximum-scale=1" in html
    assert "user-scalable=no" in html


def test_render_web_app_hides_voice_button_on_mobile() -> None:
    html = render_web_app()

    assert 'id="voice-button" class="icon-button mobile-hide"' in html
    assert "@media (max-width: 880px)" in html
    assert ".mobile-hide" in html


def test_render_web_app_restores_workspace_selection() -> None:
    html = render_web_app()

    assert "alcove-selected-workspace" in html
    assert "alcove-selected-conversation" in html
    assert "function requestedWorkspaceSelection()" in html
    assert "async function restoreWorkspaceSelection()" in html


def test_mobile_shell_locks_mobile_zoom() -> None:
    html = render_error_page("nope")

    assert "maximum-scale=1" in html
    assert "user-scalable=no" in html
