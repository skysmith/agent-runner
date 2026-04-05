from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from agent_runner.run_coordinator import RunCoordinator
from agent_runner.ui import WindowController, WorkspaceApp


class _NotebookStub:
    def __init__(self, tab_ids: list[str]) -> None:
        self._tab_ids = list(tab_ids)
        self.style = ""

    def tabs(self) -> list[str]:
        return list(self._tab_ids)

    def configure(self, **kwargs: str) -> None:
        self.style = kwargs["style"]


class _UpdateBadgeWindowStub:
    def __init__(self) -> None:
        self.available_updates: list[bool] = []
        self.queued_updates: list[bool] = []

    def set_update_available(self, available: bool) -> None:
        self.available_updates.append(available)

    def set_update_reload_queued(self, queued: bool) -> None:
        self.queued_updates.append(queued)


class _UpdateSignalStub:
    def __init__(self, values: list[bool]) -> None:
        self._values = iter(values)

    def poll(self) -> bool:
        return next(self._values)


def test_launcher_script_targets_only_originating_tty_for_close(tmp_path: Path) -> None:
    script_cmd = shutil.which("script")
    if script_cmd is None:
        pytest.skip("script utility not available")

    repo_root = Path(__file__).resolve().parents[1]
    launcher_src = repo_root / "agent-runner.command"
    launcher_dst = tmp_path / "agent-runner.command"
    launcher_dst.write_text(launcher_src.read_text(encoding="utf-8"), encoding="utf-8")
    launcher_dst.chmod(launcher_dst.stat().st_mode | stat.S_IXUSR)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "sleep 5\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    osa_log = tmp_path / "osascript.log"
    fake_osascript = bin_dir / "osascript"
    fake_osascript.write_text(
        "#!/usr/bin/env bash\n"
        "cat > \"${TMP_OSA_LOG:?}\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_osascript.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TMP_OSA_LOG"] = str(osa_log)
    env["TERM_PROGRAM"] = "Apple_Terminal"

    cmd = f"cd '{tmp_path}' && ./agent-runner.command"
    completed = subprocess.run(
        [script_cmd, "-q", "/dev/null", "bash", "-c", cmd],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    applescript_payload = osa_log.read_text(encoding="utf-8")
    assert 'set targetTty to "/dev/ttys' in applescript_payload
    assert "if tty of t is targetTty then" in applescript_payload
    assert "close t" in applescript_payload


def test_launcher_script_ignores_stale_web_url_and_rewrites_localhost(tmp_path: Path) -> None:
    port = "18765"
    repo_root = Path(__file__).resolve().parents[1]
    launcher_src = repo_root / "agent-runner.command"
    launcher_dst = tmp_path / "agent-runner.command"
    launcher_dst.write_text(launcher_src.read_text(encoding="utf-8"), encoding="utf-8")
    launcher_dst.chmod(launcher_dst.stat().st_mode | stat.S_IXUSR)

    state_dir = tmp_path / ".agent-runner"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "web-url").write_text("https://stale.example.test\n", encoding="utf-8")
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "python_log=\"${TMP_PYTHON_LOG:?}\"\n"
        "if [[ \"$1\" == \"-\" ]]; then\n"
        "  cat >/dev/null\n"
        "  exit 1\n"
        "fi\n"
        "printf '%s\\n' \"$*\" >> \"$python_log\"\n"
        "repo=''\n"
        f"port='{port}'\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    --repo) repo=\"$2\"; shift 2 ;;\n"
        "    --port) port=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 - \"$repo\" \"$port\" <<'PY'\n"
        "import json\n"
        "import sys\n"
        "import threading\n"
        "import time\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "\n"
        "repo = sys.argv[1]\n"
        "port = int(sys.argv[2])\n"
        "\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path != '/api/server-info':\n"
        "            self.send_response(404)\n"
        "            self.end_headers()\n"
        "            return\n"
        "        payload = {\n"
        "            'server_kind': 'agent_runner_web',\n"
        "            'repo_path': repo,\n"
        "            'build_label': 't01',\n"
        "        }\n"
        "        body = json.dumps(payload).encode('utf-8')\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "\n"
        "    def log_message(self, format, *args):\n"
        "        return\n"
        "\n"
        "server = ThreadingHTTPServer(('127.0.0.1', port), Handler)\n"
        "thread = threading.Thread(target=server.serve_forever, daemon=True)\n"
        "thread.start()\n"
        "time.sleep(2)\n"
        "server.shutdown()\n"
        "thread.join(timeout=1)\n"
        "PY\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    open_log = tmp_path / "open.log"
    fake_open = bin_dir / "open"
    fake_open.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"${TMP_OPEN_LOG:?}\"\n",
        encoding="utf-8",
    )
    fake_open.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TMP_OPEN_LOG"] = str(open_log)
    env["TMP_PYTHON_LOG"] = str(tmp_path / "python.log")
    env["AGENT_RUNNER_WEB_PORT"] = port

    completed = subprocess.run(
        ["/bin/bash", str(launcher_dst)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stderr
    assert (state_dir / "web-url").read_text(encoding="utf-8").strip() == f"http://127.0.0.1:{port}"
    assert f"http://127.0.0.1:{port}" in open_log.read_text(encoding="utf-8")


def test_combined_session_flow_for_update_badge_reload_queue_and_tab_bar_visibility() -> None:
    app = WorkspaceApp.__new__(WorkspaceApp)
    app.coordinator = RunCoordinator()
    app.update_signal = _UpdateSignalStub([False, True])
    app.update_available = False
    app.reload_queued = False
    app.root = object()
    app._schedule_update_poll = lambda: None

    reload_calls: list[object] = []
    app._reload_process = lambda parent: reload_calls.append(parent)

    window = _UpdateBadgeWindowStub()
    app.windows = [window]

    # Session starts with one task tab, so tab bar should be hidden.
    controller = WindowController.__new__(WindowController)
    controller.notebook = _NotebookStub(["tab-1"])
    WindowController._refresh_tab_bar_visibility(controller)
    assert controller.notebook.style == WindowController._HIDDEN_TABS_STYLE

    # A second tab appears; tab bar becomes visible.
    controller.notebook._tab_ids.append("tab-2")
    WindowController._refresh_tab_bar_visibility(controller)
    assert controller.notebook.style == WindowController._VISIBLE_TABS_STYLE

    # Polling unchanged head keeps badge hidden, then a new commit surfaces it.
    WorkspaceApp._poll_update_signal(app)
    assert app.update_available is False
    WorkspaceApp._poll_update_signal(app)
    assert app.update_available is True
    assert window.available_updates[-1] is True

    # Clicking update during an active run queues reload without interruption.
    started = app.coordinator.try_start("workspace-1")
    assert started is True
    parent = object()
    WorkspaceApp.trigger_update_reload(app, parent=parent)
    assert app.reload_queued is True
    assert app.coordinator.active_workspace_id() == "workspace-1"
    assert reload_calls == []
    assert window.queued_updates[-1] is True

    # Once the run finishes, queued reload is applied.
    WorkspaceApp.finish_workspace_run(app, "workspace-1")
    assert app.coordinator.active_workspace_id() is None
    assert app.reload_queued is False
    assert reload_calls == [app.root]
    assert window.queued_updates[-1] is False
