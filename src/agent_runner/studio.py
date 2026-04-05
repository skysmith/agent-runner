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
        "blank": "Blank Start",
        "platformer": "Platformer",
        "top-down": "Top-down Adventure",
        "clicker": "Clicker",
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
}

DEFAULT_TEMPLATES = {
    "studio_game": "platformer",
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
        "studio_web": "linear-gradient(135deg, #f6efe0 0%, #f7f3ea 45%, #d7e5df 100%)",
        "studio_data": "linear-gradient(180deg, #f4f7fb 0%, #ecf1f7 52%, #dfe8f3 100%)",
        "studio_docs": "linear-gradient(180deg, #f7f1e7 0%, #f6f3ee 42%, #e6ecf4 100%)",
    }[kind]
    body_color = "#f6f4e8" if kind == "studio_game" else "#17212b"
    shell_background = "rgba(8, 17, 14, 0.24)" if kind == "studio_game" else "rgba(255, 255, 255, 0.78)"
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
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  background: rgba(255, 255, 255, 0.5);
}}

.studio-main {{
  padding: 10px 18px 20px;
}}

.studio-surface {{
  min-height: min(78vh, 880px);
  border-radius: 24px;
  background: {shell_background};
  border: 1px solid rgba(110, 126, 144, 0.18);
  box-shadow: 0 26px 60px rgba(0, 0, 0, 0.12);
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
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(110, 126, 144, 0.18);
}}

.stack {{
  display: grid;
  gap: 16px;
}}

.card {{
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(110, 126, 144, 0.14);
  border-radius: 18px;
  padding: 18px;
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
    theme_text = _js_text(theme_prompt or "Bright, playful, and easy to understand.")
    common = f"""const GAME_TITLE = "{title_text}";
const GAME_THEME = "{theme_text}";
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
  g.fillStyle(0xf6d66f, 1);
  g.fillCircle(14, 14, 14);
  g.generateTexture("coin", 28, 28);
  g.clear();
  g.fillStyle(0x7bc8f6, 1);
  g.fillRoundedRect(0, 0, 120, 28, 10);
  g.generateTexture("platform", 120, 28);
  g.destroy();
}}

function paintSky(scene) {{
  scene.add.rectangle(width / 2, height / 2, width, height, 0x1d3b31).setDepth(-5);
  scene.add.circle(820, 90, 62, 0xf4f0c6, 0.16);
  scene.add.circle(160, 110, 42, 0x9dd4ff, 0.16);
}}

function addScore(scene, amount) {{
  score += amount;
  if (scoreText) scoreText.setText(`Stars: ${{score}}`);
  if (statusEl) statusEl.textContent = score > 0 ? `Ready to Play · Stars: ${{score}}` : "Ready to Play";
}}

function createLabel(scene, text, x, y, size = "28px") {{
  return scene.add.text(x, y, text, {{
    fontFamily: "Avenir Next, Trebuchet MS, sans-serif",
    fontSize: size,
    color: "#f6f4e8",
  }});
}}
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
    layout = {
        "landing-page": """
          <section class="card" style="padding:32px;">
            <div class="hero-chip">Launch-ready landing page</div>
            <h1 style="font-size:56px;line-height:1;max-width:10ch;margin:18px 0 12px;">${TITLE}</h1>
            <p style="max-width:58ch;font-size:19px;line-height:1.55;">${THEME}</p>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:22px;">
              <button style="padding:14px 18px;border:none;border-radius:14px;background:#183b2f;color:#fff;font-size:16px;">Get Started</button>
              <button style="padding:14px 18px;border:1px solid rgba(24,59,47,0.18);border-radius:14px;background:#fff;font-size:16px;">See Demo</button>
            </div>
          </section>
          <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;">
            <article class="card"><h3>Fast setup</h3><p>Ship a confident first draft in minutes.</p></article>
            <article class="card"><h3>Clear story</h3><p>Keep the product promise visible in the UI.</p></article>
            <article class="card"><h3>Ready to share</h3><p>Publish a polished preview without extra tools.</p></article>
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
