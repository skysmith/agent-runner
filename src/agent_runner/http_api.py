from __future__ import annotations

import base64
import json
import mimetypes
import traceback
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy_default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
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
    render_thread,
    render_web_app,
    render_workspaces,
)


def create_server(
    service: AgentRunnerService,
    host: str,
    port: int,
    *,
    access_password: str | None = None,
) -> ThreadingHTTPServer:
    password = (access_password or "").strip() or None

    def connections_payload(server_port: int) -> dict[str, Any]:
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
        return payload

    class CompanionHandler(BaseHTTPRequestHandler):
        server_version = "agent-runner-web/1.0"

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
                if path == "/api/settings":
                    self._json_response(service.get_settings())
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
                    self._json_response({"conversations": service.list_conversations(workspace_id)})
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
                    self._json_response(connections_payload(self.server.server_port))
                    return
                if path == "/api/connections":
                    self._json_response(connections_payload(self.server.server_port))
                    return
                if path == "/api/connections/phone-qr.svg":
                    payload = connections_payload(self.server.server_port)
                    phone_url = str(payload.get("phone_url") or "").strip()
                    if not phone_url:
                        self._error_response(HTTPStatus.CONFLICT, "Phone access is not available.")
                        return
                    self._svg_response(_qr_svg(phone_url))
                    return
                if path == "/":
                    self._html_response(render_web_app())
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
                if path == "/api/studio/games":
                    body = self._json_body()
                    self._json_response(
                        service.create_studio_game(
                            game_title=_required_body_text(body, "game_title"),
                            template_kind=_body_text(body, "template_kind") or "blank",
                            theme_prompt=_body_text(body, "theme_prompt"),
                        ),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path.startswith("/api/workspaces/") and path.endswith("/conversations"):
                    body = self._json_body()
                    workspace_id = _path_part(path, 2)
                    self._json_response(
                        service.create_conversation(workspace_id, title=_body_text(body, "title")),
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
                        )
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
            body = self._json_body()
            try:
                if path == "/api/settings":
                    self._json_response(service.update_settings(body))
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

            uploads_dir = service.config.repo_path / ".agent-runner" / "uploads" / workspace_id / conversation_id
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

        def _raw_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return b""
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
                self.send_header("WWW-Authenticate", 'Basic realm="agent-runner"')
                self.send_header("Content-Type", "application/json; charset=utf-8")
                data = json.dumps({"detail": "Authentication required."}).encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return False
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="agent-runner"')
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


def _query_int(query: dict[str, list[str]], key: str, *, default: int) -> int:
    text = _query_text(query, key)
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        return default
    return value


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
