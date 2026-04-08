from __future__ import annotations

import base64
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


RUN_ACTIVE_STATES = frozenset({"starting", "running", "stopping"})
KEYCHAIN_ACCOUNT = "access-password"
QUICK_ACTION_NAME = "Open in Alcove"
NATIVE_SPEECH_HELPER_NAME = "AlcoveNativeSpeech"


def is_macos() -> bool:
    return sys.platform == "darwin"


def app_bundle_path(executable_path: Path | None = None) -> Path | None:
    candidate = (executable_path or Path(sys.executable)).resolve()
    parts = list(candidate.parts)
    if "Contents" not in parts:
        return None
    try:
        contents_index = parts.index("Contents")
    except ValueError:
        return None
    if contents_index == 0:
        return None
    return Path(*parts[:contents_index]).resolve()


def native_speech_helper_path(
    *,
    app_bundle: Path | None = None,
    executable_path: Path | None = None,
) -> Path | None:
    explicit = os.environ.get("AGENT_RUNNER_NATIVE_SPEECH_HELPER", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    bundle = app_bundle or app_bundle_path(executable_path)
    if bundle is None:
        return None
    return (bundle / "Contents" / "MacOS" / NATIVE_SPEECH_HELPER_NAME).resolve()


def native_speech_available(
    *,
    app_bundle: Path | None = None,
    executable_path: Path | None = None,
) -> bool:
    helper = native_speech_helper_path(app_bundle=app_bundle, executable_path=executable_path)
    return helper is not None and helper.exists() and os.access(helper, os.X_OK)


def capture_native_speech(
    *,
    app_bundle: Path | None = None,
    executable_path: Path | None = None,
    locale: str | None = None,
    timeout: float = 45.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    helper = native_speech_helper_path(app_bundle=app_bundle, executable_path=executable_path)
    if helper is None or not helper.exists() or not os.access(helper, os.X_OK):
        raise RuntimeError("Native transcription is not available in this build.")

    args = [str(helper)]
    locale_text = str(locale or "").strip()
    if locale_text:
        args.extend(["--locale", locale_text])

    run = runner or subprocess.run
    try:
        completed = run(
            args,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Native transcription timed out.") from exc

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip()
    payload: dict[str, Any] | None = None
    if stdout:
        try:
            decoded = json.loads(stdout)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            payload = decoded

    if completed.returncode != 0:
        detail = ""
        if payload is not None:
            detail = str(payload.get("detail") or payload.get("error") or "").strip()
        raise RuntimeError(detail or stderr or stdout or "Native transcription failed.")

    if payload is None:
        raise RuntimeError("Native transcription returned an invalid response.")

    transcript = str(payload.get("transcript") or "").strip()
    if not transcript:
        detail = str(payload.get("detail") or "").strip()
        raise RuntimeError(detail or "Could not capture speech.")

    response = dict(payload)
    response["transcript"] = transcript
    response.setdefault("provider", "macos-native")
    return response


def wrapper_state_path(state_root: Path) -> Path:
    return state_root / "wrapper-runtime.json"


def wrapper_log_dir(state_root: Path) -> Path:
    return state_root / "logs"


def quick_action_path() -> Path:
    return Path.home() / "Library" / "Services" / f"{QUICK_ACTION_NAME}.workflow"


def launch_agent_label(repo_path: Path) -> str:
    digest = hashlib.sha1(str(repo_path.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"local.alcove.web.{digest}"


def launch_agent_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def prune_stale_launch_agents(
    *,
    executable_path: Path,
    repo_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> list[Path]:
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    if not launch_agents_dir.exists():
        return []

    removed: list[Path] = []
    expected_executable = executable_path.resolve()
    expected_repo = repo_path.resolve()
    run = runner or subprocess.run

    for plist_path in sorted(launch_agents_dir.glob("local.alcove.web.*.plist")):
        try:
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        program_arguments = payload.get("ProgramArguments")
        if not isinstance(program_arguments, list) or not program_arguments:
            continue
        try:
            candidate_executable = Path(str(program_arguments[0])).expanduser().resolve()
        except Exception:
            continue
        if candidate_executable != expected_executable:
            continue
        env = payload.get("EnvironmentVariables")
        candidate_repo_text = env.get("AGENT_RUNNER_REPO") if isinstance(env, dict) else None
        if not isinstance(candidate_repo_text, str) or not candidate_repo_text.strip():
            continue
        try:
            candidate_repo = Path(candidate_repo_text).expanduser().resolve()
        except Exception:
            continue
        if candidate_repo == expected_repo:
            continue

        label = str(payload.get("Label") or "").strip()
        if label:
            run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], check=False, text=True, capture_output=True)
        try:
            plist_path.unlink()
        except OSError:
            continue
        removed.append(plist_path)
    return removed


def keychain_service_name(repo_path: Path) -> str:
    return launch_agent_label(repo_path)


def load_wrapper_state(state_root: Path) -> dict[str, Any]:
    path = wrapper_state_path(state_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def save_wrapper_state(state_root: Path, payload: dict[str, Any]) -> Path:
    path = wrapper_state_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def update_wrapper_state(
    state_root: Path,
    update: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    current = load_wrapper_state(state_root)
    next_payload = update(dict(current))
    if next_payload is None:
        next_payload = current
    save_wrapper_state(state_root, next_payload)
    return next_payload


def resolve_wrapper_password(
    *,
    repo_path: Path,
    explicit_password: str | None = None,
) -> str | None:
    password = (explicit_password or "").strip() or None
    if password:
        _save_password_to_keychain(repo_path=repo_path, password=password)
        return password

    keychain_password = _load_password_from_keychain(repo_path=repo_path)
    if keychain_password:
        return keychain_password

    file_password = _load_password_from_file(repo_path)
    if file_password:
        _save_password_to_keychain(repo_path=repo_path, password=file_password)
    return file_password


def local_api_request(
    *,
    base_url: str,
    path: str,
    method: str = "GET",
    password: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 2.5,
) -> dict[str, Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), data=body, method=method)
    if password:
        token = base64.b64encode(f"user:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    for key, value in headers.items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("Expected object response from local API.")
    return decoded


def wait_for_server(
    *,
    base_url: str,
    password: str | None,
    expected_repo: Path | None = None,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    deadline = time.time() + max(0.5, timeout_seconds)
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            payload = local_api_request(
                base_url=base_url,
                path="/api/server-info",
                password=password,
                timeout=1.5,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.15)
            continue
        if payload.get("server_kind") != "agent_runner_web":
            last_error = RuntimeError("Unexpected local server kind.")
            time.sleep(0.15)
            continue
        if expected_repo is not None and str(expected_repo.resolve()) != str(payload.get("repo_path") or ""):
            last_error = RuntimeError("Local server repo did not match expected workspace.")
            time.sleep(0.15)
            continue
        return payload
    if last_error is not None:
        raise last_error
    raise TimeoutError("Timed out waiting for the Alcove web service.")


def open_url(url: str) -> None:
    if not url.strip():
        return
    subprocess.run(["open", url], check=False)


def copy_text_to_clipboard(value: str) -> None:
    if not value.strip():
        return
    subprocess.run(["pbcopy"], input=value.encode("utf-8"), check=False)


@dataclass(slots=True)
class LaunchAgentSpec:
    label: str
    plist_path: Path
    executable_path: Path
    stdout_path: Path
    stderr_path: Path
    host: str
    port: int
    repo_path: Path | None
    app_bundle: Path | None

    @property
    def gui_domain(self) -> str:
        return f"gui/{os.getuid()}"

    @property
    def bootstrap_target(self) -> str:
        return f"{self.gui_domain}/{self.label}"


class LaunchAgentManager:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> None:
        self._runner = runner or subprocess.run

    def write_plist(self, spec: LaunchAgentSpec) -> Path:
        spec.plist_path.parent.mkdir(parents=True, exist_ok=True)
        spec.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        env_lines = [
            "    <key>AGENT_RUNNER_WEB_HOST</key>",
            f"    <string>{_xml_escape(spec.host)}</string>",
            "    <key>AGENT_RUNNER_WEB_PORT</key>",
            f"    <string>{spec.port}</string>",
        ]
        if spec.repo_path is not None:
            env_lines.extend(
                [
                    "    <key>AGENT_RUNNER_REPO</key>",
                    f"    <string>{_xml_escape(str(spec.repo_path))}</string>",
                ]
            )
        if spec.app_bundle is not None:
            env_lines.extend(
                [
                    "    <key>AGENT_RUNNER_APP_BUNDLE</key>",
                    f"    <string>{_xml_escape(str(spec.app_bundle))}</string>",
                ]
            )
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{_xml_escape(spec.label)}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_xml_escape(str(spec.executable_path))}</string>
    <string>--service</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
{chr(10).join(env_lines)}
  </dict>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{_xml_escape(str(spec.stdout_path))}</string>
  <key>StandardErrorPath</key>
  <string>{_xml_escape(str(spec.stderr_path))}</string>
</dict>
</plist>
"""
        spec.plist_path.write_text(plist, encoding="utf-8")
        return spec.plist_path

    def is_loaded(self, spec: LaunchAgentSpec) -> bool:
        result = self._run(["launchctl", "print", spec.bootstrap_target], check=False)
        return result.returncode == 0

    def ensure_running(self, spec: LaunchAgentSpec) -> None:
        self.write_plist(spec)
        if not self.is_loaded(spec):
            self._run(["launchctl", "bootstrap", spec.gui_domain, str(spec.plist_path)], check=True)
        self._run(["launchctl", "kickstart", "-k", spec.bootstrap_target], check=False)

    def restart(self, spec: LaunchAgentSpec) -> None:
        self.write_plist(spec)
        self._run(["launchctl", "kickstart", "-k", spec.bootstrap_target], check=True)

    def _run(self, args: Sequence[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return self._runner(list(args), check=check, text=True, capture_output=True)


class PowerAssertionManager:
    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    def update(self, status: dict[str, Any]) -> None:
        if not is_macos():
            return
        state = str(status.get("state") or "idle")
        if state in RUN_ACTIVE_STATES:
            self._ensure_started()
            return
        self.stop()

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    def _ensure_started(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            return
        if shutil.which("caffeinate") is None:
            return
        self._process = subprocess.Popen(
            ["caffeinate", "-dimsu"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class NotificationManager:
    def __init__(self) -> None:
        self._last_signature: str | None = None

    def update(self, status: dict[str, Any], *, workspace_name: str | None = None) -> None:
        if not is_macos():
            return
        state = str(status.get("state") or "idle")
        if state not in {"succeeded", "failed"}:
            return
        signature = "|".join(
            [
                str(status.get("run_id") or ""),
                state,
                str(status.get("finished_at") or status.get("updated_at") or ""),
            ]
        )
        if signature == self._last_signature:
            return
        self._last_signature = signature
        title = "Alcove Finished" if state == "succeeded" else "Alcove Needs Attention"
        subtitle = workspace_name or str(status.get("workspace_id") or "Workspace")
        body = (
            str(status.get("step") or "Complete")
            if state == "succeeded"
            else str(status.get("last_error") or status.get("error") or "Run failed")
        )
        _display_notification(title=title, subtitle=subtitle, body=body)


class MacOSWrapperBridge:
    def __init__(
        self,
        *,
        state_root: Path,
        app_bundle: Path | None,
        executable_path: Path,
        repo_path: Path,
        password_enabled: bool,
    ) -> None:
        self._state_root = state_root
        self._app_bundle = app_bundle
        self._executable_path = executable_path
        self._repo_path = repo_path
        self._password_enabled = password_enabled
        self._notifications = NotificationManager()
        self._power = PowerAssertionManager()

    def initialize(self, *, server_info_payload: dict[str, Any], run_status: dict[str, Any]) -> None:
        workspace_name = self._workspace_name(run_status)
        self._power.update(run_status)
        save_wrapper_state(
            self._state_root,
            {
                "app_bundle": str(self._app_bundle) if self._app_bundle is not None else None,
                "binary_path": str(self._executable_path),
                "repo_path": str(self._repo_path.resolve()),
                "password_enabled": self._password_enabled,
                "server_info": server_info_payload,
                "run_status": run_status,
                "workspace_name": workspace_name,
            },
        )

    def remember_open_target(self, *, workspace_id: str | None, conversation_id: str | None) -> None:
        update_wrapper_state(
            self._state_root,
            lambda payload: {
                **payload,
                "preferred_workspace_id": workspace_id,
                "preferred_conversation_id": conversation_id,
            },
        )

    def handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if not event_type.startswith("run."):
            return
        status = payload.get("status")
        if not isinstance(status, dict):
            return
        workspace_name = self._workspace_name(status)
        self._power.update(status)
        self._notifications.update(status, workspace_name=workspace_name)
        update_wrapper_state(
            self._state_root,
            lambda current: {
                **current,
                "run_status": status,
                "workspace_name": workspace_name,
            },
        )

    def shutdown(self) -> None:
        self._power.stop()

    def _workspace_name(self, status: dict[str, Any]) -> str | None:
        preferred = str(status.get("workspace_display_name") or "").strip()
        if preferred:
            return preferred
        workspace_id = str(status.get("workspace_id") or "").strip()
        return workspace_id or None


def open_browser_for_state(state_root: Path, *, prefer_current_workspace: bool = False) -> str | None:
    payload = load_wrapper_state(state_root)
    server_info_payload = payload.get("server_info") or {}
    base_url = str(server_info_payload.get("local_url") or server_info_payload.get("localhost_url") or "").strip()
    if not base_url:
        return None
    url = base_url
    workspace_id = None
    conversation_id = None
    if prefer_current_workspace:
        run_status = payload.get("run_status") or {}
        workspace_id = str(run_status.get("workspace_id") or "").strip() or None
        conversation_id = str(run_status.get("conversation_id") or "").strip() or None
    if not workspace_id:
        workspace_id = str(payload.get("preferred_workspace_id") or "").strip() or None
    if not conversation_id:
        conversation_id = str(payload.get("preferred_conversation_id") or "").strip() or None
    if workspace_id:
        params = {"workspace_id": workspace_id}
        if conversation_id:
            params["conversation_id"] = conversation_id
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
    open_url(url)
    return url


def copy_connection_url(state_root: Path, *, kind: str) -> str | None:
    payload = load_wrapper_state(state_root)
    server_info_payload = payload.get("server_info") or {}
    if kind == "phone":
        value = str(server_info_payload.get("phone_url") or "").strip()
    else:
        value = str(server_info_payload.get("local_url") or server_info_payload.get("localhost_url") or "").strip()
    if value:
        copy_text_to_clipboard(value)
        return value
    return None


def install_open_in_alcove_quick_action(*, app_bundle: Path) -> Path:
    workflow_path = quick_action_path()
    resources_dir = workflow_path / "Contents" / "Resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    info_plist = workflow_path / "Contents" / "Info.plist"
    document = resources_dir / "document.wflow"
    version_plist = workflow_path / "Contents" / "version.plist"
    open_target = app_bundle.resolve()
    shell_script = (
        "set -euo pipefail\n"
        "while IFS= read -r item; do\n"
        "  [[ -n \"$item\" ]] || continue\n"
        f"  open -a \"{_shell_escape(str(open_target))}\" --args --open-folder \"$item\"\n"
        "done\n"
    )
    info_plist.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en_US</string>
  <key>CFBundleIdentifier</key>
  <string>local.alcove.quickaction.open-folder</string>
  <key>CFBundleName</key>
  <string>{QUICK_ACTION_NAME}</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key>
      <dict>
        <key>default</key>
        <string>{QUICK_ACTION_NAME}</string>
      </dict>
      <key>NSMessage</key>
      <string>runWorkflowAsService</string>
      <key>NSSendFileTypes</key>
      <array>
        <string>public.folder</string>
      </array>
    </dict>
  </array>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    document.write_text(
        _workflow_document(shell_script),
        encoding="utf-8",
    )
    version_plist.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>BundleVersion</key>
  <string>1</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    return workflow_path


def _workflow_document(shell_script: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>actions</key>
  <array>
    <dict>
      <key>action</key>
      <dict>
        <key>ActionBundlePath</key>
        <string>/System/Library/Automator/Run Shell Script.action</string>
        <key>ActionName</key>
        <string>Run Shell Script</string>
        <key>ActionParameters</key>
        <dict>
          <key>CheckedForUserDefaultShell</key>
          <integer>1</integer>
          <key>COMMAND_STRING</key>
          <string>{_xml_escape(shell_script)}</string>
          <key>inputMethod</key>
          <integer>0</integer>
          <key>shell</key>
          <string>/bin/bash</string>
          <key>source</key>
          <string></string>
        </dict>
        <key>AMAccepts</key>
        <dict>
          <key>Container</key>
          <string>List</string>
          <key>Optional</key>
          <true/>
          <key>Types</key>
          <array>
            <string>com.apple.cocoa.path</string>
          </array>
        </dict>
        <key>AMActionVersion</key>
        <string>2.0.3</string>
        <key>AMApplication</key>
        <array>
          <string>Automator</string>
        </array>
        <key>AMParameterProperties</key>
        <dict/>
        <key>AMProvides</key>
        <dict>
          <key>Container</key>
          <string>List</string>
          <key>Types</key>
          <array>
            <string>com.apple.cocoa.path</string>
          </array>
        </dict>
      </dict>
    </dict>
  </array>
  <key>AMApplicationBuild</key>
  <string>523</string>
  <key>AMApplicationVersion</key>
  <string>2.10</string>
  <key>AMDocumentVersion</key>
  <string>2</string>
  <key>connectors</key>
  <dict/>
  <key>workflowMetaData</key>
  <dict>
    <key>serviceApplicationBundleID</key>
    <string></string>
    <key>serviceInputTypeIdentifier</key>
    <string>com.apple.Automator.fileSystemObject</string>
    <key>serviceOutputTypeIdentifier</key>
    <string>com.apple.Automator.nothing</string>
    <key>serviceProcessesInput</key>
    <integer>0</integer>
    <key>workflowTypeIdentifier</key>
    <string>com.apple.Automator.servicesMenu</string>
  </dict>
</dict>
</plist>
"""


def _display_notification(*, title: str, subtitle: str, body: str) -> None:
    script = (
        f'display notification "{_osascript_escape(body)}" '
        f'with title "{_osascript_escape(title)}" '
        f'subtitle "{_osascript_escape(subtitle)}"'
    )
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)


def _load_password_from_file(repo_path: Path) -> str | None:
    candidates = [
        repo_path / ".agent-runner" / "web-password",
        Path.home() / "Library" / "Application Support" / "agent-runner" / "web-password",
    ]
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if not text:
            continue
        password = text[0].strip()
        if password:
            return password
    return None


def _load_password_from_keychain(*, repo_path: Path) -> str | None:
    if not is_macos():
        return None
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            keychain_service_name(repo_path),
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    password = (result.stdout or "").strip()
    return password or None


def _save_password_to_keychain(*, repo_path: Path, password: str) -> None:
    if not is_macos() or not password.strip():
        return
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            keychain_service_name(repo_path),
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
            password,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _shell_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def _osascript_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
