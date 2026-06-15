# design bible

## v0.1 — calm operational minimalism

this system is built around restraint, clarity, and confidence. it avoids the usual “software dashboard” habit of stacking cards inside cards and instead treats the interface like a well-organized working document. structure comes from spacing, typography, alignment, and thin dividers more than from containers. the result should feel calm, trustworthy, and mature.

the goal is not to make operations feel flashy. the goal is to make complex information feel readable, grounded, and quietly under control. this design language should support dashboards, finance views, ops tools, admin panels, planning systems, and internal software where good judgment matters more than spectacle.

## related context

- `wiki/life/index.md` / [[wiki/life/index|Life Philosophy]] - connects this design taste to the broader philosophy around calm tools, emotional cost, durable work, and private operating systems.
- `/Users/sky/.codex/skills/sky-design-bible/SKILL.md` - private Codex skill that applies this living source of truth during UI design, review, and frontend polish work.

---

## current taste drift

Add dated notes here when Sky's eye changes. Newer entries supersede older guidance when they conflict, unless a project-local design bible says otherwise.

### 2026-05-06

- The design bible is the source of truth for evolving taste; the private `sky-design-bible` Codex skill is the agent behavior layer that reads and applies it.

### 2026-05-11

- Dashboard, admin, ops, finance, and report surfaces should default to a Codex-like neutral palette: white canvas, white or very light gray surfaces, cool gray borders, charcoal text, and gray chart fills.
- Do not let the older "earthy" direction create a green, sage, beige, or organic cast across dashboards. Green is now only a semantic state color for explicit positive/healthy/completed meaning, not the default accent.
- When a surface needs visual weight, use typography, spacing, thin gray dividers, and neutral contrast before color. Bar charts and metric graphics should usually be black/gray unless the color itself encodes meaning.

### 2026-05-13

- For browser-based control surfaces, prefer a white canvas that feels like it flows past the browser edge over a framed app window sitting on a separate background.
- Avoid visible mode splits unless the selected mode materially changes the view, workflow, or available actions. Put prompt-behavior presets in an advanced/collapsed layer when the basic interaction is otherwise the same.
- Do not split the same user intent into a decorative prompt and a separate input field. The invitation should label or become the actual composer where the user's messy thought lives.
- For presence assistants, the basic surface should prefer one start/stop control for the live assistant loop. Background work should be launched through the assistant/tool bridge or advanced controls, not competing primary buttons.

### 2026-06-15

- Story Dock's iOS app is now the benchmark for consumer ritual surfaces in Sky's system. The lesson is interaction priority, not just visual warmth: one primary moment, management behind quiet secondary surfaces, and platform-native controls that make the product feel trustworthy.
- For branded consumer apps that support a physical ritual, do not force the neutral dashboard palette if the project has a warmer product identity. Keep the app calm and native, but let brand texture appear in the launch mark, app icon, small status moments, and physical product surfaces.
- The first screen should make the real object/action obvious. For Story Dock-like products, `tap/open -> record or play` beats a landing page, feature tour, account wall, or dashboard.
- If an item already contains value, default to playback, readiness, or the next concrete action first. Put edit, replace, record-another, owner tools, support, and advanced routing behind an info sheet, menu, or Library tab.
- Native mobile utilities should prefer platform patterns: tab navigation, navigation stacks, forms/lists, sheets, large touch targets, system icons, semantic badges, and short status copy. Custom visual language should wrap those patterns, not fight them.
- Account/library surfaces can be operational, but keep them lighter than admin dashboards. Use compact metrics, segmented/tabbed information architecture, disclosure groups for tools, redacted support status, and destructive actions that explain the safe next step.

## core philosophy

### 1. calm before clever
the interface should feel settled before it feels impressive. users should feel oriented, not dazzled.

### 2. typography does the heavy lifting
hierarchy should come primarily from type size, weight, case, spacing, and placement. avoid relying on extra borders, shadows, and decorative surfaces.

### 3. one canvas, lightly segmented
prefer a continuous page with clearly separated regions over a pile of independent widgets. use horizontal bands, thin rules, and generous spacing instead of nested boxes.

### 4. color is semantic
color should mean something. it is not there to decorate. use it to distinguish strength, caution, liabilities, positive performance, or active state.

### 5. dense but breathable
the interface can hold a lot of information, but it should never feel cramped. density is acceptable; clutter is not.

### 6. report-like, not gadget-like
the product should feel closer to an elegant report, control room, or management brief than a toy dashboard.

---

## emotional target

the ui should feel:

- calm
- intentional
- literate
- grounded
- managerial
- quiet
- trustworthy

the ui should not feel:

- trendy
- gamified
- loud
- glossy
- over-framed
- “widgety”
- hyper-optimized for novelty

---

## defining characteristics

### restrained surfaces
most of the screen should feel like open space. sections may be separated, but content should not be trapped inside aggressive containers.

### editorial hierarchy
headers, labels, metadata, and body copy should feel authored. the layout should guide the eye in a deliberate reading order.

### strong scanability
the user should be able to understand the page in layers:
1. page purpose
2. major metrics
3. section summaries
4. detailed comparisons and actions

### quiet confidence
important values should be allowed to stand on their own. they do not need dramatic badges or oversized cards to feel important.

---

## visual principles

### typography-first hierarchy
use typography to communicate structure before using borders or backgrounds.

patterns:
- small uppercase labels for section eyebrows
- bold headings for region anchors
- lighter secondary text for explanation
- prominent numerals for key metrics
- quiet metadata rows for context

### thin dividers over heavy containers
when separating information, prefer:
- 1px lines
- spacing
- background shifts
- subtle grouping

avoid:
- thick borders
- nested panels
- excessive radius
- deep shadows

### neutral codex-like palette
dashboards and operating tools should feel closer to the Codex app: white, light gray, charcoal text, cool gray borders, and restrained neutral fills.

the palette should suggest:
- white workspace
- gray chrome
- crisp dividers
- readable reports
- quiet control surfaces
- operational seriousness

---

## color philosophy

### neutrals
neutrals should dominate the interface. they create the feeling of calm and allow accent colors to retain meaning.

### positive / owned / stable
green may represent healthy assets, strong positions, positive inflow, completion, and grounded action, but only when the green is carrying that specific meaning. It should not be the default dashboard accent or chart color.

### caution / burden / liabilities
use caution colors sparingly and semantically. Avoid letting tan, beige, rust, or brown become the overall dashboard atmosphere unless a project-local style explicitly asks for it.

### usage rule
at least 90–95% of dashboard/report interfaces should be neutral. accents should be sparse and meaningful.

---

## starter token direction

```css
:root {
  --bg-canvas: #f7f7f8;
  --bg-surface: #ffffff;
  --bg-subtle: #f3f4f6;
  --border-subtle: #e5e7eb;
  --border-strong: #d1d5db;

  --text-primary: #111827;
  --text-secondary: #4b5563;
  --text-muted: #6b7280;

  --accent-neutral: #111827;
  --accent-neutral-soft: #9ca3af;
  --accent-neutral-faint: #f3f4f6;

  --state-positive: #166534;
  --state-warning: #92400e;
  --state-danger: #991b1b;
}
```
