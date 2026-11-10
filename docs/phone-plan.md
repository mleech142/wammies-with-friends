# Phones: every page usable on a phone

Step 2 of the agreed order in [hosted-version-scope.md](hosted-version-scope.md) (section 6): named players are
done (2.8), so phone layouts come next, page by page, the Play board last. The goal is that **everything** works
on a phone in the browser of a self-hosted copy: nothing left desktop-only except what is already `@desktop_only`
(native folder dialogs, paths on the server).

*Status: agreed (November 2026; section 6) and built, steps a to h, each with its checks in `tests/test_phone.py`
and `tests/test_phone_hosted.py`. Not yet tried on a real phone (Android Chrome, iPhone Safari): that testing goes
in [testing-list.md](testing-list.md).*

## 1. Where things stand (checked at 390px wide, November 2026)

- `base.html` already has the viewport tag, and about a dozen `@media (max-width: 900px)` rules stack some
  two-column layouts (Simulator, Armies, a few cards). Nothing else is phone-aware.
- **One cause breaks every page:** the header menu (`.header-nav`, up to ten links plus the version) is one flex
  row that never wraps. On a phone it makes every page about 1,000px wide, so the browser zooms the whole page
  out and everything is tiny. The cards under it are clipped on the right on every page.
- Wide tables run off the screen: the Data tab's tables, Armies' unit table, Analytics' rosters and matrix, the
  Match view's weapon tables, Scenarios' comparison table.
- Page headers (`.page-header`: title plus buttons) don't wrap, so buttons fall off the right (Armies, Data, Play).
- **Hover and `title=` carry meaning:** a rule's "Tick it only when: ..." conditions (`Core.ruleRowTitle`), button
  explanations and column-heading explanations are `title` tooltips, which phones never show. The Play board's
  datasheet card appears only after hovering over a model.
- **The Play board is mouse-and-keyboard:** zoom is the mouse wheel only; Shift-drag moves a single model;
  Shift + wheel spins a model; Q / E turn and Enter / Escape confirm placement (on-screen buttons exist for
  turning and pivoting, not for the others); right- and middle-drag pan. A second finger starts a second
  pointer the code doesn't expect. The board already has `touch-action: none`, and the input is Pointer Events,
  which is the right base for touch.
- The Play page's three columns become two at 1100px; on a phone the army panels end up side by side at about
  half the screen each, and the board is only as tall as the width allows.
- No automated check of any page at phone width exists (there are no browser tests at all).

## 2. Shared rules for every page (step a)

Written once in `style.css` and `app.js` / `core.js`, then used by every page step.

- **Breakpoints:** keep `900px` (tablet: columns stack) and add `600px` (phone). Supported down to **360px** wide
  (most Android phones; 390 is a current iPhone). Landscape phones use the tablet rules.
- **Touch, not width, decides touch behaviour:** `@media (pointer: coarse)` for larger targets (at least 44px
  high for buttons, ticks, pills and table-row actions; checkboxes and radios bigger) and to drop hover-only
  styling. A small phone-sized laptop window keeps mouse sizes.
- **Header:** at phone width, the brand shrinks to the dice icon plus a short name, and the links go into a menu
  behind a button (Font Awesome `fa-bars`), opening as a full-width panel over the page. The current page's name
  shows next to the button. The version moves into the menu. (Alternative in decision 3.)
- **Page headers:** wrap; the buttons become a full-width row under the title; long button labels may drop to
  icon plus a short word.
- **Tables:** two patterns, chosen per table.
  - *Scroll:* the table sits in a wrapper that scrolls sideways, with the first column sticky. For number grids
    (weapon profiles, the matrix, comparisons, points tables).
  - *Cards:* each row becomes a small card (label: value lines) using `data-label` on cells and a phone-only
    rule. For list tables with actions (Data tab factions, units, weapons, rules, proposals, players, saved items).
- **Pop-ups (`.modal`):** full-screen on a phone (no margins, the close button fixed at the top, the action row
  fixed at the bottom), so long forms like the Data tab's unit editor scroll inside.
