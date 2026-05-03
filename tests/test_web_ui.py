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


def test_render_web_app_keeps_setup_banner_out_of_main_flex_row() -> None:
    html = render_web_app()

    assert ".frame.has-setup-banner {" in html
    assert "grid-template-rows: auto auto minmax(0, 1fr);" in html
    assert "const frame = document.querySelector('.frame');" in html
    assert "frame.classList.add('has-setup-banner');" in html
    assert "frame.classList.remove('has-setup-banner');" in html


def test_render_web_app_defaults_game_studio_to_runner_template() -> None:
    html = render_web_app()

    runner_index = html.index("{ value: 'runner', label: 'Runner' }")
    platformer_index = html.index("{ value: 'platformer', label: 'Platformer' }")
    assert runner_index < platformer_index
    assert "Night Shift Detective" in html
    assert "A moonlit city runner where a detective leaps over street hazards and gathers clues." in html


def test_render_web_app_includes_native_image_studio_controls() -> None:
    html = render_web_app()

    assert '<option value="studio_image">Image Studio</option>' in html
    assert "{ value: 'image-gen', label: 'Image Gen' }" in html
    assert "Generate, upload, and organize image candidates from inside Alcove." in html
    assert "function renderImageStudioPane(workflow)" in html
    assert "function generateImageStudioImages()" in html
    assert "function describeSelectedImageReference(sourceImageId = null)" in html
    assert "function deleteImageStudioAsset(sourceImageId = null)" in html
    assert "function imageGenerationProfiles(workflow = imageStudioWorkflow())" in html
    assert "function imageGenerationCountOptions(workflow = imageStudioWorkflow())" in html
    assert "function imageGenerationPassOptions(workflow = imageStudioWorkflow())" in html
    assert "function imageStudioWorkloadStatus(workflow = imageStudioWorkflow())" in html
    assert "function refreshWorkloadIndicators()" in html
    assert "function updateImageGenerationSetting(field, value)" in html
    assert "function compositionSourceImage(workflow = imageStudioWorkflow())" in html
    assert "function toggleImageCompositionSource(imageId, enabled)" in html
    assert "function clearImageCompositionSource()" in html
    assert "function renderImageGenerationQueue(workflow)" in html
    assert "function imageGenerationElapsedLabel(item)" in html
    assert "function imageGenerationPassLabel(item)" in html
    assert "function imageGenerateButtonLabel(workflow = imageStudioWorkflow())" in html
    assert "function uploadImageStudioAsset(event)" in html
    assert "function droppedImageFiles(dataTransfer)" in html
    assert "function droppedImagePath(dataTransfer)" in html
    assert "function handleImageStudioDrop(dataTransfer)" in html
    assert "function uploadImageStudioDroppedFiles(files, { useAsReference = false } = {})" in html
    assert "function importImageStudioDroppedPath(imagePath, { useAsReference = false } = {})" in html
    assert "Settings" in html
    assert "Auto-refine" in html
    assert "# of generations" in html
    assert 'id="image-studio-count"' in html
    assert "Aspect" in html
    assert "Passes" in html
    assert 'id="image-studio-passes"' in html
    assert "Number of passes" in html
    assert "Time to generate" in html
    assert "portrait-768x1024" in html
    assert "workflow?.generation_profiles" in html
    assert "workflow?.generation_count_options" in html
    assert "workflow?.generation_pass_options" in html
    assert "workflow?.default_generation_passes || 2" in html
    assert "workflow?.default_generation_passes || 8" not in html
    assert "profile.display_size" in html
    assert "Describe Reference" in html
    assert "function openImageStudioFolder()" in html
    assert "Open Image Folder" in html
    assert "Use as reference" in html
    assert "Delete" in html
    assert "Could not delete that image." in html
    assert "Could not import that image into Image Studio." in html
    assert "Match" in html
    assert "Remix" in html
    assert "function updateImageRefineSetting(field, value)" in html
    assert "function openImageStudio()" in html
    assert "function openImageStudioWindow()" in html
    assert "function openBreakoutDestination(url, { desktopName = '_blank', desktopFeatures = '' } = {})" in html
    assert "Image Studio Window" in html
    assert "Open Image Pane" in html
    assert "Queued Image Runs" in html
    assert "judge and retry one candidate" in html.lower()
    assert "Use the smaller local aspect presets for the most reliable image runs." in html
    assert "Generated images automatically reuse their stored seed when you use them as a reference." in html
    assert "image running" in html
    assert "Image generation running${detail" in html
    assert "window.setInterval(refreshWorkloadIndicators, 1000)" in html
    assert "image queued" in html
    assert "Last image run failed" in html
    assert ".review-scroll.studio-scroll {" in html
    assert "overflow-y: auto;" in html
    assert ".image-studio-grid {" in html
    assert "Make 3D" not in html
    assert "3D Results" not in html
    assert "onclick=\"animateSelectedImage()\"" not in html
    assert "Video Results" not in html


def test_render_web_app_includes_video_studio_entry_points() -> None:
    html = render_web_app()

    assert '<option value="studio_video">Video Studio</option>' in html
    assert "{ value: 'video-gen', label: 'Video Gen' }" in html
    assert "function openVideoStudio()" in html
    assert 'onclick="openVideoStudio()"' in html
    assert "New Video Lab" in html
    assert "video launchpad" in html.lower()


