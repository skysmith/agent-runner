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
    assert "async function startNativeVoiceCapture(textarea)" in html
    assert "function startBrowserVoiceCapture(textarea)" in html
    assert "/api/native/transcribe" in html
    assert "native_transcription_available" in html


def test_render_web_app_defaults_game_studio_to_runner_template() -> None:
    html = render_web_app()

    runner_index = html.index("{ value: 'runner', label: 'Runner' }")
    platformer_index = html.index("{ value: 'platformer', label: 'Platformer' }")
    assert runner_index < platformer_index
    assert "Night Shift Detective" in html
    assert "A moonlit city runner where a detective leaps over street hazards and gathers clues." in html


def test_render_web_app_restores_workspace_selection() -> None:
    html = render_web_app()

    assert "alcove-selected-workspace" in html
    assert "alcove-selected-conversation" in html
    assert "function requestedWorkspaceSelection()" in html
    assert "async function restoreWorkspaceSelection()" in html
    assert "url.searchParams.delete('workspace_id')" in html
    assert "url.searchParams.delete('conversation_id')" in html
    assert "window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)" in html
    assert "function goToWorkspaceSelector()" in html
    assert "clearRememberedWorkspaceSelection();" in html
    assert "state.reviewPaneHidden = state.breakoutChatOnly || isMobileViewport();" in html


def test_render_web_app_supports_chat_breakout_window() -> None:
    html = render_web_app()

    assert "document.documentElement.classList.add('chat-breakout')" in html
    assert 'id="menu-open-breakout"' in html
    assert "function breakoutWindowUrl()" in html
    assert "function openBreakoutWindow()" in html
    assert "url.searchParams.set('view', 'chat')" in html
    assert "const windowName = `alcove-chat-${state.workspaceId}-${state.conversationId}`" in html
    assert ".shell.single-pane" in html


def test_render_web_app_keeps_settings_in_toolbar_dropdown_and_primary_hover_green() -> None:
    html = render_web_app()

    assert ".primary:hover {" in html
    assert "background: #48705a;" in html
    assert "border-color: #365845;" in html
    assert '<button class="menu-item" type="button" onclick="openSettings()">Settings</button>' in html
    assert 'id="settings-button" class="topbar-button" type="button" onclick="openSettings()"' not in html
    assert 'onclick="clearConversation()"' not in html.split('id="actions-menu"', 1)[1].split('id="global-run-chip"', 1)[0]


def test_render_web_app_places_conversation_lifecycle_actions_inside_settings_modal() -> None:
    html = render_web_app()

    assert '<h4>Conversation</h4>' in html
    assert 'id="conversation-settings-panel"' in html
    assert 'id="conversation-settings-status"' in html
    assert "Context History" in html
    assert "Summary active" in html
    assert "conversation-context-meter" in html
    assert "Conversation Actions" in html
    assert "Archive Chat" in html
    assert "Delete Permanently" in html
    assert "restoreArchivedConversation" in html
    assert "loadConversationSettings()" in html
    assert ".settings-action-menu" in html
    assert ".archived-chat-list" in html


def test_render_web_app_exposes_context_budget_setting() -> None:
    html = render_web_app()

    assert "Context history budget (chars)" in html
    assert 'id="settings-context-char-cap"' in html
    assert 'id="settings-context-char-cap-hint"' in html
    assert "function updateContextCapHint()" in html
    assert "function recommendedContextCharCap(provider, model)" in html


def test_render_web_app_shows_compact_queue_strip_above_composer() -> None:
    html = render_web_app()

    assert 'id="composer-queue" class="composer-queue" hidden' in html
    assert '<div class="composer-box">' in html
    assert '<div id="server-chip" class="composer-server-dot server-dot-offline"' in html
    assert ".composer-queue {" in html
    assert ".composer-queue-item {" in html
    assert ".composer-box {" in html
    assert "function queuedItemsForCurrentConversation()" in html
    assert "function renderComposerQueue()" in html
    assert "Queued Messages" in html
    assert '<p class="review-title">Queued Messages</p>' not in html


