from __future__ import annotations

from html import escape

from .service import AgentRunnerService


def render_workspaces(service: AgentRunnerService) -> str:
    rows = []
    for workspace in service.list_workspaces():
        rows.append(
            f"""
            <a class="rail-item" href="/m/workspaces/{escape(str(workspace["id"]))}">
              <div class="rail-title">{escape(str(workspace["id"]))}</div>
              <div class="rail-meta">{int(workspace["conversation_count"])} conversation(s)</div>
            </a>
            """
        )
    sidebar = (
        '<div class="rail-empty">No workspaces yet.</div>'
        if not rows
        else "\n".join(rows)
    )
    main = """
    <section class="panel thread-panel">
      <div class="panel-head">
        <div class="eyebrow">Workspaces</div>
        <h1>Choose a workspace</h1>
      </div>
      <div class="thread-scroll empty-state">
        Pick the thread space you want to continue from your phone.
      </div>
    </section>
    """
    return _shell(
        sidebar_title="Workspaces",
        sidebar_actions="",
        sidebar_body=sidebar,
        main_body=main,
    )


def render_conversations(service: AgentRunnerService, workspace_id: str) -> str:
    workspace = service.ensure_workspace(workspace_id)
    rows = []
    for conversation in service.list_conversations(workspace_id):
        is_active = str(conversation["id"]) == str(workspace.get("active_conversation_id"))
        active_class = " rail-item-active" if is_active else ""
        rows.append(
            f"""
            <a class="rail-item{active_class}" href="/m/conversations/{escape(str(conversation["id"]))}?workspace_id={escape(workspace_id)}">
              <div class="rail-title">{escape(str(conversation["title"]))}</div>
              <div class="rail-meta">{escape(str(conversation["updated_at"]))}</div>
            </a>
            """
        )
    sidebar = f'<a class="back-link" href="/m">All workspaces</a>' + (
        "\n".join(rows) or '<div class="rail-empty">No conversations yet.</div>'
    )
    main = f"""
    <section class="panel thread-panel">
      <div class="panel-head">
        <div class="eyebrow">Thread</div>
        <h1>{escape(workspace_id)}</h1>
      </div>
      <div class="thread-scroll empty-state">
        Choose a conversation from the left rail to open it here.
      </div>
    </section>
    """
    return _shell(
        sidebar_title="Conversations",
        sidebar_actions="",
        sidebar_body=sidebar,
        main_body=main,
    )


def render_thread(service: AgentRunnerService, conversation_id: str, *, workspace_id: str | None) -> str:
    conversation = service.get_conversation(conversation_id, workspace_id=workspace_id)
    status = service.get_run_status()
    conversations = service.list_conversations(str(conversation["workspace_id"]))
    sidebar_rows = []
    for item in conversations:
        active_class = " rail-item-active" if str(item["id"]) == str(conversation_id) else ""
        sidebar_rows.append(
            f"""
            <a class="rail-item{active_class}" href="/m/conversations/{escape(str(item["id"]))}?workspace_id={escape(str(conversation["workspace_id"]))}">
              <div class="rail-title">{escape(str(item["title"]))}</div>
              <div class="rail-meta">{escape(str(item["updated_at"]))}</div>
            </a>
            """
        )
    messages = []
    for message in conversation.get("messages", []):
        role = str(message.get("role", "assistant"))
        content_html = escape(str(message.get("content", ""))).replace("\n", "<br>")
        messages.append(
            f"""
            <article class="bubble bubble-{escape(role)}">
              <div class="bubble-content">{content_html}</div>
            </article>
            """
        )
    messages_html = "\n".join(messages) or '<div class="empty-state">No messages yet.</div>'
    status_text = escape(str(status.get("state", "idle")))
    workspace_label = escape(str(conversation["workspace_id"]))
    convo_label = escape(str(conversation["title"]))
    sidebar = f'<a class="back-link" href="/m/workspaces/{workspace_label}">{workspace_label}</a>' + (
        "\n".join(sidebar_rows) or '<div class="rail-empty">No conversations yet.</div>'
    )
    main = f"""
    <section class="panel thread-panel">
      <div class="panel-head">
        <div class="eyebrow">Thread</div>
        <h1>{convo_label}</h1>
      </div>
      <div class="thread-box">
        <div class="thread-scroll">{messages_html}</div>
      </div>
    </section>
    <section class="panel composer-panel">
      <form class="composer" onsubmit="return submitComposer(event, '{escape(str(conversation['workspace_id']))}', '{escape(str(conversation_id))}')">
        <textarea id="composer" placeholder="Type into the same thread from your phone"></textarea>
        <input id="composer-attachments" type="file" accept="image/*" multiple hidden onchange="onComposerFilesChanged()" />
        <div id="composer-attachment-list" class="attachment-list" hidden></div>
        <div class="composer-footer">
          <div class="loop-pill">Loop</div>
          <div class="status-cluster">
            <div class="pill pill-{status_text}">{status_text}</div>
            <div class="composer-actions">
              <button type="button" class="ghost icon-button" onclick="openAttachmentPicker()">Img</button>
              <button type="button" class="send-button" onclick="sendMode('message')">▶</button>
              <button type="button" class="ghost icon-button" onclick="sendMode('loop')">+</button>
              <button type="button" class="ghost icon-button" onclick="stopRun()">■</button>
              <button type="button" class="ghost icon-button" onclick="clearChat('{escape(str(conversation['workspace_id']))}', '{escape(str(conversation_id))}')">✕</button>
            </div>
          </div>
        </div>
        <input id="composer-mode" type="hidden" value="message" />
      </form>
    </section>
    """
    return _shell(
        sidebar_title="Conversations",
        sidebar_actions="",
        sidebar_body=sidebar,
        main_body=main,
    )


def render_error_page(detail: str) -> str:
    main = f"""
    <section class="panel thread-panel">
      <div class="panel-head">
        <div class="eyebrow">Companion Error</div>
        <h1>Something went wrong</h1>
      </div>
      <div class="thread-scroll empty-state">
        {escape(detail)}
      </div>
    </section>
    """
    return _shell(
        sidebar_title="Companion",
        sidebar_actions="",
        sidebar_body='<div class="rail-empty">Try reloading after the desktop app settles.</div>',
        main_body=main,
    )


