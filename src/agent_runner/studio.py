from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


STUDIO_KIND_LABELS = {
    "field_station": "Field Station",
    "studio_game": "Game Studio",
    "studio_web": "Web Studio",
    "studio_data": "Data Studio",
    "studio_docs": "Docs Studio",
    "studio_image": "Image Studio",
    "studio_video": "Video Studio",
}

STUDIO_TEMPLATES = {
    "field_station": {
        "magic-button": "Magic Button Console",
        "blank": "Blank Start",
    },
    "studio_game": {
        "runner": "Runner",
        "platformer": "Platformer",
        "top-down": "Top-down Adventure",
        "clicker": "Clicker",
        "blank": "Blank Start",
    },
    "studio_web": {
        "landing-page": "Landing Page",
        "web-app": "Web App",
        "portfolio": "Portfolio",
        "blank": "Blank Start",
    },
    "studio_data": {
        "dashboard": "Dashboard",
        "spreadsheet": "Spreadsheet",
        "query-lab": "Query Lab",
        "blank": "Blank Start",
    },
    "studio_docs": {
        "docs-site": "Docs Site",
        "guide": "Guide",
        "release-notes": "Release Notes",
        "blank": "Blank Start",
    },
    "studio_image": {
        "image-gen": "Image Gen",
        "blank": "Blank Start",
    },
    "studio_video": {
        "video-gen": "Video Gen",
        "blank": "Blank Start",
    },
}

DEFAULT_TEMPLATES = {
    "field_station": "magic-button",
    "studio_game": "runner",
    "studio_web": "landing-page",
    "studio_data": "dashboard",
    "studio_docs": "docs-site",
    "studio_image": "image-gen",
    "studio_video": "video-gen",
}

DEFAULT_TITLES = {
    "field_station": "New Field Station",
    "studio_game": "New Game",
    "studio_web": "New Website",
    "studio_data": "New Dataset",
    "studio_docs": "New Docs",
    "studio_image": "New Image Collection",
    "studio_video": "New Video Lab",
}

ENTRY_FILES = {
    "field_station": "field-station.js",
    "studio_game": "game.js",
    "studio_web": "app.js",
    "studio_data": "data.js",
    "studio_docs": "docs.js",
    "studio_image": "image.js",
    "studio_video": "video.js",
}


@dataclass(slots=True)
class StudioProject:
    workspace_id: str
    workspace_kind: str
    artifact_title: str
    template_kind: str
    theme_prompt: str | None
    repo_path: Path
    entry_file: str

    @property
    def game_title(self) -> str:
        return self.artifact_title