def test_render_web_app_restores_workspace_selection() -> None:
    html = render_web_app()

    assert "alcove-selected-workspace" in html
    assert "alcove-selected-conversation" in html
    assert "function requestedWorkspaceSelection()" in html
    assert "async function restoreWorkspaceSelection()" in html
    assert "requested.intent === 'image-studio'" in html
    assert "requested.intent === 'video-studio'" in html
    assert "url.searchParams.delete('intent')" in html
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
    assert "document.documentElement.classList.add('studio-breakout')" in html
    assert "document.documentElement.classList.add('image-pane-breakout')" in html
    assert "function imageStudioWindowUrl()" in html
    assert "url.searchParams.set('view', 'image-pane')" in html
    assert "url.searchParams.set('view', 'chat')" in html
    assert "window.open(url, '_blank', 'noopener,noreferrer')" in html
    assert "window.location.assign(url);" in html
    assert "const windowName = `alcove-chat-${state.workspaceId}-${state.conversationId}`" in html
    assert ".shell.single-pane" in html
    assert "html.image-pane-breakout .review-pane {" in html
    assert "display: flex !important;" in html
    assert "html.image-pane-breakout .thread-pane," in html
    assert "html.image-pane-breakout #review-pane-head {" in html
    assert "html.image-pane-breakout .review-scroll {" in html
    assert "if (threadPane) threadPane.style.display = 'flex';" in html
    assert "if (pane) pane.style.display = 'flex';" in html


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

    assert "<h4>Runtime</h4>" in html
    assert ">OpenAI</option>" in html
    assert ">Open Source</option>" in html
    assert 'id="settings-runtime-family"' in html
    assert 'id="settings-openai-model"' in html
    assert 'id="settings-open-source-model"' in html
    assert 'id="settings-openai-model-label"' in html
    assert "<h4>Open Source</h4>" in html
    assert "Default open-source model" in html
    assert "Refresh Ollama Models" in html
    assert "Context history budget (chars)" in html
    assert 'id="settings-context-char-cap"' in html
    assert 'id="settings-context-char-cap-hint"' in html
    assert "function updateContextCapHint()" in html
    assert "function updateRuntimeSettingsVisibility()" in html
    assert "openAiLabel.style.display = showOpenAi ? '' : 'none';" in html
    assert "openAiModel.disabled = family !== 'codex';" in html
    assert "function recommendedContextCharCap(provider, model)" in html
    assert "GPT-5.3 (medium)" in html
    assert "GPT-5.4 (medium)" in html
    assert "GPT-5.4 Mini" not in html
    assert "Planner model (optional)" not in html
    assert "Builder model (optional)" not in html
    assert "Reviewer model (optional)" not in html
    assert "Max step retries" not in html
    assert "Phase timeout (seconds)" not in html


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
    assert "workspace-card-summary" in html
    assert "workspace-card-subtitle" in html
    assert "workspace-card-context" in html
    assert "workspace-card-badge" in html
    assert "font-weight: 700;" in html
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
    assert "if (state.breakoutStudioOnly) {" in html
    assert "const singlePane = state.reviewPaneHidden && !isStudioWorkspace(state.workspace);" in html
    assert "reviewToggle.textContent = state.reviewPaneHidden && hasReviewWorkspace ? 'Show Review Panel' : 'Hide Review Panel';" in html
    assert "Studio stays visible in this workspace." in html


def test_render_web_app_has_mobile_preview_path() -> None:
    html = render_web_app()

    assert 'id="mobile-preview-button"' in html
    assert 'onclick="openMobilePreview()"' in html
    assert "function openMobilePreview()" in html
    assert "openMobilePane('right');" in html
    assert ".mobile-preview-button" in html
    assert ".mobile-preview-button { display: inline-flex;" in html
    assert "mobilePreviewButton.textContent = isStudioWorkspace(state.workspace) ? 'Preview' : 'Review';" in html


def test_render_web_app_surfaces_polling_stale_state() -> None:
    html = render_web_app()

    assert "apiProblem: null" in html
    assert "function markApiProblem(area, error)" in html
    assert "Connection stale during" in html
    assert "setChip('global-run-chip', 'stale', 'failed');" in html
    assert "markApiProblem('run status', error);" in html
    assert "markApiProblem('event sync', error);" in html
    assert "markApiProblem('review refresh', error);" in html
    assert "server-dot-stale" in html


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

    assert '<section id="workspace-dropzone" class="home-workspace-browser">' in html
    assert '<section class="workspace-grid home-list">' in html
    assert ".home-list-head" in html
    assert ".workspace-grid.home-list" in html
    assert ".workspace-grid.home-list.is-active" in html
    assert "padding: 14px 12px 0 14px;" in html
    assert "box-sizing: border-box;" in html
    assert "Recent Workspaces" not in html


def test_mobile_shell_locks_mobile_zoom() -> None:
    html = render_error_page("nope")

    assert "maximum-scale=1" in html
    assert "user-scalable=no" in html
