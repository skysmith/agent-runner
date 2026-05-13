from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import mimetypes
import os
import traceback
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy_default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import qrcode
import qrcode.image.svg

from .models import AssistantCapabilityMode, RunMode
from .server_info import server_info
from .service import AgentRunnerService
from .update_signal import read_build_label
from .web_ui import (
    render_conversations,
    render_error_page,
    render_private_intake,
    render_thread,
    render_web_app,
    render_workspaces,
)

MAX_JSON_BODY_BYTES = 8 * 1024 * 1024
MAX_MULTIPART_BODY_BYTES = 45 * 1024 * 1024
OPENAI_REALTIME_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
OPENAI_REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
OPENAI_REALTIME_DEFAULT_MODEL = "gpt-realtime"
OPENAI_REALTIME_DEFAULT_VOICE = "marin"
OPENAI_REALTIME_DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"


class RequestBodyTooLargeError(ValueError):
    pass


def create_server(
    service: AgentRunnerService,
    host: str,
    port: int,
    *,
    access_password: str | None = None,
    native_transcriber: Callable[[str | None], dict[str, Any]] | None = None,
) -> ThreadingHTTPServer:
    password = (access_password or "").strip() or None

    def connections_payload(server_port: int, *, loopback_client: bool) -> dict[str, Any]:
        payload = server_info(
            host,
            server_port,
            repo_path=service.config.repo_path,
            build_label=read_build_label(service.config.repo_path),
        )
        local_url = str(payload["localhost_url"])
        phone_url = str(payload["tailscale_url"] or "").strip()
        payload["local_url"] = local_url
        payload["phone_url"] = phone_url or None
        payload["phone_enabled"] = bool(phone_url)
        payload["phone_reason"] = (
            "Available on Tailscale."
            if phone_url
            else "Tailscale phone access is not available right now."
        )
        payload["native_transcription_available"] = native_transcriber is not None and loopback_client
        payload["native_transcription_provider"] = (
            "macos-wrapper" if native_transcriber is not None and loopback_client else None
        )
        realtime_key_available = bool(_openai_api_key())
        payload["realtime_voice_available"] = realtime_key_available and loopback_client
        payload["realtime_voice_provider"] = "openai" if realtime_key_available and loopback_client else None
        payload["realtime_voice_model"] = _openai_realtime_model()
        payload["realtime_voice_calls_url"] = (
            OPENAI_REALTIME_CALLS_URL if realtime_key_available and loopback_client else None
        )
        if not loopback_client:
            realtime_reason = "Realtime voice is only available from this machine in the local prototype."
        elif not realtime_key_available:
            realtime_reason = "Set OPENAI_API_KEY to enable realtime voice."
        else:
            realtime_reason = "OpenAI Realtime voice is ready."
        payload["realtime_voice_reason"] = realtime_reason
        return payload

    class CompanionHandler(BaseHTTPRequestHandler):
        server_version = "alcove-web/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if not self._authorized(path):
                return
            try:
                if path == "/api/workspaces":
                    self._json_response({"workspaces": service.list_workspaces()})
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/studio"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.get_studio_workspace(workspace_id))
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/field-station"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.get_field_station_snapshot(workspace_id))
                    return
                if path == "/api/field-station/snapshot":
                    self._json_response(
                        service.get_field_station_snapshot(
                            _required_query_text(query, "workspace_id"),
                        )
                    )
                    return
                if path == "/api/field-station/briefing-sources":
                    self._json_response(
                        service.list_field_station_briefing_sources(
                            _required_query_text(query, "workspace_id"),
                        )
                    )
                    return
                if path == "/api/field-station/artifact":
                    self._json_response(
                        service.get_field_station_artifact(
                            workspace_id=_required_query_text(query, "workspace_id"),
                            artifact_path=_required_query_text(query, "path"),
                        )
                    )
                    return
                if path == "/api/field-station/capture-assets":
                    self._file_response(
                        service.field_station_capture_asset_file(
                            workspace_id=_required_query_text(query, "workspace_id"),
                            asset_path=_required_query_text(query, "path"),
                        )
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.get_image_workflow_snapshot(workspace_id))
                    return
                if path == "/api/settings":
                    self._json_response(service.get_settings())
                    return
                if path == "/api/setup-check":
                    self._json_response(service.get_setup_status())
                    return
                if path == "/api/providers/ollama/models":
                    self._json_response(service.list_ollama_models())
                    return
                if path == "/api/repositories/active":
                    limit = _query_int(query, "limit", default=12)
                    root_text = _query_text(query, "root")
                    root = Path(root_text).expanduser() if root_text else None
                    self._json_response(
                        {
                            "repositories": service.list_active_repositories(
                                root=root,
                                limit=limit,
                            )
                        }
                    )
                    return
                if path == "/api/conversations":
                    self._json_response({"conversations": service.list_all_conversations()})
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/conversations"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        {
                            "conversations": service.list_conversations(
                                workspace_id,
                                include_archived=_query_bool(query, "include_archived"),
                            )
                        }
                    )
                    return
                if path.startswith("/api/workspaces/"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.ensure_workspace(workspace_id))
                    return
                if path.startswith("/api/conversations/"):
                    if path.endswith("/context"):
                        conversation_id = _path_part(path, 2)
                        conversation = service.get_conversation(
                            conversation_id,
                            workspace_id=_query_text(query, "workspace_id"),
                        )
                        self._json_response(
                            {
                                "conversation_id": conversation_id,
                                "workspace_id": conversation.get("workspace_id"),
                                "assistant_mode": conversation.get("assistant_mode", "ask"),
                                "page_context": conversation.get("page_context", {}),
                                "thread_context": conversation.get("thread_context", {}),
                            }
                        )
                        return
                    conversation_id = _path_part(path, 2)
                    self._json_response(
                        service.get_conversation(
                            conversation_id,
                            workspace_id=_query_text(query, "workspace_id"),
                        )
                    )
                    return
                if path == "/api/run-status":
                    self._json_response(service.get_run_status())
                    return
                if path == "/api/review":
                    self._json_response(
                        service.get_review_snapshot(
                            conversation_id=_query_text(query, "conversation_id"),
                            workspace_id=_query_text(query, "workspace_id"),
                        )
                    )
                    return
                if path == "/api/events/since":
                    self._json_response(
                        service.list_events_since(
                            cursor=_query_text(query, "cursor"),
                            limit=_query_int(query, "limit", default=100),
                        )
                    )
                    return
                if path == "/api/server-info":
                    self._json_response(
                        connections_payload(
                            self.server.server_port,
                            loopback_client=self._is_loopback_client(),
                        )
                    )
                    return
                if path == "/api/connections":
                    self._json_response(
                        connections_payload(
                            self.server.server_port,
                            loopback_client=self._is_loopback_client(),
                        )
                    )
                    return
                if path == "/api/connections/phone-qr.svg":
                    payload = connections_payload(
                        self.server.server_port,
                        loopback_client=self._is_loopback_client(),
                    )
                    phone_url = str(payload.get("phone_url") or "").strip()
                    if not phone_url:
                        self._error_response(HTTPStatus.CONFLICT, "Phone access is not available.")
                        return
                    self._svg_response(_qr_svg(phone_url))
                    return
                if path == "/":
                    self._html_response(render_web_app())
                    return
                if path == "/intake":
                    self._html_response(
                        render_private_intake(
                            default_workspace_id=_query_text(query, "workspace_id") or "skyler-intake"
                        )
                    )
                    return
                if path.startswith("/studio/preview/"):
                    workspace_id = _path_part(path, 2)
                    relative_path = _relative_file_path(path, prefix=f"/studio/preview/{workspace_id}/")
                    self._file_response(service.studio_preview_file(workspace_id, relative_path))
                    return
                if path.startswith("/play/"):
                    publish_slug = _path_part(path, 1)
                    relative_path = _relative_file_path(path, prefix=f"/play/{publish_slug}/")
                    self._file_response(service.published_game_file(publish_slug, relative_path))
                    return
                if path.startswith("/workspace-media/"):
                    workspace_id = _path_part(path, 1)
                    relative_path = _relative_file_path(path, prefix=f"/workspace-media/{workspace_id}/")
                    self._file_response(service.image_workflow_file(workspace_id, relative_path))
                    return
                if path == "/m":
                    self._html_response(render_workspaces(service))
                    return
                if path.startswith("/m/workspaces/"):
                    workspace_id = _path_part(path, 2)
                    self._html_response(render_conversations(service, workspace_id))
                    return
                if path.startswith("/m/conversations/"):
                    conversation_id = _path_part(path, 2)
                    self._html_response(
                        render_thread(
                            service,
                            conversation_id,
                            workspace_id=_query_text(query, "workspace_id"),
                        )
                    )
                    return
                self._error_response(HTTPStatus.NOT_FOUND, "Not found")
            except KeyError:
                self._error_response(HTTPStatus.NOT_FOUND, "Conversation not found")
            except FileNotFoundError:
                self._error_response(HTTPStatus.NOT_FOUND, "File not found")
            except ValueError as exc:
                self._error_response(HTTPStatus.BAD_REQUEST, str(exc))
            except RuntimeError as exc:
                self._error_response(HTTPStatus.CONFLICT, str(exc))
            except Exception as exc:
                self._unexpected_error(path, exc)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._authorized(path):
                return
            try:
                if path == "/api/workspaces":
                    body = self._json_body()
                    self._json_response(
                        service.define_workspace(
                            _required_body_text(body, "id"),
                            display_name=_body_text(body, "display_name"),
                            repo_path=_body_text(body, "repo_path"),
                            workspace_kind=_body_text(body, "workspace_kind"),
                            artifact_title=_body_text(body, "artifact_title"),
                            template_kind=_body_text(body, "template_kind"),
                            game_title=_body_text(body, "game_title"),
                            theme_prompt=_body_text(body, "theme_prompt"),
                            preview_url=_body_text(body, "preview_url"),
                            preview_state=_body_text(body, "preview_state"),
                            publish_url=_body_text(body, "publish_url"),
                            publish_state=_body_text(body, "publish_state"),
                            publish_slug=_body_text(body, "publish_slug"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/studio/workspaces":
                    body = self._json_body()
                    self._json_response(
                        service.create_studio_workspace(
                            workspace_kind=_body_text(body, "workspace_kind") or "studio_game",
                            artifact_title=_required_body_text(body, "artifact_title"),
                            template_kind=_body_text(body, "template_kind") or "",
                            theme_prompt=_body_text(body, "theme_prompt"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/field-station/missions":
                    body = self._json_body()
                    self._json_response(
                        service.create_field_station_mission(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            conversation_id=_body_text(body, "conversation_id"),
                            source=_body_text(body, "source"),
                            mode=_body_text(body, "mode"),
                            goal=_required_body_text(body, "goal"),
                            target=_body_text(body, "target"),
                            permission_lane=_body_text(body, "permission_lane"),
                            expected_output=_body_text(body, "expected_output"),
                            requires_approval=bool(body.get("requires_approval", True)),
                            capture_id=_body_text(body, "capture_id"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/field-station/captures":
                    body = self._json_body()
                    self._json_response(
                        service.create_field_station_capture(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            mode=_body_text(body, "mode"),
                            source=_body_text(body, "source"),
                            text=_required_body_text(body, "text"),
                            attachments=body.get("attachments") if isinstance(body.get("attachments"), list) else None,
                            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/field-station/capture-assets":
                    body = self._json_body()
                    self._json_response(
                        service.create_field_station_capture_asset(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            data_url=_required_body_text(body, "data_url"),
                            file_name=_body_text(body, "file_name"),
                            label=_body_text(body, "label"),
                            source=_body_text(body, "source"),
                            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/field-station/briefing-sources":
                    body = self._json_body()
                    self._json_response(
                        service.create_field_station_briefing_source(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            kind=_body_text(body, "kind"),
                            label=_required_body_text(body, "label"),
                            summary=_body_text(body, "summary"),
                            sample_items=body.get("sample_items") if isinstance(body.get("sample_items"), list) else None,
                            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/field-station/owner-briefings":
                    body = self._json_body()
                    self._json_response(
                        service.create_field_station_owner_briefing(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            source_ids=body.get("source_ids") if isinstance(body.get("source_ids"), list) else None,
                            note=_body_text(body, "note"),
                            provider=_body_text(body, "provider"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/field-station/jobs":
                    body = self._json_body()
                    self._json_response(
                        service.create_field_station_job(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            mission_id=_required_body_text(body, "mission_id"),
                            provider=_body_text(body, "provider"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/field-station/jobs/") and path.endswith("/cancel"):
                    body = self._json_body()
                    self._json_response(
                        service.cancel_field_station_job(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            job_id=_path_part(path, 3),
                        )
                    )
                    return
                if path == "/api/field-station/station-events":
                    body = self._json_body()
                    self._json_response(
                        service.trigger_field_station_station_event(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            event_type=_required_body_text(body, "event_type"),
                            payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/field-station/reviews/") and path.endswith("/approve"):
                    body = self._json_body()
                    self._json_response(
                        service.approve_field_station_review(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            review_id=_path_part(path, 3),
                        )
                    )
                    return
                if path == "/api/studio/games":
                    body = self._json_body()
                    self._json_response(
                        service.create_studio_game(
                            game_title=_required_body_text(body, "game_title"),
                            template_kind=_body_text(body, "template_kind") or "",
                            theme_prompt=_body_text(body, "theme_prompt"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/generate"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.queue_image_generation(
                            workspace_id=workspace_id,
                            prompt=_required_body_text(body, "prompt"),
                            count=int(body.get("count") or 1),
                            prompt_context=_body_text(body, "prompt_context"),
                            auto_refine=_body_object(body, "auto_refine"),
                            size_profile_id=_body_text(body, "size_profile_id"),
                            passes=int(body.get("passes") or 0) or None,
                            lora_name=_body_text(body, "lora_name"),
                            lora_strength=body.get("lora_strength"),
                            composition_source_image_id=_body_text(body, "composition_source_image_id"),
                            remix_mode=_body_text(body, "remix_mode"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/library-folder"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    if not self._is_loopback_client():
                        self._error_response(HTTPStatus.FORBIDDEN, "Local image library folders are only available from this machine.")
                        return
                    self._json_response(
                        service.set_image_library_folder(
                            workspace_id=workspace_id,
                            folder_path=_required_body_text(body, "folder_path"),
                        ),
                        status=HTTPStatus.OK,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/open-folder"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.open_image_asset_folder(workspace_id=workspace_id),
                        status=HTTPStatus.OK,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/describe-reference"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.describe_image_reference(
                            workspace_id=workspace_id,
                            source_image_id=_body_text(body, "source_image_id"),
                            prompt_context=_body_text(body, "prompt_context"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/make-3d"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.make_image_3d(
                            workspace_id=workspace_id,
                            source_image_id=_body_text(body, "source_image_id"),
                            prompt_context=_body_text(body, "prompt_context"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/animate"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.animate_image(
                            workspace_id=workspace_id,
                            source_image_id=_body_text(body, "source_image_id"),
                            prompt_context=_body_text(body, "prompt_context"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/assets"):
                    workspace_id = _path_part(path, 2)
                    content_type = (self.headers.get("Content-Type") or "").strip().lower()
                    if not content_type.startswith("multipart/form-data"):
                        raise ValueError("Image uploads must use multipart/form-data.")
                    _, files = self._multipart_body()
                    uploaded = self._store_uploaded_image_asset(files)
                    self._json_response(
                        service.upload_image_asset(
                            workspace_id=workspace_id,
                            file_name=uploaded["file_name"],
                            mime_type=uploaded["mime_type"],
                            data=uploaded["data"],
                            prompt_context=uploaded["prompt_context"],
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/image-workflow/import-path"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    if not self._is_loopback_client():
                        self._error_response(HTTPStatus.FORBIDDEN, "Local image import is only available from this machine.")
                        return
                    self._json_response(
                        service.import_image_asset_from_path(
                            workspace_id=workspace_id,
                            image_path=_required_body_text(body, "image_path"),
                            prompt_context=_body_text(body, "prompt_context"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/workspaces/import-folder":
                    body = self._json_body()
                    repo_path = _body_text(body, "repo_path")
                    if repo_path:
                        workspace = service.import_workspace_from_path(
                            repo_path,
                            display_name=_body_text(body, "display_name"),
                            workspace_kind=_body_text(body, "workspace_kind"),
                        )
                    else:
                        if not self._is_loopback_client():
                            self._error_response(HTTPStatus.FORBIDDEN, "Native folder picker is only available from this machine.")
                            return
                        selected_path = service.pick_local_folder_path()
                        workspace = service.import_workspace_from_path(
                            selected_path,
                            display_name=_body_text(body, "display_name"),
                            workspace_kind=_body_text(body, "workspace_kind"),
                        )
                    self._json_response(workspace, status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/conversations"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.create_conversation(
                            workspace_id,
                            title=_body_text(body, "title"),
                            thread_context=_body_object(body, "thread_context"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/conversations":
                    body = self._json_body()
                    self._json_response(
                        service.create_web_conversation(title=_body_text(body, "title")),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/conversations/") and path.endswith("/messages"):
                    conversation_id = _path_part(path, 2)
                    request_payload = self._message_body(conversation_id=conversation_id)
                    conversation = service.get_conversation(
                        conversation_id,
                        workspace_id=_body_text(request_payload, "workspace_id"),
                    )
                    self._json_response(
                        service.send_message(
                            workspace_id=str(conversation["workspace_id"]),
                            conversation_id=conversation_id,
                            content=_required_body_text(request_payload, "content"),
                            mode=RunMode(_body_text(request_payload, "mode") or "message"),
                            assistant_mode=_body_assistant_mode(request_payload),
                            page_context=_body_object(request_payload, "page_context"),
                            thread_context=_body_object(request_payload, "thread_context"),
                        )
                    )
                    return
                if path == "/api/external/messages":
                    body = self._json_body()
                    self._json_response(
                        service.deliver_external_message(
                            workspace_id=_required_body_text(body, "workspace_id"),
                            content=_required_body_text(body, "content"),
                            thread_context=_body_object(body, "thread_context") or {},
                            mode=RunMode(_body_text(body, "mode") or "message"),
                            assistant_mode=_body_assistant_mode(body),
                            page_context=_body_object(body, "page_context"),
                        ),
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if path.startswith("/api/conversations/") and path.endswith("/clear"):
                    conversation_id = _path_part(path, 2)
                    body = self._json_body()
                    self._json_response(
                        service.clear_conversation(
                            conversation_id,
                            workspace_id=_body_text(body, "workspace_id"),
                        )
                    )
                    return
                if path.startswith("/api/conversations/") and path.endswith("/archive"):
                    conversation_id = _path_part(path, 2)
                    body = self._json_body()
                    self._json_response(
                        service.archive_conversation(
                            conversation_id,
                            workspace_id=_body_text(body, "workspace_id"),
                        )
                    )
                    return
                if path.startswith("/api/conversations/") and path.endswith("/restore"):
                    conversation_id = _path_part(path, 2)
                    body = self._json_body()
                    self._json_response(
                        service.restore_conversation(
                            conversation_id,
                            workspace_id=_body_text(body, "workspace_id"),
                        )
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/runs"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    conversations = service.list_conversations(workspace_id)
                    if not conversations:
                        conversation = service.create_conversation(workspace_id)
                        conversation_id = str(conversation["id"])
                    else:
                        conversation_id = str(conversations[0]["id"])
                    self._json_response(
                        service.send_message(
                            workspace_id=workspace_id,
                            conversation_id=conversation_id,
                            content=_required_body_text(body, "content"),
                            mode=RunMode.LOOP,
                        )
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/studio/refresh"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.refresh_studio_preview(workspace_id))
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/studio/publish"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.publish_studio_game(workspace_id))
                    return
                if path == "/api/native/transcribe":
                    if not self._is_loopback_client():
                        self._error_response(HTTPStatus.FORBIDDEN, "Native transcription is only available from this machine.")
                        return
                    if native_transcriber is None:
                        self._error_response(HTTPStatus.CONFLICT, "Native transcription is not available in this build.")
                        return
                    body = self._json_body()
                    self._json_response(native_transcriber(_body_text(body, "locale")))
                    return
                if path == "/api/field-station/realtime-client-secret":
                    if not self._is_loopback_client():
                        self._error_response(HTTPStatus.FORBIDDEN, "Realtime voice is only available from this machine.")
                        return
                    if not _openai_api_key():
                        self._error_response(HTTPStatus.CONFLICT, "Set OPENAI_API_KEY to enable realtime voice.")
                        return
                    body = self._json_body()
                    self._json_response(
                        _create_openai_realtime_client_secret(
                            mode=_body_text(body, "mode"),
                            current_text=_body_text(body, "current_text"),
                            repo_path=service.config.repo_path,
                        )
                    )
                    return
                if path == "/api/runs/stop-safely":
                    self._json_response(service.stop_run())
                    return
                if path == "/api/runs/recover":
                    self._json_response(service.recover_run())
                    return
                if path == "/api/runs/retry-last":
                    self._json_response(service.retry_last_prompt())
                    return
                self._error_response(HTTPStatus.NOT_FOUND, "Not found")
            except KeyError:
                self._error_response(HTTPStatus.NOT_FOUND, "Conversation not found")
            except RequestBodyTooLargeError as exc:
                self._error_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(exc))
            except ValueError as exc:
                self._error_response(HTTPStatus.BAD_REQUEST, str(exc))
            except RuntimeError as exc:
                self._error_response(HTTPStatus.CONFLICT, str(exc))
            except Exception as exc:
                self._unexpected_error(path, exc)

        def do_PATCH(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._authorized(path):
                return
            try:
                body = self._json_body()
                if path == "/api/settings":
                    self._json_response(service.update_settings(body))
                    return
                if path.startswith("/api/workspaces/"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.rename_workspace(
                            workspace_id,
                            display_name=_required_body_text(body, "display_name"),
                        )
                    )
                    return
                if path.startswith("/api/conversations/"):
                    if path.endswith("/context"):
                        conversation_id = _path_part(path, 2)
                        self._json_response(
                            service.update_conversation_context(
                                conversation_id,
                                workspace_id=_body_text(body, "workspace_id"),
                                assistant_mode=_body_assistant_mode(body),
                                page_context=_body_object(body, "page_context"),
                                thread_context=_body_object(body, "thread_context"),
                            )
                        )
                        return
                    conversation_id = _path_part(path, 2)
                    self._json_response(
                        service.rename_conversation(
                            conversation_id,
                            workspace_id=_body_text(body, "workspace_id"),
                            title=_required_body_text(body, "title"),
                        )
                    )
                    return
                self._error_response(HTTPStatus.NOT_FOUND, "Not found")
            except KeyError:
                self._error_response(HTTPStatus.NOT_FOUND, "Conversation not found")
            except RequestBodyTooLargeError as exc:
                self._error_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(exc))
            except ValueError as exc:
                self._error_response(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                self._unexpected_error(path, exc)

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if not self._authorized(path):
                return
            try:
                if path.startswith("/api/workspaces/") and "/image-workflow/assets/" in path:
                    workspace_id = _path_part(path, 2)
                    image_id = _path_part(path, 5)
                    self._json_response(
                        service.delete_image_asset(
                            workspace_id=workspace_id,
                            image_id=image_id,
                        )
                    )
                    return
                if path.startswith("/api/workspaces/"):
                    workspace_id = _path_part(path, 2)
                    self._json_response(service.delete_workspace(workspace_id))
                    return
                if path.startswith("/api/conversations/"):
                    conversation_id = _path_part(path, 2)
                    self._json_response(
                        service.delete_conversation(
                            conversation_id,
                            workspace_id=_query_text(query, "workspace_id"),
                        )
                    )
                    return
                self._error_response(HTTPStatus.NOT_FOUND, "Not found")
            except KeyError:
                self._error_response(HTTPStatus.NOT_FOUND, "Conversation not found")
            except Exception as exc:
                self._unexpected_error(path, exc)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json_body(self) -> dict[str, Any]:
            raw = self._raw_body()
            if not raw:
                return {}
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON body.") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object.")
            return payload

        def _message_body(self, *, conversation_id: str) -> dict[str, Any]:
            content_type = (self.headers.get("Content-Type") or "").strip().lower()
            if not content_type.startswith("multipart/form-data"):
                return self._json_body()

            fields, files = self._multipart_body()
            workspace_id = self._multipart_text(fields, "workspace_id")
            payload = {
                "workspace_id": workspace_id,
                "mode": self._multipart_text(fields, "mode"),
                "assistant_mode": self._multipart_text(fields, "assistant_mode"),
                "content": self._multipart_text(fields, "content"),
                "page_context": self._multipart_json_object(fields, "page_context"),
                "thread_context": self._multipart_json_object(fields, "thread_context"),
            }
            attachment_lines = self._store_uploaded_images(
                files,
                workspace_id=workspace_id or AgentRunnerService.DEFAULT_WEB_WORKSPACE_ID,
                conversation_id=conversation_id,
            )
            payload["content"] = _merge_content_and_attachments(
                base_content=str(payload.get("content") or ""),
                attachment_lines=attachment_lines,
            )
            return payload

        def _multipart_body(self) -> tuple[dict[str, list[str]], list[dict[str, object]]]:
            content_type = self.headers.get("Content-Type", "")
            raw = self._raw_body()
            if not raw:
                return {}, []
            wrapped = (
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
            )
            message = BytesParser(policy=email_policy_default).parsebytes(wrapped)
            fields: dict[str, list[str]] = {}
            files: list[dict[str, object]] = []
            for part in message.iter_parts():
                if part.get_content_disposition() != "form-data":
                    continue
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if filename:
                    files.append(
                        {
                            "name": str(name),
                            "filename": str(filename),
                            "content_type": part.get_content_type().lower(),
                            "data": payload,
                        }
                    )
                    continue
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                fields.setdefault(str(name), []).append(text)
            return fields, files

        def _multipart_text(self, fields: dict[str, list[str]], key: str) -> str:
            values = fields.get(key, [])
            if not values:
                return ""
            return str(values[0]).strip()

        def _multipart_json_object(self, fields: dict[str, list[str]], key: str) -> dict[str, object] | None:
            text = self._multipart_text(fields, key)
            if not text:
                return None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON for multipart field '{key}'.") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"Multipart field '{key}' must be a JSON object.")
            return {str(name): value for name, value in parsed.items()}

        def _store_uploaded_images(
            self,
            uploads: list[dict[str, object]],
            *,
            workspace_id: str,
            conversation_id: str,
        ) -> list[str]:
            if not uploads:
                return []

            safe_workspace_id = _safe_storage_segment(workspace_id, label="Workspace id")
            safe_conversation_id = _safe_storage_segment(conversation_id, label="Conversation id")
            uploads_dir = (
                service.config.repo_path / ".agent-runner" / "uploads" / safe_workspace_id / safe_conversation_id
            )
            uploads_dir.mkdir(parents=True, exist_ok=True)
            max_files = 4
            max_bytes = 10 * 1024 * 1024
            lines: list[str] = []
            saved_count = 0
            for item in uploads:
                if str(item.get("name", "")) != "attachments":
                    continue
                if not item.get("filename"):
                    continue
                mime = str(item.get("content_type", "")).strip().lower()
                if not mime.startswith("image/"):
                    continue
                data = item.get("data")
                if not isinstance(data, bytes):
                    continue
                if len(data) > max_bytes:
                    raise ValueError("Each screenshot must be 10MB or smaller.")
                file_name = f"{uuid.uuid4().hex}{_image_suffix_from_mime(mime)}"
                destination = uploads_dir / file_name
                destination.write_bytes(data)
                lines.append(f"- Screenshot: {destination} ({mime}, {len(data)} bytes)")
                saved_count += 1
                if saved_count >= max_files:
                    break
            return lines

        def _store_uploaded_image_asset(self, uploads: list[dict[str, object]]) -> dict[str, object]:
            max_bytes = 20 * 1024 * 1024
            for item in uploads:
                if str(item.get("name", "")) not in {"asset", "file", "attachments"}:
                    continue
                file_name = str(item.get("filename", "")).strip()
                if not file_name:
                    continue
                mime = str(item.get("content_type", "")).strip().lower()
                if not mime.startswith("image/"):
                    continue
                data = item.get("data")
                if not isinstance(data, bytes):
                    continue
                if len(data) > max_bytes:
                    raise ValueError("Each uploaded image must be 20MB or smaller.")
                return {
                    "file_name": file_name,
                    "mime_type": mime,
                    "data": data,
                    "prompt_context": None,
                }
            raise ValueError("No image file was uploaded.")

        def _raw_body(self) -> bytes:
            length_header = (self.headers.get("Content-Length") or "0").strip()
            try:
                length = int(length_header or "0")
            except ValueError as exc:
                raise ValueError("Invalid Content-Length header.") from exc
            if length <= 0:
                return b""
            if length > _request_body_limit(self.headers.get("Content-Type", "")):
                raise RequestBodyTooLargeError("Request body is too large.")
            return self.rfile.read(length)

        def _json_response(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _html_response(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _svg_response(self, svg: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = svg.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file_response(self, path: Path, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = path.read_bytes()
            content_type, _ = mimetypes.guess_type(str(path))
            if path.suffix == ".html":
                text = data.decode("utf-8", errors="replace")
                if (path.parent / "assets").exists():
                    text = text.replace('src="/assets/', 'src="./assets/')
                    text = text.replace("src='/assets/", "src='./assets/")
                    text = text.replace('href="/assets/', 'href="./assets/')
                    text = text.replace("href='/assets/", "href='./assets/")
                data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            if path.suffix in {".html", ".js", ".css"}:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _error_response(self, status: HTTPStatus, detail: str) -> None:
            self._json_response({"detail": detail}, status=status)

        def _unexpected_error(self, path: str, exc: Exception) -> None:
            traceback.print_exc()
            detail = f"Companion UI hit an unexpected error while serving {path}: {exc}"
            if path.startswith("/m") or path == "/":
                self._html_response(render_error_page(detail), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._error_response(HTTPStatus.INTERNAL_SERVER_ERROR, detail)

        def _authorized(self, path: str) -> bool:
            if password is None:
                return True
            if self._has_valid_auth_header():
                return True
            if path.startswith("/api/"):
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("WWW-Authenticate", 'Basic realm="alcove"')
                self.send_header("Content-Type", "application/json; charset=utf-8")
                data = json.dumps({"detail": "Authentication required."}).encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return False
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="alcove"')
            data = b"Authentication required."
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return False

        def _has_valid_auth_header(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            encoded = header[6:].strip()
            if not encoded:
                return False
            try:
                decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
            except Exception:
                return False
            if ":" not in decoded:
                return False
            _, supplied_password = decoded.split(":", 1)
            return supplied_password == password

        def _is_loopback_client(self) -> bool:
            host = str(self.client_address[0] or "").strip()
            try:
                return ipaddress.ip_address(host).is_loopback
            except ValueError:
                return host in {"localhost"}

    return ThreadingHTTPServer((host, port), CompanionHandler)


def _path_part(path: str, index: int) -> str:
    parts = path.strip("/").split("/")
    if len(parts) <= index:
        raise ValueError("Malformed path.")
    return parts[index]


def _relative_file_path(path: str, *, prefix: str) -> str:
    if not path.startswith(prefix):
        return "index.html"
    remainder = path[len(prefix):].strip("/")
    return remainder or "index.html"


def _query_text(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    text = values[0].strip()
    return text or None


def _required_query_text(query: dict[str, list[str]], key: str) -> str:
    text = _query_text(query, key)
    if not text:
        raise ValueError(f"Missing required query parameter: {key}.")
    return text


def _query_int(query: dict[str, list[str]], key: str, *, default: int) -> int:
    text = _query_text(query, key)
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        return default
    return value


def _query_bool(query: dict[str, list[str]], key: str) -> bool:
    text = _query_text(query, key)
    if not text:
        return False
    return text.strip().lower() in {"1", "true", "yes", "on"}


def _body_text(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _body_object(body: dict[str, Any], key: str) -> dict[str, object] | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Field '{key}' must be an object.")
    return {str(name): item for name, item in value.items()}


def _body_assistant_mode(body: dict[str, Any]) -> AssistantCapabilityMode | None:
    text = _body_text(body, "assistant_mode")
    if not text:
        return None
    try:
        return AssistantCapabilityMode(text.lower())
    except ValueError as exc:
        raise ValueError("assistant_mode must be one of: ask, ops, dev.") from exc


def _required_body_text(body: dict[str, Any], key: str) -> str:
    text = _body_text(body, key)
    if not text:
        raise ValueError(f"Missing required field: {key}.")
    return text


def _openai_api_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def _openai_realtime_model() -> str:
    return os.environ.get("ALCOVE_REALTIME_MODEL", "").strip() or OPENAI_REALTIME_DEFAULT_MODEL


def _openai_realtime_voice() -> str:
    return os.environ.get("ALCOVE_REALTIME_VOICE", "").strip() or OPENAI_REALTIME_DEFAULT_VOICE


def _openai_realtime_transcription_model() -> str:
    return (
        os.environ.get("ALCOVE_REALTIME_TRANSCRIPTION_MODEL", "").strip()
        or OPENAI_REALTIME_DEFAULT_TRANSCRIPTION_MODEL
    )


def _create_openai_realtime_client_secret(
    *,
    mode: str | None,
    current_text: str | None,
    repo_path: Path,
) -> dict[str, Any]:
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY to enable realtime voice.")

    model = _openai_realtime_model()
    voice = _openai_realtime_voice()
    transcription_model = _openai_realtime_transcription_model()
    session_config: dict[str, Any] = {
        "type": "realtime",
        "model": model,
        "instructions": _field_station_realtime_instructions(mode=mode, current_text=current_text),
        "audio": {
            "output": {"voice": voice},
            "input": {
                "transcription": {"model": transcription_model},
                "turn_detection": {"type": "server_vad", "create_response": True},
            },
        },
        "output_modalities": ["audio"],
        "tools": [_field_station_realtime_queue_tool()],
        "tool_choice": "auto",
    }
    request_body = json.dumps({"session": session_config}).encode("utf-8")
    request = urllib.request.Request(
        OPENAI_REALTIME_CLIENT_SECRET_URL,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Safety-Identifier": _privacy_preserving_safety_identifier(repo_path),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"OpenAI Realtime client secret failed: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI Realtime client secret failed: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI Realtime client secret returned an invalid payload.")
    client_secret = _normalize_openai_client_secret_payload(payload)
    return {
        "provider": "openai",
        "model": model,
        "voice": voice,
        "transcription_model": transcription_model,
        "calls_url": OPENAI_REALTIME_CALLS_URL,
        "client_secret": client_secret,
    }


def _normalize_openai_client_secret_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = str(payload.get("value") or "").strip()
    expires_at = payload.get("expires_at")
    if not value:
        session = payload.get("session")
        if isinstance(session, dict):
            secret = session.get("client_secret")
            if isinstance(secret, dict):
                value = str(secret.get("value") or "").strip()
                expires_at = expires_at or secret.get("expires_at")
    if not value:
        raise RuntimeError("OpenAI Realtime client secret response did not include a token value.")
    return {
        "value": value,
        "expires_at": expires_at,
    }


def _privacy_preserving_safety_identifier(repo_path: Path) -> str:
    raw = f"alcove-field-station:{repo_path.resolve()}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def _field_station_realtime_queue_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "queue_alcove_job",
        "description": (
            "Queue a background Alcove/Codex task from the live Field Station conversation. "
            "Use this when the human asks you to capture, make, build, draft, prepare, summarize, "
            "turn this into a handoff, create a story, create a plan, or otherwise start work that can run "
            "while the voice conversation continues."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The concrete task or artifact Alcove should create.",
                },
                "mode": {
                    "type": "string",
                    "description": "The best Field Station mode for the task.",
                    "enum": ["maker", "family", "business", "real-estate", "demo", "codex"],
                },
                "expected_output": {
                    "type": "string",
                    "description": "The artifact shape the queued job should produce.",
                    "enum": [
                        "project_plan",
                        "kid_story",
                        "owner_briefing",
                        "transaction_brief",
                        "client_demo_explanation",
                        "codex_handoff",
                        "artifact",
                    ],
                },
                "summary": {
                    "type": "string",
                    "description": "A short plain-language summary to show in the station job queue.",
                },
            },
            "required": ["goal"],
        },
    }


def _field_station_realtime_instructions(*, mode: str | None, current_text: str | None) -> str:
    clean_mode = (mode or "maker").strip().lower()
    mode_guidance = {
        "family": "You are in Family mode. Be warm, imaginative, safe, and short. Ask one playful question when useful.",
        "maker": "You are in Maker mode. Help turn messy physical-project ideas into doable next steps.",
        "business": "You are in Business mode. Draft and summarize only; remind the human to approve external actions.",
        "real-estate": "You are in Real Estate mode. Help with checklists, deadlines, explanations, and client-update drafts.",
        "demo": "You are in Demo mode. Explain practical AI workflows in plain, local-business language.",
        "codex": "You are in Codex mode. Convert rough intent into precise build handoffs and implementation steps.",
    }.get(clean_mode, "Help turn messy real-world input into a useful next action.")
    text_hint = (current_text or "").strip()
    if text_hint:
        text_hint = f"\nCurrent composer text for context: {text_hint[:900]}"
    return (
        "You are Alcove, a calm physical AI presence in a tabletop field station. "
        "This is live voice, so speak conversationally and keep responses brief unless asked for depth. "
        "At any moment, show one invitation, one state, and one next action. "
        "Default to English. Only switch languages when the human clearly asks you to. "
        "Do not guess what the human is making from ambiguous noise or partial words. If the intent is unclear, "
        "ask one short clarifying question before naming the project or proposing specifics. "
        "Be a curious kid-friendly robot helper: playful, grounded, and calm, with no random roleplay or scene invention. "
        "You can suggest, draft, summarize, and prepare, but the human approves anything external, client-facing, "
        "financial, or hardware-moving. When the human asks you to make, capture, queue, prepare, draft, build, "
        "or turn the current thought into an artifact, call queue_alcove_job. After queueing, briefly confirm "
        "that the job is running and keep the conversation available. "
        f"{mode_guidance}{text_hint}"
    )


def _merge_content_and_attachments(*, base_content: str, attachment_lines: list[str]) -> str:
    content = base_content.strip()
    if not attachment_lines:
        return content
    attachment_block = "\n".join(["Attached screenshot files (local paths):", *attachment_lines])
    if content:
        return f"{content}\n\n{attachment_block}"
    return f"Please inspect the attached screenshot files.\n\n{attachment_block}"


def _image_suffix_from_mime(mime: str) -> str:
    if mime == "image/png":
        return ".png"
    if mime in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if mime == "image/webp":
        return ".webp"
    return ".img"


def _qr_svg(text: str) -> str:
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgImage)
    return image.to_string(encoding="unicode")


def _request_body_limit(content_type: str) -> int:
    normalized = str(content_type or "").strip().lower()
    if normalized.startswith("multipart/form-data"):
        return MAX_MULTIPART_BODY_BYTES
    return MAX_JSON_BODY_BYTES


def _safe_storage_segment(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    if text in {".", ".."}:
        raise ValueError(f"{label} cannot be '.' or '..'.")
    if any(ch in text for ch in ("/", "\\", "\x00")):
        raise ValueError(f"{label} cannot contain path separators.")
    if any(ord(ch) < 32 for ch in text):
        raise ValueError(f"{label} cannot contain control characters.")
    return text