def create_studio_project(
    *,
    root: Path,
    workspace_id: str,
    workspace_kind: str,
    artifact_title: str,
    template_kind: str,
    theme_prompt: str | None = None,
) -> StudioProject:
    kind = normalize_workspace_kind(workspace_kind)
    template = normalize_template_kind(kind, template_kind)
    title = artifact_title.strip() or DEFAULT_TITLES[kind]
    theme_text = (theme_prompt or "").strip() or None
    repo_path = root / workspace_id
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "assets").mkdir(exist_ok=True)

    spec = {
        "workspace_id": workspace_id,
        "workspace_kind": kind,
        "artifact_title": title,
        "template_kind": template,
        "theme_prompt": theme_text,
        "preview_mode": "managed-static",
        "entry_file": ENTRY_FILES[kind],
    }
    (repo_path / "alcove-studio.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    (repo_path / "README.md").write_text(_readme_content(spec), encoding="utf-8")
    (repo_path / "style.css").write_text(_style_css(kind), encoding="utf-8")
    (repo_path / "index.html").write_text(_index_html(spec), encoding="utf-8")
    (repo_path / ENTRY_FILES[kind]).write_text(_entry_script(spec), encoding="utf-8")

    if kind == "studio_data":
        (repo_path / "data.json").write_text(_sample_data_json(title), encoding="utf-8")
    if kind == "studio_docs":
        (repo_path / "guide.md").write_text(_sample_docs_markdown(title, template, theme_text), encoding="utf-8")

    return StudioProject(
        workspace_id=workspace_id,
        workspace_kind=kind,
        artifact_title=title,
        template_kind=template,
        theme_prompt=theme_text,
        repo_path=repo_path,
        entry_file=ENTRY_FILES[kind],
    )


def normalize_workspace_kind(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in STUDIO_KIND_LABELS else "studio_game"


def normalize_template_kind(workspace_kind: str, value: str | None) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    text = (value or "").strip().lower()
    if kind == "studio_game" and text in {"topdown", "top_down"}:
        text = "top-down"
    if kind == "studio_game" and text in {"side-scroller", "sidescroller"}:
        text = "runner"
    return text if text in STUDIO_TEMPLATES[kind] else DEFAULT_TEMPLATES[kind]


def publish_studio_project(*, source_repo: Path, publish_root: Path, publish_slug: str) -> Path:
    destination = publish_root / publish_slug
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_repo, destination)
    return destination


def slugify_workspace_id(raw: str) -> str:
    text = raw.strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", text)
    cleaned = cleaned.strip("-")
    return cleaned or "alcove-studio"


def studio_actions(workspace_kind: str) -> dict[str, str]:
    kind = normalize_workspace_kind(workspace_kind)
    if kind in {"field_station", "studio_image"}:
        play_label = "Open"
    else:
        play_label = "Play" if kind == "studio_game" else "Preview"
    return {
        "play_label": play_label,
        "change_label": "Ask for a Change",
        "publish_label": "Publish" if kind != "studio_image" else "Export",
        "remix_label": "Remix",
    }


def studio_placeholder(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    if kind == "field_station":
        return 'Capture a messy thought, choose a mode, and turn it into a saved artifact.'
    if kind == "studio_game":
        return 'Ask for a change in your game, like "make the jump higher" or "add coins".'
    if kind == "studio_web":
        return 'Ask for a website change, like "make the hero bolder" or "add a pricing section".'
    if kind == "studio_data":
        return 'Ask for a data change, like "group revenue by month" or "show duplicate rows".'
    if kind == "studio_image":
        return 'Use the image controls on the right, or ask for prompt help like "make it more toy-like" or "push the silhouette".'
    if kind == "studio_video":
        return 'Ask for a video workflow step, like "set up image-to-video" or "help me tune this motion prompt".'
    return 'Ask for a docs change, like "rewrite the intro" or "add a getting started section".'


def studio_empty_state(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    if kind == "field_station":
        return "The Field Station console will appear here after the workspace is created."
    if kind == "studio_game":
        return "Preview will appear here after the game is created."
    if kind == "studio_web":
        return "Preview will appear here after the website is created."
    if kind == "studio_data":
        return "Your live data view will appear here after the studio is created."
    if kind == "studio_image":
        return "Generate or upload an image to start building a native Alcove image library."
    if kind == "studio_video":
        return "Your video launchpad preview will appear here after the studio is created."
    return "Your rendered docs view will appear here after the studio is created."


def studio_summary_prompt(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    if kind == "field_station":
        return "Capture messy real-world input and turn it into useful Alcove artifacts."
    if kind == "studio_game":
        return "Describe a change and Alcove will update the game."
    if kind == "studio_web":
        return "Describe a change and Alcove will update the site."
    if kind == "studio_data":
        return "Describe a change and Alcove will update the data workspace."
    if kind == "studio_image":
        return "Generate, upload, and organize image candidates from inside Alcove."
    if kind == "studio_video":
        return "Plan and launch text-to-video or image-to-video work from inside Alcove."
    return "Describe a change and Alcove will update the docs."


def studio_welcome_message(project: StudioProject) -> str:
    studio_name = STUDIO_KIND_LABELS[project.workspace_kind]
    artifact_label = _artifact_noun(project.workspace_kind)
    if project.workspace_kind == "field_station":
        return (
            f"Welcome to {studio_name}.\n\n"
            f"This {artifact_label} starts from the `{project.template_kind}` template.\n"
            "Use it as the home for magic-button captures: messy input, mode choice, structured output, and saved artifacts.\n"
            "Hardware stays mocked until the software loop is useful."
        )
    if project.workspace_kind == "studio_image":
        return (
            f"Welcome to {studio_name}.\n\n"
            f"This {artifact_label} starts from the `{project.template_kind}` template.\n"
            "Use the native image workflow on the right to generate or upload images, then choose a favorite to keep iterating.\n"
            "Use chat when you want prompt help, naming help, or taste-level feedback."
        )
    if project.workspace_kind == "studio_video":
        return (
            f"Welcome to {studio_name}.\n\n"
            f"This {artifact_label} starts from the `{project.template_kind}` template.\n"
            "Use it as Alcove's home for text-to-video and image-to-video experiments.\n"
            "The preview is a lightweight launch surface for now while we wire in the real runtime."
        )
    return (
        f"Welcome to {studio_name}.\n\n"
        f"This {artifact_label} starts from the `{project.template_kind}` template.\n"
        f"Describe the change you want and I will update the project files.\n"
        f"{studio_actions(project.workspace_kind)['play_label']} refreshes the preview. "
        f"Publish makes a share link."
    )


def _artifact_noun(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    return {
        "field_station": "field station",
        "studio_game": "game",
        "studio_web": "website",
        "studio_data": "data workspace",
        "studio_docs": "docs workspace",
        "studio_image": "image collection",
        "studio_video": "video lab",
    }[kind]


def _readme_content(spec: dict[str, object]) -> str:
    title = str(spec["artifact_title"])
    workspace_kind = str(spec["workspace_kind"])
    template = str(spec["template_kind"])
    theme = str(spec.get("theme_prompt") or "No theme prompt yet.")
    entry_file = str(spec["entry_file"])
    studio_name = STUDIO_KIND_LABELS[workspace_kind]
    artifact_label = _artifact_noun(workspace_kind)
    return f"""# {title}

This is an {studio_name} project.

Template: `{template}`
Theme prompt: {theme}

Primary files:

- `index.html` bootstraps the preview shell
- `style.css` controls the studio presentation
- `{entry_file}` contains the main interactive behavior

Keep the {artifact_label} previewable in the browser after every change.
Prefer small, readable iterations over large rewrites.
"""


def _style_css(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    background = {
        "field_station": "#ffffff",
        "studio_game": "radial-gradient(circle at top, #1f3f35, #10201a 60%, #08110e)",
        "studio_web": "linear-gradient(180deg, #f1ece4 0%, #f6f4ef 48%, #dfe6dc 100%)",
        "studio_data": "linear-gradient(180deg, #f4f7fb 0%, #ecf1f7 52%, #dfe8f3 100%)",
        "studio_docs": "linear-gradient(180deg, #f7f1e7 0%, #f6f3ee 42%, #e6ecf4 100%)",
        "studio_image": "linear-gradient(180deg, #eef5fb 0%, #f7f3ec 42%, #f6ece7 100%)",
        "studio_video": "linear-gradient(180deg, #eaf6f5 0%, #f6f0e8 42%, #ece6f1 100%)",
    }[kind]
    body_color = "#f6f4e8" if kind == "studio_game" else "#1c241f"
    shell_background = (
        "#ffffff"
        if kind == "field_station"
        else ("rgba(8, 17, 14, 0.24)" if kind == "studio_game" else "rgba(252, 250, 246, 0.82)")
    )
    surface_radius = "0" if kind == "field_station" else ("22px" if kind == "studio_game" else "10px")
    surface_shadow = "none" if kind == "field_station" else ("0 26px 60px rgba(0, 0, 0, 0.12)" if kind == "studio_game" else "0 18px 44px rgba(34, 41, 35, 0.08)")
    surface_overflow = "visible" if kind == "field_station" else "hidden"
    surface_border = "0" if kind == "field_station" else "1px solid rgba(110, 126, 144, 0.18)"
    app_width = "100vw" if kind == "field_station" else "min(100vw, 1180px)"
    main_padding = "0" if kind == "field_station" else "10px 18px 20px"
    header_padding = "16px 28px" if kind == "field_station" else "14px 18px"
    header_border = "1px solid #e5e7eb" if kind == "field_station" else "0"
    footer_display = "none" if kind == "field_station" else "flex"
    surface_min_height = "calc(100vh - 73px)" if kind == "field_station" else "min(78vh, 880px)"
    footer_status_display = "none" if kind == "field_station" else "block"
    return f"""html, body {{
  margin: 0;
  min-height: 100%;
  background: {background};
  color: {body_color};
  font-family: "Avenir Next", "Trebuchet MS", sans-serif;
}}

* {{
  box-sizing: border-box;
}}

body {{
  display: grid;
  place-items: center;
}}

#app {{
  width: {app_width};
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
}}

.studio-header,
.studio-footer {{
  padding: {header_padding};
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}}

.studio-header {{
  border-bottom: {header_border};
}}

.studio-title {{
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.02em;
}}

.studio-tag {{
  border: 1px solid rgba(127, 143, 159, 0.34);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  background: rgba(255, 255, 255, 0.44);
}}

.studio-main {{
  padding: {main_padding};
}}

.studio-surface {{
  min-height: {surface_min_height};
  border-radius: {surface_radius};
  background: {shell_background};
  border: {surface_border};
  box-shadow: {surface_shadow};
  overflow: {surface_overflow};
}}

.studio-footer {{
  display: {footer_display};
  font-size: 13px;
  color: rgba(84, 98, 114, 0.9);
}}

.studio-footer #status {{
  display: {footer_status_display};
}}

.hero-chip {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid rgba(110, 126, 144, 0.18);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 11px;
}}

.stack {{
  display: grid;
  gap: 16px;
}}

.card {{
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(110, 126, 144, 0.14);
  border-radius: 10px;
  padding: 18px;
}}

.web-canvas {{
  position: relative;
  min-height: min(78vh, 880px);
  padding: clamp(24px, 4vw, 46px);
  display: grid;
  gap: clamp(28px, 4vw, 42px);
  background:
    radial-gradient(circle at top right, rgba(63, 100, 75, 0.14), transparent 34%),
    radial-gradient(circle at 12% 18%, rgba(166, 106, 63, 0.09), transparent 24%),
    linear-gradient(180deg, rgba(252, 250, 246, 0.94), rgba(245, 243, 238, 0.88));
  isolation: isolate;
}}

.web-canvas::after {{
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(rgba(141, 146, 137, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(141, 146, 137, 0.06) 1px, transparent 1px);
  background-size: 100% 120px, 120px 100%;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.36), transparent 86%);
  pointer-events: none;
  z-index: -1;
}}

.web-topline,
.web-hero,
.web-section,
.web-launch {{
  position: relative;
  z-index: 1;
}}

.web-topline {{
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid rgba(98, 108, 101, 0.18);
}}

.web-kicker,
.web-overline,
.web-aside-label {{
  margin: 0 0 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(61, 70, 63, 0.72);
}}

.web-wordmark {{
  font-size: clamp(20px, 3vw, 28px);
  font-weight: 700;
  letter-spacing: 0.02em;
}}

.web-nav {{
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
}}

.web-nav a {{
  color: inherit;
  text-decoration: none;
  font-size: 13px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(61, 70, 63, 0.74);
}}

.web-hero {{
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
  gap: clamp(24px, 4vw, 44px);
  align-items: start;
}}

.web-title {{
  margin: 0;
  max-width: 10ch;
  font-size: clamp(56px, 9vw, 104px);
  line-height: 0.92;
  letter-spacing: -0.05em;
}}

.web-copy {{
  max-width: 34rem;
  margin: 18px 0 0;
  font-size: clamp(18px, 2vw, 21px);
  line-height: 1.62;
  color: rgba(36, 45, 39, 0.82);
}}

.web-cta-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}}

.web-button {{
  appearance: none;
  border: 1px solid rgba(34, 46, 38, 0.12);
  border-radius: 6px;
  padding: 14px 18px;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #f7f7f2;
  background: #314b3b;
}}

.web-button.secondary {{
  color: #243028;
  background: rgba(255, 255, 255, 0.44);
}}

.web-aside {{
  padding-top: 8px;
  border-left: 1px solid rgba(98, 108, 101, 0.18);
  padding-left: clamp(18px, 2vw, 28px);
}}

.web-note-list {{
  display: grid;
}}

.web-note {{
  display: grid;
  gap: 6px;
  padding: 16px 0;
  border-top: 1px solid rgba(98, 108, 101, 0.14);
}}

.web-note:first-child {{
  padding-top: 0;
  border-top: 0;
}}

.web-note span,
.web-rail-row span {{
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(61, 70, 63, 0.66);
}}

.web-note strong,
.web-rail-row strong {{
  font-size: 17px;
  font-weight: 600;
  line-height: 1.4;
}}

.web-proof {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid rgba(98, 108, 101, 0.18);
  border-bottom: 1px solid rgba(98, 108, 101, 0.18);
}}

.web-proof-item {{
  padding: 22px 18px 20px 0;
}}

.web-proof-item + .web-proof-item {{
  padding-left: 18px;
  border-left: 1px solid rgba(98, 108, 101, 0.14);
}}

.web-proof-number {{
  display: block;
  margin-bottom: 18px;
  font-size: 13px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(61, 70, 63, 0.68);
}}

.web-proof-item h2,
.web-section-head h2,
.web-launch-copy h2 {{
  margin: 0;
  font-size: clamp(26px, 3vw, 38px);
  line-height: 1.08;
  letter-spacing: -0.03em;
}}

.web-proof-item p,
.web-feature p,
.web-launch-copy p {{
  margin: 12px 0 0;
  font-size: 16px;
  line-height: 1.62;
  color: rgba(36, 45, 39, 0.8);
}}

.web-section {{
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.4fr);
  gap: clamp(24px, 4vw, 42px);
  padding-top: 8px;
}}

.web-feature-list,
.web-launch-rail {{
  display: grid;
}}

.web-feature,
.web-rail-row {{
  padding: 16px 0 18px;
  border-top: 1px solid rgba(98, 108, 101, 0.14);
}}

.web-feature:last-child,
.web-rail-row:last-child {{
  border-bottom: 1px solid rgba(98, 108, 101, 0.14);
}}

.web-feature h3 {{
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.02em;
}}

.web-launch {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 0.9fr);
  gap: clamp(24px, 4vw, 42px);
  align-items: start;
}}

table {{
  width: 100%;
  border-collapse: collapse;
}}

th, td {{
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(110, 126, 144, 0.12);
}}

@media (max-width: 720px) {{
  .studio-header,
  .studio-footer {{
    padding-inline: 14px;
  }}

  .studio-title {{
    font-size: 22px;
  }}

  .studio-main {{
    padding-inline: 14px;
  }}

  .web-topline,
  .web-hero,
  .web-section,
  .web-launch,
  .web-proof {{
    grid-template-columns: 1fr;
  }}

  .web-nav {{
    gap: 12px;
  }}

  .web-aside {{
    border-left: 0;
    border-top: 1px solid rgba(98, 108, 101, 0.18);
    padding-left: 0;
    padding-top: 18px;
  }}

  .web-proof-item,
  .web-proof-item + .web-proof-item {{
    padding-inline: 0;
    border-left: 0;
    border-top: 1px solid rgba(98, 108, 101, 0.14);
  }}

  .web-proof-item:first-child {{
    border-top: 0;
  }}
}}
"""


def _index_html(spec: dict[str, object]) -> str:
    title = _html_text(str(spec["artifact_title"]))
    studio_name = STUDIO_KIND_LABELS[str(spec["workspace_kind"])]
    header_title = "Alcove" if str(spec["workspace_kind"]) == "field_station" else title
    entry_file = str(spec["entry_file"])
    script_tag = ""
    if spec["workspace_kind"] == "studio_game":
        script_tag = '<script src="https://cdn.jsdelivr.net/npm/phaser@3.90.0/dist/phaser.min.js"></script>'
    footer_copy = {
        "field_station": "Capture, structure, and save real-world work from Alcove.",
        "studio_game": "Play, tweak, and remix from Alcove Studio.",
        "studio_web": "Preview, tweak, and publish from Alcove Studio.",
        "studio_data": "Explore, reshape, and publish from Alcove Studio.",
        "studio_docs": "Write, preview, and share from Alcove Studio.",
        "studio_image": "Generate, upload, and organize image work from Alcove Studio.",
        "studio_video": "Plan, launch, and keep video experiments organized from Alcove Studio.",
    }[str(spec["workspace_kind"])]
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <link rel="stylesheet" href="./style.css" />
    {script_tag}
  </head>
  <body>
    <div id="app">
      <header class="studio-header">
        <div class="studio-title">{header_title}</div>
        <div class="studio-tag">{studio_name}</div>
      </header>
      <main class="studio-main">
        <div id="studio-root" class="studio-surface"></div>
      </main>
      <footer class="studio-footer">
        <div>{footer_copy}</div>
        <div id="status">Ready</div>
      </footer>
    </div>
    <script type="module" src="./{entry_file}"></script>
  </body>
</html>
"""


def _entry_script(spec: dict[str, object]) -> str:
    workspace_kind = str(spec["workspace_kind"])
    title = str(spec["artifact_title"])
    template = str(spec["template_kind"])
    theme_text = str(spec.get("theme_prompt") or "")
    if workspace_kind == "studio_game":
        return _template_game_js(title, template, theme_text or None)
    if workspace_kind == "field_station":
        return _template_field_station_js(str(spec["workspace_id"]), title, template, theme_text or None)
    if workspace_kind == "studio_web":
        return _template_web_js(title, template, theme_text or None)
    if workspace_kind == "studio_data":
        return _template_data_js(title, template, theme_text or None)
    if workspace_kind == "studio_image":
        return _template_image_js(title, template, theme_text or None)
    if workspace_kind == "studio_video":
        return _template_video_js(title, template, theme_text or None)
    return _template_docs_js(title, template, theme_text or None)


def _template_field_station_js(workspace_id: str, title: str, kind: str, theme_prompt: str | None) -> str:
    workspace_id_text = _js_text(workspace_id)
    title_text = _js_text(title)
    theme_text = _js_text(theme_prompt or "A calm physical AI workbench for family, maker, business, real estate, demo, and Codex captures.")
    return f"""const STATION_WORKSPACE_ID = "{workspace_id_text}";
const STATION_TITLE = "{title_text}";
const STATION_THEME = "{theme_text}";
const statusEl = document.getElementById("status");
const root = document.getElementById("studio-root");

const style = document.createElement("style");
style.textContent = `
  .field-station-shell {{
    min-height: inherit;
    display: grid;
    grid-template-columns: minmax(360px, 0.9fr) minmax(420px, 1.1fr);
    grid-template-rows: auto auto;
    gap: 0;
    background: #ffffff;
    color: #111827;
  }}
  .station-mode-rail {{
    grid-row: 1 / span 2;
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: 20px;
    min-height: inherit;
    padding: 22px 16px;
    border-right: 1px solid #dbe3e8;
    background: #f1f4f5;
  }}
  .station-brand {{
    display: grid;
    gap: 5px;
    padding-bottom: 16px;
    border-bottom: 1px solid #dbe3e8;
  }}
  .station-brand-title {{
    font-size: 25px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .station-brand-subtitle {{
    color: #5f6b76;
    font-size: 12px;
    line-height: 1.35;
  }}
  .station-section-label,
  .station-eyebrow,
  .panel-kicker,
  .drawer-meta {{
    color: #66727d;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.11em;
    text-transform: uppercase;
  }}
  .mode-strip {{
    display: grid;
    align-content: start;
    gap: 8px;
  }}
  .mode-chip {{
    display: grid;
    grid-template-columns: 26px minmax(0, 1fr);
    gap: 10px;
    align-items: center;
    width: 100%;
    min-height: 58px;
    border: 1px solid #d9e1e6;
    border-radius: 8px;
    padding: 9px 10px;
    background: #ffffff;
    color: #111827;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }}
  .mode-glyph {{
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border: 1px solid #d7e1e6;
    border-radius: 6px;
    color: #5f6b76;
    font-size: 10px;
    font-weight: 800;
  }}
  .mode-name {{
    display: block;
    font-size: 14px;
    font-weight: 800;
    line-height: 1.1;
  }}
  .mode-detail {{
    display: block;
    margin-top: 3px;
    color: #66727d;
    font-size: 11px;
    line-height: 1.2;
  }}
  .mode-chip.is-active {{
    border-color: #0c938c;
    background: #eefbf9;
    color: #0f2f32;
  }}
  .mode-chip.is-active .mode-glyph {{
    border-color: #0c938c;
    color: #ffffff;
    background: #0c938c;
  }}
  .mode-chip.is-active .mode-detail {{
    color: #315f61;
  }}
  .mode-chip:focus-visible,
  .bridge-action:focus-visible,
  .advanced-summary:focus-visible,
  .capture-tool:focus-visible,
  .station-button:focus-visible,
  .voice-button:focus-visible {{
    outline: 2px solid rgba(12, 147, 140, 0.34);
    outline-offset: 2px;
  }}
  .active-project-card {{
    display: grid;
    gap: 8px;
    align-self: end;
    padding-top: 16px;
    border-top: 1px solid #dbe3e8;
    color: #4b5563;
    font-size: 12px;
    line-height: 1.45;
  }}
  .station-face-panel {{
    display: grid;
    align-content: start;
    align-items: start;
    justify-items: center;
    gap: 24px;
    padding: 36px 34px;
    border-right: 1px solid #dbe3e8;
    background: #ffffff;
  }}
  .station-presence-header {{
    width: min(100%, 540px);
    display: flex;
    justify-content: space-between;
    gap: 14px;
    align-items: baseline;
  }}
  .station-presence-copy {{
    width: min(100%, 540px);
    display: grid;
    gap: 10px;
  }}
  .station-composer-label {{
    display: grid;
    gap: 10px;
    max-width: 720px;
  }}
  .station-face {{
    width: min(100%, 540px);
    aspect-ratio: 1.22;
    border: 1px solid #152426;
    border-radius: 22px;
    display: grid;
    place-items: center;
    background: linear-gradient(180deg, #162523, #090f0f);
    box-shadow: inset 0 0 0 10px rgba(255, 255, 255, 0.035), 0 18px 42px rgba(17, 24, 39, 0.2);
    overflow: hidden;
    position: relative;
    --eye-x: 0px;
    --eye-y: 0px;
    transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease;
  }}
  .station-face::after {{
    content: attr(data-state-label);
    position: absolute;
    bottom: 22px;
    left: 50%;
    transform: translateX(-50%);
    color: rgba(237, 243, 236, 0.58);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }}
  .station-face[data-state="listening"] {{
    border-color: rgba(126, 224, 204, 0.64);
    box-shadow: inset 0 0 0 10px rgba(126, 224, 204, 0.055), 0 0 52px rgba(126, 224, 204, 0.22);
  }}
  .station-face[data-state="thinking"],
  .station-face[data-state="queued"] {{
    border-color: rgba(189, 201, 255, 0.5);
    box-shadow: inset 0 0 0 10px rgba(189, 201, 255, 0.05), 0 0 52px rgba(122, 141, 224, 0.18);
  }}
  .station-face[data-state="needs-review"] {{
    border-color: rgba(250, 204, 21, 0.5);
    box-shadow: inset 0 0 0 10px rgba(250, 204, 21, 0.045), 0 0 52px rgba(250, 204, 21, 0.14);
  }}
  .station-face[data-state="done"] {{
    border-color: rgba(134, 239, 172, 0.52);
    box-shadow: inset 0 0 0 10px rgba(134, 239, 172, 0.05), 0 0 52px rgba(34, 197, 94, 0.15);
  }}
  .station-face[data-state="error"] {{
    border-color: rgba(248, 113, 113, 0.58);
    box-shadow: inset 0 0 0 10px rgba(248, 113, 113, 0.05), 0 0 52px rgba(248, 113, 113, 0.16);
  }}
  .station-eyes {{
    display: flex;
    gap: 42px;
    align-items: center;
  }}
  .station-eye {{
    width: 74px;
    height: 74px;
    border-radius: 999px;
    background: #c9f4ff;
    box-shadow: 0 0 24px rgba(103, 226, 255, 0.46);
    position: relative;
  }}
  .station-eye::after {{
    content: "";
    position: absolute;
    width: 28px;
    height: 28px;
    border-radius: 999px;
    background: #0b2428;
    top: 24px;
    left: 28px;
    transform: translate(var(--eye-x), var(--eye-y));
    transition: transform 110ms ease;
  }}
  .station-face[data-state="idle"] .station-eye::after {{
    animation: station-look 5s ease-in-out infinite;
  }}
  .physical-controls {{
    width: min(100%, 540px);
    display: grid;
    gap: 12px;
    padding: 18px 0 0;
    border-top: 1px solid #dbe3e8;
    background: transparent;
  }}
  .primary-action-row {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
    align-items: center;
  }}
  .station-queue-panel strong,
  .briefing-source-row strong,
  .library-row strong {{
    color: #111827;
  }}
  .station-button {{
    border: 1px solid rgba(7, 103, 99, 0.2);
    border-radius: 10px;
    width: 100%;
    min-height: 58px;
    color: #042f2e;
    background: #3ee3d0;
    box-shadow: 0 0 0 6px rgba(62, 227, 208, 0.12), 0 13px 28px rgba(15, 118, 110, 0.16);
    font-size: 11px;
    font-weight: 900;
    letter-spacing: 0.05em;
    cursor: pointer;
  }}
  .hardware-buttons {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }}
  .station-console {{
    padding: 36px 42px;
    display: grid;
    align-content: start;
    gap: 16px;
    background: #ffffff;
  }}
  .station-heading {{
    margin: 0;
    font-size: clamp(28px, 3.2vw, 44px);
    line-height: 1;
    letter-spacing: 0;
  }}
  .station-invitation {{
    margin-top: 7px;
    color: #111827;
    font-size: clamp(34px, 4vw, 58px);
    font-weight: 800;
    line-height: 0.98;
    letter-spacing: 0;
  }}
  .station-copy {{
    max-width: 540px;
    color: #5f6b76;
    font-size: 15px;
    line-height: 1.45;
  }}
  .mission-input {{
    width: 100%;
    min-height: 280px;
    resize: vertical;
    border: 1px solid #dbe3e8;
    border-radius: 8px;
    color: #111827;
    background: #ffffff;
    padding: 14px;
    font: inherit;
    font-size: 14px;
    line-height: 1.45;
  }}
  .mission-row {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
    align-items: stretch;
  }}
  .voice-button,
  .capture-tool,
  .drawer-action,
  .bridge-action,
  .library-row button,
  .station-review button {{
    border: 1px solid #d7e1e6;
    border-radius: 8px;
    color: #111827;
    background: #ffffff;
    font: inherit;
    font-size: 12px;
    padding: 8px 10px;
    cursor: pointer;
  }}
  .voice-button {{
    min-width: 0;
    min-height: 68px;
    font-weight: 800;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px 12px;
    align-items: center;
    justify-items: start;
    text-align: left;
    letter-spacing: 0;
  }}
  .presence-switch {{
    grid-row: 1 / span 2;
    width: 50px;
    height: 28px;
    border: 1px solid #cfd9df;
    border-radius: 999px;
    background: #eef2f4;
    position: relative;
    transition: background 180ms ease, border-color 180ms ease;
  }}
  .presence-switch-knob {{
    position: absolute;
    width: 20px;
    height: 20px;
    border-radius: 999px;
    top: 3px;
    left: 4px;
    background: #ffffff;
    border: 1px solid #ccd6dc;
    box-shadow: 0 2px 8px rgba(17, 24, 39, 0.12);
    transition: transform 180ms ease, border-color 180ms ease;
  }}
  .presence-button-label {{
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.06em;
  }}
  .presence-button-hint {{
    color: #66727d;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0;
  }}
  .voice-button.is-listening,
  .voice-button.is-connecting {{
    border-color: #0c938c;
    color: #0f2f32;
    background: #eefbf9;
  }}
  .voice-button.is-listening .presence-button-hint,
  .voice-button.is-live .presence-button-hint,
  .voice-button.is-connecting .presence-button-hint {{
    color: #315f61;
  }}
  .voice-button.is-listening .presence-switch,
  .voice-button.is-live .presence-switch,
  .voice-button.is-connecting .presence-switch {{
    border-color: #0c938c;
    background: #36d9c5;
  }}
  .voice-button.is-listening .presence-switch-knob,
  .voice-button.is-live .presence-switch-knob,
  .voice-button.is-connecting .presence-switch-knob {{
    border-color: rgba(7, 103, 99, 0.28);
    transform: translateX(20px);
  }}
  .voice-button.is-connecting .presence-switch-knob {{
    animation: switch-wake-pulse 900ms ease-in-out infinite;
  }}
  .voice-button.is-live {{
    border-color: #0c938c;
    color: #052f2f;
    background: #dff8f4;
    box-shadow: inset 0 0 0 2px rgba(12, 147, 140, 0.12);
  }}
  .voice-button.is-error {{
    border-color: #ef4444;
    color: #991b1b;
  }}
  .voice-button.is-ok {{
    border-color: #16a34a;
    color: #166534;
  }}
  @keyframes switch-wake-pulse {{
    0%, 100% {{ box-shadow: 0 2px 8px rgba(17, 24, 39, 0.12); }}
    50% {{ box-shadow: 0 0 0 5px rgba(54, 217, 197, 0.22); }}
  }}
  .capture-tools {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }}
  .capture-tool.is-active {{
    border-color: #0c938c;
    color: #0f2f32;
    background: #eefbf9;
  }}
  .capture-tool[disabled] {{
    cursor: not-allowed;
    opacity: 0.55;
  }}
  .attachment-status {{
    color: #66727d;
    font-size: 12px;
  }}
  .attachment-strip {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    min-height: 0;
  }}
  .attachment-thumb {{
    display: grid;
    grid-template-columns: 52px minmax(0, 1fr) auto;
    gap: 9px;
    align-items: center;
    width: min(100%, 310px);
    border: 1px solid #dbe3e8;
    border-radius: 8px;
    padding: 7px;
    background: #fbfcfc;
  }}
  .attachment-thumb img {{
    width: 52px;
    height: 42px;
    object-fit: cover;
    border-radius: 6px;
    background: #eef2f4;
  }}
  .attachment-thumb span {{
    color: #334155;
    font-size: 12px;
    overflow-wrap: anywhere;
  }}
  .attachment-remove {{
    border: 1px solid #d7e1e6;
    border-radius: 6px;
    color: #4b5563;
    background: transparent;
    padding: 5px 7px;
  }}
  .camera-panel {{
    display: none;
    gap: 10px;
    align-items: start;
    border-top: 1px solid #dbe3e8;
    padding-top: 12px;
    background: transparent;
  }}
  .camera-panel.is-open {{
    display: grid;
    grid-template-columns: minmax(190px, 0.8fr) minmax(160px, 1fr);
  }}
  .camera-preview {{
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    border-radius: 8px;
    background: #0b1214;
  }}
  .camera-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-content: start;
  }}
  .capture-diagnostics {{
    display: grid;
    gap: 6px;
    align-content: start;
    border-top: 1px solid #e5eaee;
    padding-top: 10px;
    color: #66727d;
    font-size: 12px;
    background: transparent;
  }}
  .capture-diagnostics strong {{
    color: #111827;
    font-size: 12px;
  }}
  .capture-diagnostics[data-state="blocked"],
  .capture-diagnostics[data-state="unsupported"],
  .capture-diagnostics[data-state="error"] {{
    color: #991b1b;
  }}
  .capture-diagnostics[data-state="heard"] {{
    color: #166534;
  }}
  .station-orchestration {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }}
  .station-queue-panel {{
    border: 1px solid #dbe3e8;
    border-radius: 8px;
    padding: 12px;
    background: #ffffff;
    min-height: 132px;
  }}
  .station-queue-panel strong {{
    display: block;
    margin-bottom: 8px;
  }}
  .panel-title-row {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: baseline;
  }}
  .owner-briefing-panel {{
    display: grid;
    gap: 10px;
  }}
  .briefing-source-list {{
    display: grid;
    gap: 8px;
  }}
  .briefing-source-row {{
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 9px;
    align-items: start;
    border-top: 1px solid #e5eaee;
    padding-top: 8px;
    color: #4b5563;
    font-size: 13px;
  }}
  .briefing-source-row:first-child {{
    border-top: 0;
    padding-top: 0;
  }}
  .briefing-source-row input {{
    margin-top: 3px;
    accent-color: #0c938c;
  }}
  .briefing-source-row strong {{
    display: inline;
    margin: 0;
  }}
  .briefing-source-row em {{
    color: #66727d;
    font-style: normal;
    font-size: 12px;
  }}
  .briefing-note {{
    width: 100%;
    min-height: 54px;
    resize: vertical;
    border: 1px solid #dbe3e8;
    border-radius: 8px;
    color: #111827;
    background: #fbfcfc;
    padding: 9px;
    font: inherit;
    font-size: 13px;
  }}
  .briefing-actions {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }}
  .briefing-status {{
    color: #66727d;
    font-size: 12px;
  }}
  .station-job,
  .station-review {{
    display: grid;
    gap: 4px;
    border-top: 1px solid #e5eaee;
    padding-top: 8px;
    margin-top: 8px;
    color: #4b5563;
    font-size: 13px;
  }}
  .station-job:first-child,
  .station-review:first-child {{
    border-top: 0;
    padding-top: 0;
    margin-top: 0;
  }}
  .station-review button {{
    justify-self: start;
  }}
  .review-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
  }}
  .review-drawer {{
    position: fixed;
    top: 22px;
    right: 22px;
    bottom: 22px;
    width: min(560px, calc(100vw - 44px));
    z-index: 20;
    display: grid;
    grid-template-rows: auto auto 1fr auto;
    gap: 12px;
    padding: 18px;
    border: 1px solid rgba(17, 24, 39, 0.12);
    border-radius: 12px;
    background: #f7f8f6;
    color: #17201d;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.28);
    pointer-events: none;
    transform: translateX(calc(100% + 32px));
    transition: transform 180ms ease;
    visibility: hidden;
  }}
  .review-drawer.is-open {{
    pointer-events: auto;
    transform: translateX(0);
    visibility: visible;
  }}
  .drawer-header {{
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: start;
  }}
  .drawer-title {{
    margin: 0;
    font-size: 22px;
    line-height: 1.08;
    letter-spacing: 0;
  }}
  .drawer-close {{
    border: 1px solid rgba(17, 24, 39, 0.12);
    border-radius: 8px;
    background: #fff;
    color: #17201d;
    padding: 7px 9px;
  }}
  .artifact-body {{
    min-height: 0;
    overflow: auto;
    border-top: 1px solid rgba(17, 24, 39, 0.1);
    border-bottom: 1px solid rgba(17, 24, 39, 0.1);
    padding: 12px 0;
    white-space: pre-wrap;
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
  .follow-up-input {{
    width: 100%;
    min-height: 68px;
    resize: vertical;
    border: 1px solid rgba(17, 24, 39, 0.14);
    border-radius: 8px;
    color: #17201d;
    background: #fff;
    padding: 9px;
    font: inherit;
  }}
  .drawer-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .drawer-action {{
    color: #17201d;
    background: #fff;
  }}
  .drawer-action.primary {{
    border-color: rgba(17, 24, 39, 0.26);
    color: #f8fafc;
    background: #17201d;
  }}
  .station-empty {{
    color: #66727d;
    font-size: 13px;
  }}
  .station-advanced {{
    grid-column: 1 / -1;
    border-top: 1px solid #dbe3e8;
    background: #ffffff;
  }}
  .advanced-summary {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 14px;
    min-height: 56px;
    padding: 0 28px;
    color: #111827;
    cursor: pointer;
    list-style: none;
  }}
  .advanced-summary::-webkit-details-marker {{
    display: none;
  }}
  .advanced-summary::after {{
    content: "+";
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border: 1px solid #d7e1e6;
    border-radius: 999px;
    background: #ffffff;
    color: #4b5563;
    font-weight: 800;
  }}
  .station-advanced[open] .advanced-summary::after {{
    content: "-";
  }}
  .advanced-summary-status {{
    color: #66727d;
    font-size: 12px;
    font-weight: 500;
  }}
  .advanced-content {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 16px;
    padding: 0 28px 28px;
  }}
  .advanced-mode-panel {{
    grid-column: 1 / -1;
    display: grid;
    gap: 10px;
    padding: 14px 0 4px;
    border-top: 1px solid #dbe3e8;
  }}
  .advanced-mode-list {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
  }}
  .station-bottom-bar {{
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.85fr);
    gap: 16px;
    padding: 0;
    background: transparent;
  }}
  .station-bottom-bar .station-queue-panel {{
    display: grid;
    align-content: start;
    gap: 12px;
  }}
  .station-library-panel {{
    display: grid;
    gap: 12px;
  }}
  .library-section {{
    display: grid;
    gap: 8px;
  }}
  .library-row {{
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 10px;
    align-items: start;
    border-top: 1px solid #e5eaee;
    padding-top: 8px;
    color: #4b5563;
    font-size: 13px;
  }}
  .library-thumb {{
    width: 46px;
    height: 38px;
    object-fit: cover;
    border-radius: 6px;
    background: #e9eef1;
  }}
  .bridge-panel {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }}
  .bridge-status {{
    color: #66727d;
    font-size: 12px;
  }}
  .service-strip {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .service-chip {{
    border: 1px solid #d7e1e6;
    border-radius: 8px;
    padding: 8px 10px;
    background: #ffffff;
    color: #334155;
    font-size: 12px;
  }}
  .service-chip[data-state="ready"],
  .service-chip[data-state="complete"] {{
    border-color: rgba(22, 163, 74, 0.34);
  }}
  .service-chip[data-state="thinking"],
  .service-chip[data-state="approval"] {{
    border-color: rgba(217, 119, 6, 0.38);
  }}
  .service-chip[data-state="error"] {{
    border-color: rgba(220, 38, 38, 0.4);
  }}
  @keyframes station-look {{
    0%, 100% {{ transform: translate(0, 0); }}
    28% {{ transform: translate(-10px, 4px); }}
    56% {{ transform: translate(9px, -3px); }}
    76% {{ transform: translate(3px, 8px); }}
  }}
  @media (max-width: 900px) {{
    .field-station-shell {{
      grid-template-columns: 1fr;
    }}
    .station-advanced {{
      grid-column: 1;
    }}
    .advanced-content,
    .station-bottom-bar {{
      grid-template-columns: 1fr;
    }}
    .station-face-panel {{
      border-right: 0;
      border-bottom: 1px solid #dbe3e8;
    }}
    .station-console {{
      padding: 28px 34px 36px;
    }}
  }}
  @media (max-width: 760px) {{
    .field-station-shell {{
      grid-template-columns: 1fr;
    }}
    .station-mode-rail {{
      grid-row: auto;
      min-height: 0;
      border-right: 0;
      border-bottom: 1px solid #dbe3e8;
    }}
    .mode-strip {{
      grid-template-columns: 1fr;
    }}
    .station-face-panel {{
      border-right: 0;
      border-bottom: 1px solid #dbe3e8;
      padding: 24px;
    }}
    .station-face {{
      position: relative;
      top: auto;
      width: min(100%, 420px);
    }}
    .station-console {{
      padding: 24px;
    }}
    .station-orchestration {{
      grid-template-columns: 1fr;
    }}
    .mission-row {{
      grid-template-columns: 1fr;
    }}
    .station-button {{
      justify-self: start;
    }}
    .station-advanced {{
      grid-column: 1;
    }}
    .advanced-summary {{
      padding: 20px 24px;
    }}
    .advanced-content {{
      grid-template-columns: 1fr;
      padding: 0 24px 22px;
    }}
    .advanced-mode-list {{
      grid-template-columns: 1fr;
    }}
    .camera-panel.is-open {{
      grid-template-columns: 1fr;
    }}
    .review-drawer {{
      inset: 14px;
      width: auto;
    }}
  }}
`;
document.head.appendChild(style);

const EXPECTED_OUTPUT_BY_MODE = {{
  family: "kid_story",
  maker: "project_plan",
  business: "owner_briefing",
  "real-estate": "transaction_brief",
  demo: "client_demo_explanation",
  codex: "codex_handoff",
}};
const MODE_UI = {{
  family: {{
    eyebrow: "Family story",
    invitation: "What story are we making?",
  }},
  maker: {{
    eyebrow: "Field Station",
    invitation: "What are we making?",
  }},
  business: {{
    eyebrow: "Business mode",
    invitation: "What needs attention?",
  }},
  "real-estate": {{
    eyebrow: "Real estate mode",
    invitation: "What needs to move forward?",
  }},
  demo: {{
    eyebrow: "Demo mode",
    invitation: "Who are we explaining this to?",
  }},
  codex: {{
    eyebrow: "Codex mode",
    invitation: "What should Codex build next?",
  }},
}};
let selectedMode = "maker";
let lastSnapshot = null;
let selectedReview = null;
let selectedArtifactContent = "";
let stationState = "idle";
let stationEventCursor = "0";
let stationServerInfo = null;
let lastCapture = null;
let currentAttachments = [];
let selectedBriefingSourceIds = new Set();
let cameraStream = null;
let voiceSession = {{
  state: "ready",
  lastTranscript: "",
  lastAssistantTranscript: "",
  error: "",
}};
let realtimeSession = {{
  active: false,
  connecting: false,
  connectionId: 0,
  peerConnection: null,
  dataChannel: null,
  mediaStream: null,
  audioElement: null,
  composerStartValue: "",
  handledToolCalls: new Set(),
}};

root.innerHTML = `
  <section class="field-station-shell">
    <div class="station-face-panel">
      <div class="station-presence-header">
        <span class="station-section-label">Station Presence</span>
      </div>
      <div class="station-face" id="station-face" aria-label="Alcove Field Station face" data-state="idle" data-state-label="Idle">
        <div class="station-eyes">
          <div class="station-eye"></div>
          <div class="station-eye"></div>
        </div>
      </div>
      <div class="physical-controls" aria-label="Physical control panel">
        <div class="primary-action-row">
          <button class="voice-button" type="button" id="voice-button" aria-pressed="false">
            <span class="presence-switch" aria-hidden="true"><span class="presence-switch-knob"></span></span>
            <span class="presence-button-label">WAKE ALCOVE</span>
            <span class="presence-button-hint">Voice off. Tap to wake.</span>
          </button>
        </div>
        <div class="capture-diagnostics" id="capture-diagnostics" data-state="ready">
          <strong id="voice-status">Alcove ready</strong>
          <span id="capture-status">Say what to make, draft, plan, or hand off.</span>
        </div>
      </div>
    </div>
    <div class="station-console">
      <label class="station-composer-label" for="mission-goal">
        <span class="station-section-label" id="mode-eyebrow">Field Station</span>
        <span class="station-invitation" id="station-invitation">What are we making?</span>
        <span class="station-copy">Type it, say it, or add what is on the desk. Alcove will turn the mess into a saved artifact.</span>
      </label>
      <div class="mission-row">
        <textarea id="mission-goal" class="mission-input" placeholder="Describe the messy idea, what is on the desk, or what Alcove should turn into a handoff.">Turn this station capture into a practical next-step plan.</textarea>
      </div>
      <div class="capture-tools" aria-label="Capture tools">
        <label class="capture-tool" for="capture-image-input">Add image</label>
        <input id="capture-image-input" type="file" accept="image/*" hidden>
        <button class="capture-tool" type="button" id="camera-button">Camera</button>
        <button class="capture-tool" type="button" id="clear-attachments">Clear images</button>
        <span class="attachment-status" id="attachment-status">No images attached.</span>
      </div>
      <div class="camera-panel" id="camera-panel" aria-label="Camera capture panel">
        <video class="camera-preview" id="camera-preview" autoplay muted playsinline></video>
        <div class="camera-actions">
          <button class="capture-tool" type="button" id="camera-snapshot">Take snapshot</button>
          <button class="capture-tool" type="button" id="camera-stop">Stop camera</button>
          <span class="attachment-status" id="camera-status">Camera is off.</span>
        </div>
      </div>
      <div class="attachment-strip" id="capture-attachments" aria-label="Attached capture images"></div>
    </div>
    <details class="station-advanced" id="advanced-panel">
      <summary class="advanced-summary">
        <span><strong>Advanced</strong></span>
        <span class="advanced-summary-status" id="advanced-summary-status">Modes, reviews, library, and station services</span>
      </summary>
      <div class="advanced-content">
        <section class="advanced-mode-panel" aria-label="Advanced modes">
          <div class="panel-title-row">
            <strong>Mode presets</strong>
            <span class="panel-kicker">Prompt behavior</span>
          </div>
          <div class="advanced-mode-list">
            ${{[
              ["maker", "01", "Maker", "Project plans"],
              ["family", "02", "Family", "Stories + quests"],
              ["business", "03", "Business", "Owner briefings"],
              ["real-estate", "04", "Real Estate", "Dates + checklists"],
              ["demo", "05", "Demo", "Client proof"],
              ["codex", "06", "Codex", "Handoffs + jobs"],
            ].map(([value, glyph, label, detail]) => `<button class="mode-chip${{value === "maker" ? " is-active" : ""}}" type="button" data-mode="${{value}}" data-mode-label="${{label}}">
              <span class="mode-glyph">${{glyph}}</span>
              <span><span class="mode-name">${{label}}</span><span class="mode-detail">${{detail}}</span></span>
            </button>`).join("")}}
          </div>
        </section>
      <section class="station-queue-panel owner-briefing-panel" aria-label="Owner briefing">
        <div class="panel-title-row">
          <strong>Owner briefing</strong>
          <span class="panel-kicker">Read-only adapters</span>
        </div>
        <div id="briefing-source-list" class="briefing-source-list station-empty">Loading briefing sources.</div>
        <textarea id="owner-briefing-note" class="briefing-note" placeholder="Optional focus, e.g. what needs Sky's attention today?"></textarea>
        <div class="briefing-actions">
          <button class="bridge-action" type="button" id="owner-briefing-button">Prepare owner brief</button>
          <span class="briefing-status" id="owner-briefing-status">Drafts and recommendations only.</span>
        </div>
      </section>
      <section class="station-orchestration" aria-label="Field Station jobs and reviews">
        <div class="station-queue-panel">
          <strong>Background jobs</strong>
          <div id="job-strip" class="station-empty">No jobs queued.</div>
        </div>
        <div class="station-queue-panel">
          <strong>Review tray</strong>
          <div id="review-tray" class="station-empty">No review bundles.</div>
        </div>
      </section>
      <div class="hardware-buttons" aria-label="Approval controls">
        <button class="bridge-action" type="button" data-physical-action="approve">Approve</button>
        <button class="bridge-action" type="button" data-physical-action="pause">Pause</button>
        <button class="bridge-action" type="button" data-physical-action="reject">Reject</button>
      </div>
      <section class="station-bottom-bar" aria-label="Station library and services">
      <section class="station-queue-panel station-library-panel" aria-label="Project library">
        <strong>Project library</strong>
        <div id="project-library" class="station-empty">No saved captures yet.</div>
      </section>
      <div class="station-queue-panel">
        <div class="panel-title-row">
          <strong>Station services</strong>
          <span class="panel-kicker">Bridge</span>
        </div>
        <div class="bridge-panel" aria-label="Station bridge">
          <button class="bridge-action" type="button" id="bridge-button-test">Button test</button>
          <button class="bridge-action" type="button" id="bridge-print-test">Printer test</button>
          <span class="bridge-status" id="bridge-status">Bridge contracts ready.</span>
        </div>
        <div class="service-strip" id="service-strip" aria-label="Station service status">
          ${{["button", "camera", "mic", "briefing", "LED", "printer"].map((service) => `<span class="service-chip">${{service}} · standby</span>`).join("")}}
        </div>
      </div>
      </section>
      </div>
    </details>
  </section>
  <aside class="review-drawer" id="review-drawer" aria-label="Artifact review drawer" aria-hidden="true">
    <div class="drawer-header">
      <div>
        <div class="drawer-meta" id="drawer-meta">No artifact selected</div>
        <h2 class="drawer-title" id="drawer-title">Review artifact</h2>
      </div>
      <button class="drawer-close" type="button" id="drawer-close">Close</button>
    </div>
    <div id="drawer-summary" class="drawer-meta"></div>
    <pre class="artifact-body" id="artifact-body">Open a review bundle to inspect the saved artifact.</pre>
    <div>
      <textarea class="follow-up-input" id="follow-up-input" placeholder="Optional revision or follow-up note"></textarea>
      <div class="drawer-actions">
        <button class="drawer-action primary" type="button" id="drawer-approve">Approve</button>
        <button class="drawer-action" type="button" id="drawer-revise">Revise</button>
        <button class="drawer-action" type="button" id="drawer-follow-up">Queue follow-up</button>
        <button class="drawer-action" type="button" id="drawer-print">Print</button>
      </div>
    </div>
  </aside>
`;

async function apiJson(url, init = {{}}) {{
  const response = await fetch(url, {{
    ...init,
    headers: {{
      "content-type": "application/json",
      ...(init.headers || {{}}),
    }},
  }});
  const payload = await response.json().catch(() => ({{}}));
  if (!response.ok) {{
    const error = new Error(payload.detail || payload.error || "Request failed");
    error.status = response.status;
    throw error;
  }}
  return payload;
}}

function escapeHtml(value) {{
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}}

function compactText(value, limit = 150) {{
  const text = String(value || "").replace(/\\s+/g, " ").trim();
  return text.length > limit ? `${{text.slice(0, limit - 3).trim()}}...` : text;
}}

const STATE_LABELS = {{
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  queued: "Queued",
  "needs-review": "Review",
  done: "Done",
  error: "Help",
}};

function syncModeUi() {{
  const mode = MODE_UI[selectedMode] || MODE_UI.maker;
  const eyebrow = document.getElementById("mode-eyebrow");
  const invitation = document.getElementById("station-invitation");
  if (eyebrow) eyebrow.textContent = mode.eyebrow;
  if (invitation) invitation.textContent = mode.invitation;
}}

function setStationState(state, label) {{
  stationState = state;
  const stateLabel = label || STATE_LABELS[state] || state;
  const face = document.getElementById("station-face");
  if (face) {{
    face.dataset.state = state;
    face.dataset.stateLabel = stateLabel;
  }}
  const stateChip = document.getElementById("station-state-chip");
  if (stateChip) {{
    stateChip.textContent = stateLabel;
  }}
  const panelLabel = document.getElementById("panel-state-label");
  if (panelLabel) {{
    panelLabel.textContent = stateLabel;
  }}
  if (statusEl && label) {{
    statusEl.textContent = label;
  }}
}}

function setCaptureStatus(message) {{
  const el = document.getElementById("capture-status");
  if (el) el.textContent = message || "Say what to make, draft, plan, or hand off.";
}}

function setPresenceButton(label = "WAKE ALCOVE", hint = "Voice off. Tap to wake.") {{
  const button = document.getElementById("voice-button");
  if (!button) return;
  const labelEl = button.querySelector(".presence-button-label");
  const hintEl = button.querySelector(".presence-button-hint");
  if (labelEl && hintEl) {{
    labelEl.textContent = label;
    hintEl.textContent = hint;
    button.setAttribute("aria-label", `${{label}}. ${{hint}}`);
    return;
  }}
  button.textContent = label;
  button.setAttribute("aria-label", label);
}}

function setVoiceStatus(state, label, detail = "") {{
  voiceSession.state = state;
  voiceSession.error = state === "error" || state === "blocked" || state === "unsupported" ? detail : "";
  const rootEl = document.getElementById("capture-diagnostics");
  const status = document.getElementById("voice-status");
  const button = document.getElementById("voice-button");
  if (rootEl) rootEl.dataset.state = state;
  if (status) status.textContent = label;
  if (button) {{
    button.classList.toggle("is-listening", state === "listening");
    button.classList.toggle("is-live", state === "realtime");
    button.classList.toggle("is-connecting", state === "connecting");
    button.classList.toggle("is-error", ["blocked", "unsupported", "error", "no-speech"].includes(state));
    button.classList.toggle("is-ok", state === "heard");
    button.setAttribute("aria-pressed", ["connecting", "listening", "realtime"].includes(state) ? "true" : "false");
    button.title = detail || label;
  }}
  if (detail) setCaptureStatus(detail);
}}

function captureText() {{
  return document.getElementById("mission-goal")?.value?.trim() || "Turn this station capture into a practical next-step plan.";
}}

function captureAssetUrl(attachment) {{
  if (!attachment) return "";
  if (attachment.url) return attachment.url;
  const path = String(attachment.path || "").trim();
  return path ? `/api/field-station/capture-assets?workspace_id=${{encodeURIComponent(STATION_WORKSPACE_ID)}}&path=${{encodeURIComponent(path)}}` : "";
}}

function renderCurrentAttachments() {{
  const strip = document.getElementById("capture-attachments");
  const status = document.getElementById("attachment-status");
  if (status) {{
    status.textContent = currentAttachments.length
      ? `${{currentAttachments.length}} image${{currentAttachments.length === 1 ? "" : "s"}} attached.`
      : "No images attached.";
  }}
  if (!strip) return;
  strip.innerHTML = currentAttachments.map((attachment, index) => `
    <div class="attachment-thumb">
      <img src="${{escapeHtml(captureAssetUrl(attachment))}}" alt="">
      <span>${{escapeHtml(attachment.label || "capture image")}}</span>
      <button class="attachment-remove" type="button" data-remove-attachment="${{index}}">Remove</button>
    </div>
  `).join("");
}}

async function dataUrlFromFile(file) {{
  return new Promise((resolve, reject) => {{
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read image file."));
    reader.readAsDataURL(file);
  }});
}}

async function uploadCaptureAsset(dataUrl, label, source, metadata = {{}}) {{
  const payload = await apiJson("/api/field-station/capture-assets", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      data_url: dataUrl,
      file_name: label,
      label,
      source,
      metadata,
    }}),
  }});
  currentAttachments.push(payload.attachment);
  renderCurrentAttachments();
  setCaptureStatus(`Attached image: ${{label || "capture image"}}.`);
  return payload.attachment;
}}

function captureComposerPayload(source, metadata = {{}}) {{
  const text = captureText();
  return {{
    workspace_id: STATION_WORKSPACE_ID,
    mode: selectedMode,
    source,
    text,
    attachments: currentAttachments,
    metadata: {{
      expected_output: EXPECTED_OUTPUT_BY_MODE[selectedMode] || "artifact",
      attachment_count: currentAttachments.length,
      voice_state: voiceSession.state,
      voice_transcript: voiceSession.lastTranscript || "",
      realtime_assistant_transcript: voiceSession.lastAssistantTranscript || "",
      ...metadata,
    }},
  }};
}}

async function saveStationCapture(source, metadata = {{}}) {{
  const payload = await apiJson("/api/field-station/captures", {{
    method: "POST",
    body: JSON.stringify(captureComposerPayload(source, metadata)),
  }});
  lastCapture = payload.capture;
  setCaptureStatus(`Saved capture ${{lastCapture.id}} from ${{lastCapture.source}}.`);
  return payload.capture;
}}

function applySnapshotState(snapshot) {{
  if (stationState === "listening") return;
  const jobs = Array.isArray(snapshot?.jobs) ? snapshot.jobs : [];
  const reviews = Array.isArray(snapshot?.reviews) ? snapshot.reviews : [];
  const pendingReviews = reviews.filter((review) => review.status === "pending");
  const activeJobs = jobs.filter((job) => ["queued", "running", "needs_approval"].includes(job.status));
  const reviewDrawerOpen = document.getElementById("review-drawer")?.classList.contains("is-open");
  if (activeJobs.length) {{
    setStationState("queued", "Working");
    return;
  }}
  if (pendingReviews.length && reviewDrawerOpen) {{
    setStationState("needs-review", "Review open");
    return;
  }}
  if (jobs.some((job) => job.status === "succeeded")) {{
    setStationState("done", "Done");
    return;
  }}
  setStationState("idle", "Ready");
}}

function missionForReview(review) {{
  const missions = Array.isArray(lastSnapshot?.missions) ? lastSnapshot.missions : [];
  return missions.find((mission) => mission.id === review?.mission_id) || null;
}}

function artifactExcerpt() {{
  return selectedArtifactContent.length > 2600
    ? `${{selectedArtifactContent.slice(0, 2600)}}\\n\\n[Artifact excerpt truncated]`
    : selectedArtifactContent;
}}

async function loadReviewArtifact(review) {{
  const artifactPath = Array.isArray(review?.artifact_paths) ? review.artifact_paths[0] : "";
  if (!artifactPath) return "";
  const payload = await apiJson(`/api/field-station/artifact?workspace_id=${{encodeURIComponent(STATION_WORKSPACE_ID)}}&path=${{encodeURIComponent(artifactPath)}}`);
  return payload.content || "";
}}

async function openReviewDrawer(reviewId) {{
  const reviews = Array.isArray(lastSnapshot?.reviews) ? lastSnapshot.reviews : [];
  const review = reviews.find((item) => item.id === reviewId);
  if (!review) return;
  selectedReview = review;
  selectedArtifactContent = "";
  setStationState("needs-review", "Opening review");
  const drawer = document.getElementById("review-drawer");
  const title = document.getElementById("drawer-title");
  const meta = document.getElementById("drawer-meta");
  const summary = document.getElementById("drawer-summary");
  const body = document.getElementById("artifact-body");
  const followUp = document.getElementById("follow-up-input");
  if (title) title.textContent = review.title || "Review artifact";
  if (meta) meta.textContent = `${{review.status || "pending"}} · ${{review.artifact_paths?.[0] || "artifact"}}`;
  if (summary) summary.textContent = review.summary || "";
  if (body) body.textContent = "Loading artifact...";
  if (followUp) followUp.value = "";
  drawer?.classList.add("is-open");
  drawer?.setAttribute("aria-hidden", "false");
  try {{
    selectedArtifactContent = await loadReviewArtifact(review);
    if (body) body.textContent = selectedArtifactContent || "No artifact content was saved.";
    setStationState("needs-review", "Review open");
  }} catch (error) {{
    if (body) body.textContent = error.message || "Could not load artifact.";
    setStationState("error", "Artifact error");
  }}
}}

function closeReviewDrawer() {{
  const drawer = document.getElementById("review-drawer");
  drawer?.classList.remove("is-open");
  drawer?.setAttribute("aria-hidden", "true");
}}

async function approveSelectedReview() {{
  if (!selectedReview) return;
  setStationState("thinking", "Approving");
  await apiJson(`/api/field-station/reviews/${{encodeURIComponent(selectedReview.id)}}/approve`, {{
    method: "POST",
    body: JSON.stringify({{ workspace_id: STATION_WORKSPACE_ID }}),
  }});
  closeReviewDrawer();
  selectedReview = null;
  selectedArtifactContent = "";
  await refreshStationSnapshot();
  setStationState("done", "Approved");
}}

async function queueDerivedJob(action) {{
  if (!selectedReview) return;
  const note = document.getElementById("follow-up-input")?.value?.trim() || "";
  const originalMission = missionForReview(selectedReview) || {{}};
  const mode = action === "revise" ? (originalMission.mode || selectedMode) : selectedMode;
  const expectedOutput = action === "revise"
    ? (originalMission.expected_output || EXPECTED_OUTPUT_BY_MODE[mode] || "artifact")
    : (EXPECTED_OUTPUT_BY_MODE[mode] || "artifact");
  const actionLabel = action === "revise" ? "Revise this reviewed artifact" : "Create a useful follow-up from this reviewed artifact";
  const defaultNote = action === "revise" ? "tighten and improve the artifact" : "choose the next practical artifact";
  const goal = `${{actionLabel}}. Request: ${{note || defaultNote}}.\\n\\nOriginal review: ${{selectedReview.title || ""}} - ${{selectedReview.summary || ""}}\\n\\nArtifact excerpt:\\n${{artifactExcerpt()}}`;
  setStationState("thinking", action === "revise" ? "Queueing revision" : "Queueing follow-up");
  const capturePayload = await apiJson("/api/field-station/captures", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      source: action === "revise" ? "review_revision" : "review_follow_up",
      mode,
      text: note || defaultNote,
      metadata: {{
        action,
        review_id: selectedReview.id,
        artifact_excerpt: artifactExcerpt(),
      }},
    }}),
  }});
  const missionPayload = await apiJson("/api/field-station/missions", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      source: action === "revise" ? "field_station_review_revision" : "field_station_review_follow_up",
      mode,
      goal,
      target: selectedReview.id,
      capture_id: capturePayload.capture.id,
      permission_lane: "read-only",
      expected_output: expectedOutput,
    }}),
  }});
  await apiJson("/api/field-station/jobs", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      mission_id: missionPayload.mission.id,
      provider: "codex",
    }}),
  }});
  closeReviewDrawer();
  await refreshStationSnapshot();
  setStationState("queued", action === "revise" ? "Revision queued" : "Follow-up queued");
}}

