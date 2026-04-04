from __future__ import annotations

from agent_runner.ui import WindowController


class _NotebookStub:
    def __init__(self, tab_ids: list[str]) -> None:
        self._tab_ids = list(tab_ids)
        self.style = ""

    def tabs(self) -> list[str]:
        return list(self._tab_ids)

    def configure(self, **kwargs: str) -> None:
        self.style = kwargs["style"]


def test_refresh_tab_bar_hides_when_exactly_one_tab() -> None:
    controller = WindowController.__new__(WindowController)
    controller.notebook = _NotebookStub(["tab-1"])

    WindowController._refresh_tab_bar_visibility(controller)

    assert controller.notebook.style == WindowController._HIDDEN_TABS_STYLE


def test_refresh_tab_bar_shows_when_multiple_tabs() -> None:
    controller = WindowController.__new__(WindowController)
    controller.notebook = _NotebookStub(["tab-1", "tab-2"])

    WindowController._refresh_tab_bar_visibility(controller)

    assert controller.notebook.style == WindowController._VISIBLE_TABS_STYLE
