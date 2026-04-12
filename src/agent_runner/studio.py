from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


STUDIO_KIND_LABELS = {
    "studio_game": "Game Studio",
    "studio_web": "Web Studio",
    "studio_data": "Data Studio",
    "studio_docs": "Docs Studio",
}

STUDIO_TEMPLATES = {
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
        "image-lab": "Image Lab",
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
}

DEFAULT_TEMPLATES = {
    "studio_game": "runner",
    "studio_web": "landing-page",
    "studio_data": "dashboard",
    "studio_docs": "docs-site",
}

DEFAULT_TITLES = {
    "studio_game": "New Game",
    "studio_web": "New Website",
    "studio_data": "New Dataset",
    "studio_docs": "New Docs",
}

ENTRY_FILES = {
    "studio_game": "game.js",
    "studio_web": "app.js",
    "studio_data": "data.js",
    "studio_docs": "docs.js",
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
    play_label = "Play" if kind == "studio_game" else "Preview"
    return {
        "play_label": play_label,
        "change_label": "Ask for a Change",
        "publish_label": "Publish",
        "remix_label": "Remix",
    }


def studio_placeholder(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    if kind == "studio_game":
        return 'Ask for a change in your game, like "make the jump higher" or "add coins".'
    if kind == "studio_web":
        return 'Ask for a website change, like "make the hero bolder" or "add a pricing section".'
    if kind == "studio_data":
        return 'Ask for a data change, like "group revenue by month" or "show duplicate rows".'
    return 'Ask for a docs change, like "rewrite the intro" or "add a getting started section".'


def studio_empty_state(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    if kind == "studio_game":
        return "Preview will appear here after the game is created."
    if kind == "studio_web":
        return "Preview will appear here after the website is created."
    if kind == "studio_data":
        return "Your live data view will appear here after the studio is created."
    return "Your rendered docs view will appear here after the studio is created."


def studio_summary_prompt(workspace_kind: str) -> str:
    kind = normalize_workspace_kind(workspace_kind)
    if kind == "studio_game":
        return "Describe a change and Alcove will update the game."
    if kind == "studio_web":
        return "Describe a change and Alcove will update the site."
    if kind == "studio_data":
        return "Describe a change and Alcove will update the data workspace."
    return "Describe a change and Alcove will update the docs."


def studio_welcome_message(project: StudioProject) -> str:
    studio_name = STUDIO_KIND_LABELS[project.workspace_kind]
    artifact_label = _artifact_noun(project.workspace_kind)
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
        "studio_game": "game",
        "studio_web": "website",
        "studio_data": "data workspace",
        "studio_docs": "docs workspace",
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
        "studio_game": "radial-gradient(circle at top, #1f3f35, #10201a 60%, #08110e)",
        "studio_web": "linear-gradient(180deg, #f1ece4 0%, #f6f4ef 48%, #dfe6dc 100%)",
        "studio_data": "linear-gradient(180deg, #f4f7fb 0%, #ecf1f7 52%, #dfe8f3 100%)",
        "studio_docs": "linear-gradient(180deg, #f7f1e7 0%, #f6f3ee 42%, #e6ecf4 100%)",
    }[kind]
    body_color = "#f6f4e8" if kind == "studio_game" else "#1c241f"
    shell_background = "rgba(8, 17, 14, 0.24)" if kind == "studio_game" else "rgba(252, 250, 246, 0.82)"
    surface_radius = "22px" if kind == "studio_game" else "10px"
    surface_shadow = "0 26px 60px rgba(0, 0, 0, 0.12)" if kind == "studio_game" else "0 18px 44px rgba(34, 41, 35, 0.08)"
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
  width: min(100vw, 1180px);
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
}}

.studio-header,
.studio-footer {{
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
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
  padding: 10px 18px 20px;
}}

.studio-surface {{
  min-height: min(78vh, 880px);
  border-radius: {surface_radius};
  background: {shell_background};
  border: 1px solid rgba(110, 126, 144, 0.18);
  box-shadow: {surface_shadow};
  overflow: hidden;
}}