function renderStationServices(station) {{
  const strip = document.getElementById("service-strip");
  const services = Array.isArray(station?.services) ? station.services : [];
  if (!strip) return;
  strip.innerHTML = services.length
    ? services.map((service) => `
        <span class="service-chip" data-state="${{escapeHtml(service.state || "stub")}}">
          ${{escapeHtml(service.label || service.id)}} · ${{escapeHtml(service.state || "stub")}}
        </span>
      `).join("")
    : ["button", "camera", "mic", "briefing", "LED", "printer"].map((service) => `<span class="service-chip">${{service}} · standby</span>`).join("");
}}

function renderProjectLibrary(snapshot) {{
  const library = snapshot?.library || {{}};
  const captures = Array.isArray(library.captures) ? library.captures : [];
  const artifacts = Array.isArray(library.artifacts) ? library.artifacts : [];
  const el = document.getElementById("project-library");
  if (!el) return;
  if (!captures.length && !artifacts.length) {{
    el.className = "station-empty";
    el.textContent = "No saved captures yet.";
    return;
  }}
  el.className = "";
  const captureHtml = captures.length
    ? `<div class="library-section"><span class="drawer-meta">Captures</span>${{captures.slice(0, 4).map((capture) => `
        <div class="library-row">
          ${{capture.attachments?.[0] ? `<img class="library-thumb" src="${{escapeHtml(captureAssetUrl(capture.attachments[0]))}}" alt="">` : `<span class="library-thumb"></span>`}}
          <span><strong>${{escapeHtml(capture.source || "capture")}}</strong><br>${{escapeHtml(compactText(capture.text || "", 110))}}</span>
          <button type="button" data-use-capture-id="${{escapeHtml(capture.id)}}">Use</button>
        </div>
      `).join("")}}</div>`
    : "";
  const artifactHtml = artifacts.length
    ? `<div class="library-section"><span class="drawer-meta">Artifacts</span>${{artifacts.slice(0, 4).map((artifact) => `
        <div class="library-row">
          <span class="library-thumb"></span>
          <span><strong>${{escapeHtml(artifact.title || "Artifact")}}</strong><br>${{escapeHtml(compactText(artifact.summary || artifact.status || "", 110))}}</span>
          ${{artifact.review_id ? `<button type="button" data-open-review-id="${{escapeHtml(artifact.review_id)}}">Open</button>` : ""}}
        </div>
      `).join("")}}</div>`
    : "";
  el.innerHTML = captureHtml + artifactHtml;
}}