def render_web_app() -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <title>Alcove</title>
        <style>
          :root {
            --bg: #f4f5f7;
            --panel: #fbfbfc;
            --panel-strong: #f5f6f8;
            --line: #d6dae0;
            --line-soft: #e4e7ec;
            --ink: #23262b;
            --muted: #69707a;
            --muted-soft: #878e98;
            --accent: #325746;
            --warning: #c78f2a;
            --danger: #b44a3f;
            --ok: #3e6a51;
            --shadow: 0 16px 42px rgba(30, 35, 31, 0.08);
            --chat-pane-width: clamp(240px, 20vw, 320px);
            --pane-divider-width: 16px;
          }
          * { box-sizing: border-box; }
          html, body {
            height: 100%;
            width: 100%;
            max-width: 100%;
            overflow-x: hidden;
            overscroll-behavior-x: none;
            touch-action: pan-y;
          }
          body {
            margin: 0;
            font-family: "Avenir Next", "Helvetica Neue", Helvetica, sans-serif;
            color: var(--ink);
            background: #fcfdff;
            overflow: hidden;
          }
          .page {
            height: 100%;
            width: 100%;
            max-width: 100vw;
            overflow-x: hidden;
            padding: 0;
          }
          .frame {
            height: 100vh;
            width: 100%;
            max-width: 100vw;
            border: 0;
            background: #fcfdff;
            box-shadow: none;
            display: grid;
            grid-template-rows: auto minmax(0, 1fr);
            overflow: hidden;
          }
          .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 10px 16px;
            border-bottom: 1px solid var(--line);
            background: #f7f8fa;
          }
          .topbar-title {
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }
          .topbar-home {
            border: 0;
            background: transparent;
            color: inherit;
            font: inherit;
            cursor: pointer;
            padding: 0;
          }
          .topbar-home:hover {
            color: var(--accent);
          }
          .topbar-copy {
            font-size: 12px;
            color: var(--muted);
          }
          .topbar-right {
            display: flex;
            gap: 6px;
            align-items: center;
            justify-content: flex-end;
            flex-wrap: wrap;
            min-width: 0;
            position: relative;
          }
          .topbar-button {
            border: 1px solid var(--line);
            background: #f3f5f8;
            color: var(--muted);
            font: inherit;
            font-size: 11px;
            line-height: 1;
            letter-spacing: 0.04em;
            padding: 7px 9px;
            cursor: pointer;
          }
          .topbar-button:hover {
            background: #e9edf2;
            color: var(--ink);
          }
          .chip {
            border: 1px solid var(--line);
            background: var(--panel);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            padding: 5px 8px;
            color: var(--muted);
            display: inline-flex;
            gap: 6px;
            align-items: center;
            white-space: nowrap;
          }
          .chip::before {
            content: "";
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: var(--accent);
          }
          .build-badge {
            position: static;
            pointer-events: none;
            border: 1px solid var(--line);
            background: #f3f5f8;
            color: var(--muted);
            font-size: 10px;
            line-height: 1;
            letter-spacing: 0.04em;
            padding: 4px 7px;
            border-radius: 999px;
            white-space: nowrap;
            flex-shrink: 0;
          }
          .chip-running::before,
          .chip-starting::before,
          .chip-stopping::before { background: var(--warning); }
          .chip-failed::before { background: var(--danger); }
          .chip-succeeded::before { background: var(--ok); }
          .shell {
            min-height: 0;
            display: grid;
            grid-template-columns: var(--chat-pane-width) var(--pane-divider-width) minmax(0, 1fr);
          }
          .setup-banner {
            display: none;
            padding: 12px 16px;
            border-bottom: 1px solid #e6d4a7;
            background:
              linear-gradient(180deg, rgba(249, 241, 216, 0.96), rgba(247, 237, 209, 0.96));
          }
          .setup-banner.is-visible {
            display: block;
          }
          .setup-banner-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            flex-wrap: wrap;
          }
          .setup-banner-title {
            margin: 0;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #8a6620;
          }
          .setup-banner-copy {
            margin: 6px 0 0;
            font-size: 13px;
            color: #5c5034;
            line-height: 1.5;
          }
          .setup-banner-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
          }
          .setup-banner-list {
            margin: 10px 0 0;
            padding-left: 18px;
            color: #5c5034;
            font-size: 13px;
            line-height: 1.5;
          }
          .setup-banner-list li {
            margin: 0 0 6px;
          }
          .pane {
            min-width: 0;
            min-height: 0;
            background: var(--panel);
          }
          .thread-pane,
          .review-pane {
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
          }
          .review-pane { background: #f7f8fb; }
          .pane-divider {
            position: relative;
            min-width: 0;
            min-height: 0;
            cursor: col-resize;
            z-index: 3;
            background: linear-gradient(
              90deg,
              transparent 0,
              transparent calc(50% - 0.5px),
              var(--line-soft) calc(50% - 0.5px),
              var(--line-soft) calc(50% + 0.5px),
              transparent calc(50% + 0.5px),
              transparent 100%
            );
            user-select: none;
            touch-action: none;
          }
          .pane-divider::after {
            content: "";
            position: absolute;
            top: 50%;
            left: 50%;
            width: 8px;
            height: 72px;
            transform: translate(-50%, -50%);
            border-radius: 999px;
            background:
              radial-gradient(circle, rgba(127, 134, 143, 0.7) 0 1.25px, transparent 1.5px) center 10px / 8px 14px repeat-y,
              rgba(127, 134, 143, 0.1);
            transition: background 120ms ease, box-shadow 120ms ease;
          }
          .pane-divider:hover::after,
          .pane-divider.is-dragging::after {
            background:
              radial-gradient(circle, rgba(50, 87, 70, 0.95) 0 1.4px, transparent 1.7px) center 10px / 8px 14px repeat-y,
              rgba(50, 87, 70, 0.18);
            box-shadow: 0 0 0 1px rgba(50, 87, 70, 0.08);
          }
          body.is-resizing,
          body.is-resizing * {
            cursor: col-resize !important;
            user-select: none !important;
          }
          .rail,
          .review {
            display: flex;
            flex-direction: column;
            min-height: 0;
            height: 100%;
          }
          .pane-head {
            padding: 14px 14px 10px;
            border-bottom: 1px solid var(--line-soft);
          }
          .pane-head-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 10px;
          }
          .pane-head-main {
            min-width: 0;
          }
          .pane-head-actions {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            justify-content: flex-end;
            align-items: center;
          }
          .pane-head-actions button {
            padding: 7px 9px;
            font-size: 12px;
          }
          .eyebrow {
            margin: 0;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.13em;
            text-transform: uppercase;
            color: var(--muted-soft);
          }
          h1 {
            margin: 4px 0 0;
            font-size: 20px;
            line-height: 1.14;
            letter-spacing: -0.02em;
          }
          .pane-copy {
            margin: 8px 0 0;
            font-size: 12px;
            color: var(--muted);
            line-height: 1.5;
          }
          .rail-toolbar {
            display: flex;
            gap: 8px;
            padding: 10px 14px;
            border-bottom: 1px solid var(--line-soft);
          }
          .list {
            min-height: 0;
            overflow: auto;
            display: flex;
            flex-direction: column;
          }
          .conversation-row {
            text-align: left;
            width: 100%;
            border: 0;
            border-bottom: 1px solid var(--line-soft);
            background: transparent;
            padding: 12px 14px;
            cursor: pointer;
          }
          .conversation-row:hover { background: #f0f1ec; }
          .conversation-row.active {
            background: #edf1f4;
            box-shadow: inset 3px 0 0 var(--accent);
          }
          .conversation-main {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 8px;
          }
          .conversation-title {
            min-width: 0;
            font-size: 15px;
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .conversation-time {
            font-size: 10px;
            color: var(--muted-soft);
            text-transform: uppercase;
            letter-spacing: 0.05em;
          }
          .conversation-meta {
            margin-top: 4px;
            font-size: 12px;
            color: var(--muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .thread {
            flex: 1;
            min-height: 0;
            display: flex;
            flex-direction: column;
            overflow: hidden;
          }
          .thread-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            padding: 12px 18px;
            border-bottom: 1px solid var(--line-soft);
            background: #f7f8fb;
          }
          .thread-title {
            margin: 0;
            font-size: 21px;
            line-height: 1.1;
            letter-spacing: -0.02em;
          }
          .thread-subtitle {
            margin-top: 3px;
            font-size: 12px;
            color: var(--muted);
          }
          .thread-actions {
            display: flex;
            gap: 8px;
            align-items: center;
            flex-wrap: wrap;
            justify-content: flex-end;
            position: relative;
          }
          .actions-menu {
            position: absolute;
            right: 0;
            top: calc(100% + 4px);
            min-width: 220px;
            border: 1px solid var(--line);
            background: #fcfdff;
            box-shadow: 0 12px 24px rgba(22, 27, 33, 0.12);
            padding: 8px;
            z-index: 20;
          }
          .actions-menu[hidden] { display: none; }
          .menu-section {
            border-bottom: 1px solid var(--line-soft);
            padding: 6px 0;
          }
          .menu-section:last-child { border-bottom: 0; }
          .menu-title {
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted-soft);
            margin: 0 0 4px;
            padding: 0 6px;
          }
          .menu-item {
            width: 100%;
            text-align: left;
            border: 0;
            background: transparent;
            padding: 7px 6px;
            font-size: 13px;
          }
          .menu-item:hover { background: #eef2f6; }
          .menu-item.active {
            background: #e8eef2;
            color: var(--accent);
            font-weight: 700;
          }
          .thread-scroll {
            flex: 1;
            min-height: 0;
            overflow: auto;
            overflow-x: hidden;
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding: 18px;
            background: #fafbfd;
            overscroll-behavior-x: none;
          }
          .thread-scroll.home-scroll {
            gap: 0;
            padding: 0 0 18px;
            background: #fcfdff;
          }
          .workspace-grid {
            display: flex;
            flex-direction: column;
            gap: 0;
            margin-top: 14px;
            border-top: 1px solid var(--line-soft);
          }
          .home-shell {
            display: grid;
            grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
            gap: 14px;
            min-height: 100%;
          }
          .home-panel {
            border: 0;
            background: transparent;
            padding: 0;
          }
          .home-panel h2,
          .home-panel h3 {
            margin: 0 0 8px;
          }
          .home-panel p {
            margin: 0;
            font-size: 13px;
            color: var(--muted);
            line-height: 1.55;
          }
          .home-panel p.hero-copy,
          .home-panel p.dropzone-copy {
            font-size: 12px;
            line-height: 1.45;
            max-width: 34ch;
          }
          .home-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 14px;
          }
          .dropzone {
            border: 0;
            background: transparent;
            padding: 12px 0 0;
            min-height: 190px;
            display: grid;
            align-content: center;
            justify-items: start;
            gap: 10px;
            transition: background 120ms ease, box-shadow 120ms ease;
          }
          .dropzone strong {
            font-size: 16px;
            letter-spacing: -0.02em;
          }
          .dropzone-copy {
            max-width: 40ch;
          }
          .dropzone-hint {
            font-size: 12px;
            color: var(--muted-soft);
          }
          .dropzone.is-active {
            background: linear-gradient(180deg, rgba(244, 250, 246, 0.92), rgba(238, 246, 241, 0.92));
            box-shadow: inset 0 0 0 1px rgba(50, 87, 70, 0.1);
          }
          .home-dropzone {
            min-height: 100%;
            align-content: start;
            padding: 16px 18px 0;
          }
          .workspace-grid.compact {
            margin-top: 14px;
          }
          .workspace-card {
            text-align: left;
            border: 0;
            border-bottom: 1px solid var(--line-soft);
            background: transparent;
            padding: 10px 0;
            cursor: pointer;
          }
          .workspace-card:hover {
            background: transparent;
            color: var(--accent);
          }
          .workspace-card:hover .workspace-card-path,
          .workspace-card:hover .workspace-card-meta {
            color: var(--accent);
          }
          .workspace-card-title {
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 4px;
          }
          .workspace-card-path,
          .workspace-card-meta {
            font-size: 11px;
            color: var(--muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .message {
            line-height: 1.54;
            font-size: 14px;
            border-radius: 14px;
            width: fit-content;
            min-width: 0;
            max-width: min(760px, 84%);
            padding: 12px 14px;
          }
          .message-body {
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            word-break: break-word;
          }
          .message.user {
            align-self: flex-end;
            background: #355a47;
            color: #f9f9f3;
          }
          .message.assistant {
            align-self: flex-start;
            background: #eef2f6;
            max-width: min(640px, 80%);
          }
          .message-phase {
            display: block;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
            color: var(--muted-soft);
          }
          .composer-wrap {
            flex-shrink: 0;
            position: sticky;
            bottom: 0;
            z-index: 4;
            border-top: 1px solid var(--line-soft);
            background: #fcfdff;
            box-shadow: none;
            padding: 0 18px 14px;
            position: sticky;
            overflow-x: clip;
          }
          .attachment-list {
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
          }
          .attachment-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border: 1px solid var(--line);
            background: #eef2f6;
            font-size: 12px;
            color: var(--ink);
            padding: 4px 8px;
            border-radius: 999px;
            max-width: 100%;
          }
          .attachment-pill span {
            min-width: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .attachment-pill button {
            border: 0;
            background: transparent;
            color: var(--muted);
            cursor: pointer;
            padding: 0;
            font-size: 12px;
          }
          .composer {
            position: relative;
            min-width: 0;
            overflow-x: clip;
          }
          .composer textarea {
            width: 100%;
            border: 0;
            background: transparent;
            color: var(--ink);
            min-height: 104px;
            resize: none;
            padding: 14px var(--composer-action-space, 126px) 18px 0;
            font: inherit;
            font-size: 14px;
            line-height: 1.45;
            outline: none;
            max-width: 100%;
          }
          .composer textarea::placeholder {
            color: #7f868f;
          }
          .composer-box {
            position: static;
            background: #fcfdff;
          }
          .composer-server-dot {
            position: absolute;
            top: 16px;
            right: 18px;
            width: 10px;
            height: 10px;
            border-radius: 999px;
            background: var(--danger);
          }
          .composer-actions {
            position: absolute;
            right: 18px;
            bottom: 12px;
            display: flex;
            gap: 8px;
            flex-shrink: 0;
          }
          .icon-button, .send-fab {
            width: 34px;
            height: 34px;
            border-radius: 999px;
            padding: 0;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid var(--line);
            background: #f5f6f8;
            color: var(--muted);
            font-weight: 700;
            line-height: 1;
            box-shadow: none;
          }
          .icon-button:hover {
            background: #e8ebf0;
            color: var(--ink);
          }
          .send-fab {
            border-color: #274839;
            background: var(--accent);
            color: #f5f7f1;
          }
          .send-fab:hover { background: #274839; }
          .send-fab:disabled {
            opacity: 0.45;
            cursor: not-allowed;
          }
          .server-dot-online { background: var(--ok); }
          .server-dot-busy { background: var(--warning); }
          .server-dot-offline { background: var(--danger); }
          .context-grid {
            margin-top: 8px;
            display: grid;
            gap: 8px;
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .context-grid input {
            width: 100%;
            border: 1px solid var(--line);
            background: #fcfdff;
            color: var(--ink);
            padding: 8px 9px;
            font: inherit;
            font-size: 12px;
          }
          .context-grid .full {
            grid-column: 1 / -1;
          }
          .composer-meta {
            margin-top: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            flex-wrap: wrap;
          }
          .composer-hint {
            font-size: 12px;
            color: var(--muted);
          }
          .active-context {
            border: 1px solid var(--line);
            background: #eef2f6;
            padding: 7px 9px;
            border-radius: 8px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 100%;
          }
          .mode-switch {
            display: inline-flex;
            border: 1px solid var(--line);
            background: #eceff3;
            padding: 2px;
            border-radius: 999px;
          }
          .mode-button {
            border: 0;
            background: transparent;
            font: inherit;
            color: var(--muted);
            cursor: pointer;
            font-size: 12px;
            padding: 6px 11px;
            border-radius: 999px;
          }
          .mode-button.active {
            background: #ffffff;
            color: var(--accent);
            font-weight: 600;
          }
          .button-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
          }
          button {
            border: 1px solid var(--line);
            background: #f1f3f6;
            color: var(--ink);
            font: inherit;
            font-size: 13px;
            padding: 8px 11px;
            cursor: pointer;
          }
          button:hover { background: #e8ebf0; }
          .primary {
            background: var(--accent);
            border-color: #274839;
            color: #f5f7f1;
          }
          .danger { color: var(--danger); }
          button:disabled {
            opacity: 0.45;
            cursor: not-allowed;
          }
          .review-scroll {
            min-height: 0;
            overflow: auto;
            overflow-x: hidden;
            padding: 8px 10px 12px;
          }
          .review-scroll.studio-scroll {
            display: flex;
            flex-direction: column;
            min-height: 0;
            height: 100%;
            overflow: hidden;
          }
          .review-card {
            border: 1px solid var(--line);
            background: #fcfdff;
            padding: 8px;
            margin-bottom: 8px;
          }
          .studio-shell {
            display: grid;
            grid-template-rows: minmax(0, 1fr) auto;
            gap: 8px;
            flex: 1;
            min-height: 0;
            height: 100%;
          }
          .studio-meta {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
          }
          .studio-pill {
            border: 1px solid var(--line);
            background: #eef2f0;
            padding: 4px 7px;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: var(--muted);
          }
          .studio-preview-card {
            border: 1px solid var(--line);
            background: #fbfcfe;
            overflow: hidden;
            min-height: 0;
            display: grid;
            grid-template-rows: auto minmax(0, 1fr);
            height: 100%;
          }
          .studio-preview-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 8px 10px;
            border-bottom: 1px solid var(--line-soft);
          }
          .studio-preview-label {
            font-size: 11px;
            color: var(--muted);
          }
          .studio-preview-frame {
            width: 100%;
            height: 100%;
            min-height: 0;
            display: block;
            border: 0;
            background: linear-gradient(180deg, #1e3a31, #0c1713);
          }
          .studio-advanced summary {
            cursor: pointer;
            font-size: 12px;
            color: var(--muted);
            margin-bottom: 8px;
          }
          .studio-advanced code {
            font-size: 12px;
          }
          .studio-empty {
            border: 1px dashed var(--line);
            padding: 14px;
            color: var(--muted);
            line-height: 1.5;
          }
          .review-title {
            margin: 0 0 8px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted-soft);
          }
          .review-line {
            font-size: 13px;
            line-height: 1.45;
            color: var(--ink);
            margin: 0 0 6px;
            white-space: pre-wrap;
          }
          .review-line.subtle {
            color: var(--muted);
            font-size: 12px;
          }
          .review-list {
            margin: 0;
            padding-left: 16px;
            color: var(--ink);
            font-size: 12px;
            line-height: 1.45;
          }
          .empty {
            color: var(--muted);
            font-size: 13px;
            line-height: 1.5;
            padding: 14px 0;
          }
          .mobile-toggle,
          .mobile-back {
            display: none;
          }
          .foot {
            padding: 8px 14px 12px;
            border-top: 1px solid var(--line-soft);
            font-size: 12px;
            color: var(--muted);
          }
          .foot a { color: inherit; }
          .settings-modal {
            position: fixed;
            inset: 0;
            z-index: 80;
          }
          .studio-modal {
            position: fixed;
            inset: 0;
            z-index: 90;
          }
          .settings-backdrop {
            position: absolute;
            inset: 0;
            background: rgba(17, 22, 29, 0.35);
          }
          .settings-dialog {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: min(640px, calc(100vw - 24px));
            max-height: calc(100vh - 24px);
            overflow: auto;
            border: 1px solid var(--line);
            background: #fcfdff;
            box-shadow: 0 20px 46px rgba(18, 24, 31, 0.22);
          }
          .settings-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            border-bottom: 1px solid var(--line-soft);
          }
          .settings-head h3 {
            margin: 0;
            font-size: 16px;
          }
          .settings-body {
            display: grid;
            gap: 10px;
            padding: 12px;
          }
          .settings-body label {
            display: grid;
            gap: 4px;
            font-size: 12px;
            color: var(--muted);
          }
          .settings-body input,
          .settings-body select {
            border: 1px solid var(--line);
            background: #fff;
            color: var(--ink);
            font: inherit;
            padding: 8px;
            font-size: 13px;
          }
          .settings-body textarea {
            border: 1px solid var(--line);
            background: #fff;
            color: var(--ink);
            font: inherit;
            padding: 8px;
            font-size: 13px;
            min-height: 88px;
            resize: vertical;
          }
          .settings-section {
            border-top: 1px solid var(--line-soft);
            padding-top: 14px;
            margin-top: 2px;
          }
          .settings-section:first-child {
            border-top: 0;
            padding-top: 0;
            margin-top: 0;
          }
          .settings-section h4 {
            margin: 0 0 8px;
            font-size: 12px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--muted-soft);
          }
          .connection-card {
            border: 1px solid var(--line);
            background: #fcfdff;
            padding: 12px;
            margin-top: 10px;
          }
          .connection-card:first-of-type {
            margin-top: 0;
          }
          .connection-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin: 0 0 4px;
            font-size: 14px;
            font-weight: 700;
          }
          .connection-state {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.04em;
            color: var(--muted);
            text-transform: uppercase;
          }
          .connection-copy {
            margin: 0 0 8px;
            font-size: 12px;
            color: var(--muted);
            line-height: 1.45;
          }
          .connection-url {
            margin: 0 0 10px;
            padding: 8px 9px;
            border: 1px solid var(--line-soft);
            background: #f6f8fb;
            font-size: 12px;
            color: var(--ink);
            overflow-wrap: anywhere;
          }
          .connection-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
          }
          .connection-meta {
            margin-top: 12px;
            font-size: 12px;
            color: var(--muted);
            line-height: 1.5;
          }
          .qr-panel {
            margin-top: 12px;
            display: grid;
            gap: 8px;
            justify-items: start;
          }
          .qr-panel img {
            width: 168px;
            height: 168px;
            border: 1px solid var(--line);
            background: white;
            padding: 8px;
          }
          .qr-caption {
            font-size: 12px;
            color: var(--muted);
          }
          @media (max-width: 1080px) {
            .shell { grid-template-columns: 1fr; }
            .pane-divider { display: none; }
            .pane.review-pane { display: none; }
            .mobile-toggle { display: inline-flex; }
            .home-shell { grid-template-columns: 1fr; }
          }
          @media (max-width: 880px) {
            .page { padding: 0; height: 100dvh; }
            .frame { height: 100dvh; }
            .shell { grid-template-columns: 1fr; }
            .pane.review-pane {
              display: none;
            }
            .shell.mobile-right .pane.review-pane {
              display: block;
            }
            .shell.mobile-right .thread-pane {
              display: none;
            }
            .mobile-back {
              display: inline-flex;
            }
            .thread-head {
              padding: 10px 12px;
              gap: 8px;
            }
            .pane-head-top {
              flex-direction: column;
              align-items: stretch;
            }
            .pane-head-actions {
              justify-content: flex-start;
            }
            .thread-title {
              font-size: 17px;
              white-space: nowrap;
              overflow: hidden;
              text-overflow: ellipsis;
              max-width: 52vw;
            }
            .thread-actions { gap: 6px; }
            .thread-scroll {
              padding: 12px;
              overflow-x: hidden;
            }
            .composer-wrap {
              position: sticky;
              bottom: var(--keyboard-offset, 0px);
              z-index: 5;
              border-top: 1px solid var(--line);
              box-shadow: none;
              padding: 0 12px calc(10px + env(safe-area-inset-bottom));
            }
            .thread-scroll { padding-bottom: calc(130px + env(safe-area-inset-bottom)); }
            .topbar-copy { display: none; }
            .topbar {
              align-items: flex-start;
            }
            .topbar-right {
              gap: 6px;
              max-width: 64vw;
            }
            .context-grid {
              grid-template-columns: 1fr;
            }
            .composer {
              --composer-action-space: 108px;
            }
            .composer textarea {
              min-height: 92px;
            }
            .composer-server-dot {
              top: 14px;
              right: 12px;
              width: 8px;
              height: 8px;
            }
            .composer-actions {
              right: 10px;
              bottom: 10px;
              gap: 6px;
            }
            .icon-button, .send-fab {
              width: 30px;
              height: 30px;
              font-size: 11px;
            }
          }
          @media (max-width: 420px) {
            .topbar {
              padding: 10px 12px;
            }
            .topbar-right {
              max-width: 58vw;
            }
            .topbar-button,
            .chip,
            .build-badge {
              font-size: 10px;
            }
            .topbar-button {
              padding: 6px 8px;
            }
            .chip {
              gap: 5px;
              padding: 4px 7px;
            }
            .chip::before {
              width: 7px;
              height: 7px;
            }
            .build-badge {
              padding: 4px 6px;
            }
            .composer {
              --composer-action-space: 86px;
            }
            .composer textarea {
              font-size: 13px;
            }
            .composer-actions {
              right: 8px;
              gap: 4px;
            }
            .icon-button, .send-fab {
              width: 26px;
              height: 26px;
            }
            .composer-server-dot {
              right: 10px;
            }
          }
        </style>
      </head>
      <body>
        <div class="page">
          <main class="frame">
            <header class="topbar">
              <div>
                <button class="topbar-home" type="button" onclick="goToWorkspaceSelector()">
                  <div class="topbar-title">Alcove</div>
                </button>
              </div>
              <div class="topbar-right">
                <button id="menu-button" class="topbar-button" type="button" onclick="toggleActionsMenu()">Menu</button>
                <div id="build-badge" class="build-badge">Build unavailable</div>
                <div id="actions-menu" class="actions-menu" hidden>
                  <section class="menu-section">
                    <p class="menu-title">Mode</p>
                    <button id="menu-mode-message" class="menu-item" type="button" onclick="setMode('message')">Message</button>
                    <button id="menu-mode-loop" class="menu-item" type="button" onclick="setMode('loop')">Loop</button>
                  </section>
                  <section class="menu-section">
                    <p class="menu-title">Capability</p>
                    <button id="menu-assistant-ask" class="menu-item" type="button" onclick="setAssistantMode('ask')">Ask</button>
                    <button id="menu-assistant-ops" class="menu-item" type="button" onclick="setAssistantMode('ops')">Ops</button>
                    <button id="menu-assistant-dev" class="menu-item" type="button" onclick="setAssistantMode('dev')">Dev</button>
                  </section>
                  <section class="menu-section">
                    <p class="menu-title">Workspace</p>
                    <button class="menu-item" type="button" onclick="createWorkspace()">Add Workspace</button>
                    <button class="menu-item" type="button" onclick="importActiveRepositories()">Top Repos</button>
                    <button class="menu-item" type="button" onclick="clearConversation()">Clear Chat</button>
                    <button class="menu-item" type="button" onclick="stopRun()">Stop Run</button>
                  </section>
                  <section class="menu-section">
                    <p class="menu-title">View</p>
                    <button class="menu-item" type="button" onclick="toggleReviewPane()">Review Panel</button>
                    <button class="menu-item" type="button" onclick="showStudioProjectDetails()">Project Details</button>
                    <button class="menu-item" type="button" onclick="hardRefresh()">Reload</button>
                    <button class="menu-item" type="button" onclick="openSettings()">Settings</button>
                  </section>
                </div>
                <div id="global-run-chip" class="chip">idle</div>
              </div>
            </header>
            <section id="setup-banner" class="setup-banner" hidden></section>
            <section id="shell" class="shell">
              <section class="pane thread-pane">
                <div class="thread">
                  <div id="thread-scroll" class="thread-scroll">
                    <div class="empty">Loading workspaces…</div>
                  </div>
                  <div class="composer-wrap">
                    <form class="composer" onsubmit="return submitComposer(event)">
                      <div class="composer-box">
                        <textarea id="composer" placeholder="Describe what should happen next."></textarea>
                      </div>
                      <div id="server-chip" class="composer-server-dot server-dot-offline" title="Offline" aria-label="Server status: offline"></div>
                      <div class="composer-actions">
                        <button id="attach-button" class="icon-button" type="button" onclick="openAttachmentPicker()" aria-label="Attach file" title="Attach file">+</button>
                        <button id="voice-button" class="icon-button" type="button" onclick="startVoiceCapture()" aria-label="Speech to text" title="Speech to text">Mic</button>
                        <button id="send-button" class="send-fab" type="submit" aria-label="Send">➤</button>
                      </div>
                      <input id="composer-attachments" type="file" accept="image/*" multiple hidden onchange="onComposerFilesChanged()" />
                      <div id="composer-attachment-list" class="attachment-list" hidden></div>
                      <input id="composer-mode" type="hidden" value="message" />
                      <input id="assistant-mode" type="hidden" value="ask" />
                    </form>
                  </div>
                </div>
              </section>
              <div
                id="pane-divider"
                class="pane-divider"
                role="separator"
                aria-label="Resize chat and studio panels"
                aria-orientation="vertical"
                ondblclick="resetPaneLayout()"
              ></div>
              <aside class="pane review-pane">
                <div class="review">
                  <div class="pane-head">
                    <div class="pane-head-top">
                      <div class="pane-head-main">
                        <button class="mobile-back" type="button" onclick="closeMobilePanes()">Back</button>
                        <p id="side-eyebrow" class="eyebrow">Review</p>
                        <h1 id="side-title">Run Output</h1>
                        <p id="side-copy" class="pane-copy">Operational detail lives here, not in the bubbles.</p>
                      </div>
                      <div id="side-actions" class="pane-head-actions"></div>
                    </div>
                  </div>
                  <div id="review-scroll" class="review-scroll">
                    <div class="review-card">
                      <p class="review-title">Status</p>
                      <p class="review-line subtle">Loading run snapshot…</p>
                    </div>
                  </div>
                </div>
              </aside>
            </section>
          </main>
        </div>
        <div id="settings-modal" class="settings-modal" hidden>
          <div class="settings-backdrop" onclick="closeSettings()"></div>
          <div class="settings-dialog">
            <div class="settings-head">
              <h3>Settings</h3>
              <button type="button" onclick="closeSettings()">Close</button>
            </div>
            <div class="settings-body">
              <section class="settings-section">
                <h4>Connections</h4>
                <div id="connections-panel" class="composer-hint">Loading connections…</div>
              </section>
              <section class="settings-section">
                <h4>Runtime</h4>
                <label>Provider
                  <select id="settings-provider">
                    <option value="codex">codex</option>
                    <option value="ollama">ollama</option>
                  </select>
                </label>
                <label>Default model
                  <select id="settings-model"></select>
                </label>
                <label>Ollama host
                  <input id="settings-ollama-host" placeholder="http://127.0.0.1:11434" />
                </label>
                <label>Planner model (optional)
                  <select id="settings-planner-model"></select>
                </label>
                <label>Builder model (optional)
                  <select id="settings-builder-model"></select>
                </label>
                <label>Reviewer model (optional)
                  <select id="settings-reviewer-model"></select>
                </label>
                <label>Max step retries
                  <input id="settings-max-step-retries" type="number" min="0" step="1" />
                </label>
                <label>Phase timeout (seconds)
                  <input id="settings-phase-timeout" type="number" min="30" step="1" />
                </label>
                <div id="settings-status" class="composer-hint"></div>
                <div class="button-row">
                  <button type="button" onclick="refreshOllamaModels()">Refresh Ollama Models</button>
                  <button class="primary" type="button" onclick="saveSettings()">Save Settings</button>
                </div>
              </section>
            </div>
          </div>
        </div>
        <div id="studio-modal" class="studio-modal" hidden>
          <div class="settings-backdrop" onclick="closeStudioModal()"></div>
          <div class="settings-dialog">
            <div class="settings-head">
              <h3>New Studio</h3>
              <button type="button" onclick="closeStudioModal()">Close</button>
            </div>
            <div class="settings-body">
              <label>Studio
                <select id="studio-workspace-kind" onchange="updateStudioTemplateOptions()">
                  <option value="studio_game">Game Studio</option>
                  <option value="studio_web">Web Studio</option>
                  <option value="studio_data">Data Studio</option>
                  <option value="studio_docs">Docs Studio</option>
                </select>
              </label>
              <label id="studio-title-label">Project name
                <input id="studio-artifact-title" placeholder="Moon Mango Jump" />
              </label>
              <label id="studio-template-label">Template
                <select id="studio-template-kind">
                </select>
              </label>
              <label id="studio-theme-label">Theme prompt (optional)
                <textarea id="studio-theme-prompt" placeholder="A playful jungle at sunset with friendly robots."></textarea>
              </label>
              <div id="studio-status" class="composer-hint"></div>
              <div class="button-row">
                <button class="primary" type="button" onclick="createStudioWorkspace()">Create Studio</button>
              </div>
            </div>
          </div>
        </div>
        <script>
          const state = {
            conversationId: null,
            workspaceId: null,
            workspace: null,
            workspaces: [],
            conversationCache: null,
            lastSignature: null,
            serverInfo: null,
            runStatus: { state: 'idle', step: 'Idle' },
            review: null,
            submitting: false,
            eventCursor: '0',
            assistantMode: 'ask',
            reviewPaneHidden: true,
            setupReport: null,
          };
          const CODEX_MODEL_OPTIONS = [
            { value: 'gpt-5.4', label: 'GPT-5.4 (medium)' },
            { value: 'gpt-5.3-codex', label: 'GPT-5.3 Codex (medium)' },
            { value: 'gpt-5.4-mini', label: 'GPT-5.4 Mini' },
          ];
          const STUDIO_TEMPLATES = {
            studio_game: [
              { value: 'platformer', label: 'Platformer' },
              { value: 'top-down', label: 'Top-down Adventure' },
              { value: 'clicker', label: 'Clicker' },
              { value: 'blank', label: 'Blank Start' },
            ],
            studio_web: [
              { value: 'landing-page', label: 'Landing Page' },
              { value: 'web-app', label: 'Web App' },
              { value: 'portfolio', label: 'Portfolio' },
              { value: 'blank', label: 'Blank Start' },
            ],
            studio_data: [
              { value: 'dashboard', label: 'Dashboard' },
              { value: 'spreadsheet', label: 'Spreadsheet' },
              { value: 'query-lab', label: 'Query Lab' },
              { value: 'blank', label: 'Blank Start' },
            ],
            studio_docs: [
              { value: 'docs-site', label: 'Docs Site' },
              { value: 'guide', label: 'Guide' },
              { value: 'release-notes', label: 'Release Notes' },
              { value: 'blank', label: 'Blank Start' },
            ],
          };
          const PANE_WIDTH_STORAGE_KEY = 'alcove-chat-pane-width';
          let paneResizeState = null;
          let dropDepth = 0;

          function isActiveState(value) {
            return value === 'starting' || value === 'running' || value === 'stopping';
          }

          function isMobileViewport() {
            return window.matchMedia('(max-width: 880px)').matches;
          }

          function openMobilePane(which) {
            const shell = document.getElementById('shell');
            if (!shell || !isMobileViewport()) return;
            shell.classList.remove('mobile-right');
            if (which === 'right') shell.classList.add('mobile-right');
          }

          function closeMobilePanes() {
            const shell = document.getElementById('shell');
            if (!shell) return;
            shell.classList.remove('mobile-right');
          }

          function applyMobileDefaults() {
            if (!isMobileViewport()) {
              closeMobilePanes();
              return;
            }
            closeMobilePanes();
          }

          function isResizableDesktopViewport() {
            return window.matchMedia('(min-width: 1081px)').matches;
          }

          function applyStoredPaneLayout() {
            if (!isResizableDesktopViewport()) {
              document.documentElement.style.removeProperty('--chat-pane-width');
              return;
            }
            const stored = window.localStorage.getItem(PANE_WIDTH_STORAGE_KEY);
            const width = Number.parseFloat(stored || '');
            if (!Number.isFinite(width)) return;
            applyPaneWidth(width);
          }

          function applyPaneWidth(width) {
            const shell = document.getElementById('shell');
            if (!shell) return;
            const totalWidth = shell.clientWidth || window.innerWidth;
            const min = 220;
            const max = Math.min(460, Math.max(280, totalWidth * 0.42));
            const clamped = Math.max(min, Math.min(max, width));
            document.documentElement.style.setProperty('--chat-pane-width', `${clamped}px`);
          }

          function resetPaneLayout() {
            window.localStorage.removeItem(PANE_WIDTH_STORAGE_KEY);
            document.documentElement.style.removeProperty('--chat-pane-width');
          }

          function startPaneResize(event) {
            if (!isResizableDesktopViewport()) return;
            const shell = document.getElementById('shell');
            const divider = document.getElementById('pane-divider');
            if (!shell || !divider) return;
            paneResizeState = {
              shellLeft: shell.getBoundingClientRect().left,
            };
            divider.classList.add('is-dragging');
            document.body.classList.add('is-resizing');
            event.preventDefault();
          }

          function handlePaneResizeMove(event) {
            if (!paneResizeState || !isResizableDesktopViewport()) return;
            const nextWidth = event.clientX - paneResizeState.shellLeft;
            applyPaneWidth(nextWidth);
            window.localStorage.setItem(PANE_WIDTH_STORAGE_KEY, String(nextWidth));
          }

          function stopPaneResize() {
            const divider = document.getElementById('pane-divider');
            if (divider) divider.classList.remove('is-dragging');
            document.body.classList.remove('is-resizing');
            paneResizeState = null;
          }

          function bindPaneDivider() {
            const divider = document.getElementById('pane-divider');
            if (!divider) return;
            divider.addEventListener('pointerdown', startPaneResize);
            window.addEventListener('pointermove', handlePaneResizeMove);
            window.addEventListener('pointerup', stopPaneResize);
            window.addEventListener('pointercancel', stopPaneResize);
          }

          function setChip(id, text, stateValue) {
            const el = document.getElementById(id);
            if (!el) return;
            const stateClass = String(stateValue || 'idle');
            el.className = `chip chip-${stateClass}`;
            el.textContent = text;
          }

          function setServerDot(status, titleText) {
            const el = document.getElementById('server-chip');
            if (!el) return;
            const normalized = status === 'online' || status === 'busy' ? status : 'offline';
            el.className = `composer-server-dot server-dot-${normalized}`;
            el.title = titleText;
            el.setAttribute('aria-label', `Server status: ${titleText}`);
          }

          function hardRefresh() {
            const url = new URL(window.location.href);
            url.searchParams.set('_ar_refresh', String(Date.now()));
            window.location.replace(url.toString());
          }

          function renderSetupBanner() {
            const banner = document.getElementById('setup-banner');
            if (!banner) return;
            const report = state.setupReport;
            if (!report || report.ok) {
              banner.hidden = true;
              banner.classList.remove('is-visible');
              banner.innerHTML = '';
              return;
            }
            const failedChecks = (report.checks || []).filter((check) => !check.ok);
            const items = failedChecks
              .map((check) => {
                const detail = escapeHtml(check.detail || '');
                const fix = check.fix ? ` Fix: ${escapeHtml(check.fix)}` : '';
                return `<li><strong>${escapeHtml(check.label || check.key || 'Setup item')}</strong>: ${detail}${fix}</li>`;
              })
              .join('');
            banner.hidden = false;
            banner.classList.add('is-visible');
            banner.innerHTML = `
              <div class="setup-banner-head">
                <div>
                  <p class="setup-banner-title">Setup Needed</p>
                  <p class="setup-banner-copy">This machine is missing something Alcove needs before Codex work can run. Fix the items below, then refresh this page or run <code>alcove doctor</code> in the repo.</p>
                </div>
                <div class="setup-banner-actions">
                  <button type="button" onclick="hardRefresh()">Refresh</button>
                  <button type="button" onclick="openSettings()">Settings</button>
                </div>
              </div>
              <ul class="setup-banner-list">${items}</ul>
            `;
          }

          async function copyText(text) {
            try {
              await navigator.clipboard.writeText(text);
            } catch (_) {
              const input = document.createElement('textarea');
              input.value = text;
              document.body.appendChild(input);
              input.select();
              document.execCommand('copy');
              input.remove();
            }
          }

          async function copyConnectionUrl(kind) {
            const info = state.serverInfo || {};
            const url = kind === 'phone' ? info.phone_url : info.local_url;
            if (!url) {
              window.alert(kind === 'phone' ? 'Phone access is not available yet.' : 'Local URL is not available.');
              return;
            }
            await copyText(url);
          }

          function openConnectionUrl(kind) {
            const info = state.serverInfo || {};
            const url = kind === 'phone' ? info.phone_url : info.local_url;
            if (!url) {
              window.alert(kind === 'phone' ? 'Phone access is not available yet.' : 'Local URL is not available.');
              return;
            }
            window.open(url, '_blank', 'noopener,noreferrer');
          }

          function updateControls() {
            const active = isActiveState(state.runStatus.state);
            const hasConversation = Boolean(state.conversationId && state.workspaceId);
            const busy = active || state.submitting;
            const ids = ['attach-button', 'voice-button', 'send-button'];
            for (const id of ids) {
              const el = document.getElementById(id);
              if (el) el.disabled = !hasConversation || busy;
            }
            const textarea = document.getElementById('composer');
            if (textarea) textarea.disabled = !hasConversation || busy;
            const attachments = document.getElementById('composer-attachments');
            if (attachments) attachments.disabled = !hasConversation || busy;
            const loopMode = document.getElementById('menu-mode-loop');
            if (loopMode) {
              const disabled = state.assistantMode !== 'dev';
              loopMode.disabled = disabled;
              loopMode.title = disabled ? 'Loop requires dev capability mode.' : '';
            }
          }

          function toggleActionsMenu() {
            const menu = document.getElementById('actions-menu');
            if (!menu) return;
            menu.hidden = !menu.hidden;
          }

          function closeActionsMenu() {
            const menu = document.getElementById('actions-menu');
            if (!menu) return;
            menu.hidden = true;
          }

          function openAttachmentPicker() {
            const input = document.getElementById('composer-attachments');
            if (input && !input.disabled) input.click();
          }

          function startVoiceCapture() {
            const textarea = document.getElementById('composer');
            if (!textarea || textarea.disabled) return;
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
              window.alert('Speech recognition is not available in this browser.');
              return;
            }
            const recognition = new SpeechRecognition();
            recognition.lang = 'en-US';
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;
            recognition.onresult = (event) => {
              const transcript = String(event.results?.[0]?.[0]?.transcript || '').trim();
              if (!transcript) return;
              const prefix = textarea.value.trim();
              textarea.value = prefix ? `${prefix} ${transcript}` : transcript;
              textarea.focus();
            };
            recognition.onerror = () => {
              window.alert('Could not capture speech. Please try again.');
            };
            recognition.start();
          }

          function removeComposerAttachment(index) {
            const input = document.getElementById('composer-attachments');
            if (!input || !input.files) return;
            const dt = new DataTransfer();
            Array.from(input.files).forEach((file, fileIndex) => {
              if (fileIndex !== index) dt.items.add(file);
            });
            input.files = dt.files;
            onComposerFilesChanged();
          }

          function clearComposerAttachments() {
            const input = document.getElementById('composer-attachments');
            if (input) input.value = '';
            onComposerFilesChanged();
          }

          function onComposerFilesChanged() {
            const input = document.getElementById('composer-attachments');
            const host = document.getElementById('composer-attachment-list');
            if (!input || !host) return;
            const files = Array.from(input.files || []);
            if (!files.length) {
              host.hidden = true;
              host.innerHTML = '';
              return;
            }
            host.hidden = false;
            host.innerHTML = files
              .map((file, index) => {
                const name = escapeHtml(file.name || `screenshot-${index + 1}`);
                return `<div class="attachment-pill"><span>${name}</span><button type="button" onclick="removeComposerAttachment(${index})">x</button></div>`;
              })
              .join('');
          }

          function syncKeyboardInset() {
            if (!isMobileViewport()) {
              document.documentElement.style.setProperty('--keyboard-offset', '0px');
              return;
            }
            const viewport = window.visualViewport;
            if (!viewport) {
              document.documentElement.style.setProperty('--keyboard-offset', '0px');
              return;
            }
            const inset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
            document.documentElement.style.setProperty('--keyboard-offset', `${inset}px`);
          }

          function formatStamp(value) {
            if (!value) return '—';
            const date = new Date(value);
            if (Number.isNaN(date.valueOf())) return value;
            return date.toLocaleString();
          }

          function escapeHtml(value) {
            return String(value)
              .replaceAll('&', '&amp;')
              .replaceAll('<', '&lt;')
              .replaceAll('>', '&gt;');
          }

          function normalizeMessage(message) {
            const role = message.role === 'user' ? 'user' : 'assistant';
            let content = String(message.content || '');
            const phase = String(message.phase || '');
            if (role === 'assistant' && phase === 'message' && content.startsWith('Message response received.\\n\\n')) {
              content = content.replace(/^Message response received\.\\n\\n/, '');
            }
            return { role, phase, content };
          }

          function phaseLabel(phase) {
            if (!phase || phase === 'message') return '';
            if (phase === 'loop-final') return 'Loop result';
            if (phase === 'error') return 'Issue';
            return phase.replaceAll('-', ' ');
          }

          async function fetchJson(url, options) {
            const response = await fetch(url, options);
            if (!response.ok) {
              let detail = 'Request failed';
              try {
                const payload = await response.json();
                detail = payload.detail || detail;
              } catch (_) {}
              throw new Error(detail);
            }
            return response.json();
          }

          function renderWorkspaces(workspaces) {
            state.workspaces = workspaces;
            if (state.workspaceId) {
              state.workspace = workspaces.find((workspace) => workspace.id === state.workspaceId) || state.workspace;
            }
            if (!state.workspaceId || !state.conversationId) {
              renderWorkspaceSelector(workspaces);
            }
          }

          function isStudioWorkspace(workspace) {
            return String(workspace?.workspace_kind || '').startsWith('studio_');
          }

          function studioKindLabel(workspaceKind) {
            const value = String(workspaceKind || '');
            if (value === 'studio_web') return 'Web Studio';
            if (value === 'studio_data') return 'Data Studio';
            if (value === 'studio_docs') return 'Docs Studio';
            return 'Game Studio';
          }

          function studioArtifactNoun(workspaceKind) {
            const value = String(workspaceKind || '');
            if (value === 'studio_web') return 'site';
            if (value === 'studio_data') return 'data workspace';
            if (value === 'studio_docs') return 'docs workspace';
            return 'game';
          }

          function studioPrimaryAction(workspaceKind) {
            return String(workspaceKind || '') === 'studio_game' ? 'Play' : 'Preview';
          }

          function studioPlaceholder(workspaceKind) {
            const value = String(workspaceKind || '');
            if (value === 'studio_web') return 'Ask for a website change, like "make the hero bolder" or "add a pricing section".';
            if (value === 'studio_data') return 'Ask for a data change, like "group revenue by month" or "show duplicate rows".';
            if (value === 'studio_docs') return 'Ask for a docs change, like "rewrite the intro" or "add a getting started section".';
            return 'Ask for a change in your game, like "make the jump higher" or "add coins".';
          }

          function studioSummaryPrompt(workspaceKind) {
            const value = String(workspaceKind || '');
            if (value === 'studio_web') return 'Describe a change and Alcove will update the site.';
            if (value === 'studio_data') return 'Describe a change and Alcove will update the data workspace.';
            if (value === 'studio_docs') return 'Describe a change and Alcove will update the docs.';
            return 'Describe a change and Alcove will update the game.';
          }

          function studioEmptyState(workspaceKind) {
            const value = String(workspaceKind || '');
            if (value === 'studio_web') return 'Preview will appear here after the website is created.';
            if (value === 'studio_data') return 'Your live data view will appear here after the studio is created.';
            if (value === 'studio_docs') return 'Your rendered docs view will appear here after the studio is created.';
            return 'Preview will appear here after the game is created.';
          }

          function studioDefaultTitle(workspaceKind) {
            const value = String(workspaceKind || '');
            if (value === 'studio_web') return 'New Website';
            if (value === 'studio_data') return 'New Dataset';
            if (value === 'studio_docs') return 'New Docs';
            return 'New Game';
          }

          function slugifyWorkspaceId(value) {
            return String(value || '')
              .toLowerCase()
              .replace(/[^a-z0-9._-]+/g, '-')
              .replace(/^-+|-+$/g, '');
          }

          function childFriendlyPreviewState(workspace) {
            const stateText = String(workspace?.preview_state || '');
            if (stateText === 'ready') {
              if (String(workspace?.workspace_kind || '') === 'studio_data') return 'Ready to Explore';
              if (String(workspace?.workspace_kind || '') === 'studio_docs') return 'Ready to Read';
              return String(workspace?.workspace_kind || '') === 'studio_game' ? 'Ready to Play' : 'Ready to Preview';
            }
            if (stateText === 'error') return 'Needs Fixing';
            if (stateText === 'building') return 'Building';
            return 'Building';
          }

          function renderWorkspaceSelector(workspaces) {
            const host = document.getElementById('thread-scroll');
            host.classList.add('home-scroll');
            if (!workspaces.length) {
              host.innerHTML = `
                <section id="workspace-dropzone" class="studio-hero dropzone home-dropzone">
                  <h2>Alcove</h2>
                  <p class="hero-copy">Open a local project or start fresh. One workspace chat, live preview, and clear run output.</p>
                  <p class="dropzone-copy">Drop a folder to map a repo, or start a Studio for a game, site, data view, or docs.</p>
                  <div class="home-actions">
                    <button class="primary" type="button" onclick="openStudioModal()">New Studio</button>
                    <button type="button" onclick="promptImportWorkspace()">Import Folder</button>
                  </div>
                  <div class="dropzone-hint">Best on desktop. If the browser hides the path, Alcove will ask you to paste it.</div>
                </section>
              `;
              return;
            }
            host.innerHTML = `
              <section id="workspace-dropzone" class="studio-hero dropzone home-dropzone">
                <h2>Alcove</h2>
                <p class="hero-copy">Open a local project or start fresh. One workspace chat, live preview, and clear run output.</p>
                <p class="dropzone-copy">Drop a folder to map a repo, or start a Studio for a game, site, data view, or docs.</p>
                <div class="home-actions">
                  <button class="primary" type="button" onclick="openStudioModal()">New Studio</button>
                  <button type="button" onclick="promptImportWorkspace()">Import Folder</button>
                </div>
                <div class="dropzone-hint">Best on desktop. If the browser hides the path, Alcove will ask you to paste it.</div>
                <section class="workspace-grid">
                  ${workspaces.map((workspace) => `
                    <button class="workspace-card" type="button" onclick="selectWorkspace('${workspace.id}')">
                      <div class="workspace-card-title">${escapeHtml(workspace.display_name || workspace.id)}</div>
                      <div class="workspace-card-path">${escapeHtml(isStudioWorkspace(workspace) ? `${studioKindLabel(workspace.workspace_kind)} · ${workspace.template_kind || 'blank'}` : (workspace.repo_path || 'No repo path set yet'))}</div>
                      <div class="workspace-card-meta">${escapeHtml(String(workspace.conversation_count || 1))} chat · ${escapeHtml(formatStamp(workspace.updated_at))}</div>
                    </button>
                  `).join('')}
                </section>
              </section>
            `;
          }

          function goToWorkspaceSelector() {
            state.workspaceId = null;
            state.conversationId = null;
            state.workspace = null;
            state.lastSignature = null;
            state.reviewPaneHidden = true;
            closeMobilePanes();
            applyReviewPaneVisibility();
            renderWorkspaceSelector(state.workspaces || []);
            loadReview();
            updateControls();
          }

          function renderHomePane() {
            const recent = (state.workspaces || []).slice(0, 4);
            return `
              <section class="home-shell">
                <section class="home-panel">
                  <h2>Bring in a project</h2>
                  <p>Start a Studio or map a local repo. Alcove keeps the chat, preview, and run details together.</p>
                  <div class="home-actions">
                    <button class="primary" type="button" onclick="openStudioModal()">New Studio</button>
                    <button type="button" onclick="promptImportWorkspace()">Import Folder</button>
                  </div>
                  <div id="workspace-dropzone" class="dropzone">
                    <strong>Drop a folder to map a local project</strong>
                    <p class="dropzone-copy">Drag a project folder from Finder into Alcove and it will create a workspace for that repo.</p>
                    <div class="dropzone-hint">Best on desktop. If the browser hides the file path, Alcove will ask you to paste it.</div>
                  </div>
                </section>
                <section class="home-panel">
                  <h3>Recent Workspaces</h3>
                  <p>Pick up where you left off.</p>
                  <section class="workspace-grid compact">
                    ${recent.length ? recent.map((workspace) => `
                      <button class="workspace-card" type="button" onclick="selectWorkspace('${workspace.id}')">
                        <div class="workspace-card-title">${escapeHtml(workspace.display_name || workspace.id)}</div>
                        <div class="workspace-card-path">${escapeHtml(isStudioWorkspace(workspace) ? `${studioKindLabel(workspace.workspace_kind)} · ${workspace.template_kind || 'blank'}` : (workspace.repo_path || 'No repo path set yet'))}</div>
                        <div class="workspace-card-meta">${escapeHtml(String(workspace.conversation_count || 1))} chat · ${escapeHtml(formatStamp(workspace.updated_at))}</div>
                      </button>
                    `).join('') : '<div class="empty">No recent workspaces yet.</div>'}
                  </section>
                </section>
              </section>
            `;
          }

          function renderThread(conversation) {
            state.conversationCache = conversation;
            const host = document.getElementById('thread-scroll');
            host.classList.remove('home-scroll');
            const messages = (conversation.messages || []).map(normalizeMessage);
            const shouldStickToBottom =
              !state.lastSignature ||
              (host.scrollHeight - host.scrollTop - host.clientHeight) < 48;
            if (!messages.length) {
              host.innerHTML = '<div class="empty">No messages yet. Start with a short prompt to verify the browser workflow.</div>';
              return;
            }
            host.innerHTML = messages.map((message) => {
              const phase = phaseLabel(message.phase);
              return `<article class="message ${message.role === 'user' ? 'user' : 'assistant'}">${phase ? `<span class="message-phase">${escapeHtml(phase)}</span>` : ''}<div class="message-body">${escapeHtml(message.content)}</div></article>`;
            }).join('');
            if (shouldStickToBottom) {
              host.scrollTop = host.scrollHeight;
            }
          }

          function renderStatus(status) {
            state.runStatus = status || { state: 'idle', step: 'Idle' };
            const stateText = String(state.runStatus.state || 'idle');
            setChip('global-run-chip', `run: ${stateText}`, stateText);
            const active = isActiveState(stateText);
            if (!state.serverInfo) {
              setServerDot('offline', 'Offline');
            } else if (active) {
              setServerDot('busy', 'Working');
            } else {
              setServerDot('online', 'Ready');
            }
            const buildBadge = document.getElementById('build-badge');
            if (buildBadge) {
              buildBadge.textContent = state.serverInfo?.build_label || 'Build unavailable';
              const repoPath = state.serverInfo?.repo_path || 'unknown repo';
              const port = state.serverInfo?.bind_port || 'unknown port';
              buildBadge.title = `${repoPath} on ${port}`;
            }
            updateStudioModeUI();
            updateControls();
          }

          function toggleReviewPane() {
            state.reviewPaneHidden = !state.reviewPaneHidden;
            applyReviewPaneVisibility();
            closeActionsMenu();
          }

          function applyReviewPaneVisibility() {
            const pane = document.querySelector('.review-pane');
            if (!pane) return;
            pane.style.display = state.reviewPaneHidden ? 'none' : '';
          }

          function renderReviewPane(payload) {
            state.review = payload;
            const host = document.getElementById('review-scroll');
            const eyebrow = document.getElementById('side-eyebrow');
            const title = document.getElementById('side-title');
            const copy = document.getElementById('side-copy');
            const actions = document.getElementById('side-actions');
            if (!state.workspaceId || !state.conversationId || !state.workspace) {
              host.classList.remove('studio-scroll');
              if (actions) actions.innerHTML = '';
              if (eyebrow) eyebrow.textContent = 'Home';
              if (title) title.textContent = 'Bring in a project';
              if (copy) copy.textContent = 'Open a repo or start a Studio. Preview, publish, and run details show up here.';
              host.innerHTML = renderHomePane();
              return;
            }
            if (isStudioWorkspace(state.workspace)) {
              host.classList.add('studio-scroll');
              if (eyebrow) eyebrow.textContent = 'Studio';
              if (title) title.textContent = state.workspace.artifact_title || state.workspace.game_title || state.workspace.display_name || 'Alcove Studio';
              if (copy) copy.textContent = 'Preview, publish, and project details live here beside the workspace chat.';
              if (actions) {
                const workspaceKind = state.workspace?.workspace_kind || 'studio_game';
                actions.innerHTML = `
                  <button class="primary" type="button" onclick="refreshStudioPreview()">${escapeHtml(studioPrimaryAction(workspaceKind))}</button>
                  <button type="button" onclick="publishStudioWorkspace()">Publish</button>
                  <button type="button" onclick="remixStudioWorkspace()">Remix</button>
                `;
              }
              host.innerHTML = renderStudioPane();
              return;
            }
            host.classList.remove('studio-scroll');
            if (actions) actions.innerHTML = '';
            if (eyebrow) eyebrow.textContent = 'Review';
            if (title) title.textContent = 'Run Output';
            if (copy) copy.textContent = 'Operational detail lives here, not in the bubbles.';
            const run = payload.run || {};
            const checks = payload.checks || {};
            const changedFiles = payload.changed_files || [];
            const summary = payload.summary || 'No summary yet.';
            const latest = (payload.latest_result && payload.latest_result.content) || '';
            host.innerHTML = `
              <section class="review-card">
                <p class="review-title">Lifecycle</p>
                <p class="review-line">State: ${escapeHtml(run.state || 'idle')}</p>
                <p class="review-line subtle">Step: ${escapeHtml(run.step || 'Idle')}</p>
                <p class="review-line subtle">Mode: ${escapeHtml(run.mode || 'message')}</p>
                <p class="review-line subtle">Updated: ${escapeHtml(formatStamp(run.updated_at))}</p>
              </section>
              <section class="review-card">
                <p class="review-title">Summary</p>
                <p class="review-line">${escapeHtml(summary)}</p>
              </section>
              <section class="review-card">
                <p class="review-title">Changed Files</p>
                ${
                  changedFiles.length
                    ? `<ul class="review-list">${changedFiles.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
                    : '<p class="review-line subtle">No file list yet.</p>'
                }
              </section>
              <section class="review-card">
                <p class="review-title">Checks</p>
                <p class="review-line subtle">Passed: ${escapeHtml(String(checks.passed ?? 0))} · Failed: ${escapeHtml(String(checks.failed ?? 0))}</p>
              </section>
              <section class="review-card">
                <p class="review-title">Errors</p>
                <p class="review-line ${run.last_error ? '' : 'subtle'}">${escapeHtml(run.last_error || 'No active error.')}</p>
              </section>
              <section class="review-card">
                <p class="review-title">Artifacts</p>
                <p class="review-line subtle">${escapeHtml(payload.artifacts_path || 'Not available yet.')}</p>
              </section>
              <section class="review-card">
                <p class="review-title">Latest Output</p>
                <p class="review-line subtle">${escapeHtml(latest || 'No operational output yet.')}</p>
              </section>
            `;
          }

          function renderStudioPane() {
            const workspace = state.workspace || {};
            const previewUrl = workspace.preview_url ? `${workspace.preview_url}${workspace.preview_url.includes('?') ? '&' : '?'}v=${Date.now()}` : '';
            const publishUrl = workspace.publish_url || '';
            const workspaceKind = workspace.workspace_kind || 'studio_game';
            return `
              <section class="studio-shell">
                <section class="studio-preview-card">
                  <div class="studio-preview-bar">
                    <div class="studio-meta">
                      <div class="studio-pill">${escapeHtml(studioKindLabel(workspaceKind))}</div>
                      <div class="studio-pill">${escapeHtml(workspace.template_kind || 'blank')}</div>
                      <div class="studio-pill">${escapeHtml(childFriendlyPreviewState(workspace))}</div>
                      <div class="studio-pill">${escapeHtml(workspace.publish_state === 'published' ? 'Published' : 'Not Published')}</div>
                    </div>
                    ${publishUrl ? `<a href="${escapeHtml(publishUrl)}" target="_blank" rel="noreferrer">Share Link</a>` : '<span class="studio-preview-label">Share link appears after Publish.</span>'}
                  </div>
                  ${
                    previewUrl
                      ? `<iframe class="studio-preview-frame" src="${escapeHtml(previewUrl)}" title="${escapeHtml(studioArtifactNoun(workspaceKind))} preview"></iframe>`
                      : `<div class="studio-empty">${escapeHtml(studioEmptyState(workspaceKind))}</div>`
                  }
                </section>
              </section>
            `;
          }

          function showStudioProjectDetails() {
            closeActionsMenu();
            if (!isStudioWorkspace(state.workspace)) {
              window.alert('Project details are available for Studio workspaces.');
              return;
            }
            const workspace = state.workspace || {};
            const lines = [
              `Title: ${workspace.artifact_title || workspace.game_title || workspace.display_name || 'Alcove Studio'}`,
              `Studio: ${studioKindLabel(workspace.workspace_kind)}`,
              `Template: ${workspace.template_kind || 'blank'}`,
              `Preview URL: ${workspace.preview_url || 'Not ready yet'}`,
              `Publish URL: ${workspace.publish_url || 'Not published yet'}`,
              `Repo path: ${workspace.repo_path || 'Managed by Alcove'}`,
            ];
            window.alert(lines.join('\\n'));
          }

          async function loadWorkspaces() {
            const payload = await fetchJson('/api/workspaces');
            const workspaces = payload.workspaces || [];
            renderWorkspaces(workspaces);
            if (
              state.workspaceId &&
              !workspaces.some((workspace) => workspace.id === state.workspaceId)
            ) {
              state.conversationId = null;
              state.workspaceId = null;
              state.lastSignature = null;
              renderWorkspaceSelector(workspaces);
            }
          }

          async function selectWorkspace(workspaceId) {
            state.workspaceId = workspaceId;
            const workspace = await fetchJson(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
            state.workspace = workspace;
            state.conversationId = workspace.active_conversation_id || null;
            state.reviewPaneHidden = false;
            closeMobilePanes();
            applyReviewPaneVisibility();
            renderWorkspaces((await fetchJson('/api/workspaces')).workspaces || []);
            await loadConversationDetail();
            await loadReview();
          }

          async function loadConversationDetail() {
            if (!state.conversationId || !state.workspaceId) return;
            const payload = await fetchJson(
              `/api/conversations/${encodeURIComponent(state.conversationId)}?workspace_id=${encodeURIComponent(state.workspaceId)}`
            );
            state.workspaceId = payload.workspace_id;
            state.workspace = state.workspaces.find((workspace) => workspace.id === state.workspaceId) || state.workspace;
            syncAssistantModeUI(payload.assistant_mode || 'ask');
            const signature = JSON.stringify({
              updated_at: payload.updated_at,
              message_count: (payload.messages || []).length,
              title: payload.title,
              assistant_mode: payload.assistant_mode || 'ask',
            });
            if (signature !== state.lastSignature) {
              renderThread(payload);
              state.lastSignature = signature;
            }
            updateStudioModeUI();
          }

          async function loadReview() {
            if (!state.conversationId || !state.workspaceId) {
              renderReviewPane({ run: state.runStatus, checks: {}, changed_files: [] });
              return;
            }
            try {
              const payload = await fetchJson(
                `/api/review?conversation_id=${encodeURIComponent(state.conversationId)}&workspace_id=${encodeURIComponent(state.workspaceId)}`
              );
              renderReviewPane(payload);
            } catch (_) {
              renderReviewPane({ run: state.runStatus, checks: {}, changed_files: [] });
            }
          }

          function updateStudioModeUI() {
            const textarea = document.getElementById('composer');
            if (!textarea) return;
            if (isStudioWorkspace(state.workspace)) {
              document.getElementById('composer-mode').value = 'message';
              document.getElementById('assistant-mode').value = 'dev';
              state.assistantMode = 'dev';
              textarea.placeholder = studioPlaceholder(state.workspace?.workspace_kind);
              const modeMessage = document.getElementById('menu-mode-message');
              const modeLoop = document.getElementById('menu-mode-loop');
              if (modeMessage) modeMessage.classList.add('active');
              if (modeLoop) modeLoop.classList.remove('active');
              const ask = document.getElementById('menu-assistant-ask');
              const ops = document.getElementById('menu-assistant-ops');
              const dev = document.getElementById('menu-assistant-dev');
              if (ask) ask.classList.remove('active');
              if (ops) ops.classList.remove('active');
              if (dev) dev.classList.add('active');
            } else {
              textarea.placeholder = 'Describe what should happen next.';
            }
          }

          async function setMode(mode) {
            if (mode === 'loop' && state.assistantMode !== 'dev') {
              window.alert('Loop mode requires dev capability mode.');
              return;
            }
            document.getElementById('composer-mode').value = mode;
            const modeMessage = document.getElementById('menu-mode-message');
            const modeLoop = document.getElementById('menu-mode-loop');
            if (modeMessage) modeMessage.classList.toggle('active', mode === 'message');
            if (modeLoop) modeLoop.classList.toggle('active', mode === 'loop');
            closeActionsMenu();
          }

          function syncAssistantModeUI(mode) {
            const resolved = mode === 'dev' || mode === 'ops' ? mode : 'ask';
            state.assistantMode = resolved;
            document.getElementById('assistant-mode').value = resolved;
            const ask = document.getElementById('menu-assistant-ask');
            const ops = document.getElementById('menu-assistant-ops');
            const dev = document.getElementById('menu-assistant-dev');
            if (ask) ask.classList.toggle('active', resolved === 'ask');
            if (ops) ops.classList.toggle('active', resolved === 'ops');
            if (dev) dev.classList.toggle('active', resolved === 'dev');
            if (resolved !== 'dev' && document.getElementById('composer-mode').value === 'loop') {
              document.getElementById('composer-mode').value = 'message';
              if (document.getElementById('menu-mode-message')) document.getElementById('menu-mode-message').classList.add('active');
              if (document.getElementById('menu-mode-loop')) document.getElementById('menu-mode-loop').classList.remove('active');
            }
            updateControls();
          }

          async function setAssistantMode(mode) {
            if (!state.workspaceId || !state.conversationId) {
              syncAssistantModeUI(mode);
              return;
            }
            try {
              const payload = await fetchJson(`/api/conversations/${encodeURIComponent(state.conversationId)}/context`, {
                method: 'PATCH',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({
                  workspace_id: state.workspaceId,
                  assistant_mode: mode,
                }),
              });
              syncAssistantModeUI(payload.assistant_mode || mode);
            } catch (error) {
              window.alert(error.message || 'Could not set assistant capability mode');
            }
            closeActionsMenu();
          }

          function setSelectOptions(selectId, options, selectedValue, config = {}) {
            const allowBlank = Boolean(config.allowBlank);
            const blankLabel = config.blankLabel || 'Use default model';
            const select = document.getElementById(selectId);
            if (!select) return;
            select.innerHTML = '';
            if (allowBlank) {
              const blank = document.createElement('option');
              blank.value = '';
              blank.textContent = blankLabel;
              select.appendChild(blank);
            }
            for (const option of options) {
              const el = document.createElement('option');
              el.value = option.value;
              el.textContent = option.label;
              select.appendChild(el);
            }
            if (selectedValue && !options.some((item) => item.value === selectedValue)) {
              const custom = document.createElement('option');
              custom.value = selectedValue;
              custom.textContent = `${selectedValue} (custom)`;
              select.appendChild(custom);
            }
            select.value = selectedValue || '';
          }

          function modelOptionUnion(ollamaModels) {
            const codexOptions = CODEX_MODEL_OPTIONS.map((item) => ({ value: item.value, label: item.label }));
            const ollamaOptions = (ollamaModels || []).map((model) => ({ value: model, label: `${model} (Ollama)` }));
            return [...codexOptions, ...ollamaOptions];
          }

          async function loadSettings() {
            const payload = await fetchJson('/api/settings');
            document.getElementById('settings-provider').value = payload.provider || 'codex';
            document.getElementById('settings-ollama-host').value = payload.ollama_host || 'http://127.0.0.1:11434';
            document.getElementById('settings-max-step-retries').value = String(payload.max_step_retries ?? 2);
            document.getElementById('settings-phase-timeout').value = String(payload.phase_timeout_seconds ?? 240);
            setSelectOptions(
              'settings-model',
              modelOptionUnion([]),
              payload.model || 'gpt-5.3-codex',
              { allowBlank: false }
            );
            setSelectOptions(
              'settings-planner-model',
              modelOptionUnion([]),
              payload.planner_model || '',
              { allowBlank: true, blankLabel: 'Use default model' }
            );
            setSelectOptions(
              'settings-builder-model',
              modelOptionUnion([]),
              payload.builder_model || '',
              { allowBlank: true, blankLabel: 'Use default model' }
            );
            setSelectOptions(
              'settings-reviewer-model',
              modelOptionUnion([]),
              payload.reviewer_model || '',
              { allowBlank: true, blankLabel: 'Use default model' }
            );
          }

          function renderConnectionsPanel() {
            const host = document.getElementById('connections-panel');
            if (!host) return;
            const info = state.serverInfo || {};
            const setupReport = state.setupReport || {};
            const localUrl = info.local_url || info.localhost_url || 'http://127.0.0.1:8765/';
            const phoneUrl = info.phone_url || '';
            const phoneEnabled = Boolean(info.phone_enabled && phoneUrl);
            const build = info.build_label || 'Build unavailable';
            const repoPath = info.repo_path || 'Unknown repo';
            const port = info.bind_port || '8765';
            host.innerHTML = `
              ${setupReport.ok === false ? `
                <article class="connection-card">
                  <div class="connection-title">
                    <span>Setup</span>
                    <span class="connection-state">Needs attention</span>
                  </div>
                  <p class="connection-copy">Alcove detected a local setup issue. Run <code>alcove doctor</code> in this repo after fixing the items below.</p>
                  <div class="connection-meta">
                    ${(setupReport.checks || [])
                      .filter((check) => !check.ok)
                      .map((check) => `${escapeHtml(check.label || check.key)}: ${escapeHtml(check.fix || check.detail || '')}`)
                      .join('<br />')}
                  </div>
                </article>
              ` : ''}
              <article class="connection-card">
                <div class="connection-title">
                  <span>This Mac</span>
                  <span class="connection-state">Ready</span>
                </div>
                <p class="connection-copy">Alcove runs locally on this Mac. Desktop always uses the local address.</p>
                <p class="connection-url">${escapeHtml(localUrl)}</p>
                <div class="connection-actions">
                  <button type="button" onclick="openConnectionUrl('local')">Open Local</button>
                  <button type="button" onclick="copyConnectionUrl('local')">Copy Local Link</button>
                </div>
              </article>
              <article class="connection-card">
                <div class="connection-title">
                  <span>Phone</span>
                  <span class="connection-state">${phoneEnabled ? 'Available' : 'Unavailable'}</span>
                </div>
                <p class="connection-copy">Use Tailscale to open Alcove from your phone when you want companion access.</p>
                <p class="connection-url">${escapeHtml(phoneEnabled ? phoneUrl : (info.phone_reason || 'Tailscale phone access is not available right now.'))}</p>
                <div class="connection-actions">
                  <button type="button" onclick="openConnectionUrl('phone')" ${phoneEnabled ? '' : 'disabled'}>Open on Phone</button>
                  <button type="button" onclick="copyConnectionUrl('phone')" ${phoneEnabled ? '' : 'disabled'}>Copy Phone Link</button>
                </div>
                ${phoneEnabled ? `
                  <div class="qr-panel">
                    <img src="/api/connections/phone-qr.svg?v=${Date.now()}" alt="QR code for phone access" />
                    <div class="qr-caption">Scan to open on your phone.</div>
                  </div>
                ` : ''}
              </article>
              <div class="connection-meta">
                Running from: ${escapeHtml(repoPath)}<br />
                Port: ${escapeHtml(String(port))}<br />
                Build: ${escapeHtml(build)}
              </div>
            `;
          }

          function openSettings() {
            const modal = document.getElementById('settings-modal');
            if (!modal) return;
            modal.hidden = false;
            closeActionsMenu();
            renderConnectionsPanel();
            loadSettings().catch((error) => {
              const status = document.getElementById('settings-status');
              if (status) status.textContent = error.message || 'Could not load settings.';
            });
            refreshOllamaModels().catch(() => {});
          }

          function closeSettings() {
            const modal = document.getElementById('settings-modal');
            if (!modal) return;
            modal.hidden = true;
          }

          function openStudioModal() {
            const modal = document.getElementById('studio-modal');
            if (!modal) return;
            const status = document.getElementById('studio-status');
            if (status) status.textContent = '';
            updateStudioTemplateOptions();
            modal.hidden = false;
            closeActionsMenu();
          }

          function closeStudioModal() {
            const modal = document.getElementById('studio-modal');
            if (!modal) return;
            modal.hidden = true;
          }

          function updateStudioTemplateOptions() {
            const workspaceKind = document.getElementById('studio-workspace-kind')?.value || 'studio_game';
            const titleLabel = document.getElementById('studio-title-label');
            const titleInput = document.getElementById('studio-artifact-title');
            const templateSelect = document.getElementById('studio-template-kind');
            const themeLabel = document.getElementById('studio-theme-label');
            const themePrompt = document.getElementById('studio-theme-prompt');
            const options = STUDIO_TEMPLATES[workspaceKind] || STUDIO_TEMPLATES.studio_game;
            if (templateSelect) {
              templateSelect.innerHTML = options.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join('');
            }
            if (titleLabel) {
              titleLabel.firstChild.textContent =
                workspaceKind === 'studio_game' ? 'Game name' :
                workspaceKind === 'studio_web' ? 'Site name' :
                workspaceKind === 'studio_data' ? 'Dataset name' :
                'Docs name';
            }
            if (themeLabel) {
              themeLabel.firstChild.textContent = workspaceKind === 'studio_data' ? 'Focus prompt (optional)' : 'Theme prompt (optional)';
            }
            if (titleInput && !titleInput.value.trim()) {
              titleInput.placeholder = studioDefaultTitle(workspaceKind);
            }
            if (themePrompt && !themePrompt.value.trim()) {
              themePrompt.placeholder =
                workspaceKind === 'studio_game' ? 'A playful jungle at sunset with friendly robots.' :
                workspaceKind === 'studio_web' ? 'A bold launch page for a calm, premium product.' :
                workspaceKind === 'studio_data' ? 'Revenue data with trust cues, clear trends, and simple charts.' :
                'Helpful docs with a friendly getting started flow.';
            }
          }

          async function refreshOllamaModels() {
            const status = document.getElementById('settings-status');
            try {
              const settings = await fetchJson('/api/settings');
              const payload = await fetchJson('/api/providers/ollama/models');
              const models = payload.models || [];
              const options = modelOptionUnion(models);
              setSelectOptions('settings-model', options, settings.model || 'gpt-5.3-codex', { allowBlank: false });
              setSelectOptions('settings-planner-model', options, settings.planner_model || '', { allowBlank: true, blankLabel: 'Use default model' });
              setSelectOptions('settings-builder-model', options, settings.builder_model || '', { allowBlank: true, blankLabel: 'Use default model' });
              setSelectOptions('settings-reviewer-model', options, settings.reviewer_model || '', { allowBlank: true, blankLabel: 'Use default model' });
              if (status) status.textContent = payload.message || `Found ${models.length} model(s).`;
            } catch (error) {
              if (status) status.textContent = error.message || 'Could not fetch Ollama models.';
            }
          }

          async function saveSettings() {
            const status = document.getElementById('settings-status');
            try {
              const payload = await fetchJson('/api/settings', {
                method: 'PATCH',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({
                  provider: document.getElementById('settings-provider').value,
                  model: document.getElementById('settings-model').value,
                  ollama_host: document.getElementById('settings-ollama-host').value,
                  planner_model: document.getElementById('settings-planner-model').value,
                  builder_model: document.getElementById('settings-builder-model').value,
                  reviewer_model: document.getElementById('settings-reviewer-model').value,
                  max_step_retries: Number(document.getElementById('settings-max-step-retries').value || 2),
                  phase_timeout_seconds: Number(document.getElementById('settings-phase-timeout').value || 240),
                }),
              });
              if (status) status.textContent = `Saved. Provider: ${payload.provider}, model: ${payload.model}`;
            } catch (error) {
              if (status) status.textContent = error.message || 'Could not save settings.';
            }
          }

          async function submitComposer(event) {
            event.preventDefault();
            if (state.submitting) return false;
            if (!state.conversationId || !state.workspaceId) {
              window.alert('Choose a workspace before sending a prompt.');
              return false;
            }
            const textarea = document.getElementById('composer');
            const input = document.getElementById('composer-attachments');
            const files = Array.from((input && input.files) || []);
            const content = textarea.value.trim();
            const mode = document.getElementById('composer-mode').value;
            if (!content && !files.length) {
              window.alert('Type a prompt or attach a screenshot first.');
              return false;
            }
            state.submitting = true;
            updateControls();
            try {
              if (files.length) {
                const formData = new FormData();
                formData.append('content', content);
                formData.append('mode', mode);
                formData.append('assistant_mode', document.getElementById('assistant-mode').value);
                formData.append('workspace_id', state.workspaceId);
                files.forEach((file) => formData.append('attachments', file));
                await fetchJson(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages`, {
                  method: 'POST',
                  body: formData,
                });
              } else {
                await fetchJson(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages`, {
                  method: 'POST',
                  headers: { 'content-type': 'application/json' },
                  body: JSON.stringify({
                    content,
                    mode,
                    assistant_mode: document.getElementById('assistant-mode').value,
                    workspace_id: state.workspaceId,
                  }),
                });
              }
              textarea.value = '';
              if (input) input.value = '';
              onComposerFilesChanged();
              state.lastSignature = null;
              if (mode === 'loop') {
                await setMode('message');
              }
              await loadConversationDetail();
              await pollStatus();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Request failed');
            } finally {
              state.submitting = false;
              updateControls();
            }
            return false;
          }

          async function createWorkspace() {
            const label = (window.prompt('Workspace name (for example: Clementine Kids)') || '').trim();
            const raw = (window.prompt('Workspace ID (optional). Leave blank to auto-generate.') || '').trim();
            const workspaceIdSeed = raw || label;
            const workspaceId = workspaceIdSeed.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
            if (!workspaceId) return;
            const repoPath = (window.prompt('Repository path (optional)', '') || '').trim();
            try {
              const workspace = await fetchJson('/api/workspaces', {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({
                  id: workspaceId,
                  display_name: label || workspaceId,
                  repo_path: repoPath || null,
                }),
              });
              state.workspaceId = workspace.id || workspaceId;
              state.conversationId = workspace.active_conversation_id || null;
              state.lastSignature = null;
              await loadWorkspaces();
              await loadConversationDetail();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Could not create workspace');
            }
            closeActionsMenu();
          }

          async function createWorkspaceFromFolderPath(folderPath, displayName) {
            const trimmedPath = String(folderPath || '').trim();
            if (!trimmedPath) return;
            const cleanPath = trimmedPath.replace(/^file:\/\//, '');
            const segments = cleanPath.split('/').filter(Boolean);
            const folderName = String(displayName || segments[segments.length - 1] || 'workspace').trim();
            const workspaceId = slugifyWorkspaceId(folderName);
            if (!workspaceId) {
              window.alert('Could not create a workspace id from that folder.');
              return;
            }
            const workspace = await fetchJson('/api/workspaces', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({
                id: workspaceId,
                display_name: folderName,
                repo_path: decodeURIComponent(cleanPath),
              }),
            });
            state.workspaceId = workspace.id || workspaceId;
            state.conversationId = workspace.active_conversation_id || null;
            state.lastSignature = null;
            await loadWorkspaces();
            await loadConversationDetail();
            await loadReview();
          }

          async function promptImportWorkspace() {
            const folderPath = (window.prompt('Paste the local folder path to map into Alcove.', '') || '').trim();
            if (!folderPath) return;
            try {
              await createWorkspaceFromFolderPath(folderPath);
            } catch (error) {
              window.alert(error.message || 'Could not import that folder.');
            }
          }

          function setDropzoneActive(active) {
            const zones = document.querySelectorAll('.dropzone');
            zones.forEach((zone) => zone.classList.toggle('is-active', active));
          }

          function extractDroppedFolderPath(dataTransfer) {
            if (!dataTransfer) return null;
            const uriList = dataTransfer.getData('text/uri-list') || dataTransfer.getData('text/plain') || '';
            const candidate = uriList
              .split(String.fromCharCode(10))
              .map((line) => line.trim())
              .find((line) => line && !line.startsWith('#') && line.startsWith('file://'));
            return candidate || null;
          }

          async function handleWorkspaceDrop(event) {
            event.preventDefault();
            dropDepth = 0;
            setDropzoneActive(false);
            const droppedPath = extractDroppedFolderPath(event.dataTransfer);
            if (!droppedPath) {
              window.alert('Finder did not share a folder path here. Please use Import Folder and paste the path.');
              return;
            }
            try {
              await createWorkspaceFromFolderPath(droppedPath);
            } catch (error) {
              window.alert(error.message || 'Could not import that folder.');
            }
          }

          function bindWorkspaceDropTargets() {
            const targets = [document.getElementById('thread-scroll'), document.getElementById('review-scroll'), document.getElementById('shell')].filter(Boolean);
            if (!targets.length) return;
            targets.forEach((target) => {
              target.addEventListener('dragenter', (event) => {
                event.preventDefault();
                dropDepth += 1;
                setDropzoneActive(true);
              });
              target.addEventListener('dragover', (event) => {
                event.preventDefault();
                setDropzoneActive(true);
              });
              target.addEventListener('dragleave', () => {
                dropDepth = Math.max(0, dropDepth - 1);
                if (dropDepth === 0) setDropzoneActive(false);
              });
              target.addEventListener('drop', handleWorkspaceDrop);
            });
          }

          async function createStudioWorkspace() {
            const workspaceKind = document.getElementById('studio-workspace-kind')?.value || 'studio_game';
            const title = (document.getElementById('studio-artifact-title')?.value || '').trim();
            const templateKind = document.getElementById('studio-template-kind')?.value || '';
            const themePrompt = (document.getElementById('studio-theme-prompt')?.value || '').trim();
            const status = document.getElementById('studio-status');
            if (!title) {
              if (status) status.textContent = `Give your ${studioArtifactNoun(workspaceKind)} a name first.`;
              return;
            }
            if (status) status.textContent = 'Building your studio...';
            try {
              const payload = await fetchJson('/api/studio/workspaces', {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({
                  workspace_kind: workspaceKind,
                  artifact_title: title,
                  template_kind: templateKind,
                  theme_prompt: themePrompt || null,
                }),
              });
              state.workspace = payload.workspace;
              state.workspaceId = payload.workspace?.id || null;
              state.conversationId = payload.conversation?.id || payload.workspace?.active_conversation_id || null;
              state.lastSignature = null;
              closeStudioModal();
              await loadWorkspaces();
              await loadConversationDetail();
              await loadReview();
            } catch (error) {
              if (status) status.textContent = error.message || 'Could not create the studio.';
            }
          }

          async function importActiveRepositories() {
            try {
              const payload = await fetchJson('/api/repositories/active?limit=8');
              const repositories = payload.repositories || [];
              if (!repositories.length) {
                window.alert('No active repositories were found.');
                return;
              }
              if (!window.confirm(`Import top ${repositories.length} active repositories as workspace definitions?`)) {
                return;
              }
              for (const repo of repositories) {
                await fetchJson('/api/workspaces', {
                  method: 'POST',
                  headers: { 'content-type': 'application/json' },
                  body: JSON.stringify({
                    id: repo.workspace_id,
                    display_name: repo.repo_name,
                    repo_path: repo.repo_path,
                  }),
                });
              }
              await loadWorkspaces();
            } catch (error) {
              window.alert(error.message || 'Could not load active repositories');
            }
            closeActionsMenu();
          }

          async function clearConversation() {
            if (!state.workspaceId || !state.conversationId) {
              window.alert('Choose a workspace first.');
              return;
            }
            if (!window.confirm('Clear all messages in this workspace chat?')) return;
            try {
              await fetchJson(`/api/conversations/${encodeURIComponent(state.conversationId)}/clear`, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ workspace_id: state.workspaceId }),
              });
              state.lastSignature = null;
              clearComposerAttachments();
              await loadWorkspaces();
              await loadConversationDetail();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Could not clear chat');
            }
            closeActionsMenu();
          }

          async function refreshStudioPreview() {
            if (!state.workspaceId || !isStudioWorkspace(state.workspace)) return;
            try {
              state.workspace = await fetchJson(`/api/workspaces/${encodeURIComponent(state.workspaceId)}/studio/refresh`, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({}),
              });
              await loadWorkspaces();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Could not refresh the preview');
            }
          }

          async function publishStudioWorkspace() {
            if (!state.workspaceId || !isStudioWorkspace(state.workspace)) return;
            try {
              state.workspace = await fetchJson(`/api/workspaces/${encodeURIComponent(state.workspaceId)}/studio/publish`, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({}),
              });
              await loadWorkspaces();
              await loadReview();
              if (state.workspace?.publish_url) {
                window.open(state.workspace.publish_url, '_blank', 'noopener,noreferrer');
              }
            } catch (error) {
              window.alert(error.message || 'Could not publish the studio');
            }
          }

          function focusStudioComposer() {
            closeActionsMenu();
            const textarea = document.getElementById('composer');
            if (!textarea) return;
            textarea.focus();
            if (!textarea.value.trim()) {
              textarea.value = 'Please ';
              textarea.setSelectionRange(textarea.value.length, textarea.value.length);
            }
          }

          async function remixStudioWorkspace() {
            if (!isStudioWorkspace(state.workspace)) {
              openStudioModal();
              return;
            }
            const sourceTitle = state.workspace?.artifact_title || state.workspace?.game_title || state.workspace?.display_name || 'Remix';
            const payload = {
              workspace_kind: state.workspace?.workspace_kind || 'studio_game',
              artifact_title: `${sourceTitle} Remix`,
              template_kind: state.workspace?.template_kind || 'blank',
              theme_prompt: state.workspace?.theme_prompt || '',
            };
            try {
              const created = await fetchJson('/api/studio/workspaces', {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify(payload),
              });
              state.workspace = created.workspace;
              state.workspaceId = created.workspace?.id || null;
              state.conversationId = created.conversation?.id || created.workspace?.active_conversation_id || null;
              state.lastSignature = null;
              await loadWorkspaces();
              await loadConversationDetail();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Could not remix this studio');
            }
          }

          async function stopRun() {
            try {
              await fetchJson('/api/runs/stop-safely', { method: 'POST' });
              await pollStatus();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Could not stop the run');
            }
            closeActionsMenu();
          }

          async function loadServerInfo() {
            try {
              state.serverInfo = await fetchJson('/api/server-info');
            } catch (_) {
              state.serverInfo = null;
            }
            renderStatus(state.runStatus);
          }

          async function loadSetupStatus() {
            try {
              state.setupReport = await fetchJson('/api/setup-check');
            } catch (_) {
              state.setupReport = null;
            }
            renderSetupBanner();
          }

          async function pollStatus() {
            try {
              const status = await fetchJson('/api/run-status');
              renderStatus(status);
              if (state.conversationId) {
                await loadConversationDetail();
              }
            } catch (_) {}
          }

          async function pollEvents() {
            try {
              const payload = await fetchJson(`/api/events/since?cursor=${encodeURIComponent(state.eventCursor)}&limit=100`);
              state.eventCursor = String(payload.next_cursor || state.eventCursor || '0');
              const events = payload.events || [];
              if (!events.length) return;
              let refreshWorkspaces = false;
              let refreshThread = false;
              let refreshReview = false;
              for (const event of events) {
                const type = String(event.type || '');
                const data = event.payload || {};
                if (type.startsWith('run.')) {
                  refreshReview = true;
                  if (data.status && typeof data.status === 'object') {
                    renderStatus(data.status);
                  } else {
                    await pollStatus();
                  }
                }
                if (type.startsWith('conversation.')) {
                  refreshWorkspaces = true;
                  refreshReview = true;
                  const id = data.conversation_id;
                  if (!id || id === state.conversationId) {
                    refreshThread = true;
                  }
                }
                if (type.startsWith('workspace.')) {
                  refreshWorkspaces = true;
                  refreshReview = true;
                }
              }
              if (refreshWorkspaces) await loadWorkspaces();
              if (refreshThread && state.conversationId) {
                state.lastSignature = null;
                await loadConversationDetail();
              }
              if (refreshReview) await loadReview();
            } catch (_) {}
          }

          async function bootstrap() {
            setMode('message');
            syncAssistantModeUI('ask');
            renderStatus({ state: 'idle', step: 'Loading workspaces' });
            applyStoredPaneLayout();
            bindPaneDivider();
            applyReviewPaneVisibility();
            bindWorkspaceDropTargets();
            await loadSetupStatus();
            await loadServerInfo();
            await loadWorkspaces();
            await pollStatus();
            await loadReview();
            updateControls();
            applyMobileDefaults();
            syncKeyboardInset();
            document.addEventListener('click', (event) => {
              const menu = document.getElementById('actions-menu');
              const button = document.getElementById('menu-button');
              if (!menu || !button) return;
              const target = event.target;
              if (!(target instanceof Node)) return;
              if (menu.contains(target) || button.contains(target)) return;
              closeActionsMenu();
            });
            if (window.visualViewport) {
              window.visualViewport.addEventListener('resize', syncKeyboardInset);
              window.visualViewport.addEventListener('scroll', syncKeyboardInset);
            }
            const composer = document.getElementById('composer');
            if (composer) {
              composer.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') return;
                if (event.shiftKey) return;
                event.preventDefault();
                document.querySelector('.composer')?.requestSubmit();
              });
            }
            window.setInterval(pollEvents, 1200);
            window.setInterval(pollStatus, 5000);
            window.setInterval(loadServerInfo, 10000);
            window.setInterval(loadSetupStatus, 15000);
            window.addEventListener('resize', () => {
              applyStoredPaneLayout();
              applyMobileDefaults();
              syncKeyboardInset();
            });
          }

          bootstrap().catch((error) => {
            document.getElementById('thread-scroll').innerHTML = `<div class="empty">${escapeHtml(error.message || 'Could not load the web UI.')}</div>`;
          });
        </script>
      </body>
    </html>
    """

def _shell(*, sidebar_title: str, sidebar_actions: str, sidebar_body: str, main_body: str) -> str:
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <title>Alcove Companion</title>
        <style>
          :root {{
            --bg: #f4f5f7;
            --panel: #fbfbfc;
            --ink: #24272c;
            --muted: #808791;
            --line: #d6dae0;
            --soft: #edf1f5;
            --accent: #3f644b;
            --danger: #b64e43;
            --warning: #d5a021;
          }}
          * {{ box-sizing: border-box; }}
          html, body {{
            max-width: 100%;
            overflow-x: hidden;
            overscroll-behavior-x: none;
            touch-action: pan-y;
          }}
          body {{
            margin: 0;
            font-family: Helvetica, Arial, sans-serif;
            color: var(--ink);
            background: var(--bg);
            min-height: 100vh;
          }}
          .app-bar {{
            height: 38px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-bottom: 1px solid #d4d8de;
            background: #f6f7f9;
            font-size: 12px;
            font-weight: 700;
          }}
          .app {{
            display: flex;
            gap: 12px;
            padding: 20px;
            min-height: calc(100vh - 38px);
            max-width: 100%;
            overflow-x: clip;
          }}
          .sidebar {{
            width: 220px;
            min-width: 220px;
            background: var(--panel);
            padding: 14px 12px 12px;
          }}
          .sidebar-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
          }}
          .eyebrow {{
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.1em;
            color: var(--muted);
            font-weight: 700;
          }}
          .back-link {{
            display: inline-block;
            margin-bottom: 8px;
            color: var(--muted);
            text-decoration: none;
            font-size: 12px;
          }}
          .rail {{
            display: flex;
            flex-direction: column;
            gap: 0;
            border-top: 1px solid var(--line);
          }}
          .rail-item {{
            display: block;
            text-decoration: none;
            color: inherit;
            border: 0;
            border-bottom: 1px solid var(--line);
            background: transparent;
            padding: 10px 0;
          }}
          .rail-item:hover {{
            color: var(--accent);
          }}
          .rail-item-active {{
            background: transparent;
            box-shadow: inset 2px 0 0 var(--accent);
            padding-left: 8px;
          }}
          .rail-title {{
            font-size: 13px;
            font-weight: 600;
            line-height: 1.3;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }}
          .rail-meta, .rail-empty {{
            margin-top: 4px;
            font-size: 12px;
            color: var(--muted);
            line-height: 1.35;
          }}
          .rail-item:hover .rail-meta {{
            color: var(--accent);
          }}
          .main {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 12px;
            min-width: 0;
          }}
          .panel {{
            background: var(--panel);
            border: 1px solid #e3e7ec;
            padding: 16px;
          }}
          .panel-head {{
            margin-bottom: 12px;
          }}
          h1 {{
            margin: 3px 0 0;
            font-size: 18px;
            font-weight: 700;
            line-height: 1.25;
          }}
          .thread-panel {{
            flex: 1;
            min-height: 0;
            display: flex;
            flex-direction: column;
          }}
          .thread-box {{
            border: 2px solid #3a3934;
            min-height: 340px;
            flex: 1;
            background: #fbfcfe;
          }}
          .thread-scroll {{
            height: 100%;
            overflow: auto;
            overflow-x: hidden;
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            overscroll-behavior-x: none;
          }}
          .empty-state {{
            color: var(--muted);
            font-size: 14px;
            line-height: 1.5;
          }}
          .bubble {{
            width: fit-content;
            max-width: min(62ch, 72%);
            min-width: 0;
            padding: 8px 11px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.4;
            white-space: normal;
          }}
          .bubble-content {{
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            word-break: break-word;
          }}
          .bubble-user {{
            align-self: flex-end;
            background: var(--accent);
            color: #fcfcfa;
          }}
          .bubble-assistant {{
            align-self: flex-start;
            background: var(--soft);
            color: var(--ink);
          }}
          .composer-panel {{
            padding-top: 10px;
            padding-bottom: 10px;
          }}
          .composer {{
            border: 1px solid var(--line);
            background: #fbfcfe;
            padding: 10px;
            overflow-x: clip;
          }}
          .attachment-list {{
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
          }}
          .attachment-pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border: 1px solid var(--line);
            background: #eef2f6;
            font-size: 12px;
            color: var(--ink);
            padding: 3px 8px;
            border-radius: 999px;
            max-width: 100%;
          }}
          .attachment-pill span {{
            min-width: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }}
          .attachment-pill button {{
            border: 0;
            background: transparent;
            color: var(--muted);
            cursor: pointer;
            padding: 0;
            font-size: 12px;
          }}
          textarea {{
            width: 100%;
            min-height: 58px;
            border: 0;
            resize: vertical;
            background: transparent;
            color: var(--ink);
            font: inherit;
            font-size: 14px;
            line-height: 1.35;
            outline: none;
            max-width: 100%;
          }}
          .composer-footer {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-top: 8px;
          }}
          .loop-pill {{
            border: 1px solid #b5bcc5;
            padding: 5px 11px;
            font-size: 12px;
            color: #76808a;
            background: #f3f5f8;
          }}
          .status-cluster {{
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
          }}
          .pill {{
            width: 10px;
            height: 10px;
            border-radius: 999px;
            text-indent: -9999px;
            overflow: hidden;
            background: var(--accent);
          }}
          .pill-running {{ background: var(--warning); }}
          .pill-error {{ background: var(--danger); }}
          button {{
            appearance: none;
            border: 0;
            background: transparent;
            color: var(--ink);
            font: inherit;
          }}
          .composer-actions {{
            display: flex;
            gap: 6px;
          }}
          .send-button, .icon-button {{
            width: 24px;
            height: 24px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid var(--line);
            background: #eff2f6;
            color: var(--muted);
            font-size: 12px;
            font-weight: 700;
          }}
          .send-button {{
            background: #dfe8e0;
            color: var(--accent);
          }}
          @media (max-width: 760px) {{
            .app {{
              flex-direction: column;
              padding: 12px;
            }}
            .sidebar {{
              width: auto;
              min-width: 0;
            }}
            .thread-box {{
              min-height: 280px;
            }}
            .thread-scroll {{
              padding-bottom: calc(120px + env(safe-area-inset-bottom));
            }}
            .bubble {{
              max-width: 100%;
            }}
            .composer-panel {{
              position: sticky;
              bottom: var(--keyboard-offset, 0px);
              z-index: 4;
              background: var(--panel);
              border-top: 1px solid var(--line);
              margin-bottom: 0;
            }}
            .composer-footer {{
              flex-wrap: wrap;
              justify-content: space-between;
            }}
            .status-cluster {{
              width: 100%;
              justify-content: space-between;
            }}
          }}
        </style>
      </head>
      <body>
        <div class="app-bar">Alcove</div>
        <main class="app">
          <aside class="sidebar">
            <div class="sidebar-head">
              <div class="eyebrow">{escape(sidebar_title)}</div>
            </div>
            <div class="rail">
              {sidebar_actions}
              {sidebar_body}
            </div>
          </aside>
          <section class="main">
            {main_body}
          </section>
        </main>
        <script>
          function openAttachmentPicker() {{
            const input = document.getElementById('composer-attachments');
            if (input) input.click();
          }}

          function removeComposerAttachment(index) {{
            const input = document.getElementById('composer-attachments');
            if (!input || !input.files) return;
            const dt = new DataTransfer();
            Array.from(input.files).forEach((file, fileIndex) => {{
              if (fileIndex !== index) dt.items.add(file);
            }});
            input.files = dt.files;
            onComposerFilesChanged();
          }}

          function onComposerFilesChanged() {{
            const input = document.getElementById('composer-attachments');
            const host = document.getElementById('composer-attachment-list');
            if (!input || !host) return;
            const files = Array.from(input.files || []);
            if (!files.length) {{
              host.hidden = true;
              host.innerHTML = '';
              return;
            }}
            host.hidden = false;
            host.innerHTML = files
              .map((file, index) => {{
                const label = file.name || ('screenshot-' + (index + 1));
                const safeLabel = String(label)
                  .replaceAll('&', '&amp;')
                  .replaceAll('<', '&lt;')
                  .replaceAll('>', '&gt;');
                return `<div class="attachment-pill"><span>${{safeLabel}}</span><button type="button" onclick="removeComposerAttachment(${{index}})">x</button></div>`;
              }})
              .join('');
          }}

          function syncKeyboardInset() {{
            if (!window.matchMedia('(max-width: 760px)').matches) {{
              document.documentElement.style.setProperty('--keyboard-offset', '0px');
              return;
            }}
            const viewport = window.visualViewport;
            if (!viewport) {{
              document.documentElement.style.setProperty('--keyboard-offset', '0px');
              return;
            }}
            const inset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
            document.documentElement.style.setProperty('--keyboard-offset', `${{inset}}px`);
          }}

          async function submitComposer(event, workspaceId, conversationId) {{
            event.preventDefault();
            const textarea = document.getElementById('composer');
            const mode = document.getElementById('composer-mode').value;
            const input = document.getElementById('composer-attachments');
            const files = Array.from((input && input.files) || []);
            const content = textarea.value.trim();
            if (!content && !files.length) {{
              window.alert('Type a prompt or attach a screenshot first.');
              return false;
            }}
            let response;
            if (files.length) {{
              const formData = new FormData();
              formData.append('content', content);
              formData.append('mode', mode);
              formData.append('workspace_id', workspaceId);
              files.forEach((file) => formData.append('attachments', file));
              response = await fetch(`/api/conversations/${{conversationId}}/messages`, {{
                method: 'POST',
                body: formData,
              }});
            }} else {{
              const payload = {{ content, mode, workspace_id: workspaceId }};
              response = await fetch(`/api/conversations/${{conversationId}}/messages`, {{
                method: 'POST',
                headers: {{ 'content-type': 'application/json' }},
                body: JSON.stringify(payload),
              }});
            }}
            if (!response.ok) {{
              const error = await response.json().catch(() => ({{ detail: 'Request failed' }}));
              window.alert(error.detail || 'Request failed');
              return false;
            }}
            textarea.value = '';
            if (input) input.value = '';
            onComposerFilesChanged();
            window.location.reload();
            return false;
          }}
          function sendMode(mode) {{
            document.getElementById('composer-mode').value = mode;
            document.querySelector('.composer').requestSubmit();
          }}
          async function stopRun() {{
            await fetch('/api/runs/stop-safely', {{ method: 'POST' }});
            window.location.reload();
          }}
          async function clearChat(workspaceId, conversationId) {{
            if (!window.confirm('Clear all messages in this chat?')) return;
            const response = await fetch(`/api/conversations/${{conversationId}}/clear`, {{
              method: 'POST',
              headers: {{ 'content-type': 'application/json' }},
              body: JSON.stringify({{ workspace_id: workspaceId }}),
            }});
            if (!response.ok) {{
              const error = await response.json().catch(() => ({{ detail: 'Request failed' }}));
              window.alert(error.detail || 'Request failed');
              return;
            }}
            window.location.reload();
          }}
          syncKeyboardInset();
          if (window.visualViewport) {{
            window.visualViewport.addEventListener('resize', syncKeyboardInset);
            window.visualViewport.addEventListener('scroll', syncKeyboardInset);
          }}
          window.addEventListener('resize', syncKeyboardInset);
        </script>
      </body>
    </html>
    """