def test_render_web_app_uses_workspace_info_drawers_for_secondary_details() -> None:
    html = render_web_app()

    assert "function workspaceCardMarkup(workspace)" in html
    assert "workspace-card-info" in html
    assert "workspace-card-info-icon" in html
    assert "workspace-card-drawer" in html
    assert "workspace-card-drawer-head" in html
    assert "workspace-card-drawer-copy" in html
    assert "function toggleWorkspaceDetails(workspaceId, event)" in html
    assert "function renameWorkspace(workspaceId, event)" in html
    assert "function removeWorkspace(workspaceId, event)" in html
    assert "Expand workspace details" in html
    assert "Collapse workspace details" in html
    assert 'class="workspace-remove"' in html
    assert "Remove</button>" in html
    assert "font-weight: 400;" in html
    assert "justify-content: space-between;" in html
    assert "justify-content: flex-end;" in html
    assert "color: var(--warning);" in html
    assert "width: 100%;" in html
    assert "align-self: stretch;" in html
    assert 'Remove "${workspaceTitle(workspace)}" from Alcove?' in html
    assert "This removes the workspace and chat history from Alcove, but leaves any repo files on disk." in html
    assert "Could not remove workspace." in html
    assert "conversation_count || 1" not in html
    assert " chat · " not in html


def test_render_web_app_hides_review_header_on_home_view() -> None:
    html = render_web_app()

    assert 'id="review-pane-head"' in html
    assert 'id="review-pane-collapse"' in html
    assert 'class="pane-collapse-button"' in html
    assert 'onclick="toggleReviewPane()"' in html
    assert "Hide review panel" in html
    assert ".pane-head-side" in html
    assert ".pane-collapse-button {" in html
    assert "const paneHead = document.getElementById('review-pane-head');" in html
    assert "const collapseButton = document.getElementById('review-pane-collapse');" in html
    assert "if (paneHead) paneHead.style.display = 'none';" in html
    assert "if (collapseButton) collapseButton.style.display = 'none';" in html
    assert "if (paneHead) paneHead.style.display = '';" in html
    assert "if (collapseButton) collapseButton.style.display = '';" in html


def test_render_web_app_keeps_studio_pane_visible_and_menu_can_reopen_review_panel() -> None:
    html = render_web_app()

    assert 'id="menu-toggle-review-pane"' in html
    assert 'onclick="toggleReviewPane()">Hide Review Panel</button>' in html
    assert "if (isStudioWorkspace(state.workspace)) {" in html
    assert "state.reviewPaneHidden = false;" in html
    assert "(state.reviewPaneHidden && !isStudioWorkspace(state.workspace));" in html
    assert "reviewToggle.textContent = state.reviewPaneHidden && hasReviewWorkspace ? 'Show Review Panel' : 'Hide Review Panel';" in html
    assert "Studio stays visible in this workspace." in html


def test_render_web_app_keeps_studio_link_addresses_out_of_default_studio_surface() -> None:
    html = render_web_app()

    assert ".studio-preview-actions" not in html
    assert ".studio-preview-link-row" not in html
    assert "Share link appears after Publish." not in html
    assert "const publishUrl = workspace.publish_url || '';" not in html
    assert "const previewLink = links.preview_current || '';" not in html
    assert "const phonePreviewLink = links.preview_phone || '';" not in html


def test_render_web_app_uses_workspace_list_only_for_populated_home_left_pane() -> None:
    html = render_web_app()

    assert '<section id="workspace-dropzone" class="workspace-grid home-list">' in html
    assert ".workspace-grid.home-list" in html
    assert ".workspace-grid.home-list.is-active" in html
    assert "padding: 0 12px 0 14px;" in html
    assert "box-sizing: border-box;" in html


def test_mobile_shell_locks_mobile_zoom() -> None:
    html = render_error_page("nope")

    assert "maximum-scale=1" in html
    assert "user-scalable=no" in html