function renderOwnerBriefing(snapshot) {{
  const briefing = snapshot?.owner_briefing || {{}};
  const sources = Array.isArray(briefing.sources) ? briefing.sources : [];
  const list = document.getElementById("briefing-source-list");
  const status = document.getElementById("owner-briefing-status");
  if (!list) return;
  const sourceIds = sources.map((source) => String(source.id || "")).filter(Boolean);
  if (!selectedBriefingSourceIds.size) {{
    selectedBriefingSourceIds = new Set(sourceIds);
  }} else {{
    selectedBriefingSourceIds = new Set([...selectedBriefingSourceIds].filter((id) => sourceIds.includes(id)));
    if (!selectedBriefingSourceIds.size && sourceIds.length) selectedBriefingSourceIds = new Set(sourceIds);
  }}
  if (!sources.length) {{
    list.className = "briefing-source-list station-empty";
    list.textContent = "No briefing sources available.";
    if (status) status.textContent = "Add a read-only source before preparing a brief.";
    return;
  }}
  list.className = "briefing-source-list";
  list.innerHTML = sources.map((source) => `
    <label class="briefing-source-row">
      <input type="checkbox" data-briefing-source-id="${{escapeHtml(source.id)}}"
        ${{selectedBriefingSourceIds.has(String(source.id || "")) ? "checked" : ""}}>
      <span>
        <strong>${{escapeHtml(source.label || "Briefing source")}}</strong>
        <em> · ${{escapeHtml(source.kind || "manual")}} · ${{escapeHtml(source.permission_lane || "read-only")}}${{source.is_sample ? " · sample" : ""}}</em><br>
        ${{escapeHtml(compactText(source.summary || "", 140))}}
      </span>
    </label>
  `).join("");
  if (status) {{
    const jobs = Array.isArray(snapshot?.jobs) ? snapshot.jobs : [];
    const latestOwnerJob = [...jobs].reverse().find((job) => job.input_snapshot?.expected_output === "owner_briefing");
    if (latestOwnerJob?.status === "needs_review") {{
      status.textContent = "Owner brief ready in the review tray.";
    }} else if (["queued", "running", "needs_approval"].includes(latestOwnerJob?.status || "")) {{
      status.textContent = "Owner brief is running. Drafts and recommendations only.";
    }} else {{
      status.textContent = `${{selectedBriefingSourceIds.size}} source${{selectedBriefingSourceIds.size === 1 ? "" : "s"}} selected. Drafts and recommendations only.`;
    }}
  }}
}}

