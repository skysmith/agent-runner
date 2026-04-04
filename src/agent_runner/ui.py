from __future__ import annotations

import json
import os
import subprocess
import queue
import re
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar,
    Canvas,
    DoubleVar,
    Entry,
    Frame,
    Label,
    Menu,
    StringVar,
    Text,
    Tk,
    Toplevel,
    messagebox,
    simpledialog,
)
from tkinter import ttk

from .context_assembler import ContextAssembler, EffectiveContext
from .conversation_store import ConversationStore, WorkspaceConversationController
from .models import AppSettings, ChecksPolicy, ProviderKind, RunMode, WorkspaceSettings
from .preflight import generate_clarifying_questions
from .providers import ExecutionRequest, ProviderRouter, probe_ollama
from .run_coordinator import RunCoordinator
from .runner import AgentRunner, RunnerConfig
from .settings_store import load_app_settings, save_app_settings
from .update_signal import CommitUpdateSignal, read_build_label
from .voice import VoiceError, VoiceRecordingSession, start_recording, stop_recording, transcribe_audio

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_ERROR = "error"


@dataclass(slots=True)
class UiSettings:
    repo_path: Path
    artifacts_dir: Path
    settings_path: Path
    packaged_mode: bool
    provider: ProviderKind
    codex_bin: str
    model: str
    ollama_host: str
    extra_access_dir: Path | None
    max_step_retries: int
    phase_timeout_seconds: int
    check_commands: list[str]
    dry_run: bool