- **Tooltips that carry meaning:** a shared "info" pattern in `app.js`: an element with `data-info` shows a small
  ⓘ that opens the text in a pop-over on tap (and still shows on hover with a mouse). Every `title` that explains
  something a player needs (rule conditions, "No effect on the calculations", column headings) moves to it.
  Plain icon-button labels stay as `title` plus `aria-label`.
- **Forms:** inputs, selects and textareas at least 16px text on phones (iOS zooms into anything smaller when it
  is focused); `inputmode="numeric"` on number fields; selects full width.
- **Safe areas:** `viewport-fit=cover` and `env(safe-area-inset-*)` padding on the header, fixed bars and the
  Play board's floating buttons (notches and home bars).
- **Charts (Plotly):** `responsive: true`, smaller margins and legend under the chart on phones, no mode bar.
- **Automated phone check** (decision 2): a test that opens every page at 390×844 with touch emulation on the
  test fixtures and fails if the page scrolls sideways (`document.documentElement.scrollWidth > innerWidth`) or a
  visible button is smaller than 44px. It runs with the other tests and in `tests.yml`. Each page step adds its
  page's states to it (a modal open, a list filled in, a game open).

## 3. Page by page

Sizes as in the scope: S (a day or less), M (a few days), L (a week or more).

**b. Simulator (`/`)** — S. Mostly done by step a: the attacker, defender, conditions and results cards already
stack at 900px. Left: the weapons table (scroll pattern, the Use tick and Qty kept on screen), results tiles in
two columns, the breakdown table, the conditions buttons wrapping, Run Simulation fixed at the bottom of the
screen once the attacker and defender are chosen (so results are one tap away), and scrolling to the results
after a run.

**c. Armies (`/armies`) and Match view (`/armies/<id>/match`)** — M.
- Armies: the saved list and the builder stack; the unit table becomes cards (name, size, points, leader, the
  enhancement and wargear buttons); the action buttons become a two-column grid; detachments and force
  disposition full width; the points total fixed at the top of the builder while scrolling. The wargear editor
  pop-up goes full-screen. Add Units: search plus results as a list under the builder.
- Match view: the stat boxes wrap, weapon tables use the scroll pattern with the weapon name sticky, ability
  text wraps (it is clipped today), the tabs and the filter row wrap, and the phase/turn filter sticks to the
  top. Print stays as it is.

**d. Analytics (`/analytics`)** — L. The page with the most to change.
- Options, attacker and defender rosters: the options bar wraps into a pop-up ("Conditions") on phones; the
  rosters become cards per unit (name, weapons count, models, points; tap for its weapons) instead of the wide
  tables.
- **The matrix** (decision 4): on a phone it shows one attacker at a time (a picker at the top, swipe or arrows
  to the next), each defender a row with its result coloured as today; tapping a row opens the cell detail. A
  "Grid" switch keeps the full grid in the scroll pattern with sticky headers for those who want it.
- Cell detail and the Army Analysis tabs (summary tiles, gaps, role scores, coverage, reverse durability): stack,
  charts full width, tabs scroll sideways.
- Save / Load Comparison buttons and Run Matrix as on the Simulator.

**e. The other pages** — M in total.
- Scenarios: the grid of saved items becomes one column; the comparison table uses the scroll pattern.
- Data tab: tabs scroll sideways; every list table uses the cards pattern; the editors (units, weapons, rules,
  stratagems, modifiers, leader buffs, points by size) are full-screen pop-ups with their inner tables stacked;
  Keywords and Target Profiles become cards. Import/Export buttons go into the page-header row.
- Setup: already a single 860px column; fix its import-notes table and the job progress rows.
- Proposals, Players, Account, the welcome and login pages: the cards pattern for their tables, full-width forms.
  The "what changed since" view on a proposal stacks the two sides instead of side by side.