function renderStationSnapshot(snapshot) {{
  lastSnapshot = snapshot;
  const allJobs = Array.isArray(snapshot?.jobs) ? snapshot.jobs : [];
  const allReviews = Array.isArray(snapshot?.reviews) ? snapshot.reviews : [];
  const jobs = allJobs.slice(-4).reverse();
  const reviews = Array.isArray(snapshot?.reviews)
    ? snapshot.reviews.filter((review) => review.status === "pending").slice(-3).reverse()
    : [];
  const jobStrip = document.getElementById("job-strip");
  const reviewTray = document.getElementById("review-tray");
  const advancedStatus = document.getElementById("advanced-summary-status");
  if (advancedStatus) {{
    const activeJobs = allJobs.filter((job) => ["queued", "running", "needs_approval"].includes(job.status || ""));
    const pendingReviews = allReviews.filter((review) => review.status === "pending");
    advancedStatus.textContent = activeJobs.length || pendingReviews.length
      ? `${{activeJobs.length}} active job${{activeJobs.length === 1 ? "" : "s"}} · ${{pendingReviews.length}} review${{pendingReviews.length === 1 ? "" : "s"}}`
      : "Modes, reviews, library, and station services";
  }}
  if (jobStrip) {{
    jobStrip.className = jobs.length ? "" : "station-empty";
    jobStrip.innerHTML = jobs.length
      ? jobs.map((job) => `
          <div class="station-job">
            <span><strong>${{escapeHtml(job.status)}}</strong> · ${{escapeHtml(job.provider || "worker")}} · ${{escapeHtml(job.input_snapshot?.expected_output || "artifact")}}</span>
            <span>${{escapeHtml(compactText(job.input_snapshot?.goal || ""))}}</span>
          </div>
        `).join("")
      : "No jobs queued.";
  }}
  if (reviewTray) {{
    reviewTray.className = reviews.length ? "" : "station-empty";
    reviewTray.innerHTML = reviews.length
      ? reviews.map((review) => `
          <div class="station-review">
            <span><strong>${{escapeHtml(review.title)}}</strong></span>
            <span>${{escapeHtml(compactText(review.summary || "", 120))}}</span>
            <div class="review-actions">
              <button type="button" data-open-review-id="${{escapeHtml(review.id)}}">Open</button>
              <button type="button" data-approve-review-id="${{escapeHtml(review.id)}}">Approve</button>
            </div>
          </div>
        `).join("")
      : "No review bundles.";
  }}
  renderProjectLibrary(snapshot);
  renderOwnerBriefing(snapshot);
  renderStationServices(snapshot?.station);
  applySnapshotState(snapshot);
}}

async function refreshStationSnapshot() {{
  const snapshot = await apiJson(`/api/field-station/snapshot?workspace_id=${{encodeURIComponent(STATION_WORKSPACE_ID)}}`);
  renderStationSnapshot(snapshot);
  return snapshot;
}}

async function pollStationEventStream() {{
  const payload = await apiJson(`/api/events/since?cursor=${{encodeURIComponent(stationEventCursor)}}&limit=40`);
  stationEventCursor = payload.next_cursor || stationEventCursor;
  const events = Array.isArray(payload.events) ? payload.events : [];
  const relevant = events.some((event) => event.type === "field-station.updated" && event.payload?.workspace_id === STATION_WORKSPACE_ID);
  if (relevant) {{
    await refreshStationSnapshot();
  }}
}}

async function queueMagicButtonJob() {{
  const goal = captureText();
  setStationState("thinking", "Queueing");
  const expectedOutput = EXPECTED_OUTPUT_BY_MODE[selectedMode] || "artifact";
  const capture = await saveStationCapture("magic_button", {{
    trigger: "onscreen_go",
    station_state: stationState,
  }});
  const missionPayload = await apiJson("/api/field-station/missions", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      source: "field_station_preview",
      mode: selectedMode,
      goal,
      capture_id: capture.id,
      permission_lane: "read-only",
      expected_output: expectedOutput,
    }}),
  }});
  await apiJson("/api/field-station/jobs", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      mission_id: missionPayload.mission.id,
      provider: "codex",
    }}),
  }});
  setStationState("queued", "Job queued");
  await refreshStationSnapshot();
}}

function normalizeRealtimeMode(mode) {{
  const clean = String(mode || "").trim();
  return EXPECTED_OUTPUT_BY_MODE[clean] ? clean : selectedMode;
}}

function normalizeRealtimeExpectedOutput(output, mode) {{
  const clean = String(output || "").trim();
  const allowed = new Set([...Object.values(EXPECTED_OUTPUT_BY_MODE), "artifact"]);
  return allowed.has(clean) ? clean : (EXPECTED_OUTPUT_BY_MODE[mode] || "artifact");
}}

function readableOutputName(output) {{
  return String(output || "artifact").replace(/_/g, " ");
}}

function parseRealtimeToolArguments(rawArgs) {{
  if (!rawArgs) return {{}};
  if (typeof rawArgs === "object") return rawArgs;
  try {{
    const parsed = JSON.parse(String(rawArgs));
    return parsed && typeof parsed === "object" ? parsed : {{}};
  }} catch (_) {{
    return {{}};
  }}
}}

async function queueRealtimeAlcoveJob(args = {{}}) {{
  const mode = normalizeRealtimeMode(args.mode);
  const goal = String(args.goal || captureText()).trim();
  if (!goal) throw new Error("Realtime task did not include a goal.");
  const expectedOutput = normalizeRealtimeExpectedOutput(args.expected_output, mode);
  selectedMode = mode;
  document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("is-active", item.dataset.mode === selectedMode));
  syncModeUi();
  setStationState("thinking", "Queueing job");
  setCaptureStatus("Queuing that as a background Alcove job.");
  const capturePayload = await apiJson("/api/field-station/captures", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      mode,
      source: "realtime_voice",
      text: goal,
      attachments: currentAttachments,
      metadata: {{
        trigger: "realtime_tool",
        expected_output: expectedOutput,
        attachment_count: currentAttachments.length,
        summary: String(args.summary || "").trim(),
        voice_state: voiceSession.state,
        voice_transcript: voiceSession.lastTranscript || "",
        realtime_assistant_transcript: voiceSession.lastAssistantTranscript || "",
      }},
    }}),
  }});
  lastCapture = capturePayload.capture;
  const missionPayload = await apiJson("/api/field-station/missions", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      source: "realtime_voice_assistant",
      mode,
      goal,
      capture_id: capturePayload.capture.id,
      permission_lane: "read-only",
      expected_output: expectedOutput,
    }}),
  }});
  const jobPayload = await apiJson("/api/field-station/jobs", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      mission_id: missionPayload.mission.id,
      provider: "codex",
    }}),
  }});
  await refreshStationSnapshot();
  setStationState(realtimeSession.active ? "listening" : "queued", realtimeSession.active ? "Voice live" : "Job queued");
  setCaptureStatus(`Queued ${{readableOutputName(expectedOutput)}} while Alcove stays live.`);
  return {{
    ok: true,
    capture_id: capturePayload.capture.id,
    mission_id: missionPayload.mission.id,
    job_id: jobPayload.job.id,
    mode,
    expected_output: expectedOutput,
  }};
}}

function nextRealtimeConnectionId() {{
  return Number(realtimeSession.connectionId || 0) + 1;
}}

function isRealtimeConnectionCurrent(connectionId) {{
  return realtimeSession.connectionId === connectionId && realtimeSession.connecting;
}}

function stopMediaStream(stream) {{
  try {{ stream?.getTracks?.().forEach((track) => track.stop()); }} catch (_) {{}}
}}

function cleanupRealtimePieces({{ peerConnection = null, dataChannel = null, mediaStream = null, audioElement = null }} = {{}}) {{
  try {{ dataChannel?.close(); }} catch (_) {{}}
  try {{ peerConnection?.close(); }} catch (_) {{}}
  stopMediaStream(mediaStream);
  try {{ audioElement?.remove(); }} catch (_) {{}}
}}

function withTimeout(promise, timeoutMs, timeoutMessage, onTimeout) {{
  let timer = null;
  return new Promise((resolve, reject) => {{
    timer = window.setTimeout(() => {{
      try {{ onTimeout?.(); }} catch (_) {{}}
      reject(new Error(timeoutMessage));
    }}, timeoutMs);
    promise.then(
      (value) => {{
        window.clearTimeout(timer);
        resolve(value);
      }},
      (error) => {{
        window.clearTimeout(timer);
        reject(error);
      }},
    );
  }});
}}

function waitForDataChannelOpen(dataChannel, timeoutMs = 8000) {{
  if (dataChannel.readyState === "open") return Promise.resolve();
  return withTimeout(new Promise((resolve, reject) => {{
    const cleanup = () => {{
      dataChannel.removeEventListener("open", onOpen);
      dataChannel.removeEventListener("error", onError);
      dataChannel.removeEventListener("close", onClose);
    }};
    const onOpen = () => {{
      cleanup();
      resolve();
    }};
    const onError = () => {{
      cleanup();
      reject(new Error("Realtime event channel could not open."));
    }};
    const onClose = () => {{
      cleanup();
      reject(new Error("Realtime event channel closed before Alcove woke up."));
    }};
    dataChannel.addEventListener("open", onOpen);
    dataChannel.addEventListener("error", onError);
    dataChannel.addEventListener("close", onClose);
  }}), timeoutMs, "Alcove did not finish waking up. Tap Wake Alcove to try again.");
}}

function realtimeToolCallKey(item) {{
  return String(item?.call_id || item?.callId || item?.id || `${{item?.name || "tool"}}:${{item?.arguments || ""}}`);
}}

function sendRealtimeFunctionOutput(callId, output) {{
  const channel = realtimeSession.dataChannel;
  if (!callId || !channel || channel.readyState !== "open") return false;
  channel.send(JSON.stringify({{
    type: "conversation.item.create",
    item: {{
      type: "function_call_output",
      call_id: callId,
      output: JSON.stringify(output),
    }},
  }}));
  channel.send(JSON.stringify({{ type: "response.create" }}));
  return true;
}}

async function handleRealtimeFunctionCall(item) {{
  if (!item || item.name !== "queue_alcove_job") return;
  const key = realtimeToolCallKey(item);
  if (realtimeSession.handledToolCalls?.has(key)) return;
  realtimeSession.handledToolCalls?.add(key);
  const callId = item.call_id || item.callId || item.id;
  let output;
  try {{
    output = await queueRealtimeAlcoveJob(parseRealtimeToolArguments(item.arguments));
  }} catch (error) {{
    output = {{ ok: false, error: error.message || "Could not queue Alcove job." }};
    setVoiceStatus("error", "Job queue failed", output.error);
    setStationState("error", "Queue failed");
  }}
  sendRealtimeFunctionOutput(callId, output);
}}

document.querySelectorAll("[data-mode]").forEach((button) => {{
  button.addEventListener("click", () => {{
    selectedMode = button.dataset.mode || "maker";
    document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("is-active", item === button));
    syncModeUi();
    setStationState("idle", `${{button.dataset.modeLabel || "Mode"}} mode`);
  }});
}});

document.getElementById("capture-button")?.addEventListener("click", () => {{
  queueMagicButtonJob().catch((error) => {{
    setStationState("error", error.message || "Queue failed");
  }});
}});

document.querySelectorAll("[data-physical-action]").forEach((button) => {{
  button.addEventListener("click", () => {{
    const action = button.dataset.physicalAction || "";
    if (action === "approve") {{
      if (selectedReview) {{
        approveSelectedReview().catch((error) => setStationState("error", error.message || "Approval failed"));
      }} else {{
        setStationState("needs-review", "Open a review first");
      }}
      return;
    }}
    if (action === "pause") {{
      setStationState("idle", "Paused");
      setCaptureStatus("Station paused. Capture is still manual and human-approved.");
      return;
    }}
    if (action === "reject") {{
      closeReviewDrawer();
      selectedReview = null;
      selectedArtifactContent = "";
      setStationState("idle", "Review closed");
    }}
  }});
}});

document.getElementById("review-tray")?.addEventListener("click", (event) => {{
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const openReviewId = target.dataset.openReviewId;
  const approveReviewId = target.dataset.approveReviewId;
  if (openReviewId) {{
    openReviewDrawer(openReviewId).catch((error) => setStationState("error", error.message || "Open failed"));
    return;
  }}
  if (!approveReviewId) return;
  const reviews = Array.isArray(lastSnapshot?.reviews) ? lastSnapshot.reviews : [];
  selectedReview = reviews.find((item) => item.id === approveReviewId) || null;
  approveSelectedReview().catch((error) => setStationState("error", error.message || "Approval failed"));
}});

document.getElementById("project-library")?.addEventListener("click", (event) => {{
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const captureId = target.dataset.useCaptureId;
  const openReviewId = target.dataset.openReviewId;
  if (captureId) {{
    const captures = Array.isArray(lastSnapshot?.captures) ? lastSnapshot.captures : [];
    const capture = captures.find((item) => item.id === captureId);
    const input = document.getElementById("mission-goal");
    if (capture && input) {{
      input.value = capture.text || "";
      currentAttachments = Array.isArray(capture.attachments) ? [...capture.attachments] : [];
      selectedMode = capture.mode || selectedMode;
      document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("is-active", item.dataset.mode === selectedMode));
      syncModeUi();
      renderCurrentAttachments();
      setCaptureStatus(`Loaded capture ${{capture.id}} into the composer.`);
      setStationState("idle", "Capture loaded");
    }}
    return;
  }}
  if (openReviewId) {{
    openReviewDrawer(openReviewId).catch((error) => setStationState("error", error.message || "Open failed"));
  }}
}});

document.getElementById("briefing-source-list")?.addEventListener("change", (event) => {{
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const sourceId = target.dataset.briefingSourceId;
  if (!sourceId) return;
  if (target.checked) selectedBriefingSourceIds.add(sourceId);
  else selectedBriefingSourceIds.delete(sourceId);
  const status = document.getElementById("owner-briefing-status");
  if (status) {{
    status.textContent = `${{selectedBriefingSourceIds.size}} source${{selectedBriefingSourceIds.size === 1 ? "" : "s"}} selected. Drafts and recommendations only.`;
  }}
}});

async function queueOwnerBriefing() {{
  const status = document.getElementById("owner-briefing-status");
  const note = document.getElementById("owner-briefing-note")?.value?.trim() || "";
  if (!selectedBriefingSourceIds.size) {{
    if (status) status.textContent = "Choose at least one read-only source.";
    setStationState("error", "No sources");
    return;
  }}
  setStationState("thinking", "Owner brief");
  if (status) status.textContent = "Preparing read-only owner brief.";
  const response = await apiJson("/api/field-station/owner-briefings", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      source_ids: [...selectedBriefingSourceIds],
      note,
      provider: "codex",
    }}),
  }});
  selectedMode = "business";
  document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("is-active", item.dataset.mode === selectedMode));
  syncModeUi();
  renderStationSnapshot(response.snapshot);
  if (status) status.textContent = "Owner brief queued for review.";
  setStationState("queued", "Owner brief queued");
}}

document.getElementById("owner-briefing-button")?.addEventListener("click", () => {{
  queueOwnerBriefing().catch((error) => {{
    const status = document.getElementById("owner-briefing-status");
    if (status) status.textContent = error.message || "Owner brief failed.";
    setStationState("error", error.message || "Owner brief failed");
  }});
}});

async function sendStationBridgeEvent(eventType, payload = {{}}) {{
  const bridgeStatus = document.getElementById("bridge-status");
  if (bridgeStatus) bridgeStatus.textContent = "Bridge event queued.";
  const response = await apiJson("/api/field-station/station-events", {{
    method: "POST",
    body: JSON.stringify({{
      workspace_id: STATION_WORKSPACE_ID,
      event_type: eventType,
      payload,
    }}),
  }});
  if (bridgeStatus) bridgeStatus.textContent = `${{eventType}} acknowledged.`;
  renderStationSnapshot(response.snapshot);
  return response;
}}

document.getElementById("bridge-button-test")?.addEventListener("click", () => {{
  sendStationBridgeEvent("button.capture", {{
    simulated: true,
    mode: selectedMode,
    text: captureText(),
    expected_output: EXPECTED_OUTPUT_BY_MODE[selectedMode] || "artifact",
    provider: "codex",
  }}).catch((error) => setStationState("error", error.message || "Bridge failed"));
}});

document.getElementById("bridge-print-test")?.addEventListener("click", () => {{
  sendStationBridgeEvent("printer.print", {{
    simulated: true,
    review_id: selectedReview?.id || null,
  }}).catch((error) => setStationState("error", error.message || "Printer bridge failed"));
}});

document.getElementById("capture-attachments")?.addEventListener("click", (event) => {{
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const removeIndex = target.dataset.removeAttachment;
  if (removeIndex === undefined) return;
  const index = Number(removeIndex);
  if (Number.isInteger(index)) {{
    currentAttachments.splice(index, 1);
    renderCurrentAttachments();
    setCaptureStatus("Image attachment removed.");
  }}
}});