.studio-footer {{
  font-size: 13px;
  color: rgba(84, 98, 114, 0.9);
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
    entry_file = str(spec["entry_file"])
    script_tag = ""
    if spec["workspace_kind"] == "studio_game":
        script_tag = '<script src="https://cdn.jsdelivr.net/npm/phaser@3.90.0/dist/phaser.min.js"></script>'
    footer_copy = {
        "studio_game": "Play, tweak, and remix from Alcove Studio.",
        "studio_web": "Preview, tweak, and publish from Alcove Studio.",
        "studio_data": "Explore, reshape, and publish from Alcove Studio.",
        "studio_docs": "Write, preview, and share from Alcove Studio.",
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
        <div class="studio-title">{title}</div>
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
    if workspace_kind == "studio_web":
        return _template_web_js(title, template, theme_text or None)
    if workspace_kind == "studio_data":
        return _template_data_js(title, template, theme_text or None)
    return _template_docs_js(title, template, theme_text or None)


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
    if kind == "image-lab":
        return f"""const TITLE = "{title_text}";
const THEME = "{theme_text}";
const root = document.getElementById("studio-root");
const statusEl = document.getElementById("status");

root.innerHTML = `
  <div class="stack" style="padding:22px;">
    <section class="card" style="padding:0;overflow:hidden;background:linear-gradient(145deg,#fff7ec 0%,#f4efe7 48%,#efe6d7 100%);">
      <div style="display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,0.85fr);gap:0;">
        <div style="padding:30px 30px 34px;">
          <div class="hero-chip">Alcove Studio · Image Lab</div>
          <h1 style="font-size:56px;line-height:0.98;margin:18px 0 14px;max-width:10ch;">${{TITLE}}</h1>
          <p style="font-size:18px;line-height:1.65;max-width:54ch;margin:0 0 22px;">${{THEME}}</p>
          <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:24px;">
            <div class="hero-chip" style="background:#fff;color:#6f5132;">Prompt-first</div>
            <div class="hero-chip" style="background:#fff;color:#6f5132;">Variant gallery</div>
            <div class="hero-chip" style="background:#fff;color:#6f5132;">z-image ready</div>
          </div>
          <div class="card" style="padding:18px;background:rgba(255,255,255,0.72);border-color:rgba(111,81,50,0.16);box-shadow:none;">
            <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#7b644b;margin-bottom:8px;">Prompt</div>
            <div style="font-size:24px;line-height:1.35;color:#2d241a;">Painterly canyon dusk, cinematic clouds, warm mineral light, crisp silhouette, editorial fantasy poster.</div>
          </div>
        </div>
        <aside style="padding:30px;background:linear-gradient(160deg,#8f5b35 0%,#6d7c65 54%,#2d4d62 100%);color:#fff;display:grid;align-content:space-between;gap:18px;">
          <div>
            <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;opacity:0.76;">Session</div>
            <h2 style="font-size:28px;line-height:1.15;margin:10px 0 12px;">Studio shell for image generation workflows.</h2>
            <p style="margin:0;line-height:1.6;opacity:0.9;">Use this starter to shape prompts, compare variants, and connect Alcove's chat loop to an external dashboard like ai-art.</p>
          </div>
          <div class="stack" style="gap:10px;">
            <div class="card" style="background:rgba(14,20,26,0.22);color:#fff;border-color:rgba(255,255,255,0.16);box-shadow:none;">
              <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;opacity:0.72;">Recommended hook-up</div>
              <div style="font-size:17px;line-height:1.5;margin-top:8px;">Swap the mock run controls for your ai-art dashboard actions, then stream generated assets back into the gallery.</div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;">
              <div class="card" style="background:rgba(255,255,255,0.14);color:#fff;border-color:rgba(255,255,255,0.18);box-shadow:none;padding:14px;">
                <div style="font-size:12px;opacity:0.72;text-transform:uppercase;letter-spacing:.14em;">Model</div>
                <strong style="display:block;margin-top:8px;font-size:16px;">z-image</strong>
              </div>
              <div class="card" style="background:rgba(255,255,255,0.14);color:#fff;border-color:rgba(255,255,255,0.18);box-shadow:none;padding:14px;">
                <div style="font-size:12px;opacity:0.72;text-transform:uppercase;letter-spacing:.14em;">Aspect</div>
                <strong style="display:block;margin-top:8px;font-size:16px;">4:5</strong>
              </div>
              <div class="card" style="background:rgba(255,255,255,0.14);color:#fff;border-color:rgba(255,255,255,0.18);box-shadow:none;padding:14px;">
                <div style="font-size:12px;opacity:0.72;text-transform:uppercase;letter-spacing:.14em;">Batch</div>
                <strong style="display:block;margin-top:8px;font-size:16px;">4 variants</strong>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </section>
    <section style="display:grid;grid-template-columns:minmax(0,0.95fr) minmax(0,1.05fr);gap:16px;">
      <article class="card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;">
          <div>
            <div class="hero-chip">Generation Queue</div>
            <h3 style="font-size:30px;margin:16px 0 10px;">Prompt sets and run controls</h3>
          </div>
          <div style="font-size:13px;color:#75624d;">Draft flow</div>
        </div>
        <div class="stack" style="gap:12px;">
          <div class="card" style="padding:16px;background:#fffaf2;border-color:rgba(111,81,50,0.12);box-shadow:none;">
            <strong style="display:block;font-size:16px;">Hero illustration</strong>
            <p style="margin:8px 0 0;line-height:1.55;">Generate a lead image for the campaign page, tuned for headline-safe negative space.</p>
          </div>
          <div class="card" style="padding:16px;background:#f8fbff;border-color:rgba(57,89,116,0.12);box-shadow:none;">
            <strong style="display:block;font-size:16px;">Style exploration</strong>
            <p style="margin:8px 0 0;line-height:1.55;">Compare painterly, graphic, and cinematic directions before committing to one visual voice.</p>
          </div>
          <div class="card" style="padding:16px;background:#f6faf5;border-color:rgba(63,95,72,0.12);box-shadow:none;">
            <strong style="display:block;font-size:16px;">Production handoff</strong>
            <p style="margin:8px 0 0;line-height:1.55;">Save approved prompts, chosen seeds, and exported filenames so the workflow stays reproducible.</p>
          </div>
        </div>
      </article>
      <article class="card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px;">
          <div>
            <div class="hero-chip">Variant Gallery</div>
            <h3 style="font-size:30px;margin:16px 0 8px;">Preview the outputs beside the chat.</h3>
          </div>
          <div style="font-size:13px;color:#75624d;">Mock gallery</div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;">
          <div style="aspect-ratio:4 / 5;border-radius:24px;background:linear-gradient(180deg,#f7c98d 0%,#df8352 35%,#53406e 100%);position:relative;overflow:hidden;">
            <div style="position:absolute;inset:14px;border-radius:18px;background:radial-gradient(circle at 50% 28%,rgba(255,247,218,0.78),transparent 34%),linear-gradient(180deg,transparent 42%,rgba(34,20,44,0.35) 100%);"></div>
          </div>
          <div style="aspect-ratio:4 / 5;border-radius:24px;background:linear-gradient(180deg,#9fd3e8 0%,#5d8fb6 42%,#21344b 100%);position:relative;overflow:hidden;">
            <div style="position:absolute;inset:14px;border-radius:18px;background:radial-gradient(circle at 60% 24%,rgba(248,252,255,0.72),transparent 30%),linear-gradient(180deg,transparent 46%,rgba(8,18,34,0.42) 100%);"></div>
          </div>
          <div style="aspect-ratio:4 / 5;border-radius:24px;background:linear-gradient(180deg,#bed6a8 0%,#7f9760 42%,#39452d 100%);position:relative;overflow:hidden;">
            <div style="position:absolute;inset:14px;border-radius:18px;background:radial-gradient(circle at 42% 22%,rgba(250,245,214,0.7),transparent 32%),linear-gradient(180deg,transparent 48%,rgba(26,39,20,0.42) 100%);"></div>
          </div>
          <div style="aspect-ratio:4 / 5;border-radius:24px;background:linear-gradient(180deg,#f0d9bb 0%,#b88763 44%,#5a3550 100%);position:relative;overflow:hidden;">
            <div style="position:absolute;inset:14px;border-radius:18px;background:radial-gradient(circle at 50% 24%,rgba(255,247,237,0.72),transparent 30%),linear-gradient(180deg,transparent 48%,rgba(38,18,32,0.4) 100%);"></div>
          </div>
        </div>
      </article>
    </section>
  </div>
`;

if (statusEl) statusEl.textContent = "Ready to Preview";
"""
    layout = {
        "image-lab": """
          <section class="card" style="padding:28px;">
            <div class="hero-chip">Image Lab</div>
            <h1 style="font-size:48px;margin:18px 0 12px;">${TITLE}</h1>
            <p style="font-size:18px;line-height:1.55;max-width:52ch;">${THEME}</p>
          </section>
        """,
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