**f. Play, outside the board** — M.
- Layout on a phone: the board on top at full width, as tall as the screen allows (the HUD compacted above it:
  names, CP, the score and the phase as one line; the phase steps as a row of icons). Below the board, the two
  army panels and the battle log become **tabs** (my army / their army / log) instead of side-by-side columns.
- The selected unit's details (now inside its army panel) open as a **bottom sheet** over the lower part of the
  board when a unit is tapped, with its actions (turn, Advance, shoot, charge, stratagems) as large buttons.
- Pop-ups (games, new game, battlefields, dice, mission choices, stratagem targets) full-screen.
- The dice tray: dice large enough to tap; "Next phase" and "Go" stay as floating buttons inside the safe area.
- Landscape on a phone: board on the left, the tabs on the right, like a tablet.

**g. Play board, touch** — L. The design already asked for touch-ready controls (`play-mode-design.md`). On
touch (`event.pointerType === 'touch'`), with mouse and pen unchanged:
- **One finger:** tap selects (or places, as a click does today); drag on a unit moves it; drag on empty board
  pans. A move only starts after about 8px (today 4px) so taps don't nudge units.
- **Two fingers:** pinch zooms around the midpoint, two-finger drag pans; any move in progress is cancelled
  (`pointercancel` handled everywhere a drag is). Zoom +/- buttons beside "Fit" for one-handed use.
- **Long-press** (about half a second, finger still) on a model shows its datasheet card (the hover card),
  placed so the finger doesn't cover it, with a close button; it stays until tapped away.
- **What Shift and keys do today gets a button** in the selected unit's sheet: "Move one model" (a toggle, then
  drag the model), spin a model (±15° buttons once a model is chosen), and the placement bar gets Confirm and
  Cancel buttons next to its pivots. Keys keep working with a keyboard.
- **Measure:** tap two points, as clicks do now; the distance label above the finger.
- **Fat fingers:** each model gets an invisible hit circle at least about 44px on screen at the current zoom, so
  small bases (25mm at full-board zoom) can still be picked; when circles overlap, the nearest model wins.
- **Drag routes and waypoints** work the same with a finger (lift to drop, a waypoint button instead of any
  modifier key, if one is used).
- **The battlefield editor** (`play-editor.js`): the same pinch, pan and long-press rules; rotate and resize
  terrain with on-screen handles big enough to grab.
- Tests: the gesture maths (pinch zoom around a point, tap-versus-drag, the nearest model under a finger) as pure
  functions in `core.js` with cases in `tests/js/core.test.js`; the phone check opens a game and drives a tap, a
  drag and a pinch.

**h. Install to the home screen (optional)** — S. A web app manifest and icons (bundled, no Games Workshop art)
so a self-hosted copy can be added to the home screen and opens without the browser's bars. Needs the HTTPS the
self-hosting docs already ask for. No offline mode and no push notifications: those belong to the phone app
(Pyodide, scope option C), which this plan doesn't start.

## 4. Order and releases

One release, **2.10 Phones**, built in the steps above, each to master with its tests and with the phone check
extended to its pages: a (shared rules and the check) → b → c → e → d → f → g → h. Analytics is after the small
pages because its matrix layout needs the most decisions; the Play board is last, as agreed. If the owner wants
something sooner, a–c and e can go out as their own release (2.10) with Analytics and Play in 2.11.

Testing on real phones (Android Chrome and iPhone Safari) at the end of each step, logged in
[testing-list.md](testing-list.md) as usual.

## 5. What doesn't change

- No game rules move into JavaScript: phone layouts only change how pages draw and take input.
- No new dependencies the pages load (still bundled locally, no CDNs); icons from the bundled Font Awesome.
- Desktop layouts and mouse and keyboard controls stay as they are; every phone rule is behind a width or
  `pointer: coarse` query, or `pointerType === 'touch'`.
- The print layout of the Match view.

## 6. Decisions (agreed with the owner, November 2026)

