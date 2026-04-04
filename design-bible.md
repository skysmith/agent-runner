# design bible

## v0.1 — calm operational minimalism

this system is built around restraint, clarity, and confidence. it avoids the usual “software dashboard” habit of stacking cards inside cards and instead treats the interface like a well-organized working document. structure comes from spacing, typography, alignment, and thin dividers more than from containers. the result should feel calm, trustworthy, and mature.

the goal is not to make operations feel flashy. the goal is to make complex information feel readable, grounded, and quietly under control. this design language should support dashboards, finance views, ops tools, admin panels, planning systems, and internal software where good judgment matters more than spectacle.

---

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

### muted, earthy palette
colors should be low-saturation and slightly organic rather than neon or default-saas blue.

the palette should suggest:
- paper
- ink
- ledger
- field report
- natural materials
- operational seriousness

---

## color philosophy

### neutrals
neutrals should dominate the interface. they create the feeling of calm and allow accent colors to retain meaning.

### positive / owned / stable
greens should represent healthy assets, strong positions, positive inflow, completion, and grounded action.

### caution / burden / liabilities
warm rust, tan, or muted orange-brown tones should represent liabilities, drag, burden, cleanup, or caution.

### usage rule
at least 80–90% of the interface should be neutral. accents should be sparse and meaningful.

---

## starter token direction

```css
:root {
  --bg-canvas: #f5f5f3;
  --bg-surface: #fcfcfa;
  --border-subtle: #dddcd7;

  --text-primary: #2d2c29;
  --text-secondary: #6f726d;
  --text-muted: #8c8f89;

  --accent-green: #3f644b;
  --accent-green-soft: #6f8b78;
  --accent-green-faint: #d9e3db;

  --accent-rust: #a66a3f;
  --accent-rust-soft: #c08d65;
  --accent-rust-faint: #eadccf;

  --state-warning: #a66a3f;
  --state-positive: #3f644b;
}