document.getElementById("capture-image-input")?.addEventListener("change", async (event) => {{
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.files?.length) return;
  const file = input.files[0];
  if (!file.type.startsWith("image/")) {{
    setCaptureStatus("Choose an image file for this capture.");
    return;
  }}
  try {{
    setStationState("thinking", "Adding image");
    const dataUrl = await dataUrlFromFile(file);
    await uploadCaptureAsset(dataUrl, file.name || "uploaded image", "upload", {{
      file_type: file.type,
      file_size: file.size,
    }});
    setStationState("idle", "Image attached");
  }} catch (error) {{
    setStationState("error", "Image failed");
    setCaptureStatus(error.message || "Could not attach image.");
  }} finally {{
    input.value = "";
  }}
}});

document.getElementById("clear-attachments")?.addEventListener("click", () => {{
  currentAttachments = [];
  renderCurrentAttachments();
  setCaptureStatus("Image attachments cleared.");
}});

async function startCameraCapture() {{
  const panel = document.getElementById("camera-panel");
  const video = document.getElementById("camera-preview");
  const cameraButton = document.getElementById("camera-button");
  const cameraStatus = document.getElementById("camera-status");
  if (!(video instanceof HTMLVideoElement)) return;
  if (!navigator.mediaDevices?.getUserMedia) {{
    if (cameraStatus) cameraStatus.textContent = "Camera capture is not available in this browser.";
    setStationState("error", "No camera API");
    return;
  }}
  try {{
    setStationState("listening", "Camera");
    if (cameraStatus) cameraStatus.textContent = "Requesting camera...";
    cameraStream = await navigator.mediaDevices.getUserMedia({{ video: true, audio: false }});
    video.srcObject = cameraStream;
    panel?.classList.add("is-open");
    cameraButton?.classList.add("is-active");
    if (cameraStatus) cameraStatus.textContent = "Camera ready. Take a snapshot when the desk is framed.";
    setStationState("idle", "Camera ready");
  }} catch (error) {{
    if (cameraStatus) cameraStatus.textContent = error.message || "Camera permission was blocked.";
    setStationState("error", "Camera blocked");
  }}
}}

function stopCameraCapture() {{
  const panel = document.getElementById("camera-panel");
  const video = document.getElementById("camera-preview");
  const cameraButton = document.getElementById("camera-button");
  const cameraStatus = document.getElementById("camera-status");
  if (cameraStream) {{
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }}
  if (video instanceof HTMLVideoElement) video.srcObject = null;
  panel?.classList.remove("is-open");
  cameraButton?.classList.remove("is-active");
  if (cameraStatus) cameraStatus.textContent = "Camera is off.";
}}

async function takeCameraSnapshot() {{
  const video = document.getElementById("camera-preview");
  const cameraStatus = document.getElementById("camera-status");
  if (!(video instanceof HTMLVideoElement) || !cameraStream) {{
    if (cameraStatus) cameraStatus.textContent = "Start the camera before taking a snapshot.";
    return;
  }}
  const width = video.videoWidth || 960;
  const height = video.videoHeight || 720;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.drawImage(video, 0, 0, width, height);
  const dataUrl = canvas.toDataURL("image/png");
  try {{
    setStationState("thinking", "Saving snapshot");
    await uploadCaptureAsset(dataUrl, `camera-snapshot-${{Date.now()}}.png`, "camera", {{
      width,
      height,
    }});
    if (cameraStatus) cameraStatus.textContent = "Snapshot attached to the capture composer.";
    setStationState("idle", "Snapshot ready");
  }} catch (error) {{
    if (cameraStatus) cameraStatus.textContent = error.message || "Could not save snapshot.";
    setStationState("error", "Snapshot failed");
  }}
}}

document.getElementById("camera-button")?.addEventListener("click", () => {{
  if (cameraStream) {{
    stopCameraCapture();
    return;
  }}
  startCameraCapture();
}});
document.getElementById("camera-stop")?.addEventListener("click", stopCameraCapture);
document.getElementById("camera-snapshot")?.addEventListener("click", () => {{
  takeCameraSnapshot().catch((error) => setStationState("error", error.message || "Snapshot failed"));
}});

document.getElementById("drawer-close")?.addEventListener("click", closeReviewDrawer);
document.getElementById("drawer-approve")?.addEventListener("click", () => {{
  approveSelectedReview().catch((error) => setStationState("error", error.message || "Approval failed"));
}});
document.getElementById("drawer-revise")?.addEventListener("click", () => {{
  queueDerivedJob("revise").catch((error) => setStationState("error", error.message || "Revision failed"));
}});
document.getElementById("drawer-follow-up")?.addEventListener("click", () => {{
  queueDerivedJob("follow-up").catch((error) => setStationState("error", error.message || "Follow-up failed"));
}});
document.getElementById("drawer-print")?.addEventListener("click", () => {{
  window.print();
}});

function setupVoiceCapture() {{
  const voiceButton = document.getElementById("voice-button");
  const missionInput = document.getElementById("mission-goal");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!voiceButton || !missionInput) return;
  let recognition = SpeechRecognition ? new SpeechRecognition() : null;
  let startValue = "";
  let active = false;
  let heardTranscript = "";

  voiceButton.addEventListener("click", async () => {{
    if (realtimeSession.active || realtimeSession.connecting) {{
      stopRealtimeVoiceSession(realtimeSession.connecting ? "Wake-up canceled. Alcove is asleep." : "Alcove is asleep.");
      return;
    }}
    if (active) {{
      recognition?.stop();
      return;
    }}
    if (stationServerInfo?.realtime_voice_available) {{
      await startRealtimeVoiceSession(missionInput);
      return;
    }}
    if (stationServerInfo?.native_transcription_available) {{
      const handled = await startNativeStationVoiceCapture(missionInput);
      if (handled) return;
    }}
    if (!recognition) {{
      setVoiceStatus("unsupported", "Speech unsupported", stationServerInfo?.realtime_voice_reason || "No realtime, native, or browser speech capture is available.");
      setStationState("error", "No mic path");
      return;
    }}
    startValue = missionInput.value.trim();
    heardTranscript = "";
    try {{
      recognition.start();
    }} catch (error) {{
      setVoiceStatus("error", "Mic did not start", error.message || "Speech recognition could not start.");
      setStationState("error", "Mic start failed");
    }}
  }});

  if (!recognition) {{
    setVoiceStatus("ready", "Mic setup", "Checking for realtime or native voice support.");
    return;
  }}

  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";
  recognition.onstart = () => {{
    active = true;
    voiceButton.classList.add("is-listening");
    setPresenceButton("ALCOVE AWAKE", "Listening now. Tap to sleep.");
    setVoiceStatus("listening", "Listening", "Say the messy idea, then pause.");
    setStationState("listening", "Listening");
  }};
  recognition.onresult = (event) => {{
    const transcript = Array.from(event.results)
      .map((result) => result[0]?.transcript || "")
      .join(" ")
      .trim();
    if (transcript) {{
      heardTranscript = transcript;
      voiceSession.lastTranscript = transcript;
      missionInput.value = [startValue, transcript].filter(Boolean).join("\\n");
      setVoiceStatus("heard", "Heard speech", `Heard: "${{compactText(transcript, 80)}}"`);
    }}
  }};
  recognition.onerror = (event) => {{
    const error = event.error || "mic-error";
    const label = voiceErrorLabel(error);
    const state = error === "not-allowed" || error === "service-not-allowed" ? "blocked" : (error === "no-speech" ? "no-speech" : "error");
    setVoiceStatus(state, label, voiceErrorDetail(error));
    if (state !== "no-speech") setStationState("error", label);
  }};
  recognition.onend = () => {{
    active = false;
    voiceButton.classList.remove("is-listening");
    setPresenceButton();
    if (!heardTranscript && stationState === "listening") {{
      setVoiceStatus("no-speech", "No speech detected", "The mic session ended without a transcript.");
    }}
    if (heardTranscript) {{
      setVoiceStatus("heard", "Transcript ready", `Captured: "${{compactText(heardTranscript, 80)}}"`);
      setCaptureStatus("Voice transcript is in the capture composer.");
    }}
    if (stationState === "listening") {{
      setStationState("idle", "Ready");
    }}
  }};
}}

async function startRealtimeVoiceSession(missionInput) {{
  const voiceButton = document.getElementById("voice-button");
  if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {{
    setVoiceStatus("unsupported", "Realtime unavailable", "This browser does not expose the WebRTC microphone APIs Alcove needs.");
    setStationState("error", "No WebRTC");
    return;
  }}
  const connectionId = nextRealtimeConnectionId();
  realtimeSession.connecting = true;
  realtimeSession.active = false;
  realtimeSession.connectionId = connectionId;
  realtimeSession.composerStartValue = missionInput.value.trim();
  realtimeSession.handledToolCalls = new Set();
  if (voiceButton) {{
    voiceButton.disabled = false;
    setPresenceButton("WAKING UP", "Tap to cancel.");
  }}
  setVoiceStatus("connecting", "Waking up", "Opening Alcove's live voice link.");
  setStationState("thinking", "Voice link");
  let peerConnection = null;
  let dataChannel = null;
  let mediaStream = null;
  let audioElement = null;
  let sdpController = null;
  try {{
    const sessionPayload = await apiJson("/api/field-station/realtime-client-secret", {{
      method: "POST",
      body: JSON.stringify({{
        workspace_id: STATION_WORKSPACE_ID,
        mode: selectedMode,
        current_text: captureText(),
      }}),
    }});
    if (!isRealtimeConnectionCurrent(connectionId)) return;
    const clientSecret = String(sessionPayload.client_secret?.value || sessionPayload.value || "").trim();
    if (!clientSecret) throw new Error("Realtime client secret did not include a token.");
    const callsUrl = sessionPayload.calls_url || stationServerInfo?.realtime_voice_calls_url || "https://api.openai.com/v1/realtime/calls";
    const mediaStreamPromise = navigator.mediaDevices.getUserMedia({{ audio: true, video: false }});
    mediaStreamPromise.then((stream) => {{
      if (!isRealtimeConnectionCurrent(connectionId) && realtimeSession.mediaStream !== stream) {{
        stopMediaStream(stream);
      }}
    }}).catch(() => {{}});
    mediaStream = await withTimeout(
      mediaStreamPromise,
      15000,
      "Mic permission did not finish. Check the browser prompt, then tap Wake Alcove again.",
    );
    if (!isRealtimeConnectionCurrent(connectionId)) {{
      stopMediaStream(mediaStream);
      return;
    }}
    peerConnection = new RTCPeerConnection();
    audioElement = document.createElement("audio");
    audioElement.autoplay = true;
    audioElement.hidden = true;
    audioElement.setAttribute("aria-hidden", "true");
    document.body.appendChild(audioElement);
    peerConnection.ontrack = (event) => {{
      audioElement.srcObject = event.streams[0];
    }};
    mediaStream.getAudioTracks().forEach((track) => peerConnection.addTrack(track, mediaStream));
    dataChannel = peerConnection.createDataChannel("oai-events");
    dataChannel.addEventListener("open", () => {{
      if (realtimeSession.active) {{
        setVoiceStatus("realtime", "Alcove awake", "Voice is on. Tap to sleep.");
        setStationState("listening", "Voice on");
      }}
    }});
    dataChannel.addEventListener("message", handleRealtimeEvent);
    dataChannel.addEventListener("close", () => {{
      if (realtimeSession.active) stopRealtimeVoiceSession("Realtime voice ended.");
    }});
    peerConnection.onconnectionstatechange = () => {{
      const state = peerConnection.connectionState;
      if (["failed", "disconnected"].includes(state)) {{
        stopRealtimeVoiceSession(`Realtime connection ${{state}}.`);
      }}
    }};
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    if (!isRealtimeConnectionCurrent(connectionId)) {{
      cleanupRealtimePieces({{ peerConnection, dataChannel, mediaStream, audioElement }});
      return;
    }}
    sdpController = new AbortController();
    const sdpResponse = await withTimeout(
      fetch(callsUrl, {{
        method: "POST",
        body: offer.sdp,
        signal: sdpController.signal,
        headers: {{
          "Authorization": `Bearer ${{clientSecret}}`,
          "Content-Type": "application/sdp",
        }},
      }}),
      18000,
      "Alcove could not reach the live voice service. Tap Wake Alcove to try again.",
      () => sdpController?.abort(),
    );
    if (!sdpResponse.ok) {{
      const detail = await sdpResponse.text().catch(() => "");
      throw new Error(detail || `Realtime WebRTC handshake failed with HTTP ${{sdpResponse.status}}.`);
    }}
    const answerSdp = await sdpResponse.text();
    if (!isRealtimeConnectionCurrent(connectionId)) {{
      cleanupRealtimePieces({{ peerConnection, dataChannel, mediaStream, audioElement }});
      return;
    }}
    await peerConnection.setRemoteDescription({{ type: "answer", sdp: answerSdp }});
    await waitForDataChannelOpen(dataChannel);
    if (!isRealtimeConnectionCurrent(connectionId)) {{
      cleanupRealtimePieces({{ peerConnection, dataChannel, mediaStream, audioElement }});
      return;
    }}
    realtimeSession.active = true;
    realtimeSession.connecting = false;
    realtimeSession.peerConnection = peerConnection;
    realtimeSession.dataChannel = dataChannel;
    realtimeSession.mediaStream = mediaStream;
    realtimeSession.audioElement = audioElement;
    if (voiceButton) {{
      voiceButton.disabled = false;
      setPresenceButton("ALCOVE AWAKE", "Voice on. Tap to sleep.");
    }}
    setVoiceStatus("realtime", "Alcove awake", `Voice is on with ${{sessionPayload.model || "Realtime"}}.`);
    setStationState("listening", "Voice on");
  }} catch (error) {{
    cleanupRealtimePieces({{ peerConnection, dataChannel, mediaStream, audioElement }});
    if (!isRealtimeConnectionCurrent(connectionId)) return;
    cleanupRealtimeVoiceSession();
    if (voiceButton) {{
      voiceButton.disabled = false;
      setPresenceButton();
    }}
    setVoiceStatus("error", "Voice link failed", error.message || "Could not start realtime voice.");
    setStationState("error", "Voice failed");
  }}
}}

function handleRealtimeEvent(messageEvent) {{
  let event = null;
  try {{
    event = JSON.parse(messageEvent.data);
  }} catch (_) {{
    return;
  }}
  const type = String(event?.type || "");
  if (type === "input_audio_buffer.speech_started") {{
    setVoiceStatus("realtime", "Listening", "I hear you.");
    setStationState("listening", "Listening");
    return;
  }}
  if (type === "input_audio_buffer.speech_stopped") {{
    setVoiceStatus("realtime", "Thinking", "Alcove is thinking.");
    setStationState("thinking", "Thinking");
    return;
  }}
  if (type === "conversation.item.input_audio_transcription.completed") {{
    appendRealtimeTranscriptToComposer(event.transcript || "");
    return;
  }}
  if (type === "response.output_audio_transcript.done" || type === "response.audio_transcript.done") {{
    voiceSession.lastAssistantTranscript = String(event.transcript || "").trim();
    if (voiceSession.lastAssistantTranscript) {{
      setCaptureStatus(`Alcove said: "${{compactText(voiceSession.lastAssistantTranscript, 90)}}"`);
    }}
    return;
  }}
  if (type === "response.output_text.done") {{
    voiceSession.lastAssistantTranscript = String(event.text || "").trim();
    if (voiceSession.lastAssistantTranscript) {{
      setCaptureStatus(`Alcove said: "${{compactText(voiceSession.lastAssistantTranscript, 90)}}"`);
    }}
    return;
  }}
  if (type === "response.function_call_arguments.done" && event.name === "queue_alcove_job") {{
    handleRealtimeFunctionCall({{
      id: event.item_id,
      call_id: event.call_id,
      name: event.name,
      arguments: event.arguments,
    }}).catch((error) => {{
      setVoiceStatus("error", "Job queue failed", error.message || "Could not queue Alcove job.");
      setStationState("error", "Queue failed");
    }});
    return;
  }}
  if (type === "response.done") {{
    const outputItems = Array.isArray(event.response?.output) ? event.response.output : [];
    const functionCalls = outputItems.filter((item) => item?.type === "function_call" && item?.name === "queue_alcove_job");
    if (functionCalls.length) {{
      functionCalls.forEach((item) => {{
        handleRealtimeFunctionCall(item).catch((error) => {{
          setVoiceStatus("error", "Job queue failed", error.message || "Could not queue Alcove job.");
          setStationState("error", "Queue failed");
        }});
      }});
      return;
    }}
    setVoiceStatus("realtime", "Alcove awake", "Ready for the next thing.");
    setStationState("listening", "Voice on");
    return;
  }}
  if (type === "error") {{
    const detail = event.error?.message || "Realtime voice returned an error.";
    setVoiceStatus("error", "Realtime error", detail);
    setStationState("error", "Voice error");
  }}
}}

function appendRealtimeTranscriptToComposer(transcript) {{
  const missionInput = document.getElementById("mission-goal");
  const text = String(transcript || "").trim();
  if (!missionInput || !text) return;
  const current = missionInput.value.trim();
  if (!current) {{
    missionInput.value = text;
  }} else if (!current.endsWith(text)) {{
    missionInput.value = [current, text].filter(Boolean).join("\\n");
  }}
  voiceSession.lastTranscript = text;
  setCaptureStatus(`Captured voice: "${{compactText(text, 90)}}"`);
}}

function stopRealtimeVoiceSession(detail = "Realtime voice stopped.") {{
  const voiceButton = document.getElementById("voice-button");
  cleanupRealtimeVoiceSession();
  if (voiceButton) {{
    voiceButton.disabled = false;
    setPresenceButton();
  }}
  const hasTranscript = Boolean(voiceSession.lastTranscript);
  setVoiceStatus(hasTranscript ? "heard" : "ready", hasTranscript ? "Voice captured" : "Mic ready", detail);
  if (stationState === "listening" || stationState === "thinking") {{
    setStationState("idle", "Ready");
  }}
}}

