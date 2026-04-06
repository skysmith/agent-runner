from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        pass


@dataclass(slots=True)
class TaskSpec:
    task: str
    constraints: list[str]
    success_criteria: list[str]
    checks: list[str]
    source_path: Path


@dataclass(slots=True)
class PlanStep:
    id: str
    title: str
    instructions: str
    done_criteria: list[str]
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlannerResult:
    steps: list[PlanStep]
    assumptions: list[str]


@dataclass(slots=True)
class BuildResult:
    status: str
    summary: str
    files_touched: list[str]
    commands_run: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CheckResult:
    command: str
    return_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.return_code == 0


@dataclass(slots=True)
class ReviewResult:
    verdict: str
    task_complete: bool
    step_complete: bool
    issues: list[str]
    guidance: str


@dataclass(slots=True)
class StepRun:
    step_id: str
    attempt: int
    build_result: BuildResult
    check_results: list[CheckResult]
    review_result: ReviewResult


@dataclass(slots=True)
class RunOutcome:
    ok: bool
    reason: str
    step_runs: list[StepRun]
    planner_result: PlannerResult | None = None
    final_message: str = ""


class ProviderKind(StrEnum):
    CODEX = "codex"
    OLLAMA = "ollama"


class RunMode(StrEnum):
    LOOP = "loop"
    MESSAGE = "message"


class AssistantCapabilityMode(StrEnum):
    ASK = "ask"
    OPS = "ops"
    DEV = "dev"


class ChecksPolicy(StrEnum):
    AUTO = "auto"
    CUSTOM = "custom"


@dataclass(slots=True)
class WorkspaceSettings:
    override_enabled: bool = False
    provider: ProviderKind = ProviderKind.CODEX
    model: str = "gpt-5.3-codex"
    run_mode: RunMode = RunMode.MESSAGE
    loop_count: int | None = None


@dataclass(slots=True)
class ConversationMessage:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    run_id: str | None = None
    phase: str | None = None


@dataclass(slots=True)
class ConversationRecord:
    id: str
    workspace_id: str
    title: str
    created_at: str
    updated_at: str
    assistant_mode: AssistantCapabilityMode = AssistantCapabilityMode.ASK
    page_context: dict[str, object] = field(default_factory=dict)
    summary: str | None = None
    messages: list[ConversationMessage] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceSessionState:
    workspace_id: str
    active_conversation_id: str | None = None
    conversation_ids: list[str] = field(default_factory=list)
    conversations_panel_collapsed: bool = False
    display_name: str | None = None
    repo_path: str | None = None
    workspace_kind: str = "standard"
    artifact_title: str | None = None
    template_kind: str | None = None
    game_title: str | None = None
    theme_prompt: str | None = None
    preview_url: str | None = None
    preview_state: str | None = None
    publish_url: str | None = None
    publish_state: str | None = None
    publish_slug: str | None = None


@dataclass(slots=True)
class AppSettings:
    provider: ProviderKind = ProviderKind.CODEX
    model: str = "gpt-5.3-codex"
    planner_model: str | None = None
    builder_model: str | None = None
    reviewer_model: str | None = None
    codex_bin: str = "codex"
    ollama_host: str = "http://127.0.0.1:11434"
    extra_access_dir: Path | None = None
    default_run_mode: RunMode = RunMode.MESSAGE
    preflight_clarifications: bool = True
    checks_policy: ChecksPolicy = ChecksPolicy.AUTO
    animate_status_scenes: bool = True
    max_step_retries: int = 2
    phase_timeout_seconds: int = 240
    default_checks: list[str] = field(default_factory=list)