1. **Smallest width supported:** 360px.
2. **The automated phone check:** Playwright (Python), development only; its Chromium is installed in `tests.yml`
   and `release.yml`. On a PC without it the tests use Chrome or Edge if installed, else they are skipped.
3. **Header on phones:** a menu button that opens the links.
4. **Analytics matrix on phones:** one attacker at a time as a list, the full grid one switch away.
5. **Play on a phone in portrait:** the board on top, the armies and the log as tabs.
6. **Install to the home screen:** in this release (step h).

## 7. What was built (November 2026)

Where the build differs from section 3, it says so.

- **a. Shared rules** (`style.css`, end: "Phones and touch"; `app.js`: the menu, `InfoPopover`, `TableCards`;
  `core.js`: `infoButton`, `cellLabels`). The header links wrap above 900px and go behind the menu button at 900px
  and below. On touch screens (`pointer: coarse`) buttons, selects and fields are at least 44px, ticks 24px and
  field text 16px (with `!important`: a floor over every page's smaller sizes). Pop-ups are full-screen on phones
  with their buttons pinned to the bottom. Tables: `.table-scroll.sticky-first` (number grids) or
  `table.cards-on-phone` with `data-auto-labels` (lists: each cell labelled with its column heading, kept up to
  date as script redraws the rows). Grid columns get `min-width: 0` so a wide table scrolls in its own box.
  *Not done:* the page's name beside the menu button (the menu marks it instead).
- **b. Simulator.** Rule conditions are a tap-for-info ⓘ (also in Analytics); weapon names keep a readable
  width; smaller result tiles. *Instead of a Run button fixed to the bottom:* a run on a phone scrolls to the
  results.
- **c. Armies and Match view.** The army's units as cards, the "!" problems as an ⓘ; the wargear pop-up full
  screen. The Match view needed nothing beyond the shared rules. *Not done:* a points total and a phase filter
  that stay at the top while scrolling.
- **d. Analytics.** The conditions bar as label / dropdown pairs in two columns (*not a pop-up*); the matrix as a
  list on phones (`matrixListHtml`: an attacker picker with previous / next, the army's total included, each
  defender a row, weapons under it with Show weapons; List / Grid switch); the cell detail full-screen.
- **e. The other pages.** Data tab: faction, stratagem and rule lists as cards (a faction's rules and
  stratagems nested inside its card), units, weapons and profiles scrolling with the name pinned, tabs scrolling
  sideways. Players as cards. Scenarios needed only the shared rules; its chart has no toolbar on touch.
- **f. Play, outside the board** (`play.css`, end; `play.js`: `PHONE`, `renderPhoneTabs`). Tabs under the board
  (each army by name, then the log; the acting player's army until one is picked). The selected unit's details
  in a sheet over the bottom 40% of the screen; opening it scrolls the board into view above it. *Also:* Next
  phase sits full-width under the board on phones (over the small board it covered the bottom deployment zone).
- **g. Play board, touch** (`play.js`: `TOUCH`, `touches`, `startPinch`, `longPress`, `modelNear`,
  `cancelPointer`, `zoomBy`; `core.js`: `playPinch`, `nearestWithin`). Two fingers pinch and pan (a move in
  progress is dropped); a finger starts a drag only after 8px; held still for half a second on a model it shows
  the unit's card; a finger within 22px of a base picks that model; zoom +/- and a **One model** switch in the
  toolbar on touch screens (*in the toolbar, not the unit's sheet*, so it works in every phase, as Shift does),
  and Spin model buttons under the turn buttons once a model is picked. The battlefield editor drops a cancelled
  drag and ignores a second finger. *Not needed:* zoom, rotate and resize in the editor (it has none on the
  desktop either: turning is already buttons).
- **h. Home screen.** `static/manifest.webmanifest` (served as `application/manifest+json`), icons drawn by
  `scripts/make_app_icons.py` (an orange cube; no Games Workshop art), Apple's tags. No service worker: Chrome
  may offer it as a shortcut rather than an installed app; that and push notifications come with the phone app
  (scope option C).