function cleanupRealtimeVoiceSession() {{
  const session = realtimeSession;
  const connectionId = Number(session.connectionId || 0) + 1;
  realtimeSession = {{
    active: false,
    connecting: false,
    connectionId,
    peerConnection: null,
    dataChannel: null,
    mediaStream: null,
    audioElement: null,
    composerStartValue: "",
    handledToolCalls: new Set(),
  }};
  cleanupRealtimePieces(session);
}}

function voiceErrorLabel(error) {{
  if (error === "not-allowed" || error === "service-not-allowed") return "Mic blocked";
  if (error === "no-speech") return "No speech detected";
  if (error === "audio-capture") return "No microphone";
  if (error === "network") return "Speech service unavailable";
  return "Mic error";
}}

function voiceErrorDetail(error) {{
  if (error === "not-allowed" || error === "service-not-allowed") return "Microphone permission was blocked or unavailable.";
  if (error === "no-speech") return "Alcove listened, but no transcript came back.";
  if (error === "audio-capture") return "The browser could not find a usable microphone.";
  if (error === "network") return "The browser speech service could not be reached.";
  return `Speech recognition ended with: ${{error}}.`;
}}

async function startNativeStationVoiceCapture(missionInput) {{
  setVoiceStatus("listening", "Native mic", "Recording through the local Alcove wrapper.");
  setStationState("listening", "Listening");
  try {{
    const payload = await apiJson("/api/native/transcribe", {{
      method: "POST",
      body: JSON.stringify({{ locale: "en-US" }}),
    }});
    const transcript = String(payload.transcript || "").trim();
    if (!transcript) {{
      setVoiceStatus("no-speech", "No speech detected", "Native transcription returned no words.");
      return true;
    }}
    const startValue = missionInput.value.trim();
    missionInput.value = [startValue, transcript].filter(Boolean).join("\\n");
    voiceSession.lastTranscript = transcript;
    setVoiceStatus("heard", "Transcript ready", `Captured: "${{compactText(transcript, 80)}}"`);
    setCaptureStatus("Voice transcript is in the capture composer.");
    setStationState("idle", "Ready");
    return true;
  }} catch (error) {{
    const status = Number(error?.status || 0);
    if (status === 404 || status === 409) {{
      return false;
    }}
    setVoiceStatus("error", "Native mic error", error.message || "Native transcription failed.");
    setStationState("error", "Mic error");
    return true;
  }}
}}

async function loadStationServerInfo() {{
  try {{
    stationServerInfo = await apiJson("/api/connections");
    const voiceButton = document.getElementById("voice-button");
    if (stationServerInfo.realtime_voice_available) {{
      if (voiceButton) {{
        voiceButton.disabled = false;
        setPresenceButton("WAKE ALCOVE", "Realtime voice ready.");
      }}
      setVoiceStatus("ready", "Realtime voice ready", `OpenAI ${{stationServerInfo.realtime_voice_model || "Realtime"}} is ready.`);
    }} else if (stationServerInfo.native_transcription_available) {{
      if (voiceButton) {{
        voiceButton.disabled = false;
        setPresenceButton("WAKE ALCOVE", "Native voice ready.");
      }}
      setVoiceStatus("ready", "Native mic ready", "Local transcription is available.");
    }} else if (window.SpeechRecognition || window.webkitSpeechRecognition) {{
      if (voiceButton) voiceButton.disabled = false;
      setVoiceStatus("ready", "Browser mic ready", "Browser speech recognition is available.");
    }} else {{
      if (voiceButton) {{
        voiceButton.disabled = true;
        setPresenceButton("VOICE UNAVAILABLE", "Check mic or API setup.");
      }}
      setVoiceStatus("unsupported", "Voice unavailable", stationServerInfo.realtime_voice_reason || "No voice capture path is available.");
    }}
  }} catch (_) {{
    stationServerInfo = null;
  }}
}}

function setupEyeTracking() {{
  const face = document.getElementById("station-face");
  if (!face) return;
  root.addEventListener("pointermove", (event) => {{
    const rect = face.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const x = Math.max(-12, Math.min(12, ((event.clientX - centerX) / rect.width) * 24));
    const y = Math.max(-9, Math.min(9, ((event.clientY - centerY) / rect.height) * 18));
    face.style.setProperty("--eye-x", x.toFixed(1) + "px");
    face.style.setProperty("--eye-y", y.toFixed(1) + "px");
  }});
  root.addEventListener("pointerleave", () => {{
    face.style.setProperty("--eye-x", "0px");
    face.style.setProperty("--eye-y", "0px");
  }});
}}

setupVoiceCapture();
setupEyeTracking();

loadStationServerInfo().catch(() => {{}});
refreshStationSnapshot().catch(() => {{
  setStationState("error", "Station API unavailable");
}});
window.setInterval(() => {{
  pollStationEventStream().catch(() => {{}});
}}, 1000);
window.setInterval(() => {{
  refreshStationSnapshot().catch(() => {{}});
}}, 5000);
"""


def _template_game_js(title: str, kind: str, theme_prompt: str | None) -> str:
    title_text = _js_text(title)
    theme_default = (
        "A moonlit city runner where a detective leaps over street hazards and gathers clues."
        if kind == "runner"
        else "Bright, playful, and easy to understand."
    )
    theme_text = _js_text(theme_prompt or theme_default)
    score_label = "Clues" if kind == "runner" else "Stars"
    common = f"""const GAME_TITLE = "{title_text}";
const GAME_THEME = "{theme_text}";
const SCORE_LABEL = "{score_label}";
const statusEl = document.getElementById("status");
const width = 960;
const height = 540;

const config = {{
  type: Phaser.AUTO,
  width,
  height,
  parent: "studio-root",
  backgroundColor: "#13241d",
  physics: {{
    default: "arcade",
    arcade: {{ gravity: {{ y: 900 }}, debug: false }},
  }},
  scene: {{ preload, create, update }},
}};

const game = new Phaser.Game(config);
let cursors;
let player;
let score = 0;
let scoreText;
let helpers = {{}};

function preload() {{
  const g = this.add.graphics();
  g.fillStyle(0x9ad58b, 1);
  g.fillRoundedRect(0, 0, 36, 36, 12);
  g.generateTexture("hero", 36, 36);
  g.clear();
  g.fillStyle(0x5f7695, 1);
  g.fillRoundedRect(0, 0, 34, 42, 10);
  g.generateTexture("detective", 34, 42);
  g.clear();
  g.fillStyle(0xf6d66f, 1);
  g.fillCircle(14, 14, 14);
  g.generateTexture("coin", 28, 28);
  g.clear();
  g.fillStyle(0xf4c86b, 1);
  g.fillCircle(18, 18, 18);
  g.fillStyle(0x213749, 1);
  g.fillRect(22, 24, 16, 6);
  g.generateTexture("clue", 42, 42);
  g.clear();
  g.fillStyle(0x7bc8f6, 1);
  g.fillRoundedRect(0, 0, 120, 28, 10);
  g.generateTexture("platform", 120, 28);
  g.clear();
  g.fillStyle(0xc9704c, 1);
  g.fillRoundedRect(0, 0, 42, 56, 8);
  g.generateTexture("obstacle", 42, 56);
  g.destroy();
}}

function paintSky(scene) {{
  scene.add.rectangle(width / 2, height / 2, width, height, 0x1d3b31).setDepth(-5);
  scene.add.circle(820, 90, 62, 0xf4f0c6, 0.16);
  scene.add.circle(160, 110, 42, 0x9dd4ff, 0.16);
}}

function addScore(scene, amount) {{
  score += amount;
  if (scoreText) scoreText.setText(`${{SCORE_LABEL}}: ${{score}}`);
  if (statusEl) statusEl.textContent = score > 0 ? `Ready to Play · ${{SCORE_LABEL}}: ${{score}}` : "Ready to Play";
}}

function createLabel(scene, text, x, y, size = "28px") {{
  return scene.add.text(x, y, text, {{
    fontFamily: "Avenir Next, Trebuchet MS, sans-serif",
    fontSize: size,
    color: "#f6f4e8",
  }});
}}
"""
    if kind == "runner":
        return common + """
let hazards;
let clues;
let jumpKey;
let gameOver = false;
const runnerSpeed = 280;

function paintRunnerCity(scene) {
  scene.add.rectangle(width / 2, height / 2, width, height, 0x9dc1e6).setDepth(-8);
  scene.add.rectangle(width / 2, height * 0.72, width, height * 0.34, 0x7ea5cf).setDepth(-7);
  scene.add.circle(790, 102, 48, 0xf7e18c, 0.9).setDepth(-7);
  const skyline = [
    [50, 390, 96, 170],
    [164, 410, 118, 150],
    [304, 380, 92, 180],
    [418, 404, 110, 156],
    [564, 372, 126, 188],
    [714, 398, 102, 162],
    [838, 384, 118, 176],
  ];
  skyline.forEach(([x, y, w, h]) => {
    scene.add.rectangle(x, y, w, h, 0x243246).setOrigin(0, 0).setDepth(-6);
    for (let row = 0; row < 4; row += 1) {
      for (let col = 0; col < 3; col += 1) {
        scene.add.rectangle(x + 18 + col * 22, y + 24 + row * 28, 8, 12, 0xf2d87c, 0.55).setDepth(-5);
      }
    }
  });
  scene.add.rectangle(width / 2, height - 84, width, 122, 0x6f6351).setDepth(-4);
  scene.add.rectangle(width / 2, height - 62, width, 14, 0xd9c59a).setDepth(-3);
  scene.add.rectangle(width / 2, height - 16, width, 18, 0x564a38).setDepth(-2);
}

function resetRunner(scene) {
  score = 0;
  gameOver = false;
  hazards.clear(true, true);
  clues.clear(true, true);
  player.setPosition(150, height - 104);
  player.setVelocity(0, 0);
  if (scoreText) scoreText.setText(`${SCORE_LABEL}: 0`);
  if (statusEl) statusEl.textContent = "Ready to Play";
}

function spawnRunnerBeat(scene) {
  if (gameOver) return;
  const obstacle = hazards.create(width + Phaser.Math.Between(40, 150), height - 90, "obstacle");
  obstacle.body.setAllowGravity(false);
  obstacle.setVelocityX(-runnerSpeed);
  if (Phaser.Math.Between(0, 100) > 18) {
    const clue = clues.create(width + Phaser.Math.Between(140, 230), Phaser.Math.Between(height - 210, height - 160), "clue");
    clue.body.setAllowGravity(false);
    clue.setVelocityX(-runnerSpeed);
  }
}

function create() {
  paintRunnerCity(this);
  const ground = this.physics.add.staticGroup();
  ground.create(width / 2, height - 24, "platform").setScale(10, 1.3).refreshBody();
  createLabel(this, GAME_TITLE, 30, 28);
  createLabel(this, GAME_THEME, 30, 68, "18px").setAlpha(0.82);
  scoreText = createLabel(this, `${SCORE_LABEL}: 0`, 30, 108, "22px");
  this.add.text(30, 145, "Up or space to jump. Collect clues and dodge the street hazards.", {
    fontFamily: "Avenir Next, Trebuchet MS, sans-serif",
    fontSize: "20px",
    color: "#f6f4e8",
  });
  player = this.physics.add.image(150, height - 104, "detective").setScale(1.2);
  player.setCollideWorldBounds(true);
  player.setBounce(0);
  this.physics.add.collider(player, ground);
  hazards = this.physics.add.group({ allowGravity: false, immovable: true });
  clues = this.physics.add.group({ allowGravity: false, immovable: true });
  this.physics.add.overlap(player, clues, (_, clue) => {
    clue.destroy();
    addScore(this, 1);
  });
  this.physics.add.overlap(player, hazards, () => {
    if (gameOver) return;
    gameOver = true;
    if (statusEl) statusEl.textContent = "Case Interrupted";
    this.cameras.main.flash(160, 255, 244, 228);
    this.time.delayedCall(700, () => resetRunner(this));
  });
  cursors = this.input.keyboard.createCursorKeys();
  jumpKey = this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.SPACE);
  this.time.addEvent({
    delay: 980,
    loop: true,
    callback: () => spawnRunnerBeat(this),
  });
  if (statusEl) statusEl.textContent = "Ready to Play";
}

function update() {
  if (!player || !cursors) return;
  const grounded = Boolean(player.body?.blocked?.down || player.body?.touching?.down);
  if (!gameOver && grounded && (Phaser.Input.Keyboard.JustDown(cursors.up) || Phaser.Input.Keyboard.JustDown(jumpKey))) {
    player.setVelocityY(-560);
  }
  for (const item of hazards.getChildren()) {
    if (item.x < -80) item.destroy();
  }
  for (const item of clues.getChildren()) {
    if (item.x < -80) item.destroy();
  }
}
"""
    if kind == "clicker":
        return common + """
function create() {
  paintSky(this);
  createLabel(this, GAME_TITLE, 30, 28);
  createLabel(this, GAME_THEME, 30, 68, "18px").setAlpha(0.82);
  scoreText = createLabel(this, "Stars: 0", 30, 110, "22px");
  const orb = this.add.image(width / 2, height / 2, "coin").setScale(4.2);
  const pulse = this.tweens.add({
    targets: orb,
    scale: 4.45,
    duration: 700,
    yoyo: true,
    repeat: -1,
  });
  helpers.orb = orb;
  helpers.pulse = pulse;
  orb.setInteractive({ useHandCursor: true });
  orb.on("pointerdown", () => {
    addScore(this, 1);
    this.tweens.add({ targets: orb, angle: orb.angle + 12, duration: 100, yoyo: true });
  });
  this.add.text(width / 2 - 150, height - 70, "Tap the star to grow your score.", {
    fontFamily: "Avenir Next, Trebuchet MS, sans-serif",
    fontSize: "22px",
    color: "#f6f4e8",
  });
  if (statusEl) statusEl.textContent = "Ready to Play";
}

function update() {}
"""
    if kind == "top-down":
        return common + """
function create() {
  paintSky(this);
  createLabel(this, GAME_TITLE, 30, 28);
  createLabel(this, GAME_THEME, 30, 68, "18px").setAlpha(0.82);
  this.add.rectangle(width / 2, height / 2, 720, 360, 0x19352b, 0.88).setStrokeStyle(4, 0x8ccca6, 0.3);
  helpers.coins = this.physics.add.staticGroup();
  scoreText = createLabel(this, "Stars: 0", 30, 108, "22px");
  player = this.physics.add.image(width / 2, height / 2, "hero").setScale(1.3);
  player.setCollideWorldBounds(true);
  cursors = this.input.keyboard.createCursorKeys();
  const points = [
    [220, 200],
    [700, 180],
    [640, 360],
    [300, 340],
  ];
  points.forEach(([x, y]) => helpers.coins.create(x, y, "coin"));
  this.physics.add.overlap(player, helpers.coins, (_, coin) => {
    coin.destroy();
    addScore(this, 1);
  });
  if (statusEl) statusEl.textContent = "Ready to Play";
}

function update() {
  if (!player || !cursors) return;
  player.setVelocity(0, 0);
  const speed = 220;
  if (cursors.left.isDown) player.setVelocityX(-speed);
  if (cursors.right.isDown) player.setVelocityX(speed);
  if (cursors.up.isDown) player.setVelocityY(-speed);
  if (cursors.down.isDown) player.setVelocityY(speed);
}
"""
    return common + """
function create() {
  paintSky(this);
  createLabel(this, GAME_TITLE, 30, 28);
  createLabel(this, GAME_THEME, 30, 68, "18px").setAlpha(0.82);
  const platforms = this.physics.add.staticGroup();
  platforms.create(480, 500, "platform").setScale(8, 1).refreshBody();
  platforms.create(260, 390, "platform").setScale(2, 1).refreshBody();
  platforms.create(720, 320, "platform").setScale(2, 1).refreshBody();
  platforms.create(480, 250, "platform").setScale(2, 1).refreshBody();
  helpers.coins = this.physics.add.staticGroup();
  helpers.coins.create(260, 346, "coin");
  helpers.coins.create(720, 276, "coin");
  helpers.coins.create(480, 206, "coin");
  player = this.physics.add.image(120, 420, "hero");
  player.setBounce(0.08);
  player.setCollideWorldBounds(true);
  this.physics.add.collider(player, platforms);
  this.physics.add.overlap(player, helpers.coins, (_, coin) => {
    coin.destroy();
    addScore(this, 1);
  });
  cursors = this.input.keyboard.createCursorKeys();
  scoreText = createLabel(this, "Stars: 0", 30, 108, "22px");
  this.add.text(30, 145, "Arrow keys to move, up to jump.", {
    fontFamily: "Avenir Next, Trebuchet MS, sans-serif",
    fontSize: "20px",
    color: "#f6f4e8",
  });
  if (statusEl) statusEl.textContent = "Ready to Play";
}

