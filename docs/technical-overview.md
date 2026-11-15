# Technical overview

For anyone working on the code: how to run and test it, where the data comes from, how the pieces fit, and how releases are made. For using the app, see the [user guide](user-guide.md).

**Contents:** [At a glance](#at-a-glance) · [Run from source](#run-from-source) · [Tests](#tests) · [Data](#data) · [Architecture](#architecture) · [Project structure](#project-structure) · [Conventions](#conventions) · [Releases](#releases)

---

## At a glance

| | |
| --- | --- |
| **What** | A local web app (Flask) for Warhammer 40,000 11th edition combat maths, army lists and army analysis |
| **Backend** | Python 3.10+, Flask, Flask-SQLAlchemy, SQLite, NumPy, waitress |
| **Frontend** | Server-rendered Jinja pages with vanilla JavaScript; Plotly.js and Font Awesome Free 7.3.1 bundled in `static/vendor` (works offline) |
| **Game data** | The [Wahapedia data export](https://wahapedia.ru/wh40k11ed/the-rules/data-export) (units, weapons, points, wargear options, detachments, enhancements, stratagems and rules), downloaded by the user, never committed or shipped (BSData's catalogues before 3.0) |
| **Maths** | Mirrors the original `40KCombatSimulator_v2.xlsx` formula for formula ([parity notes](excel-parity.md)); analytical and Monte Carlo engines |
| **Shipping** | Windows and Linux builds made by PyInstaller and published together by GitHub Actions on a version tag; tests run on Linux for every push |

---

## Run from source

```bash
pip install -r requirements.txt
python run.py              # --debug for Flask's debugger while developing (never in a release)
```

The browser opens <http://127.0.0.1:5000> (or the next free port; the console says which). The app only listens on this computer. From source it reads and writes `data/` in the repository; the exe uses `%APPDATA%\Wammies With Friends\` instead (`paths.py`).

Shortcuts: `launcher.bat` (Windows) or `./launcher.sh` (Linux/Mac) create a virtual environment, install the requirements and start the app. On Debian/Ubuntu you may need `sudo apt install python3-venv` first, and `python3-tk` for the Setup page's Browse button (optional: you can type a folder path instead).

On first run the app opens **Setup**: download Wahapedia's export there.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests                       # Python and (with Node 18+) the JavaScript tests
node --test "tests/js/*.test.js"             # JavaScript only
python -m coverage run --source=src/combat_sim -m pytest tests && python -m coverage report
```

- **Isolated data:** tests never touch `data/`. Each starts the app on its own temporary data file (`make_client` in `tests/conftest.py`).
- **Fixtures:** a made-up Wahapedia export, from `tests/fixtures/make_wahapedia_fixtures.py`. Never put real game data in tests.
- **Parity:** the spreadsheet's cached results are fixtures, and analytical and Monte Carlo are checked against each other.
- **JavaScript:** tests cover the pure page helpers in `static/js/core.js`.

---

## Data

| Source | Holds | Where |
| --- | --- | --- |
| **Wahapedia export** | Factions, datasheets, weapons, loadouts, points by unit size, wargear options, detachments (with Detachment Points and dispositions), enhancements; stratagems, detachment rules, army rules (text) | Downloaded on Setup into `wahapedia/`; imported by `wahapedia_units.py` and `wahapedia.py` on every start |
| **App data JSON** | Custom factions, units and weapons; hand-written rules; edits to how Wahapedia's rules are read; modifiers added to downloaded units; leader-buff edits; keywords; benchmark target profiles | `data/app_data.json`: committed and shipped; every Data-tab edit is written back |
| **Database** | A working copy of all of the above (rebuilt on start) plus saved comparisons, armies, games and stable IDs | `combat_sim.db` (SQLite) |

Downloaded records keep stable database IDs across downloads (the `stable_ids` table), so saved armies and comparisons survive updates. Data saved before 3.0 (BSData's IDs) is moved to Wahapedia's on the first start with the export (`carry_over.py`). Reference tables are rebuilt on every start, so their schema can change freely; persistent tables only gain new nullable columns automatically.

---

## Architecture

```text
 Wahapedia datasheets ─► wahapedia_units.py ─┐
 Wahapedia rules ─► wahapedia.py ─────────────┼─► data_store.merge_data ─► SQLite (reference tables)
 data/app_data.json ──────────────────────────┘                                │
                                                                       ▼
 Browser pages ──fetch──► Flask routes (routes/) ──► simulation.py (resolve → analytical / Monte Carlo)
                                   │
                                   ├─► armies.py   (army lists: pricing and checks)
                                   ├─► loadouts.py (wargear: how many models carry each weapon)
                                   └─► rules_text.py (rule text → modifiers)
```

| Module | Does |
| --- | --- |
| `app.py` | App factory: config, data loading, error handlers |
| `routes/` | Every route (pages and JSON API), one module per area |
| `simulation.py` | The combat engine: `resolve()` turns a weapon and target into rolls; analytical and Monte Carlo engines, attached units |
| `wahapedia_units.py` | Wahapedia's datasheets: units, points, loadouts, wargear options, leaders, detachments, enhancements |
| `wahapedia.py` | Wahapedia's rules and stratagems, matched to the imported factions and detachments |
| `carry_over.py` | Moves data saved before 3.0 from BSData's IDs to Wahapedia's |
| `rules_text.py` | Reads rule text into modifiers (leaders, stratagems, detachment and army rules, enhancements) |
| `armies.py` | Army lists: points, Detachment Points, unit limits, leaders and support units, Warlord, enhancements, Analytics roster |
| `loadouts.py` | Wargear: a unit's loadout and options, and how many models carry each weapon |
| `data_store.py` | App data JSON format; merging Wahapedia's export and the app data; rebuilding tables; export |
| `models.py` | SQLAlchemy models |
| `static/js/core.js` | Pure page helpers (tested in Node); `app.js`, `analytics.js`, `armies.js` drive the pages |

The full module map, invariants and maintainability notes are in [architecture.md](architecture.md).

---

## Project structure

```text
wammies-with-friends/
├── src/combat_sim/          # The app (modules above), templates/ and static/
├── data/                    # app_data.json (committed); downloads, cache and database (local only)
├── tests/                   # pytest suite, fixtures/ (made-up game data), js/ (Node tests)
├── docs/                    # This overview, the user guide, architecture, parity, releasing, images/
├── archive/                 # Version 1 workbook, data and migration script
├── .github/workflows/       # release.yml: builds and publishes the Windows release on a version tag
├── run.py                   # Entry point (waitress; --debug for development)
├── combat_sim.spec          # PyInstaller build
└── requirements*.txt        # Runtime / test and build dependencies
```

---

## Conventions

- **Game rules live in Python only.** Pages get them from the API (points tables, keyword checks, army pricing, wargear forms); never re-implement a rule in JavaScript.
- **Pure page logic** goes in `static/js/core.js`, with a test in `tests/js/core.test.js`.
- **Every Data-tab write** commits and then rewrites the app data JSON (`save_data()`); any new write route must call it.
- **New engine features** go through `resolve()`, both engines, and must work for attached units.
- **Never commit or ship game data:** `data/wahapedia/` is gitignored. Keep the Wahapedia credit on the pages.
- **Wording:** say "modifier", never "mod", in UI text and identifiers.
- **Bundling:** anything new the pages load must be bundled locally (no CDNs), and anything new on disk added to `combat_sim.spec`.

More detail for contributors is in [`CLAUDE.md`](../CLAUDE.md).

---

## Releases

1. Bump `__version__` in `src/combat_sim/__init__.py`.
2. Add release notes in `docs/release-notes/vX.Y.Z.md`.
3. Commit, tag `vX.Y.Z` and push.

GitHub Actions then tests and builds on Windows and Linux and publishes both zips. A trial build without publishing: Actions → Release → *Run workflow*. Full steps and how the build works: [releasing.md](releasing.md).

---

*MIT licensed. A fan project, not affiliated with Games Workshop. Warhammer 40,000 is a trademark of Games Workshop Ltd.*
