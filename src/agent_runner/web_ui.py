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
          }
          * { box-sizing: border-box; }
          html, body { height: 100%; }
          body {
            margin: 0;
            font-family: "Avenir Next", "Helvetica Neue", Helvetica, sans-serif;
            color: var(--ink);
            background:
              radial-gradient(1200px 440px at 10% -14%, #ffffff 0%, #f4f5f7 58%),
              var(--bg);
            overflow: hidden;
          }
          .page {
            height: 100%;
            padding: 14px;
          }
          .frame {
            height: calc(100vh - 28px);
            border: 1px solid var(--line);
            background: var(--panel);
            box-shadow: var(--shadow);
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
          .topbar-copy {
            font-size: 12px;
            color: var(--muted);
          }
          .topbar-right {
            display: flex;
            gap: 8px;
            align-items: center;
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
            position: fixed;
            right: 12px;
            bottom: 10px;
            z-index: 40;
            pointer-events: none;
            border: 1px solid var(--line);
            background: rgba(251, 251, 252, 0.92);
            color: var(--muted);
            font-size: 10px;
            line-height: 1;
            letter-spacing: 0.04em;
            padding: 4px 7px;
            border-radius: 999px;
            box-shadow: 0 6px 18px rgba(26, 30, 34, 0.08);
            backdrop-filter: blur(8px);
          }
          .chip-running::before,
          .chip-starting::before,
          .chip-stopping::before { background: var(--warning); }
          .chip-failed::before { background: var(--danger); }
          .chip-succeeded::before { background: var(--ok); }
          .shell {
            min-height: 0;
            display: grid;
            grid-template-columns: 280px minmax(0, 1fr) 360px;
          }
          .pane {
            min-width: 0;
            min-height: 0;
            border-right: 1px solid var(--line-soft);
            background: var(--panel);
          }
          .thread-pane,
          .review-pane {
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
          }
          .pane:last-child {
            border-right: 0;
            background: #f7f8fb;
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
            height: 100%;
            min-height: 0;
            display: grid;
            grid-template-rows: auto minmax(0, 1fr) auto;
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
          }
          .thread-scroll {
            min-height: 0;
            height: 100%;
            overflow: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding: 18px;
            background: #fafbfd;
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
            border-top: 1px solid var(--line-soft);
            background: #f7f8fb;
            padding: 12px 18px 14px;
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
          .composer textarea {
            width: 100%;
            border: 1px solid var(--line);
            background: #fcfdff;
            color: var(--ink);
            min-height: 72px;
            resize: vertical;
            padding: 10px;
            font: inherit;
            outline: none;
          }
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
            padding: 12px 14px 18px;
          }
          .review-card {
            border: 1px solid var(--line);
            background: #fcfdff;
            padding: 10px;
            margin-bottom: 10px;
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
          @media (max-width: 1080px) {
            .shell { grid-template-columns: 260px minmax(0, 1fr); }
            .pane.review-pane { display: none; }
            .mobile-toggle { display: inline-flex; }
          }
          @media (max-width: 880px) {
            .page { padding: 8px; height: 100dvh; }
            .frame { height: calc(100dvh - 16px); }
            .shell { grid-template-columns: 1fr; }
            .thread { grid-template-rows: auto minmax(0, 1fr); }
            .pane.rail-pane,
            .pane.review-pane {
              display: none;
            }
            .shell.mobile-left .pane.rail-pane {
              display: block;
              border-right: 0;
            }
            .shell.mobile-right .pane.review-pane {
              display: block;
            }
            .shell.mobile-left .thread-pane,
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
            .thread-title {
              font-size: 17px;
              white-space: nowrap;
              overflow: hidden;
              text-overflow: ellipsis;
              max-width: 52vw;
            }
            .thread-actions { gap: 6px; }
            .thread-scroll { padding: 12px; }
            .composer-wrap {
              position: sticky;
              bottom: var(--keyboard-offset, 0px);
              z-index: 5;
              border-top: 1px solid var(--line);
              box-shadow: 0 -8px 22px rgba(20, 26, 33, 0.08);
              padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
            }
            .thread-scroll { padding-bottom: calc(130px + env(safe-area-inset-bottom)); }
            .topbar-copy { display: none; }
            .context-grid {
              grid-template-columns: 1fr;
            }
            .build-badge {
              right: 8px;
              bottom: 8px;
            }
          }
        </style>
      </head>
      <body>
        <div class="page">
          <main class="frame">
            <header class="topbar">
              <div>
                <div class="topbar-title">Alcove</div>
                <div class="topbar-copy">Defined workspaces, one active chat per workspace, one review surface.</div>
              </div>
              <div class="topbar-right">
                <button class="topbar-button" type="button" onclick="hardRefresh()">Reload</button>
                <div id="server-chip" class="chip">server</div>
                <div id="global-run-chip" class="chip">idle</div>
              </div>
            </header>
            <section id="shell" class="shell">
              <aside class="pane rail-pane">
                <div class="rail">
                  <div class="pane-head">
                    <p class="eyebrow">Workspaces</p>
                    <h1>Workspace Chats</h1>
                    <p class="pane-copy">One active chat per workspace.</p>
                  </div>
                  <div class="rail-toolbar">
                    <button class="primary" type="button" onclick="createWorkspace()">Add Workspace</button>
                    <button type="button" onclick="importActiveRepositories()">Top Repos</button>
                  </div>
                  <div id="conversation-list" class="list">
                    <div class="empty">Loading workspaces…</div>
                  </div>
                  <div class="foot">Companion mode: <a href="/m">open compact surface</a></div>
                </div>
              </aside>
              <section class="pane thread-pane">
                <div class="thread">
                  <div class="thread-head">
                    <button class="mobile-back" type="button" onclick="openMobilePane('left')">Workspaces</button>
                    <div>
                      <h2 id="thread-title" class="thread-title">Pick a workspace</h2>
                      <div id="thread-subtitle" class="thread-subtitle">No active run</div>
                    </div>
                    <div class="thread-actions">
                      <button class="mobile-toggle" type="button" onclick="openMobilePane('right')">Review</button>
                      <div id="thread-run-chip" class="chip">idle</div>
                    </div>
                  </div>
                  <div id="thread-scroll" class="thread-scroll">
                    <div class="empty">Select a workspace from the rail to open its chat.</div>
                  </div>
                  <div class="composer-wrap">
                    <form class="composer" onsubmit="return submitComposer(event)">
                      <textarea id="composer" placeholder="Describe what should happen next."></textarea>
                      <input id="composer-attachments" type="file" accept="image/*" multiple hidden onchange="onComposerFilesChanged()" />
                      <div id="composer-attachment-list" class="attachment-list" hidden></div>
                      <div class="context-grid">
                        <input id="ctx-route" class="full" placeholder="Context route (for example: /finance/cash-flow)" />
                        <input id="ctx-entity" placeholder="Entity (for example: sku=SKU-123 or account_id=acct_42)" />
                        <input id="ctx-date-window" placeholder="Date window (for example: 2026-03-01..2026-03-31)" />
                        <input id="ctx-filters" class="full" placeholder="Filters (for example: status=flagged,region=west)" />
                        <input id="ctx-columns" class="full" placeholder="Visible columns (comma-separated)" />
                      </div>
                      <div id="active-context" class="composer-hint active-context">Active context: none</div>
                      <div class="composer-meta">
                        <div class="composer-hint">Composer is the main action surface.</div>
                        <div class="mode-switch" role="tablist" aria-label="Send mode">
                          <button id="mode-message" class="mode-button active" type="button" onclick="setMode('message')">Message</button>
                          <button id="mode-loop" class="mode-button" type="button" onclick="setMode('loop')">Loop</button>
                        </div>
                      </div>
                      <div class="composer-meta">
                        <div class="composer-hint">Capability mode</div>
                        <div class="mode-switch" role="tablist" aria-label="Assistant capability mode">
                          <button id="assistant-ask" class="mode-button active" type="button" onclick="setAssistantMode('ask')">Ask</button>
                          <button id="assistant-ops" class="mode-button" type="button" onclick="setAssistantMode('ops')">Ops</button>
                          <button id="assistant-dev" class="mode-button" type="button" onclick="setAssistantMode('dev')">Dev</button>
                        </div>
                      </div>
                      <div class="composer-meta">
                        <div class="button-row">
                          <button id="attach-button" type="button" onclick="openAttachmentPicker()">Add Screenshot</button>
                          <button id="send-button" class="primary" type="submit">Send</button>
                          <button id="stop-button" type="button" onclick="stopRun()">Stop</button>
                          <button id="clear-button" class="danger" type="button" onclick="clearConversation()">Clear Chat</button>
                        </div>
                      </div>
                      <input id="composer-mode" type="hidden" value="message" />
                      <input id="assistant-mode" type="hidden" value="ask" />
                    </form>
                  </div>
                </div>
              </section>
              <aside class="pane review-pane">
                <div class="review">
                  <div class="pane-head">
                    <button class="mobile-back" type="button" onclick="closeMobilePanes()">Back</button>
                    <p class="eyebrow">Review</p>
                    <h1>Run Output</h1>
                    <p class="pane-copy">Operational detail lives here, not in the bubbles.</p>
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
        <div id="build-badge" class="build-badge">Build unavailable</div>
        <script>
          const state = {
            conversationId: null,
            workspaceId: null,
            conversationCache: null,
            lastSignature: null,
            serverInfo: null,
            runStatus: { state: 'idle', step: 'Idle' },
            review: null,
            submitting: false,
            eventCursor: '0',
            assistantMode: 'ask',
          };

          function isActiveState(value) {
            return value === 'starting' || value === 'running' || value === 'stopping';
          }

          function isMobileViewport() {
            return window.matchMedia('(max-width: 880px)').matches;
          }

          function openMobilePane(which) {
            const shell = document.getElementById('shell');
            if (!shell || !isMobileViewport()) return;
            shell.classList.remove('mobile-left', 'mobile-right');
            if (which === 'left') shell.classList.add('mobile-left');
            if (which === 'right') shell.classList.add('mobile-right');
          }

          function closeMobilePanes() {
            const shell = document.getElementById('shell');
            if (!shell) return;
            shell.classList.remove('mobile-left', 'mobile-right');
          }

          function applyMobileDefaults() {
            if (!isMobileViewport()) {
              closeMobilePanes();
              return;
            }
            if (!state.conversationId) {
              openMobilePane('left');
            }
          }

          function setChip(id, text, stateValue) {
            const el = document.getElementById(id);
            if (!el) return;
            const stateClass = String(stateValue || 'idle');
            el.className = `chip chip-${stateClass}`;
            el.textContent = text;
          }

          function hardRefresh() {
            const url = new URL(window.location.href);
            url.searchParams.set('_ar_refresh', String(Date.now()));
            window.location.replace(url.toString());
          }

          function updateControls() {
            const active = isActiveState(state.runStatus.state);
            const hasConversation = Boolean(state.conversationId && state.workspaceId);
            const busy = active || state.submitting;
            const ids = ['attach-button', 'send-button', 'clear-button'];
            for (const id of ids) {
              const el = document.getElementById(id);
              if (el) el.disabled = !hasConversation || busy;
            }
            const textarea = document.getElementById('composer');
            if (textarea) textarea.disabled = !hasConversation || busy;
            const attachments = document.getElementById('composer-attachments');
            if (attachments) attachments.disabled = !hasConversation || busy;
            const stop = document.getElementById('stop-button');
            if (stop) stop.disabled = !active;
            const loopMode = document.getElementById('mode-loop');
            if (loopMode) {
              const disabled = state.assistantMode !== 'dev';
              loopMode.disabled = disabled;
              loopMode.title = disabled ? 'Loop requires dev capability mode.' : '';
            }
          }

          function openAttachmentPicker() {
            const input = document.getElementById('composer-attachments');
            if (input && !input.disabled) input.click();
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

          function splitCsv(value) {
            return String(value || '')
              .split(',')
              .map((item) => item.trim())
              .filter(Boolean);
          }

          function parseKeyValuePairs(value) {
            const out = {};
            for (const chunk of splitCsv(value)) {
              const idx = chunk.indexOf('=');
              if (idx <= 0) continue;
              const key = chunk.slice(0, idx).trim();
              const val = chunk.slice(idx + 1).trim();
              if (key && val) out[key] = val;
            }
            return out;
          }

          function parseDateWindow(value) {
            const text = String(value || '').trim();
            if (!text) return {};
            const parts = text.split('..').map((item) => item.trim()).filter(Boolean);
            if (parts.length === 2) {
              return { start: parts[0], end: parts[1] };
            }
            return { label: text };
          }

          function buildPageContextDraft() {
            const route = String(document.getElementById('ctx-route').value || '').trim();
            const entityText = String(document.getElementById('ctx-entity').value || '').trim();
            const filters = parseKeyValuePairs(document.getElementById('ctx-filters').value || '');
            const visibleColumns = splitCsv(document.getElementById('ctx-columns').value || '');
            const dateWindow = parseDateWindow(document.getElementById('ctx-date-window').value || '');
            const entities = parseKeyValuePairs(entityText);
            if (!Object.keys(entities).length && entityText) {
              entities.primary = entityText;
            }
            const payload = {};
            if (route) payload.route = route;
            if (Object.keys(entities).length) payload.entities = entities;
            if (Object.keys(filters).length) payload.filters = filters;
            if (visibleColumns.length) payload.visible_columns = visibleColumns;
            if (Object.keys(dateWindow).length) payload.date_window = dateWindow;
            return payload;
          }

          function inferAdapterFromRoute(route) {
            const text = String(route || '').toLowerCase();
            if (!text) return 'generic';
            if (text.includes('inventory')) return 'inventory';
            if (text.includes('cash') || text.includes('flow')) return 'cashflow';
            if (text.includes('payout')) return 'payouts';
            return 'generic';
          }

          function summarizeContext(payload) {
            const context = payload && typeof payload === 'object' ? payload : {};
            const route = String(context.route || '').trim();
            const adapter = String(context.adapter || inferAdapterFromRoute(route));
            const entities = context.entities && typeof context.entities === 'object' ? context.entities : {};
            const filters = context.filters && typeof context.filters === 'object' ? context.filters : {};
            const dateWindow = context.date_window && typeof context.date_window === 'object' ? context.date_window : {};
            const columns = Array.isArray(context.visible_columns) ? context.visible_columns : [];
            const parts = [];
            if (route) parts.push(route);
            if (adapter && adapter !== 'generic') parts.push(adapter);
            const entityKeys = Object.keys(entities);
            if (entityKeys.length) parts.push(`entity:${entityKeys.join('+')}`);
            const filterCount = Object.keys(filters).length;
            if (filterCount) parts.push(`filters:${filterCount}`);
            if (dateWindow.start && dateWindow.end) parts.push(`${dateWindow.start}..${dateWindow.end}`);
            if (columns.length) parts.push(`cols:${columns.length}`);
            return parts.length ? parts.join(' | ') : 'none';
          }

          function renderActiveContext(payload) {
            const el = document.getElementById('active-context');
            if (!el) return;
            const summary = summarizeContext(payload);
            el.textContent = `Active context: ${summary}`;
            el.title = summary === 'none' ? 'No active context' : summary;
          }

          function applyPageContextInputs(payload) {
            const context = payload && typeof payload === 'object' ? payload : {};
            document.getElementById('ctx-route').value = context.route || '';
            const entities = context.entities && typeof context.entities === 'object' ? context.entities : {};
            const entityEntries = Object.entries(entities).map(([key, value]) => `${key}=${value}`);
            document.getElementById('ctx-entity').value = entityEntries.join(', ');
            const dateWindow = context.date_window && typeof context.date_window === 'object' ? context.date_window : {};
            if (dateWindow.start && dateWindow.end) {
              document.getElementById('ctx-date-window').value = `${dateWindow.start}..${dateWindow.end}`;
            } else {
              document.getElementById('ctx-date-window').value = dateWindow.label || '';
            }
            const filters = context.filters && typeof context.filters === 'object' ? context.filters : {};
            document.getElementById('ctx-filters').value = Object.entries(filters)
              .map(([key, value]) => `${key}=${value}`)
              .join(', ');
            const columns = Array.isArray(context.visible_columns) ? context.visible_columns : [];
            document.getElementById('ctx-columns').value = columns.join(', ');
            renderActiveContext(context);
          }

          function contextSignature(payload) {
            return JSON.stringify(payload || {});
          }

          function inferContextFromWorkspace(conversationPayload) {
            const params = new URLSearchParams(window.location.search);
            const seededRoute = String(params.get('ctx_route') || '').trim();
            const seededEntity = String(params.get('ctx_entity') || '').trim();
            const seededFilters = parseKeyValuePairs(params.get('ctx_filters') || '');
            const seededColumns = splitCsv(params.get('ctx_columns') || '');
            const seededDate = parseDateWindow(params.get('ctx_date_window') || '');
            const seed = {};
            if (seededRoute) seed.route = seededRoute;
            if (seededEntity) seed.entities = parseKeyValuePairs(seededEntity);
            if (seededEntity && !Object.keys(seed.entities || {}).length) {
              seed.entities = { primary: seededEntity };
            }
            if (Object.keys(seededFilters).length) seed.filters = seededFilters;
            if (seededColumns.length) seed.visible_columns = seededColumns;
            if (Object.keys(seededDate).length) seed.date_window = seededDate;
            if (Object.keys(seed).length) return seed;

            const label = String(
              conversationPayload.workspace_display_name ||
              conversationPayload.workspace_id ||
              ''
            ).toLowerCase();
            if (label.includes('inventory')) return { route: '/finance/inventory' };
            if (label.includes('cash') || label.includes('flow')) return { route: '/finance/cash-flow' };
            if (label.includes('payout')) return { route: '/finance/payouts' };
            return {};
          }

          async function persistPageContext(payload) {
            if (!state.workspaceId || !state.conversationId) return;
            await fetchJson(`/api/conversations/${encodeURIComponent(state.conversationId)}/context`, {
              method: 'PATCH',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({
                workspace_id: state.workspaceId,
                page_context: payload,
              }),
            });
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
            const host = document.getElementById('conversation-list');
            if (!workspaces.length) {
              host.innerHTML = '<div class="empty">No workspaces yet. Add one to start chatting.</div>';
              return;
            }
            host.innerHTML = workspaces.map((workspace) => `
              <button class="conversation-row ${state.workspaceId === workspace.id ? 'active' : ''}" type="button" onclick="selectWorkspace('${workspace.id}')">
                <div class="conversation-main">
                  <div class="conversation-title">${escapeHtml(workspace.display_name || workspace.id)}</div>
                  <div class="conversation-time">${escapeHtml(formatStamp(workspace.updated_at))}</div>
                </div>
                <div class="conversation-meta">${escapeHtml(workspace.repo_path || workspace.title || 'No messages yet.')}</div>
              </button>
            `).join('');
          }

          function renderThread(conversation) {
            state.conversationCache = conversation;
            document.getElementById('thread-title').textContent = conversation.workspace_display_name || conversation.workspace_id || conversation.title;
            const host = document.getElementById('thread-scroll');
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
            setChip('thread-run-chip', stateText, stateText);
            setChip('global-run-chip', `run: ${stateText}`, stateText);
            const subtitle = state.runStatus.last_error || state.runStatus.error || state.runStatus.step || 'Idle';
            document.getElementById('thread-subtitle').textContent = subtitle;
            const serverState = state.serverInfo ? 'server online' : 'server loading';
            setChip('server-chip', serverState, state.serverInfo ? 'succeeded' : 'starting');
            const buildBadge = document.getElementById('build-badge');
            if (buildBadge) {
              buildBadge.textContent = state.serverInfo?.build_label || 'Build unavailable';
            }
            updateControls();
          }

          function renderReviewPane(payload) {
            state.review = payload;
            const host = document.getElementById('review-scroll');
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

          async function loadWorkspaces() {
            const payload = await fetchJson('/api/workspaces');
            const workspaces = payload.workspaces || [];
            renderWorkspaces(workspaces);
            if (!state.workspaceId && workspaces.length) {
              if (!isMobileViewport()) {
                await selectWorkspace(workspaces[0].id);
              }
            } else if (
              state.workspaceId &&
              !workspaces.some((workspace) => workspace.id === state.workspaceId)
            ) {
              state.conversationId = null;
              state.workspaceId = null;
              state.lastSignature = null;
              if (workspaces.length && !isMobileViewport()) {
                await selectWorkspace(workspaces[0].id);
              }
            }
          }

          async function selectWorkspace(workspaceId) {
            state.workspaceId = workspaceId;
            const workspace = await fetchJson(`/api/workspaces/${encodeURIComponent(workspaceId)}`);
            state.conversationId = workspace.active_conversation_id || null;
            closeMobilePanes();
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
            syncAssistantModeUI(payload.assistant_mode || 'ask');
            const existingContext = payload.page_context && typeof payload.page_context === 'object'
              ? payload.page_context
              : {};
            let effectiveContext = existingContext;
            if (!Object.keys(existingContext).length) {
              const inferred = inferContextFromWorkspace(payload);
              if (Object.keys(inferred).length) {
                await persistPageContext(inferred);
                effectiveContext = inferred;
              }
            }
            applyPageContextInputs(effectiveContext);
            const signature = JSON.stringify({
              updated_at: payload.updated_at,
              message_count: (payload.messages || []).length,
              title: payload.title,
              assistant_mode: payload.assistant_mode || 'ask',
              page_context: contextSignature(effectiveContext),
            });
            if (signature !== state.lastSignature) {
              renderThread(payload);
              state.lastSignature = signature;
            }
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

          async function setMode(mode) {
            if (mode === 'loop' && state.assistantMode !== 'dev') {
              window.alert('Loop mode requires dev capability mode.');
              return;
            }
            document.getElementById('composer-mode').value = mode;
            document.getElementById('mode-message').classList.toggle('active', mode === 'message');
            document.getElementById('mode-loop').classList.toggle('active', mode === 'loop');
          }

          function syncAssistantModeUI(mode) {
            const resolved = mode === 'dev' || mode === 'ops' ? mode : 'ask';
            state.assistantMode = resolved;
            document.getElementById('assistant-mode').value = resolved;
            document.getElementById('assistant-ask').classList.toggle('active', resolved === 'ask');
            document.getElementById('assistant-ops').classList.toggle('active', resolved === 'ops');
            document.getElementById('assistant-dev').classList.toggle('active', resolved === 'dev');
            if (resolved !== 'dev' && document.getElementById('composer-mode').value === 'loop') {
              document.getElementById('composer-mode').value = 'message';
              document.getElementById('mode-message').classList.add('active');
              document.getElementById('mode-loop').classList.remove('active');
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
          }

          async function submitComposer(event) {
            event.preventDefault();
            if (state.submitting) return false;
            if (!state.conversationId || !state.workspaceId) {
              window.alert('Choose a workspace before sending a prompt.');
              return false;
            }
            const textarea = document.getElementById('composer');
            const attachmentInput = document.getElementById('composer-attachments');
            const content = textarea.value.trim();
            const pageContext = buildPageContextDraft();
            const files = Array.from((attachmentInput && attachmentInput.files) || []);
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
                formData.append('mode', document.getElementById('composer-mode').value);
                formData.append('assistant_mode', document.getElementById('assistant-mode').value);
                formData.append('workspace_id', state.workspaceId);
                formData.append('page_context', JSON.stringify(pageContext));
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
                    mode: document.getElementById('composer-mode').value,
                    assistant_mode: document.getElementById('assistant-mode').value,
                    workspace_id: state.workspaceId,
                    page_context: pageContext,
                  }),
                });
              }
              textarea.value = '';
              clearComposerAttachments();
              state.lastSignature = null;
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
          }

          async function stopRun() {
            try {
              await fetchJson('/api/runs/stop-safely', { method: 'POST' });
              await pollStatus();
              await loadReview();
            } catch (error) {
              window.alert(error.message || 'Could not stop the run');
            }
          }

          async function loadServerInfo() {
            try {
              state.serverInfo = await fetchJson('/api/server-info');
            } catch (_) {
              state.serverInfo = null;
            }
            renderStatus(state.runStatus);
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
            renderStatus({ state: 'idle', step: 'Loading workspaces' });
            await loadServerInfo();
            await loadWorkspaces();
            await pollStatus();
            await loadReview();
            updateControls();
            applyMobileDefaults();
            syncKeyboardInset();
            const contextFieldIds = ['ctx-route', 'ctx-entity', 'ctx-date-window', 'ctx-filters', 'ctx-columns'];
            contextFieldIds.forEach((id) => {
              const el = document.getElementById(id);
              if (!el) return;
              el.addEventListener('input', () => {
                renderActiveContext(buildPageContextDraft());
              });
              el.addEventListener('blur', async () => {
                try {
                  await persistPageContext(buildPageContextDraft());
                } catch (_) {}
              });
            });
            renderActiveContext(buildPageContextDraft());
            if (window.visualViewport) {
              window.visualViewport.addEventListener('resize', syncKeyboardInset);
              window.visualViewport.addEventListener('scroll', syncKeyboardInset);
            }
            window.setInterval(pollEvents, 1200);
            window.setInterval(pollStatus, 5000);
            window.setInterval(loadServerInfo, 10000);
            window.addEventListener('resize', () => {
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
            gap: 6px;
          }}
          .rail-item {{
            display: block;
            text-decoration: none;
            color: inherit;
            border: 1px solid var(--line);
            background: #f7f8fb;
            padding: 10px;
          }}
          .rail-item-active {{
            background: #edf1f4;
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
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 10px;
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