function update() {
  if (!player || !cursors) return;
  const onGround = Math.abs(player.body.velocity.y) < 2;
  if (cursors.left.isDown) {
    player.setVelocityX(-220);
  } else if (cursors.right.isDown) {
    player.setVelocityX(220);
  } else {
    player.setVelocityX(0);
  }
  if (cursors.up.isDown && onGround) {
    player.setVelocityY(-520);
  }
}
"""


def _template_web_js(title: str, kind: str, theme_prompt: str | None) -> str:
    title_text = _js_text(title)
    theme_text = _js_text(theme_prompt or "Clean, inviting, and surprisingly polished.")
    if kind == "landing-page":
        return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

root.innerHTML = `
  <div class="web-canvas">
    <section class="web-topline">
      <div>
        <div class="web-kicker">Web Studio</div>
        <div class="web-wordmark">Landing Page Template</div>
      </div>
      <nav class="web-nav" aria-label="Landing page sections">
        <a href="#story">Story</a>
        <a href="#proof">Proof</a>
        <a href="#launch">Launch</a>
      </nav>
    </section>

    <section id="story" class="web-hero">
      <div>
        <p class="web-overline">Quiet launch template</p>
        <h1 class="web-title">${{TITLE}}</h1>
        <p class="web-copy">${{THEME}}</p>
        <div class="web-cta-row">
          <button class="web-button" type="button">Start Project</button>
          <button class="web-button secondary" type="button">See Preview</button>
        </div>
      </div>
      <aside class="web-aside" aria-label="Launch notes">
        <div class="web-aside-label">Launch Notes</div>
        <div class="web-note-list">
          <div class="web-note">
            <span>Posture</span>
            <strong>Minimal, composed, and product-first.</strong>
          </div>
          <div class="web-note">
            <span>Structure</span>
            <strong>One continuous canvas shaped by spacing and hairline dividers.</strong>
          </div>
          <div class="web-note">
            <span>Signal</span>
            <strong>Professional enough for a premium launch without feeling overdesigned.</strong>
          </div>
        </div>
      </aside>
    </section>

    <section id="proof" class="web-proof">
      <article class="web-proof-item">
        <span class="web-proof-number">01</span>
        <h2>Lead with a clear promise.</h2>
        <p>Put the offer up front so the visitor understands the product before they scan the details.</p>
      </article>
      <article class="web-proof-item">
        <span class="web-proof-number">02</span>
        <h2>Let typography carry the page.</h2>
        <p>Big signals come from type, rhythm, and alignment instead of decorative tiles and nested panels.</p>
      </article>
      <article class="web-proof-item">
        <span class="web-proof-number">03</span>
        <h2>Make the preview feel publishable.</h2>
        <p>Every section is built to read like a polished first draft, not a placeholder wireframe.</p>
      </article>
    </section>

    <section class="web-section">
      <div class="web-section-head">
        <div class="web-kicker">Framework</div>
        <h2>Sleek enough for a launch, restrained enough for a real product.</h2>
      </div>
      <div class="web-feature-list">
        <article class="web-feature">
          <h3>Typography-first hierarchy</h3>
          <p>Scale, weight, and spacing organize the page before borders or backgrounds need to step in.</p>
        </article>
        <article class="web-feature">
          <h3>Quiet visual confidence</h3>
          <p>Soft earthy color and disciplined whitespace make the page feel mature, calm, and ready to trust.</p>
        </article>
        <article class="web-feature">
          <h3>Clean publishing rhythm</h3>
          <p>Ship a solid narrative, refine the copy, and move straight from preview to publish without reworking the structure.</p>
        </article>
      </div>
    </section>

    <section id="launch" class="web-launch">
      <div class="web-launch-copy">
        <div class="web-kicker">Launch Flow</div>
        <h2>Preview fast, sharpen the story, publish when the page feels inevitable.</h2>
        <p>The template gives you a high-trust baseline so the next iterations can focus on message, proof, and product texture.</p>
      </div>
      <div class="web-launch-rail">
        <div class="web-rail-row">
          <span>Step 1</span>
          <strong>Frame the product in one sentence.</strong>
        </div>
        <div class="web-rail-row">
          <span>Step 2</span>
          <strong>Add just enough proof to feel credible.</strong>
        </div>
        <div class="web-rail-row">
          <span>Step 3</span>
          <strong>Polish the details, then publish.</strong>
        </div>
      </div>
    </section>
  </div>
`;

if (statusEl) statusEl.textContent = "Ready to Preview";
"""
    layout = {
        "portfolio": """
          <section class="card" style="display:grid;grid-template-columns:1.3fr 1fr;gap:20px;padding:28px;">
            <div>
              <div class="hero-chip">Creative portfolio</div>
              <h1 style="font-size:52px;line-height:1.02;margin:18px 0 12px;">${TITLE}</h1>
              <p style="font-size:19px;line-height:1.6;max-width:44ch;">${THEME}</p>
            </div>
            <div class="card" style="background:linear-gradient(135deg,#183b2f,#294f7f);color:#fff;min-height:240px;">
              <p style="font-size:13px;text-transform:uppercase;letter-spacing:.12em;opacity:.78;">Featured project</p>
              <h3 style="font-size:30px;margin:18px 0 10px;">Field Notes</h3>
              <p>Interactive stories, immersive visuals, and product-ready front-end craft.</p>
            </div>
          </section>
          <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;">
            <article class="card"><h3>Brand systems</h3><p>Visual systems that feel distinct instead of generic.</p></article>
            <article class="card"><h3>Interactive builds</h3><p>Prototype and production work that stays previewable.</p></article>
            <article class="card"><h3>Trusted delivery</h3><p>Clear iteration loop from brief to polished result.</p></article>
          </section>
        """,
        "blank": """
          <section class="card" style="padding:28px;">
            <div class="hero-chip">Blank website starter</div>
            <h1 style="font-size:48px;margin:18px 0 12px;">${TITLE}</h1>
            <p style="font-size:18px;line-height:1.55;max-width:52ch;">${THEME}</p>
          </section>
        """,
    }.get(kind, """
      <section class="card" style="padding:28px;">
        <div class="hero-chip">Product app starter</div>
        <h1 style="font-size:48px;margin:18px 0 12px;">${TITLE}</h1>
        <p style="font-size:18px;line-height:1.55;max-width:52ch;">${THEME}</p>
      </section>
      <section style="display:grid;grid-template-columns:280px 1fr;gap:16px;">
        <aside class="card">
          <h3 style="margin-top:0;">Navigation</h3>
          <p>Overview</p><p>Projects</p><p>Tasks</p><p>Analytics</p>
        </aside>
        <section class="stack">
          <article class="card"><h3>Team activity</h3><p>Live signals, progress, and momentum all in one place.</p></article>
          <article class="card"><h3>Launch checklist</h3><p>Preview, review, publish, and share from the same workspace.</p></article>
        </section>
      </section>
    """)
    return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

root.innerHTML = `
  <div class="stack" style="padding:22px;">
    {layout}
  </div>
`;

if (statusEl) statusEl.textContent = "Ready to Preview";
"""


def _template_image_js(title: str, kind: str, theme_prompt: str | None) -> str:
    title_text = _js_text(title)
    theme_text = _js_text(theme_prompt or "Stylized concepts, prop studies, and collectible image exploration.")
    view_label = {
        "image-gen": "Native image workflow",
        "blank": "Blank image studio",
    }[kind]
    return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

root.innerHTML = `
  <div class="stack" style="padding:22px;">
    <section class="card">
      <div class="hero-chip">{view_label}</div>
      <h1 style="font-size:44px;margin:18px 0 12px;">${{TITLE}}</h1>
      <p style="font-size:18px;line-height:1.55;max-width:58ch;">${{THEME}}</p>
      <p style="font-size:15px;line-height:1.6;max-width:62ch;color:rgba(57,68,78,0.9);">
        This page keeps Image Studio rooted in a local workspace. Use the native Alcove panel as the authoritative home for generation, uploads, references, and review.
      </p>
    </section>
  </div>
`;

if (statusEl) statusEl.textContent = "Ready to Generate";
"""


def _template_data_js(title: str, kind: str, theme_prompt: str | None) -> str:
    title_text = _js_text(title)
    theme_text = _js_text(theme_prompt or "Readable, trustworthy, and easy to explore.")
    view_label = {
        "dashboard": "Live dashboard",
        "spreadsheet": "Spreadsheet view",
        "query-lab": "Query lab",
        "blank": "Blank data studio",
    }[kind]
    return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

async function boot() {{
  const response = await fetch("./data.json");
  const data = await response.json();
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const revenue = rows.reduce((sum, row) => sum + Number(row.revenue || 0), 0);
  const topRegion = rows.slice().sort((a, b) => Number(b.revenue || 0) - Number(a.revenue || 0))[0];
  root.innerHTML = `
    <div class="stack" style="padding:22px;">
      <section class="card">
        <div class="hero-chip">{view_label}</div>
        <h1 style="font-size:44px;margin:18px 0 12px;">${{TITLE}}</h1>
        <p style="font-size:18px;line-height:1.55;max-width:56ch;">${{THEME}}</p>
      </section>
      <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;">
        <article class="card"><h3>Total Revenue</h3><p style="font-size:32px;margin:12px 0 0;">${{new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD', maximumFractionDigits: 0 }}).format(revenue)}}</p></article>
        <article class="card"><h3>Rows</h3><p style="font-size:32px;margin:12px 0 0;">${{rows.length}}</p></article>
        <article class="card"><h3>Top Region</h3><p style="font-size:24px;margin:12px 0 0;">${{topRegion?.region || 'Unknown'}}</p></article>
      </section>
      <section class="card">
        <h3 style="margin-top:0;">Dataset</h3>
        <table>
          <thead><tr><th>Region</th><th>Accounts</th><th>Revenue</th><th>Status</th></tr></thead>
          <tbody>
            ${{rows.map((row) => `
              <tr>
                <td>${{row.region}}</td>
                <td>${{row.accounts}}</td>
                <td>${{new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD', maximumFractionDigits: 0 }}).format(row.revenue)}}</td>
                <td>${{row.status}}</td>
              </tr>
            `).join('')}}
          </tbody>
        </table>
      </section>
    </div>
  `;
  if (statusEl) statusEl.textContent = "Ready to Explore";
}}

boot().catch((error) => {{
  root.innerHTML = `<div class="card" style="margin:22px;"><h3>Preview Error</h3><p>${{String(error?.message || error)}}</p></div>`;
  if (statusEl) statusEl.textContent = "Needs Fixing";
}});
"""


def _template_video_js(title: str, kind: str, theme_prompt: str | None) -> str:
    title_text = _js_text(title)
    theme_text = _js_text(theme_prompt or "Short motion studies, text-to-video prompts, and image-to-video experiments.")
    template_label = {
        "video-gen": "Motion launchpad",
        "blank": "Blank video studio",
    }[kind]
    return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

root.innerHTML = `
  <div class="web-canvas">
    <section class="web-topline">
      <div>
        <div class="web-kicker">Video Studio</div>
        <div class="web-wordmark">{template_label}</div>
      </div>
      <nav class="web-nav" aria-label="Video studio sections">
        <a href="#modes">Modes</a>
        <a href="#workflow">Workflow</a>
        <a href="#next">Next</a>
      </nav>
    </section>

    <section id="modes" class="web-hero">
      <div>
        <p class="web-overline">Alcove-owned motion workflow</p>
        <h1 class="web-title">${{TITLE}}</h1>
        <p class="web-copy">${{THEME}}</p>
        <div class="web-cta-row">
          <button class="web-button" type="button">Text to Video</button>
          <button class="web-button secondary" type="button">Image to Video</button>
        </div>
      </div>
      <aside class="web-aside" aria-label="Video notes">
        <div class="web-aside-label">Current Shape</div>
        <div class="web-note-list">
          <div class="web-note">
            <span>Entry</span>
            <strong>Open from Alcove and keep prompts, previews, and outputs together.</strong>
          </div>
          <div class="web-note">
            <span>Runtime</span>
            <strong>Designed to plug into a local or external video worker without changing the product surface.</strong>
          </div>
          <div class="web-note">
            <span>Goal</span>
            <strong>Use Alcove as the authoritative home instead of a separate dashboard.</strong>
          </div>
        </div>
      </aside>
    </section>

    <section class="web-proof">
      <article class="web-proof-item">
        <span class="web-proof-number">01</span>
        <h2>Start from text.</h2>
        <p>Use Alcove to iterate on prompts and keep candidate clips organized in one place.</p>
      </article>
      <article class="web-proof-item">
        <span class="web-proof-number">02</span>
        <h2>Start from an image.</h2>
        <p>Reuse strong Alcove images as the first frame for image-to-video experiments.</p>
      </article>
      <article class="web-proof-item">
        <span class="web-proof-number">03</span>
        <h2>Own the outputs.</h2>
        <p>Store clips, previews, and metadata in the workspace instead of scattering them across tools.</p>
      </article>
    </section>

    <section id="workflow" class="web-section">
      <div class="web-section-head">
        <p class="web-overline">Workflow</p>
        <h2>Keep the UI light and let the backend be swappable.</h2>
      </div>
      <div class="web-feature-list">
        <article class="web-feature">
          <h3>Prompt and source selection</h3>
          <p>Alcove should handle ideation, image selection, and job history instead of sending you out to a second app.</p>
        </article>
        <article class="web-feature">
          <h3>Worker-backed renders</h3>
          <p>LTX or another backend can stay behind an adapter while Alcove owns job state and stored artifacts.</p>
        </article>
        <article class="web-feature">
          <h3>Small first deliverable</h3>
          <p>Start with a launchpad and a clean job model, then layer in real text-to-video and image-to-video runs.</p>
        </article>
      </div>
    </section>

    <section id="next" class="web-launch">
      <div class="web-launch-copy">
        <p class="web-overline">Next Step</p>
        <h2>Wire the first video provider into this workspace.</h2>
        <p>The product entry is ready now. The next meaningful addition is a provider-backed generate action, not a whole new surface.</p>
      </div>
      <div class="web-launch-rail">
        <div class="web-rail-row">
          <span>Suggested backend</span>
          <strong>LTX-Video on the M2 Mac path</strong>
        </div>
        <div class="web-rail-row">
          <span>Best first mode</span>
          <strong>Image to Video</strong>
        </div>
        <div class="web-rail-row">
          <span>Storage plan</span>
          <strong>Keep clips, previews, and metadata in Alcove outputs.</strong>
        </div>
      </div>
    </section>
  </div>
`;

if (statusEl) statusEl.textContent = "Ready to Plan";
"""


def _template_docs_js(title: str, kind: str, theme_prompt: str | None) -> str:
    title_text = _js_text(title)
    theme_text = _js_text(theme_prompt or "Calm, readable, and confidently structured.")
    template_label = {
        "docs-site": "Documentation site",
        "guide": "Guide",
        "release-notes": "Release notes",
        "blank": "Blank docs starter",
    }[kind]
    return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

async function boot() {{
  const response = await fetch("./guide.md");
  const markdown = await response.text();
  const sections = markdown.split(/^## /m).filter(Boolean);
  const toc = sections.map((section) => {{
    const firstLine = section.split("\\n")[0].trim();
    const slug = firstLine.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return {{ firstLine, slug, body: section }};
  }});

  root.innerHTML = `
    <div style="display:grid;grid-template-columns:240px 1fr;min-height:100%;">
      <aside class="card" style="border-radius:0;border:0;border-right:1px solid rgba(110,126,144,0.12);">
        <div class="hero-chip">{template_label}</div>
        <h2 style="margin:18px 0 10px;">${{TITLE}}</h2>
        <p style="line-height:1.55;">${{THEME}}</p>
        <nav style="margin-top:18px;display:grid;gap:10px;">
          ${{toc.map((item) => `<a href="#${{item.slug}}" style="color:inherit;text-decoration:none;">${{item.firstLine}}</a>`).join('')}}
        </nav>
      </aside>
      <main class="stack" style="padding:22px;">
        <section class="card">
          <div class="hero-chip">Rendered preview</div>
          <h1 style="font-size:44px;margin:18px 0 12px;">${{TITLE}}</h1>
          <p style="font-size:18px;line-height:1.6;max-width:60ch;">${{THEME}}</p>
        </section>
        ${{toc.map((item) => `
          <article id="${{item.slug}}" class="card">
            <h2 style="margin-top:0;">${{item.firstLine}}</h2>
            <div style="white-space:pre-wrap;line-height:1.7;">${{item.body.split('\\n').slice(1).join('\\n').trim()}}</div>
          </article>
        `).join('')}}
      </main>
    </div>
  `;
  if (statusEl) statusEl.textContent = "Ready to Read";
}}

boot().catch((error) => {{
  root.innerHTML = `<div class="card" style="margin:22px;"><h3>Preview Error</h3><p>${{String(error?.message || error)}}</p></div>`;
  if (statusEl) statusEl.textContent = "Needs Fixing";
}});
"""


def _sample_data_json(title: str) -> str:
    payload = {
        "title": title,
        "rows": [
            {"region": "North", "accounts": 18, "revenue": 42000, "status": "Healthy"},
            {"region": "West", "accounts": 11, "revenue": 31500, "status": "Growing"},
            {"region": "South", "accounts": 9, "revenue": 18750, "status": "Watch"},
            {"region": "East", "accounts": 14, "revenue": 39200, "status": "Healthy"},
        ],
    }
    return json.dumps(payload, indent=2)


def _sample_docs_markdown(title: str, template: str, theme_prompt: str | None) -> str:
    theme = theme_prompt or "Clear documentation that is easy to scan and safe to share."
    return f"""## Overview
{title} is an Alcove Studio docs workspace built from the `{template}` template.

{theme}

## Getting Started
Open the workspace chat, describe the change you want, and refresh the preview to see the rendered result.

## Publishing
Use Publish when you want a stable share link for the current version of the docs.
"""


def _html_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _js_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