class WorkspacePane:
    def __init__(
        self,
        parent: ttk.Notebook,
        workspace_id: str,
        app: WorkspaceApp,
        prompt_text: str | None = None,
    ):
        self.parent = parent
        self.workspace_id = workspace_id
        self.app = app
        self.controller = WorkspaceConversationController(app.conversation_store, workspace_id)
        self.frame = ttk.Frame(parent, style="Root.TFrame", padding=(24, 20, 24, 20))
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.is_running = False
        self.stop_requested = False
        self.voice_session: VoiceRecordingSession | None = None
        self.override = WorkspaceSettings(
            run_mode=app.app_settings.default_run_mode,
            loop_count=app.app_settings.max_step_retries + 1,
        )
        self.animation_frames = ("·  ", "·· ", "···", " ··")
        self.animation_frame_index = 0
        self.animation_after_id: str | None = None
        self.status_tooltip: Toplevel | None = None

        self.state_var = StringVar(value=STATE_IDLE)
        self.step_var = StringVar(value="Not started")
        self.last_run_var = StringVar(value="Never")
        self.checks_var = StringVar(value="Not run yet")
        self.artifacts_var = StringVar(value="-")
        self.error_var = StringVar(value="")
        self.status_animation_var = StringVar(value="")
        self.status_tooltip_var = StringVar(value="")
        self.thread_title_var = StringVar(value=self.controller.active_conversation().title)
        self.loop_mode_var = BooleanVar(value=self.override.run_mode == RunMode.LOOP)
        self.loop_mode_text_var = StringVar()

        self.prompt_input: Text
        self.change_list: Text
        self.conversation_tree: ttk.Treeview
        self.conversation_panel: ttk.Frame
        self.conversation_rail: ttk.Frame
        self.conversation_title_label: ttk.Label
        self.new_conversation_button: ttk.Button
        self.rename_conversation_button: ttk.Button
        self.delete_conversation_button: ttk.Button
        self.panel_toggle_button: ttk.Button
        self.panel_rail_button: ttk.Button
        self.mic_button: ttk.Button
        self.run_button: ttk.Button
        self.stop_button: ttk.Button
        self.loop_mode_pill: ttk.Frame
        self.loop_mode_title_label: ttk.Label
        self.loop_mode_switch: Canvas
        self.status_dot: Canvas
        self.status_animation_label: ttk.Label
        self.conversation_initialized = False

        self._build_ui(prompt_text=prompt_text)
        self._refresh_conversation_list()
        self._render_active_conversation()
        self.frame.after(80, self._drain_events)

    def tab_title(self) -> str:
        return f"Task {self.workspace_id.split('-')[-1]}"

    def _build_ui(self, prompt_text: str | None = None) -> None:
        content = ttk.Frame(self.frame, style="Root.TFrame")
        content.pack(fill="both", expand=True)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)

        self.conversation_panel = ttk.Frame(content, style="Surface.TFrame", padding=(12, 12, 12, 12), width=220)
        self.conversation_panel.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        self.conversation_panel.grid_propagate(False)
        self.conversation_panel.rowconfigure(1, weight=1)
        self.conversation_panel.columnconfigure(0, weight=1)

        panel_header = ttk.Frame(self.conversation_panel, style="Surface.TFrame")
        panel_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        panel_header.columnconfigure(0, weight=1)
        ttk.Label(panel_header, text="CONVERSATIONS", style="SectionEyebrow.TLabel").grid(row=0, column=0, sticky="w")
        self.panel_toggle_button = ttk.Button(
            panel_header,
            text="‹",
            style="Icon.TButton",
            width=2,
            command=self.toggle_conversations_panel,
        )
        self.panel_toggle_button.grid(row=0, column=1, sticky="e")

        panel_actions = ttk.Frame(self.conversation_panel, style="Surface.TFrame")
        panel_actions.grid(row=1, column=0, sticky="nsew")
        panel_actions.rowconfigure(1, weight=1)
        panel_actions.columnconfigure(0, weight=1)

        actions_row = ttk.Frame(panel_actions, style="Surface.TFrame")
        actions_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.new_conversation_button = ttk.Button(
            actions_row,
            text="+ New",
            style="Icon.TButton",
            command=self.create_new_conversation,
        )
        self.new_conversation_button.pack(side="left")
        self.rename_conversation_button = ttk.Button(
            actions_row,
            text="Rename",
            style="Icon.TButton",
            command=self.rename_selected_conversation,
        )
        self.rename_conversation_button.pack(side="left", padx=(6, 0))
        self.delete_conversation_button = ttk.Button(
            actions_row,
            text="Delete",
            style="Icon.TButton",
            command=self.delete_selected_conversation,
        )
        self.delete_conversation_button.pack(side="left", padx=(6, 0))

        self.conversation_tree = ttk.Treeview(
            panel_actions,
            show="tree",
            selectmode="browse",
            style="Conversation.Treeview",
            height=18,
        )
        self.conversation_tree.grid(row=1, column=0, sticky="nsew")
        self.conversation_tree.bind("<<TreeviewSelect>>", self._handle_conversation_selected)

        self.conversation_rail = ttk.Frame(content, style="Surface.TFrame", padding=(4, 12, 4, 12), width=30)
        self.conversation_rail.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        self.conversation_rail.grid_propagate(False)
        self.panel_rail_button = ttk.Button(
            self.conversation_rail,
            text="›",
            style="Icon.TButton",
            width=2,
            command=self.toggle_conversations_panel,
        )
        self.panel_rail_button.pack(anchor="n")

        column = ttk.Frame(content, style="Root.TFrame")
        column.grid(row=0, column=1, sticky="nsew")
        column.columnconfigure(0, weight=1)
        column.rowconfigure(0, weight=1)

        changes = ttk.Frame(column, style="Surface.TFrame", padding=(16, 14, 16, 14))
        changes.grid(row=0, column=0, sticky="nsew")
        ttk.Label(changes, text="THREAD", style="SectionEyebrow.TLabel").pack(anchor="w")
        self.conversation_title_label = ttk.Label(changes, textvariable=self.thread_title_var, style="SectionTitle.TLabel")
        self.conversation_title_label.pack(anchor="w", pady=(2, 8))
        self.change_list = Text(
            changes,
            height=22,
            wrap="word",
            relief="flat",
            bg="#fcfcfa",
            fg="#2d2c29",
            font=("Helvetica", 11),
            highlightthickness=1,
            highlightbackground="#dddcd7",
            padx=10,
            pady=10,
            state="disabled",
        )
        self.change_list.pack(fill="both", expand=True)

        prompt_section = ttk.Frame(column, style="Surface.TFrame", padding=(16, 14, 16, 14))
        prompt_section.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(prompt_section, text="YOUR REQUEST", style="SectionEyebrow.TLabel").pack(anchor="w")
        ttk.Label(prompt_section, text="What should happen next?", style="SectionTitle.TLabel").pack(anchor="w", pady=(2, 8))

        composer_shell = ttk.Frame(prompt_section, style="ComposerShell.TFrame", padding=1)
        composer_shell.pack(fill="x")
        composer_body = ttk.Frame(composer_shell, style="ComposerInner.TFrame")
        composer_body.pack(fill="x")

        self.prompt_input = Text(
            composer_body,
            height=4,
            wrap="word",
            relief="flat",
            bg="#fcfcfa",
            fg="#2d2c29",
            font=("Helvetica", 12),
            insertbackground="#2d2c29",
            highlightthickness=0,
            bd=0,
            padx=12,
            pady=12,
        )
        self.prompt_input.pack(fill="x")
        self.prompt_input.focus_set()
        initial_prompt = prompt_text if prompt_text else "Describe what you want in plain language."
        self.prompt_input.insert("1.0", initial_prompt)
        self.prompt_input.bind("<FocusIn>", self._clear_placeholder)
        self.prompt_input.bind("<Return>", self._run_from_shortcut)
        self.prompt_input.bind("<Shift-Return>", self._insert_newline_from_shortcut)
        self.prompt_input.bind("<Command-Return>", self._run_from_shortcut)
        self.prompt_input.bind("<Control-Return>", self._run_from_shortcut)

        status_cluster = ttk.Frame(composer_shell, style="ComposerInner.TFrame")
        status_cluster.place(relx=1.0, rely=0.0, x=-10, y=10, anchor="ne")
        self.status_dot = Canvas(
            status_cluster,
            width=12,
            height=12,
            bg="#fcfcfa",
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor="hand2",
        )
        self.status_dot.pack(side="left")
        self.status_animation_label = ttk.Label(
            status_cluster,
            textvariable=self.status_animation_var,
            style="Muted.TLabel",
            font=("Menlo", 10),
        )
        self.status_animation_label.pack(side="left", padx=(4, 0))
        for widget in (status_cluster, self.status_dot, self.status_animation_label):
            widget.bind("<Enter>", self._show_status_tooltip)
            widget.bind("<Leave>", self._hide_status_tooltip)

        actions = ttk.Frame(composer_body, style="ComposerInner.TFrame", padding=(10, 0, 10, 10))
        actions.pack(fill="x")
        controls = ttk.Frame(actions, style="ComposerInner.TFrame")
        controls.pack(side="left")
        self.loop_mode_pill = ttk.Frame(controls, style="LoopPillOff.TFrame", padding=(8, 4, 10, 4))
        self.loop_mode_pill.pack(side="left")
        self.loop_mode_switch = Canvas(
            self.loop_mode_pill,
            width=38,
            height=20,
            bg="#f3f2ed",
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor="hand2",
        )
        self.loop_mode_switch.pack(side="left")
        self.loop_mode_title_label = ttk.Label(self.loop_mode_pill, text="Loop", style="LoopPillOff.TLabel")
        self.loop_mode_title_label.pack(side="left", padx=(8, 0))
        self.loop_mode_switch.bind("<Button-1>", self._on_loop_switch_click)
        self.loop_mode_pill.bind("<Button-1>", self._on_loop_switch_click)
        self.loop_mode_title_label.bind("<Button-1>", self._on_loop_switch_click)

        self.mic_button = ttk.Button(actions, text="◎", style="Icon.TButton", width=2, command=self.toggle_voice_capture)
        self.mic_button.pack(side="right")
        self.stop_button = ttk.Button(actions, text="■", style="Icon.TButton", width=2, command=self.request_stop)
        self.stop_button.pack(side="right", padx=(0, 6))
        self.run_button = ttk.Button(actions, text="▶", style="RunIcon.TButton", width=2, command=self.start_run)
        self.run_button.pack(side="right", padx=(0, 6))
        self.stop_button.state(["disabled"])
        self._sync_loop_mode_ui()
        self._refresh_status_labels()
        self._apply_conversation_panel_state()

    def _clear_placeholder(self, _: object) -> None:
        text = self.prompt_input.get("1.0", "end").strip()
        if text == "Describe what you want in plain language.":
            self.prompt_input.delete("1.0", "end")

    def _run_from_shortcut(self, _: object) -> str:
        self.start_run()
        return "break"

    def _insert_newline_from_shortcut(self, _: object) -> str:
        self.prompt_input.insert("insert", "\n")
        return "break"

    def start_run(self) -> None:
        if self.is_running:
            return
        raw_prompt = self.prompt_input.get("1.0", "end").strip()
        if not raw_prompt or raw_prompt == "Describe what you want in plain language.":
            self._set_error("Please type a request before running.")
            return
        prompt = raw_prompt
        provider, model, _, run_mode = self._effective_run_settings()
        if run_mode == RunMode.LOOP and self.app.app_settings.preflight_clarifications:
            prompt = self._prepare_prompt_with_clarifications(prompt=prompt, provider=provider, model=model)
            if not prompt:
                return
        if not self.app.coordinator.try_start(self.workspace_id):
            self._set_error("Another workspace is running. Please wait for it to finish.")
            return

        self.is_running = True
        self.stop_requested = False
        self._set_state(STATE_RUNNING)
        self._set_error("")
        self.step_var.set("Getting ready")
        self.checks_var.set("In progress")
        self.run_button.state(["disabled"])
        self.stop_button.state(["!disabled"])
        self._set_conversation_controls_enabled(False)
        self._start_animation()
        self.prompt_input.delete("1.0", "end")
        record = self.controller.append_message(role="user", content=raw_prompt)
        self._maybe_refresh_conversation_summary(record.id)
        active_conversation = self.controller.active_conversation()
        effective_context = (
            self.app.context_assembler.build_for_loop(
                repo_path=self.app.bootstrap.repo_path,
                provider=provider,
                model=model,
                run_mode=run_mode,
                conversation=active_conversation,
                current_input=prompt,
            )
            if run_mode == RunMode.LOOP
            else self.app.context_assembler.build_for_message(
                repo_path=self.app.bootstrap.repo_path,
                provider=provider,
                model=model,
                run_mode=run_mode,
                conversation=active_conversation,
                current_input=prompt,
            )
        )
        self._refresh_conversation_list(selected_id=active_conversation.id)
        self._render_active_conversation()

        thread = threading.Thread(
            target=self._run_in_background,
            args=(prompt, active_conversation.id, effective_context),
            daemon=True,
        )
        thread.start()

    def _effective_run_settings(self) -> tuple[ProviderKind, str, int, RunMode]:
        global_settings = self.app.app_settings
        if self.override.override_enabled:
            provider = self.override.provider
            model = self.override.model
        else:
            provider = global_settings.provider
            model = global_settings.model
        loop_count = self.override.loop_count or (global_settings.max_step_retries + 1)
        run_mode = self.override.run_mode
        return provider, model, max(1, loop_count), run_mode

    def _toggle_loop_mode(self) -> None:
        self.override.run_mode = RunMode.LOOP if self.loop_mode_var.get() else RunMode.MESSAGE
        self._sync_loop_mode_ui()

    def _on_loop_switch_click(self, _: object) -> None:
        self.loop_mode_var.set(not self.loop_mode_var.get())
        self._toggle_loop_mode()

    def _sync_loop_mode_ui(self) -> None:
        is_loop = self.override.run_mode == RunMode.LOOP
        self.loop_mode_var.set(is_loop)
        track_color = "#3f644b" if is_loop else "#d9d6cc"
        knob_color = "#fcfcfa" if is_loop else "#f5f4f0"
        knob_outline = "#d2d0c8"
        knob_center_x = 28 if is_loop else 10
        c = self.loop_mode_switch
        c.delete("all")
        c.create_oval(1, 1, 19, 19, fill=track_color, outline=track_color)
        c.create_oval(19, 1, 37, 19, fill=track_color, outline=track_color)
        c.create_rectangle(10, 1, 28, 19, fill=track_color, outline=track_color)
        c.create_oval(
            knob_center_x - 7,
            3,
            knob_center_x + 7,
            17,
            fill=knob_color,
            outline=knob_outline,
        )
        self.loop_mode_pill.configure(style="LoopPillOn.TFrame" if is_loop else "LoopPillOff.TFrame")
        self.loop_mode_title_label.configure(style="LoopPillOn.TLabel" if is_loop else "LoopPillOff.TLabel")
        c.configure(bg="#dfe8e0" if is_loop else "#f3f2ed")
        self.loop_mode_text_var.set(
            "On: iterative loop with planner, builder, and reviewer."
            if is_loop
            else "Off: send one direct prompt and return the reply."
        )

    def _show_status_tooltip(self, event: object) -> None:
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        self._hide_status_tooltip()
        tooltip = Toplevel(self.frame.winfo_toplevel())
        tooltip.wm_overrideredirect(True)
        tooltip.attributes("-topmost", True)
        x = widget.winfo_rootx() - 220
        y = widget.winfo_rooty() - 90
        tooltip.wm_geometry(f"+{x}+{y}")
        body = ttk.Frame(tooltip, style="Tooltip.TFrame", padding=(10, 8, 10, 8))
        body.pack(fill="both", expand=True)
        ttk.Label(body, textvariable=self.status_tooltip_var, style="Tooltip.TLabel", justify="left", wraplength=240).pack(anchor="w")
        self.status_tooltip = tooltip

    def _hide_status_tooltip(self, _: object | None = None) -> None:
        if self.status_tooltip is not None:
            self.status_tooltip.destroy()
            self.status_tooltip = None

    def request_stop(self) -> None:
        if not self.is_running:
            return
        self.stop_requested = True
        self._set_error("Stopping safely after the current phase.")
        self.step_var.set("Stopping safely")
        self.stop_button.state(["disabled"])

    def toggle_voice_capture(self) -> None:
        if self.is_running:
            self._set_error("Finish or stop the current run before recording.")
            return
        if self.voice_session is None:
            try:
                device_index = os.environ.get("AGENT_RUNNER_MIC_DEVICE", "").strip() or None
                self.voice_session = start_recording(audio_device_index=device_index)
            except VoiceError as exc:
                self._set_error(str(exc))
                return
            self.mic_button.configure(text="●")
            self._set_error("Recording. Click Stop Mic when you're done.")
            return

        session = self.voice_session
        self.voice_session = None
        self.mic_button.configure(text="◎")
        try:
            stop_recording(session)
        except Exception as exc:  # pragma: no cover - UI safety
            self._set_error(f"Could not stop recording: {exc}")
            return
        self._set_error("Transcribing voice note...")
        threading.Thread(target=self._transcribe_voice_note, args=(session.audio_path,), daemon=True).start()

    def _transcribe_voice_note(self, audio_path: Path) -> None:
        try:
            transcript = transcribe_audio(audio_path)
            self.events.put(("transcript_ready", transcript))
        except Exception as exc:  # pragma: no cover - UI safety
            self.events.put(("transcript_error", str(exc)))

    def _prepare_prompt_with_clarifications(self, *, prompt: str, provider: ProviderKind, model: str) -> str | None:
        try:
            clarify = generate_clarifying_questions(
                provider_router=self.app.phase_client,
                provider=provider,
                model=model,
                prompt=prompt,
                repo_path=self.app.bootstrap.repo_path,
                codex_bin=self.app.app_settings.codex_bin,
                extra_access_dir=self.app.app_settings.extra_access_dir,
                ollama_host=self.app.app_settings.ollama_host,
                timeout_seconds=self.app.app_settings.phase_timeout_seconds,
                dry_run=self.app.bootstrap.dry_run,
            )
        except Exception as exc:
            self._set_error(f"Clarifying pass failed: {exc}")
            return prompt
        if not clarify.questions:
            return prompt
        return self._show_clarify_modal(prompt=prompt, summary=clarify.summary, questions=clarify.questions)

    def _show_clarify_modal(self, *, prompt: str, summary: str, questions: list[str]) -> str | None:
        modal = Toplevel(self.frame)
        modal.title("Clarify Task")
        modal.geometry("560x360")
        modal.configure(bg="#f5f5f3")
        modal.transient(self.frame.winfo_toplevel())
        modal.grab_set()

        frame = ttk.Frame(modal, style="Root.TFrame", padding=(18, 16, 18, 16))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="CLARIFY", style="SectionEyebrow.TLabel").pack(anchor="w")
        ttk.Label(frame, text="A couple of quick questions before we run", style="SectionTitle.TLabel").pack(
            anchor="w", pady=(2, 10)
        )
        if summary:
            ttk.Label(frame, text=summary, style="Muted.TLabel", wraplength=500).pack(anchor="w", pady=(0, 12))

        answer_vars: list[StringVar] = []
        for question in questions[:2]:
            ttk.Label(frame, text=question, style="Body.TLabel", wraplength=500).pack(anchor="w", pady=(6, 4))
            answer_var = StringVar(value="")
            answer_vars.append(answer_var)
            Entry(frame, textvariable=answer_var).pack(fill="x")

        result: dict[str, str | None] = {"prompt": None}

        def continue_run() -> None:
            clarification_lines = []
            for question, answer_var in zip(questions[:2], answer_vars):
                answer = answer_var.get().strip()
                if answer:
                    clarification_lines.append(f"Q: {question}\nA: {answer}")
            if clarification_lines:
                result["prompt"] = f"{prompt}\n\nClarifications:\n" + "\n\n".join(clarification_lines)
            else:
                result["prompt"] = prompt
            modal.destroy()

        def cancel_run() -> None:
            result["prompt"] = None
            modal.destroy()

        actions = ttk.Frame(frame, style="Root.TFrame")
        actions.pack(fill="x", pady=(16, 0))
        ttk.Button(actions, text="Cancel", command=cancel_run).pack(side="left")
        ttk.Button(actions, text="Continue", style="Run.TButton", command=continue_run).pack(side="right")

        modal.wait_window()
        return result["prompt"]

    def _run_in_background(self, prompt: str, conversation_id: str, effective_context: EffectiveContext) -> None:
        try:
            provider, model, loop_count, run_mode = self._effective_run_settings()
            if run_mode == RunMode.MESSAGE:
                self._run_message_only(
                    prompt=prompt,
                    provider=provider,
                    model=model,
                    conversation_id=conversation_id,
                    effective_context=effective_context,
                )
                return
            global_settings = self.app.app_settings
            check_commands = (
                list(self.app.bootstrap.check_commands)
                if self.app.bootstrap.check_commands
                else (
                    list(global_settings.default_checks)
                    if global_settings.checks_policy == ChecksPolicy.CUSTOM
                    else None
                )
            )
            config = RunnerConfig(
                task_file=None,
                task_text=prompt,
                repo_path=self.app.bootstrap.repo_path,
                artifacts_dir=self.app.bootstrap.artifacts_dir,
                codex_bin=global_settings.codex_bin,
                provider=provider,
                model=model,
                ollama_host=global_settings.ollama_host,
                extra_access_dir=global_settings.extra_access_dir,
                max_step_retries=max(0, loop_count - 1),
                phase_timeout_seconds=global_settings.phase_timeout_seconds,
                check_commands=check_commands,
                conversation_context=effective_context.conversation_context,
                dry_run=self.app.bootstrap.dry_run,
                progress=False,
                status_callback=lambda msg: self.events.put(("status", msg)),
                stop_requested=lambda: self.stop_requested,
            )
            runner = AgentRunner(config)
            outcome = runner.run()
            self.events.put(
                (
                    "done",
                    {
                        "outcome": outcome,
                        "artifacts_dir": str(runner.store.run_dir),
                        "build_number": runner.store.build_number,
                        "conversation_id": conversation_id,
                    },
                )
            )
        except Exception as exc:  # pragma: no cover - defensive UI safety
            self.events.put(("error", str(exc)))

    def _run_message_only(
        self,
        prompt: str,
        provider: ProviderKind,
        model: str,
        conversation_id: str,
        effective_context: EffectiveContext,
    ) -> None:
        self.events.put(("status", "Phase: message"))
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["message"],
            "properties": {"message": {"type": "string"}},
        }
        response = self.app.phase_client.run(
            ExecutionRequest(
                provider=provider,
                codex_bin=self.app.app_settings.codex_bin,
                model=model,
                prompt=(
                    "You are a concise coding assistant for this repository. "
                    "Respond to the user's message directly. Do not perform iterative planning/build/review loops. "
                    "Return JSON matching schema.\n\n"
                    f"{effective_context.system_context}\n\n"
                    f"{effective_context.conversation_context}\n\n"
                    f"{effective_context.current_input}\n"
                ),
                schema=schema,
                repo_path=self.app.bootstrap.repo_path,
                extra_access_dir=self.app.app_settings.extra_access_dir,
                ollama_host=self.app.app_settings.ollama_host,
                dry_run=self.app.bootstrap.dry_run,
                timeout_seconds=self.app.app_settings.phase_timeout_seconds,
                phase_name="message",
            )
        )
        message = str(response.payload.get("message", "")).strip()
        if not message:
            message = json.dumps(response.payload, indent=2, sort_keys=True)
        self.events.put(("message_done", {"message": message, "conversation_id": conversation_id}))

    def _drain_events(self) -> None:
        try:
            while True:
                event_type, payload = self.events.get_nowait()
                if event_type == "status":
                    self._consume_status(str(payload))
                elif event_type == "done":
                    self._consume_done(payload)
                    self.app.finish_workspace_run(self.workspace_id)
                elif event_type == "message_done":
                    self._consume_message_done(payload)
                    self.app.finish_workspace_run(self.workspace_id)
                elif event_type == "transcript_ready":
                    self._consume_transcript_ready(str(payload))
                elif event_type == "transcript_error":
                    self._set_error(str(payload))
                elif event_type == "error":
                    self._set_state(STATE_ERROR)
                    self._set_error(str(payload))
                    self._append_assistant_message(text=f"Run failed.\n\nReason: {payload}", phase="error")
                    self.is_running = False
                    self.run_button.state(["!disabled"])
                    self.stop_button.state(["disabled"])
                    self._stop_animation("error")
                    self._set_conversation_controls_enabled(True)
                    self.app.finish_workspace_run(self.workspace_id)
        except queue.Empty:
            pass
        self._refresh_status_labels()
        self.frame.after(80, self._drain_events)

    def _consume_status(self, message: str) -> None:
        if "Phase: planner" in message:
            self.step_var.set("Understanding your request")
        elif "Phase: message" in message:
            self.step_var.set("Sending message")
        elif "builder" in message:
            self.step_var.set("Making updates")
        elif "reviewer" in message:
            self.step_var.set("Checking the result")
        elif "Run finished:" in message:
            self.step_var.set("Wrapping up")

        step_match = re.search(r"Step (\S+) attempt (\d+)", message)
        if step_match:
            self.step_var.set(f"Working on {step_match.group(1)} (try {step_match.group(2)})")

        check_match = re.search(r"Checks: (.+)$", message)
        if check_match:
            checks_text = check_match.group(1)
            passed = checks_text.count("=ok")
            failed = checks_text.count("=fail")
            self.checks_var.set(f"{passed} passed, {failed} failed")

    def _consume_done(self, payload: object) -> None:
        data = dict(payload) if isinstance(payload, dict) else {}
        outcome = data.get("outcome")
        artifacts_dir = str(data.get("artifacts_dir", "-"))
        build_number = data.get("build_number")
        conversation_id = str(data.get("conversation_id") or self.controller.active_conversation().id)

        self.last_run_var.set(datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"))
        self.artifacts_var.set(artifacts_dir)
        self.is_running = False
        self.run_button.state(["!disabled"])
        self.stop_button.state(["disabled"])
        self._set_conversation_controls_enabled(True)
        state_label = "done" if getattr(outcome, "ok", False) else "error"
        self._stop_animation(state_label)

        if outcome is None:
            self._set_state(STATE_ERROR)
            self._set_error("Runner finished without outcome.")
            self._append_assistant_message(
                text="Run failed.\n\nNo outcome was returned.",
                phase="loop-final",
                conversation_id=conversation_id,
            )
            return

        check_results = []
        change_lines: list[str] = []
        for step_run in getattr(outcome, "step_runs", []):
            summary = step_run.build_result.summary.strip()
            if summary:
                change_lines.append(f"{step_run.step_id}: {summary}")
            files = step_run.build_result.files_touched
            if files:
                preview = ", ".join(files[:3])
                suffix = "..." if len(files) > 3 else ""
                change_lines.append(f"Updated {len(files)} file(s): {preview}{suffix}")
            commands = step_run.build_result.commands_run
            if commands:
                change_lines.append(f"Ran {len(commands)} command(s) to do the work.")
            check_results.extend(step_run.check_results)

        passed = sum(1 for c in check_results if c.ok)
        failed = sum(1 for c in check_results if not c.ok)
        if check_results:
            self.checks_var.set(f"{passed} passed, {failed} failed")
        else:
            self.checks_var.set("No checks configured")

        if getattr(outcome, "ok", False):
            self._set_state(STATE_DONE)
            self._set_error("")
            self.step_var.set("Complete")
            if getattr(outcome, "final_message", ""):
                change_lines.insert(0, f"Result: {outcome.final_message}")
        else:
            self._set_state(STATE_ERROR)
            self.step_var.set("Needs attention")
            reason = getattr(outcome, "reason", "Run failed.")
            self._set_error(reason)
            change_lines.insert(0, f"Needs attention: {reason}")

        if not change_lines:
            change_lines = ["Run finished with no reported changes."]
        if isinstance(build_number, int):
            change_lines.insert(0, f"Build number: {build_number}")
        self._append_assistant_message(
            text="\n".join(change_lines),
            phase="loop-final",
            conversation_id=conversation_id,
        )

    def _consume_message_done(self, payload: object) -> None:
        data = dict(payload) if isinstance(payload, dict) else {}
        response = str(data.get("message", "")).strip()
        conversation_id = str(data.get("conversation_id") or self.controller.active_conversation().id)
        self.last_run_var.set(datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"))
        self.is_running = False
        self.run_button.state(["!disabled"])
        self.stop_button.state(["disabled"])
        self._set_conversation_controls_enabled(True)
        self._stop_animation("idle")
        self._set_state(STATE_DONE)
        self.step_var.set("Complete")
        self._set_error("")
        self.checks_var.set("Skipped (message mode)")
        self.artifacts_var.set("Message mode (no loop artifacts)")
        text = "Message response received."
        if response:
            text = f"{text}\n\n{response}"
        self._append_assistant_message(text=text, phase="message", conversation_id=conversation_id)

    def _consume_transcript_ready(self, transcript: str) -> None:
        self._set_error("")
        existing = self.prompt_input.get("1.0", "end").strip()
        if existing == "Describe what you want in plain language.":
            existing = ""
            self.prompt_input.delete("1.0", "end")
        addition = transcript.strip()
        if not addition:
            self._set_error("No speech was transcribed.")
            return
        if existing:
            self.prompt_input.insert("end", "\n\n" + addition)
        else:
            self.prompt_input.insert("1.0", addition)

    def _start_animation(self) -> None:
        self.animation_frame_index = 0
        if not self.app.app_settings.animate_status_scenes:
            self.status_animation_var.set("")
            return
        self.status_animation_var.set(self.animation_frames[0])
        self._schedule_animation_tick()

    def _stop_animation(self, label: str) -> None:
        if self.animation_after_id is not None:
            self.frame.after_cancel(self.animation_after_id)
            self.animation_after_id = None
        self.animation_frame_index = 0
        self.status_animation_var.set("!" if label == "error" else "")

    def _advance_animation(self) -> None:
        self.animation_after_id = None
        if self.is_running and self.app.app_settings.animate_status_scenes:
            self.animation_frame_index = (self.animation_frame_index + 1) % len(self.animation_frames)
            self.status_animation_var.set(self.animation_frames[self.animation_frame_index])
            self._schedule_animation_tick()

    def _schedule_animation_tick(self) -> None:
        if not self.is_running or not self.app.app_settings.animate_status_scenes:
            return
        if self.animation_after_id is not None:
            return
        self.animation_after_id = self.frame.after(420, self._advance_animation)

    def prompt_snapshot(self) -> str:
        return self.prompt_input.get("1.0", "end").strip()

    def _set_state(self, state: str) -> None:
        self.state_var.set(state)

    def _set_error(self, message: str) -> None:
        self.error_var.set(message)

    def _append_assistant_message(
        self,
        *,
        text: str,
        phase: str,
        conversation_id: str | None = None,
    ) -> None:
        target_id = conversation_id or self.controller.active_conversation().id
        if self.controller.state.active_conversation_id != target_id:
            self.controller.select_conversation(target_id)
        record = self.controller.append_message(role="assistant", content=text, phase=phase)
        self._maybe_refresh_conversation_summary(record.id)
        self._refresh_conversation_list(selected_id=record.id)
        self._render_active_conversation()

    def _append_conversation_message(self, *, from_user: bool, text: str) -> None:
        clean_text = text.strip()
        if not clean_text:
            return
        self.change_list.configure(state="normal")
        if self.conversation_initialized:
            self.change_list.insert("end", "\n")
        bubble_bg = "#3f644b" if from_user else "#ecebe5"
        bubble_fg = "#fcfcfa" if from_user else "#2d2c29"
        bubble_wrap = max(280, self.change_list.winfo_width() - 180)

        row = Frame(self.change_list, bg="#fcfcfa", bd=0, highlightthickness=0)
        bubble = Label(
            row,
            text=clean_text,
            bg=bubble_bg,
            fg=bubble_fg,
            font=("Helvetica", 11),
            justify="left",
            wraplength=bubble_wrap,
            padx=10,
            pady=8,
        )
        if from_user:
            bubble.pack(side="right", padx=(96, 10))
        else:
            bubble.pack(side="left", padx=(10, 96))
        self.change_list.window_create("end", window=row, stretch=1)
        self.change_list.insert("end", "\n")
        self.change_list.see("end")
        self.conversation_initialized = True
        self.change_list.configure(state="disabled")

    def _clear_thread(self) -> None:
        self.change_list.configure(state="normal")
        self.change_list.delete("1.0", "end")
        self.change_list.configure(state="disabled")
        self.conversation_initialized = False

    def _render_active_conversation(self) -> None:
        record = self.controller.active_conversation()
        self.thread_title_var.set(record.title)
        self._clear_thread()
        if not record.messages:
            self._append_conversation_message(
                from_user=False,
                text="No messages yet. Type your request below to start this conversation.",
            )
            return
        for message in record.messages:
            self._append_conversation_message(from_user=message.role == "user", text=message.content)

    def _refresh_conversation_list(self, selected_id: str | None = None) -> None:
        active_id = selected_id or self.controller.state.active_conversation_id
        existing_ids = set(self.conversation_tree.get_children(""))
        ordered_records = self.controller.metadata()
        desired_ids = {record.id for record in ordered_records}
        for item_id in existing_ids - desired_ids:
            self.conversation_tree.delete(item_id)
        for index, record in enumerate(ordered_records):
            label = self._conversation_row_label(record)
            if record.id in existing_ids:
                self.conversation_tree.item(record.id, text=label)
            else:
                self.conversation_tree.insert("", "end", iid=record.id, text=label)
            self.conversation_tree.move(record.id, "", index)
        if active_id and active_id in desired_ids:
            self.conversation_tree.selection_set(active_id)
            self.conversation_tree.focus(active_id)

    def _conversation_row_label(self, record) -> str:
        try:
            stamp = datetime.fromisoformat(record.updated_at).strftime("%b %d %I:%M %p")
        except ValueError:
            stamp = record.updated_at
        return f"{record.title}  ·  {stamp}"

    def _handle_conversation_selected(self, _: object) -> None:
        selected_id = self._selected_conversation_id()
        if not selected_id:
            return
        if self.is_running:
            self._refresh_conversation_list(selected_id=self.controller.active_conversation().id)
            return
        self.controller.select_conversation(selected_id)
        self._render_active_conversation()

    def _selected_conversation_id(self) -> str | None:
        selection = self.conversation_tree.selection()
        if not selection:
            return None
        return str(selection[0])

    def create_new_conversation(self) -> None:
        if self.is_running:
            return
        record = self.controller.create_conversation()
        self._refresh_conversation_list(selected_id=record.id)
        self._render_active_conversation()
        self.prompt_input.focus_set()

    def rename_selected_conversation(self) -> None:
        if self.is_running:
            return
        record = self.controller.active_conversation()
        new_title = simpledialog.askstring(
            "Rename conversation",
            "Conversation title",
            initialvalue=record.title,
            parent=self.frame.winfo_toplevel(),
        )
        if new_title is None:
            return
        self.controller.rename_conversation(record.id, new_title)
        self._refresh_conversation_list(selected_id=record.id)
        self._render_active_conversation()

    def delete_selected_conversation(self) -> None:
        if self.is_running:
            return
        record = self.controller.active_conversation()
        confirmed = messagebox.askyesno(
            "Delete conversation",
            f"Delete '{record.title}'?",
            parent=self.frame.winfo_toplevel(),
        )
        if not confirmed:
            return
        fallback = self.controller.delete_conversation(record.id)
        self._refresh_conversation_list(selected_id=fallback.id)
        self._render_active_conversation()

    def toggle_conversations_panel(self) -> None:
        self.controller.set_panel_collapsed(not self.controller.state.conversations_panel_collapsed)
        self._apply_conversation_panel_state()

    def _apply_conversation_panel_state(self) -> None:
        collapsed = self.controller.state.conversations_panel_collapsed
        if collapsed:
            self.conversation_panel.grid_remove()
            self.conversation_rail.grid()
        else:
            self.conversation_rail.grid_remove()
            self.conversation_panel.grid()

    def _set_conversation_controls_enabled(self, enabled: bool) -> None:
        state = ["!disabled"] if enabled else ["disabled"]
        for button in (
            self.new_conversation_button,
            self.rename_conversation_button,
            self.delete_conversation_button,
            self.panel_toggle_button,
            self.panel_rail_button,
        ):
            button.state(state)

    def _maybe_refresh_conversation_summary(self, conversation_id: str) -> None:
        record = self.controller.active_conversation()
        if record.id != conversation_id:
            return
        summary = self.app.context_assembler.refresh_summary(record)
        if summary != record.summary:
            self.controller.update_summary(conversation_id, summary)

    def _refresh_status_labels(self) -> None:
        state = self.state_var.get()
        dot = self.status_dot
        dot.delete("all")
        color = self._state_color(state)
        dot.create_oval(2, 2, 10, 10, fill=color, outline=color)
        status_name = "Idle"
        if state == STATE_RUNNING:
            status_name = "Working"
        elif state == STATE_ERROR:
            status_name = "Error"
        elif state == STATE_DONE:
            status_name = "Idle"
        details = [
            f"Status: {status_name}",
            f"Doing now: {self.step_var.get()}",
            f"Last run: {self.last_run_var.get()}",
            f"Quick checks: {self.checks_var.get()}",
            f"Saved details: {self.artifacts_var.get()}",
        ]
        error_text = self.error_var.get().strip()
        if error_text:
            details.append(f"Note: {error_text}")
        self.status_tooltip_var.set("\n".join(details))

    def _state_color(self, state: str) -> str:
        if state == STATE_DONE:
            return "#3f644b"
        if state == STATE_ERROR:
            return "#b64e43"
        if state == STATE_RUNNING:
            return "#d5a021"
        return "#3f644b"


class ImageGenPane:
    def __init__(self, parent: ttk.Notebook, app: WorkspaceApp):
        self.parent = parent
        self.app = app
        self.frame = ttk.Frame(parent, style="Root.TFrame", padding=(24, 20, 24, 20))
        self.url_var = StringVar(value="")
        self.status_var = StringVar(value="Not checked yet.")
        self._build_ui()
        self.refresh_status()

    def tab_title(self) -> str:
        return "Image Gen"

    def _build_ui(self) -> None:
        header = ttk.Frame(self.frame, style="Root.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Image Gen Dashboard", style="Headline.TLabel").pack(anchor="w")
        ttk.Label(header, text="Launch and open the ai-art dashboard from here.", style="Subhead.TLabel").pack(
            anchor="w", pady=(2, 12)
        )

        panel = ttk.Frame(self.frame, style="Surface.TFrame", padding=(16, 14, 16, 14))
        panel.pack(fill="x")
        ttk.Label(panel, text="DASHBOARD", style="SectionEyebrow.TLabel").pack(anchor="w")
        ttk.Label(panel, text="ai-art status", style="SectionTitle.TLabel").pack(anchor="w", pady=(2, 8))
        ttk.Label(panel, textvariable=self.status_var, style="Body.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(panel, textvariable=self.url_var, style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        actions = ttk.Frame(panel, style="Surface.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="Refresh", command=self.refresh_status).pack(side="left")
        ttk.Button(actions, text="Launch Dashboard", command=self.launch_dashboard).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Open Dashboard URL", style="Run.TButton", command=self.open_dashboard_url).pack(
            side="right"
        )

    def refresh_status(self) -> None:
        ai_art_dir = self.app.ai_art_dir
        if ai_art_dir is None:
            self.status_var.set("ai-art directory not found.")
            self.url_var.set("")
            return
        url_file = ai_art_dir / ".dashboard-url"
        if url_file.exists():
            url = url_file.read_text(encoding="utf-8").strip()
            self.url_var.set(url)
            self.status_var.set("Dashboard URL available.")
        else:
            self.url_var.set("")
            self.status_var.set("Dashboard URL not found. Launch first.")

    def launch_dashboard(self) -> None:
        ai_art_dir = self.app.ai_art_dir
        if ai_art_dir is None:
            messagebox.showerror("agent-runner", "ai-art directory not found.")
            return
        launcher = ai_art_dir / "launch_dashboard.sh"
        if not launcher.exists():
            messagebox.showerror("agent-runner", f"Missing launcher: {launcher}")
            return
        try:
            subprocess.Popen(["/bin/bash", str(launcher)], cwd=str(ai_art_dir))
        except Exception as exc:  # pragma: no cover - GUI fallback
            messagebox.showerror("agent-runner", f"Failed to launch dashboard: {exc}")
            return
        self.status_var.set("Launch requested. Refreshing status...")
        self.frame.after(1200, self.refresh_status)

    def open_dashboard_url(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            self.refresh_status()
            url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("agent-runner", "No dashboard URL found yet.")
            return
        webbrowser.open(url)


class WindowController:
    _VISIBLE_TABS_STYLE = "TNotebook"
    _HIDDEN_TABS_STYLE = "Tabless.TNotebook"

    def __init__(self, app: WorkspaceApp, root: Tk | Toplevel):
        self.app = app
        self.root = root
        self.tab_by_id: dict[str, WorkspacePane | ImageGenPane] = {}

        self.root.title("agent-runner")
        self.root.configure(bg="#f5f5f3")
        self.root.geometry("720x760")
        self.root.minsize(680, 620)
        self._configure_menu()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.add_workspace_tab()

    def _configure_menu(self) -> None:
        menubar = Menu(self.root)
        is_macos = sys.platform == "darwin"

        if is_macos:
            app_menu = Menu(menubar, name="apple", tearoff=0)
            app_menu.add_command(label="About agent-runner", command=self.app.show_about_dialog)
            app_menu.add_separator()
            app_menu.add_command(label="Safe Reload", command=lambda: self.app.trigger_safe_reload(parent=self.root))
            menubar.add_cascade(menu=app_menu)

        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Window", command=lambda: self.app.create_window())
        file_menu.add_command(label="New Tab", command=self.add_workspace_tab)
        file_menu.add_command(label="New Image Gen Tab", command=self.add_image_gen_tab)
        file_menu.add_command(label="Close Tab", command=self.close_active_tab)
        if not is_macos:
            file_menu.add_separator()
            file_menu.add_command(label="Safe Reload", command=lambda: self.app.trigger_safe_reload(parent=self.root))
        file_menu.add_separator()
        file_menu.add_command(label="Close Window", command=self.close_window)
        menubar.add_cascade(label="File", menu=file_menu)

        workspace_menu = Menu(menubar, tearoff=0)
        workspace_menu.add_command(label="Workspace Options...", command=self.edit_active_workspace_settings)
        workspace_menu.add_command(label="Open Tab In New Window", command=self.popout_active_tab)
        menubar.add_cascade(label="Workspace", menu=workspace_menu)

        settings_menu = Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Preferences...", command=self.app.open_settings_window)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="About agent-runner", command=self.app.show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.configure(menu=menubar)
        self.root.createcommand("tkAboutDialog", self.app.show_about_dialog)

    def _tab_changed(self, _: object) -> None:
        self.root.title("agent-runner")

    def _refresh_tab_bar_visibility(self) -> None:
        tab_count = len(self.notebook.tabs())
        if tab_count == 1:
            self.notebook.configure(style=self._HIDDEN_TABS_STYLE)
            return
        self.notebook.configure(style=self._VISIBLE_TABS_STYLE)

    def add_workspace_tab(self, prompt_text: str | None = None) -> WorkspacePane:
        workspace_id = self.app.next_workspace_id()
        pane = WorkspacePane(parent=self.notebook, workspace_id=workspace_id, app=self.app, prompt_text=prompt_text)
        self.notebook.add(pane.frame, text=pane.tab_title())
        tab_id = self.notebook.select()
        self.tab_by_id[tab_id] = pane
        self.notebook.select(tab_id)
        self._refresh_tab_bar_visibility()
        return pane

    def add_image_gen_tab(self) -> None:
        pane = ImageGenPane(parent=self.notebook, app=self.app)
        self.notebook.add(pane.frame, text=pane.tab_title())
        tab_id = self.notebook.select()
        self.tab_by_id[tab_id] = pane
        self.notebook.select(tab_id)
        self._refresh_tab_bar_visibility()

    def active_workspace(self) -> WorkspacePane | None:
        tab_id = self.notebook.select()
        if not tab_id:
            return None
        pane = self.tab_by_id.get(tab_id)
        if isinstance(pane, WorkspacePane):
            return pane
        return None

    def close_active_tab(self) -> None:
        tab_id = self.notebook.select()
        if not tab_id:
            return
        pane = self.tab_by_id.get(tab_id)
        if isinstance(pane, WorkspacePane) and pane.is_running:
            messagebox.showerror("agent-runner", "This workspace is currently running.")
            return
        self.tab_by_id.pop(tab_id, None)
        self.notebook.forget(tab_id)
        self._refresh_tab_bar_visibility()
        if not self.notebook.tabs():
            self.close_window()

    def close_window(self) -> None:
        for pane in self.tab_by_id.values():
            if isinstance(pane, WorkspacePane) and pane.is_running:
                messagebox.showerror("agent-runner", "A workspace in this window is currently running.")
                return
        self.app.close_window(self)

    def edit_active_workspace_settings(self) -> None:
        pane = self.active_workspace()
        if pane is None:
            return
        if pane.is_running:
            messagebox.showerror("agent-runner", "Cannot change workspace settings while running.")
            return
        self.app.open_workspace_settings_modal(self.root, pane)

    def popout_active_tab(self) -> None:
        tab_id = self.notebook.select()
        pane = self.tab_by_id.get(tab_id)
        if pane is None:
            return
        if not isinstance(pane, WorkspacePane):
            messagebox.showerror("agent-runner", "Only task tabs can be moved to a new window.")
            return
        if pane.is_running:
            messagebox.showerror("agent-runner", "Cannot move a running workspace.")
            return
        prompt_text = pane.prompt_snapshot()
        override = WorkspaceSettings(
            override_enabled=pane.override.override_enabled,
            provider=pane.override.provider,
            model=pane.override.model,
            run_mode=pane.override.run_mode,
            loop_count=pane.override.loop_count,
        )
        self.tab_by_id.pop(tab_id, None)
        self.notebook.forget(tab_id)
        self._refresh_tab_bar_visibility()
        new_window = self.app.create_window()
        new_pane = new_window.active_workspace()
        if new_pane is not None:
            new_pane.prompt_input.delete("1.0", "end")
            new_pane.prompt_input.insert("1.0", prompt_text)
            new_pane.override = override
            new_pane._sync_loop_mode_ui()
        if not self.notebook.tabs():
            self.close_window()


class WorkspaceApp:
    def __init__(self, root: Tk, bootstrap: UiSettings):
        self.root = root
        self.bootstrap = bootstrap
        self.coordinator = RunCoordinator()
        self.phase_client = ProviderRouter()
        self.windows: list[WindowController] = []
        self.workspace_counter = 0
        self.ai_art_dir = self._detect_ai_art_dir()

        self.settings_path = bootstrap.settings_path
        self.conversation_store = ConversationStore(self.settings_path.parent / "workspaces")
        self.context_assembler = ContextAssembler()
        defaults = AppSettings(
            provider=bootstrap.provider,
            model=bootstrap.model,
            codex_bin=bootstrap.codex_bin,
            ollama_host=bootstrap.ollama_host,
            extra_access_dir=bootstrap.extra_access_dir,
            max_step_retries=bootstrap.max_step_retries,
            phase_timeout_seconds=bootstrap.phase_timeout_seconds,
            default_checks=list(bootstrap.check_commands),
        )
        self.app_settings = load_app_settings(self.settings_path, defaults)
        self.ollama_status = "Unknown"
        self.ollama_models: list[str] = []
        self.settings_window: Toplevel | None = None
        self.update_signal = CommitUpdateSignal(repo_path=bootstrap.repo_path)
        self.update_available = False
        self.reload_queued = False

        self._configure_style()
        self._refresh_ollama()
        self.create_window(root=root)
        self._schedule_update_poll()

    def iter_workspaces(self) -> list[WorkspacePane]:
        panes: list[WorkspacePane] = []
        for window in self.windows:
            for pane in window.tab_by_id.values():
                if isinstance(pane, WorkspacePane):
                    panes.append(pane)
        return panes

    def _detect_ai_art_dir(self) -> Path | None:
        if self.bootstrap.packaged_mode:
            return None
        candidates: list[Path] = []
        repo = self.bootstrap.repo_path
        candidates.append(repo.parent / "ai-art")
        env_ai_art = os.environ.get("AGENT_RUNNER_AI_ART_DIR", "").strip()
        if env_ai_art:
            candidates.append(Path(env_ai_art).expanduser())
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.layout("Tabless.TNotebook.Tab", [])
        style.layout("Tabless.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        style.configure("Root.TFrame", background="#f5f5f3")
        style.configure("Surface.TFrame", background="#fcfcfa")
        style.configure("ComposerShell.TFrame", background="#d8d7d1")
        style.configure("ComposerInner.TFrame", background="#fcfcfa")
        style.configure(
            "Conversation.Treeview",
            background="#fcfcfa",
            fieldbackground="#fcfcfa",
            foreground="#2d2c29",
            rowheight=26,
            borderwidth=0,
        )
        style.map(
            "Conversation.Treeview",
            background=[("selected", "#ecebe5")],
            foreground=[("selected", "#2d2c29")],
        )
        style.configure("Tooltip.TFrame", background="#2d2c29")
        style.configure(
            "Tooltip.TLabel",
            background="#2d2c29",
            foreground="#fcfcfa",
            font=("Helvetica", 10),
        )
        style.configure(
            "Headline.TLabel",
            background="#f5f5f3",
            foreground="#2d2c29",
            font=("Helvetica", 22, "bold"),
        )
        style.configure(
            "Subhead.TLabel",
            background="#f5f5f3",
            foreground="#6f726d",
            font=("Helvetica", 11),
        )
        style.configure(
            "SectionEyebrow.TLabel",
            background="#fcfcfa",
            foreground="#6f726d",
            font=("Helvetica", 9, "bold"),
        )
        style.configure(
            "SectionTitle.TLabel",
            background="#fcfcfa",
            foreground="#2d2c29",
            font=("Helvetica", 13, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background="#fcfcfa",
            foreground="#2d2c29",
            font=("Helvetica", 11),
        )
        style.configure(
            "Muted.TLabel",
            background="#fcfcfa",
            foreground="#8c8f89",
            font=("Helvetica", 10),
        )
        style.configure(
            "LoopPillOff.TFrame",
            background="#f3f2ed",
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "LoopPillOn.TFrame",
            background="#dfe8e0",
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "LoopPillOff.TLabel",
            background="#f3f2ed",
            foreground="#6f726d",
            font=("Helvetica", 11, "bold"),
        )
        style.configure(
            "LoopPillOn.TLabel",
            background="#dfe8e0",
            foreground="#35543f",
            font=("Helvetica", 11, "bold"),
        )
        style.configure(
            "Run.TButton",
            font=("Helvetica", 11, "bold"),
            foreground="#fcfcfa",
            background="#3f644b",
            borderwidth=0,
            focusthickness=0,
            padding=(16, 10),
        )
        style.map(
            "Run.TButton",
            background=[("active", "#35543f"), ("disabled", "#b7c2ba")],
            foreground=[("disabled", "#f2f2f0")],
        )
        style.configure(
            "Icon.TButton",
            font=("Helvetica", 10, "bold"),
            foreground="#5f625d",
            background="#f1f0eb",
            borderwidth=0,
            focusthickness=0,
            padding=(7, 4),
        )
        style.map(
            "Icon.TButton",
            background=[("active", "#e7e5de"), ("disabled", "#f3f2ee")],
            foreground=[("active", "#2d2c29"), ("disabled", "#b5b7b1")],
        )
        style.configure(
            "RunIcon.TButton",
            font=("Helvetica", 10, "bold"),
            foreground="#fcfcfa",
            background="#3f644b",
            borderwidth=0,
            focusthickness=0,
            padding=(7, 4),
        )
        style.map(
            "RunIcon.TButton",
            background=[("active", "#35543f"), ("disabled", "#b7c2ba")],
            foreground=[("disabled", "#f2f2f0")],
        )
    def next_workspace_id(self) -> str:
        self.workspace_counter += 1
        return f"workspace-{self.workspace_counter}"

    def create_window(self, root: Tk | None = None) -> WindowController:
        if root is None:
            root = Toplevel(self.root)
        window = WindowController(app=self, root=root)
        self.windows.append(window)
        root.protocol("WM_DELETE_WINDOW", window.close_window)
        return window

    def close_window(self, window: WindowController) -> None:
        if window not in self.windows:
            return
        self.windows.remove(window)
        window.root.destroy()
        if not self.windows:
            self.root.quit()

    def show_about_dialog(self) -> None:
        build_label = read_build_label(self.bootstrap.repo_path) or "Build unavailable"
        messagebox.showinfo(
            "About agent-runner",
            f"agent-runner\n\n{build_label}",
            parent=self.root,
        )

    def _schedule_update_poll(self) -> None:
        self.root.after(2500, self._poll_update_signal)

    def _poll_update_signal(self) -> None:
        try:
            update_available = self.update_signal.poll()
        except Exception:
            update_available = False
        if update_available != self.update_available:
            self.update_available = update_available
            self._sync_update_badges()
        self._maybe_perform_queued_reload()
        self._schedule_update_poll()

    def trigger_safe_reload(self, parent: Tk | Toplevel) -> None:
        if self.coordinator.active_workspace_id() is not None:
            if not self.reload_queued:
                self.reload_queued = True
                self._sync_update_badges()
                try:
                    messagebox.showinfo(
                        "Safe Reload Queued",
                        "Reload will happen after the current run finishes safely.",
                        parent=parent,
                    )
                except Exception:
                    pass
            return
        self._reload_process(parent=parent)

    def trigger_update_reload(self, parent: Tk | Toplevel) -> None:
        self.trigger_safe_reload(parent=parent)

    def finish_workspace_run(self, workspace_id: str) -> None:
        self.coordinator.finish(workspace_id)
        self._maybe_perform_queued_reload()

    def _sync_update_badges(self) -> None:
        for window in self.windows:
            if hasattr(window, "set_update_available"):
                window.set_update_available(self.update_available)
            if hasattr(window, "set_update_reload_queued"):
                window.set_update_reload_queued(self.reload_queued)

    def _maybe_perform_queued_reload(self) -> None:
        if not self.reload_queued:
            return
        if self.coordinator.active_workspace_id() is not None:
            return
        self.reload_queued = False
        self._sync_update_badges()
        self._reload_process(parent=self.root)

    def _reload_process(self, parent: Tk | Toplevel) -> None:
        try:
            if self.bootstrap.packaged_mode:
                executable = sys.executable
                self.root.after(50, lambda: os.execv(executable, [executable]))
                return
            bundle_path = os.environ.get("AGENT_RUNNER_APP_BUNDLE", "").strip()
            if bundle_path:
                subprocess.Popen(["open", "-na", bundle_path], cwd=str(self.bootstrap.repo_path))
            else:
                launcher = self.bootstrap.repo_path / "agent-runner.command"
                if launcher.exists():
                    subprocess.Popen(["/bin/bash", str(launcher)], cwd=str(self.bootstrap.repo_path))
                else:
                    executable = sys.executable
                    args = [executable, *sys.argv]
                    self.root.after(50, lambda: os.execv(executable, args))
                    return
            shutdown = getattr(self.root, "destroy", None) or getattr(self.root, "quit", None)
            if callable(shutdown):
                self.root.after(50, shutdown)
        except Exception as exc:  # pragma: no cover - UI fallback
            messagebox.showerror("agent-runner", f"Could not reload app: {exc}", parent=parent)

    def _refresh_ollama(self) -> None:
        probe = probe_ollama(self.app_settings.ollama_host)
        self.ollama_status = probe.message
        self.ollama_models = probe.models

    def open_settings_window(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_set()
            return

        self._refresh_ollama()
        win = Toplevel(self.root)
        win.title("Preferences")
        win.geometry("620x720")
        win.minsize(580, 660)
        win.configure(bg="#f5f5f3")
        self.settings_window = win

        frame = ttk.Frame(win, style="Root.TFrame", padding=(20, 18, 20, 18))
        frame.pack(fill="both", expand=True)

        provider_var = StringVar(value=str(self.app_settings.provider))
        model_var = StringVar(value=self.app_settings.model)
        codex_bin_var = StringVar(value=self.app_settings.codex_bin)
        ollama_host_var = StringVar(value=self.app_settings.ollama_host)
        extra_dir_var = StringVar(value="" if self.app_settings.extra_access_dir is None else str(self.app_settings.extra_access_dir))
        run_mode_var = StringVar(value=str(self.app_settings.default_run_mode))
        loop_count_var = StringVar(value=str(self.app_settings.max_step_retries + 1))
        preflight_var = BooleanVar(value=self.app_settings.preflight_clarifications)
        checks_policy_var = StringVar(value=str(self.app_settings.checks_policy))
        animate_var = BooleanVar(value=self.app_settings.animate_status_scenes)
        timeout_var = StringVar(value=str(self.app_settings.phase_timeout_seconds))
        checks_var = StringVar(value="\n".join(self.app_settings.default_checks))
        ollama_status_var = StringVar(value=self.ollama_status)

        ttk.Label(frame, text="SETTINGS", style="SectionEyebrow.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Global defaults", style="SectionTitle.TLabel").pack(anchor="w", pady=(2, 12))
        ttk.Label(
            frame,
            text="Loop mode keeps Codex planning, building, and checking until it reaches success or hits limits.",
            style="Muted.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(frame, style="Surface.TFrame", padding=(14, 12, 14, 12))
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="Provider", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        provider_box = ttk.Combobox(form, textvariable=provider_var, values=[str(ProviderKind.CODEX), str(ProviderKind.OLLAMA)], state="readonly")
        provider_box.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Model", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        model_values = sorted(set([self.app_settings.model, "gpt-5.3-codex", "gpt-5.4", *self.ollama_models]))
        model_box = ttk.Combobox(form, textvariable=model_var, values=model_values)
        model_box.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Codex binary", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=codex_bin_var).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Ollama host", style="Body.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=ollama_host_var).grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Extra access dir", style="Body.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=extra_dir_var).grid(row=4, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Default run mode", style="Body.TLabel").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(
            form,
            textvariable=run_mode_var,
            values=[str(RunMode.LOOP), str(RunMode.MESSAGE)],
            state="readonly",
        ).grid(row=5, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Default loop count", style="Body.TLabel").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=loop_count_var).grid(row=6, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Preflight clarifications", style="Body.TLabel").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Checkbutton(form, variable=preflight_var).grid(row=7, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Checks policy", style="Body.TLabel").grid(row=8, column=0, sticky="w", pady=4)
        ttk.Combobox(
            form,
            textvariable=checks_policy_var,
            values=[str(ChecksPolicy.AUTO), str(ChecksPolicy.CUSTOM)],
            state="readonly",
        ).grid(row=8, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Animate status scenes", style="Body.TLabel").grid(row=9, column=0, sticky="w", pady=4)
        ttk.Checkbutton(form, variable=animate_var).grid(row=9, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Phase timeout (sec)", style="Body.TLabel").grid(row=10, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=timeout_var).grid(row=10, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Default checks (one per line)", style="Body.TLabel").grid(row=11, column=0, sticky="nw", pady=4)
        checks_text = Text(form, height=5, relief="flat", bg="#fcfcfa", fg="#2d2c29", font=("Helvetica", 10), highlightthickness=1, highlightbackground="#dddcd7")
        checks_text.grid(row=11, column=1, sticky="ew", pady=4)
        checks_text.insert("1.0", checks_var.get())

        ttk.Label(
            form,
            text="When checks policy is auto, agent-runner uses task checks first and falls back to repo detection.",
            style="Muted.TLabel",
            wraplength=360,
        ).grid(row=12, column=1, sticky="w", pady=(2, 8))

        ttk.Label(
            form,
            text="Stop always means: finish the current phase, save progress, then halt safely.",
            style="Muted.TLabel",
            wraplength=360,
        ).grid(row=13, column=1, sticky="w", pady=(0, 8))

        ttk.Label(form, text="Ollama status", style="Body.TLabel").grid(row=14, column=0, sticky="w", pady=4)
        ttk.Label(form, textvariable=ollama_status_var, style="Muted.TLabel").grid(row=14, column=1, sticky="w", pady=4)

        form.columnconfigure(1, weight=1)

        def refresh_ollama() -> None:
            self.app_settings.ollama_host = ollama_host_var.get().strip() or self.app_settings.ollama_host
            self._refresh_ollama()
            ollama_status_var.set(self.ollama_status)
            updated_values = sorted(set([model_var.get(), "gpt-5.3-codex", "gpt-5.4", *self.ollama_models]))
            model_box.configure(values=updated_values)

        actions = ttk.Frame(frame, style="Root.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Refresh Ollama", command=refresh_ollama).pack(side="left")

        def save_settings() -> None:
            old_settings = self.app_settings
            provider = ProviderKind(provider_var.get())
            checks_blob = checks_text.get("1.0", "end").strip()
            checks = [line.strip() for line in checks_blob.splitlines() if line.strip()]
            default_loop_count = max(1, int(loop_count_var.get().strip() or "1"))
            self.app_settings = AppSettings(
                provider=provider,
                model=model_var.get().strip() or self.app_settings.model,
                codex_bin=codex_bin_var.get().strip() or "codex",
                ollama_host=ollama_host_var.get().strip() or self.app_settings.ollama_host,
                extra_access_dir=Path(extra_dir_var.get().strip()) if extra_dir_var.get().strip() else None,
                default_run_mode=RunMode(run_mode_var.get()),
                preflight_clarifications=bool(preflight_var.get()),
                checks_policy=ChecksPolicy(checks_policy_var.get()),
                animate_status_scenes=bool(animate_var.get()),
                max_step_retries=max(0, default_loop_count - 1),
                phase_timeout_seconds=max(1, int(timeout_var.get().strip() or "1")),
                default_checks=checks,
            )
            save_app_settings(self.settings_path, self.app_settings)
            old_loop_count = old_settings.max_step_retries + 1
            new_loop_count = self.app_settings.max_step_retries + 1
            for pane in self.iter_workspaces():
                if pane.override.run_mode == old_settings.default_run_mode:
                    pane.override.run_mode = self.app_settings.default_run_mode
                    pane._sync_loop_mode_ui()
                if (pane.override.loop_count or old_loop_count) == old_loop_count:
                    pane.override.loop_count = new_loop_count
                if not self.app_settings.animate_status_scenes and pane.is_running:
                    pane._stop_animation("running")
            win.destroy()

        ttk.Button(actions, text="Save", style="Run.TButton", command=save_settings).pack(side="right")

    def open_workspace_settings_modal(self, parent: Tk | Toplevel, pane: WorkspacePane) -> None:
        win = Toplevel(parent)
        win.title("Workspace Options")
        win.geometry("460x340")
        win.configure(bg="#f5f5f3")

        frame = ttk.Frame(win, style="Root.TFrame", padding=(16, 14, 16, 14))
        frame.pack(fill="both", expand=True)

        override_var = BooleanVar(value=pane.override.override_enabled)
        provider_var = StringVar(value=str(pane.override.provider))
        model_var = StringVar(value=pane.override.model)
        mode_var = StringVar(value=str(pane.override.run_mode))
        loop_count = pane.override.loop_count or (self.app_settings.max_step_retries + 1)
        loop_var = DoubleVar(value=float(loop_count))
        loop_label_var = StringVar(value=str(loop_count))

        ttk.Label(frame, text="WORKSPACE", style="SectionEyebrow.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Workspace run controls", style="SectionTitle.TLabel").pack(anchor="w", pady=(2, 10))
        ttk.Checkbutton(frame, text="Enable override", variable=override_var).pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(frame, style="Root.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Provider", style="Body.TLabel").pack(side="left")
        ttk.Combobox(row, textvariable=provider_var, values=[str(ProviderKind.CODEX), str(ProviderKind.OLLAMA)], state="readonly").pack(side="right")

        row2 = ttk.Frame(frame, style="Root.TFrame")
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Model", style="Body.TLabel").pack(side="left")
        ttk.Combobox(row2, textvariable=model_var, values=sorted(set([pane.override.model, self.app_settings.model, "gpt-5.3-codex", "gpt-5.4", *self.ollama_models]))).pack(side="right")

        row3 = ttk.Frame(frame, style="Root.TFrame")
        row3.pack(fill="x", pady=4)
        ttk.Label(row3, text="Run mode", style="Body.TLabel").pack(side="left")
        ttk.Combobox(
            row3,
            textvariable=mode_var,
            values=[str(RunMode.LOOP), str(RunMode.MESSAGE)],
            state="readonly",
        ).pack(side="right")

        row4 = ttk.Frame(frame, style="Root.TFrame")
        row4.pack(fill="x", pady=(8, 2))
        ttk.Label(row4, text="Loop count", style="Body.TLabel").pack(side="left")
        ttk.Label(row4, textvariable=loop_label_var, style="Muted.TLabel").pack(side="right")

        def on_scale_change(value: str) -> None:
            loop_label_var.set(str(int(round(float(value)))))

        ttk.Scale(
            frame,
            from_=1.0,
            to=6.0,
            orient="horizontal",
            variable=loop_var,
            command=on_scale_change,
        ).pack(fill="x", pady=(0, 8))

        def apply_changes() -> None:
            pane.override = WorkspaceSettings(
                override_enabled=bool(override_var.get()),
                provider=ProviderKind(provider_var.get()),
                model=model_var.get().strip() or self.app_settings.model,
                run_mode=RunMode(mode_var.get()),
                loop_count=max(1, int(round(loop_var.get()))),
            )
            pane._sync_loop_mode_ui()
            win.destroy()

        ttk.Button(frame, text="Apply", style="Run.TButton", command=apply_changes).pack(anchor="e", pady=(16, 0))


def launch_ui(settings: UiSettings) -> int:
    root = Tk()
    try:
        root.tk.call("tk", "appname", "agent-runner")
    except Exception:
        pass
    WorkspaceApp(root=root, bootstrap=settings)
    root.mainloop()
    return 0
