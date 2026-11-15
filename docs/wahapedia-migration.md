# Moving from BSData to Wahapedia

BSData's wh40k-11e repository was taken down (DMCA) in November 2026. Wahapedia's data export becomes the
only source of units, weapons, points, detachments and enhancements, as it already is for stratagems and
rules. The last BSData download (commit `b8667d4`, 2026-10-19) is backed up outside the repo, at
`F:\BSData-backup\` on the owner's PC. It is used only to build the ID map (step 1), never shipped or
committed.

## Decisions (agreed with the owner, 2026-11-15)

1. **BSData is removed completely**: the importer (`bsdata.py`), "Download latest" (`bsdata_download.py`),
   the folder picker for it, `bsdata_cache.json` and the BSData fixtures all go. Nobody can import BSData
   files any more.
2. **Wargear is simple options**: a unit gets its default loadout (Wahapedia's `loadout` text against its
   `Datasheets_wargear` profiles), and the other weapons on its datasheet are tickable extras, with
   Wahapedia's option text (`Datasheets_options`) shown beside them. There are no per-option limits,
   checks or wargear points. `wargear.py`'s option tree, `Unit.wargear`, `stat_changes` and
   `weapon_swaps` go.
3. **Old IDs are mapped**, not dropped: saved armies, comparisons, games, app data and share codes keep
   working.

## What Wahapedia gives (the export's files)

| Needed for | File(s) |
|---|---|
| Factions | `Factions.csv` (Space Marine chapters are one faction, "Space Marines", with chapter keywords) |
| Units | `Datasheets.csv` (`legend`, `role`, `loadout`, `is_support`, `virtual`), `Datasheets_models.csv` (M T Sv inv W Ld OC per model line), `Datasheets_keywords.csv` |
| Weapons | `Datasheets_wargear.csv` (per datasheet: A, BS/WS, S, AP, D, range, abilities in `description`) |
| Loadout | `Datasheets.loadout` ("This model is equipped with: …") and `Datasheets_unit_composition.csv` |
| Wargear options | `Datasheets_options.csv` (text only) |
| Points | `Datasheets_models_cost.csv` (cost by model count; some rows are "your 1st to 2nd units cost") |
| Leaders | `Datasheets_leader.csv` (who can lead whom) and the Leader ability text in `Datasheets_abilities.csv` |
| Abilities | `Datasheets_abilities.csv` + `Abilities.csv` (core, faction, datasheet) |
| Detachments | `Detachments.csv` (`dp`, `force_disposition`, `type`: leave out Boarding Actions etc.), `Detachment_abilities.csv` |
| Enhancements | `Enhancements.csv` (cost, detachment, `upgrade`, `support_leader`), `Datasheets_enhancements.csv` (who may take it) |

Each datasheet carries its own weapon rows, so the importer merges a faction's weapons with the same name
and profile into one weapon record (weapons belong to a faction).

## Steps

1. **ID map** (one-off script, `scripts/make_bsdata_id_map.py`, run against the backup): match BSData
   factions, units, weapons, detachments and enhancements to Wahapedia's by faction and name (normalised
   punctuation and case, profile as tie-break for weapons). Writes `data/bsdata_id_map.json`
   (BSData stable key → Wahapedia ID, or faction + name for weapons: IDs and names only, no BSData
   content) and a report of what didn't match.
   **Done** (2026-11-15, BSData `b8667d4` against Wahapedia's export of 2026-11-12): all 37 factions
   (chapters → Space Marines, Titanicus Traitoris → Adeptus Titanicus), 2,360 of 3,277 unit records,
   8,370 of 9,828 weapon profiles, 662 of 674 detachments, 1,633 of 1,861 enhancements. What's left is
   almost all Legends (Forge World / Heresy units, repeated in each chapter catalogue) and Crucible
   units, which Wahapedia's 11th-edition export doesn't have, plus BSData's unfinished "Deathwatch
   Support (ITS NOT READY)" detachment; about 180 weapon records on matched units have no Wahapedia
   weapon. Variants Wahapedia folds into one datasheet are mapped to it (four Soul Grinders → Soul
   Grinder, Spore Mines (Biovore) → Spore Mines), and weapons named differently to the one with the
   same profile on the carrier's datasheet (Agonizer → Agoniser). Step 3 must deal with saved records
   whose unit has no match (keep them flagged, or drop them from the army with a note).
2. **Importer**: `wahapedia_units.py` reads the datasheet files into the records `bsdata.import_folder`
   made, each with its stable key (`_key`), so `data_store._add_bsdata` fills the same tables. Fields and
   columns keep their names (`bsdata_id` holds the Wahapedia ID; imported factions keep `source`
   'bsdata'), as the package keeps its own; renaming them is step 5's cleanup.
   **Done** (2026-11-15). `reference.load` takes the units from Wahapedia whenever its folder has the
   datasheet files (`wahapedia_units.has_datasheets`; `Reference.units_source`), else still from BSData
   until step 4 removes it; "Download latest" for Wahapedia now fetches them too
   (`wahapedia_download.DOWNLOAD_FILES`). Before the first rebuild from Wahapedia it runs
   `carry_over_database` (report in `carry_over_report.json` next to the app data, for the Setup page)
   and upgrades a version 2 app data JSON to version 3, written back at once; `army_share` writes
   version 2 codes and reads version 1 codes through `share_payload`. Tests: `tests/test_wahapedia_units.py`
   on a made-up export with datasheets (`tests/fixtures/wahapedia_units`, from
   `make_wahapedia_unit_fixtures.py`; `tests/fixtures/wahapedia` stays rules-only so the other tests
   keep the BSData fixtures until step 6).
   Against BSData on the real export (1,015 non-Legends units matched by the ID map): T/Sv/W differ on
   15, all units with several stat lines (kill teams, Fabius Bile), points on 8 (Wahapedia's newer),
   sizes on 4; Feel No Pain on about 80, mostly BSData counting conditional ones ("against psychic
   attacks") that Wahapedia gives as text; Knights' 5+ invulnerable saves are "ranged attacks only" on
   Wahapedia, so they become that modifier. An end-to-end start on copies of the owner's database and
   app data took 3 s, carried both armies over and priced them (985 and 1,000 points) with no unit
   problems; Match view and the Simulator work.
   **Gaps left** (for step 5 unless noted): wargear option points ("per Multi-melta", 92 datasheets)
   aren't priced; Upgrades that several datasheets can take (69) count as enhancements; Wahapedia has
   no Unique Tags and no "max N in the army" (the core rule applies); kill-team loadouts split by
   weapon ("Every Kill Team Intercessor with plasma incinerator") count one model each; the Setup page
   and messages still said BSData (done in step 4); `DEFENSIVE_TEXT` / `parse_base` are copied from `bsdata.py`
   and lose their originals in step 6.
3. **Carrying over** (on first start after upgrading, once): re-key `stable_ids` rows from BSData keys to
   the Wahapedia keys in the map, so every saved database ID stays the same; rewrite saved armies'
   `detachment_keys` and `enhancement`, drop their `wargear` choices; rewrite the app data's BSData IDs
   (`schema_version` 3, same field names). Share codes made before the move are translated through the
   map. Unmatched records are listed on the Setup page.
   **Done** (2026-11-15): `carry_over.py` (`carry_over_database`, `upgrade_app_data`, `share_payload`;
   tests in `tests/test_carry_over.py`), with the key scheme in `wahapedia.py` (`stable_key`,
   `weapon_key`, `weapon_id`, `weapon_profile`), called by step 2. Where several BSData records became
   one Wahapedia record (each chapter's copy of a unit, the chapters themselves), the lowest database ID
   is kept and saved records using the others are changed to it. A saved army's unit with no match
   keeps its entry with `missing` (its old name), kept by `clean_army`. Wargear choices are dropped, not
   turned into ticks (that waits for step 5's option format). The map ships in the build
   (`combat_sim.spec`). A dry run on the owner's database re-keyed 13,062 rows (7,164 merged), carried
   both saved armies over with every unit matched, and changed nothing when run again. Showing the
   report on the Setup page is step 4.
4. **Setup page and downloads**: one "Download latest" for Wahapedia, which now also fetches the
   datasheet files; BSData's section, settings (`bsdata_dir`, `BSDATA_DIR`) and its job go. `/` redirects
   to Setup until Wahapedia data is loaded.
   **Done** (2026-11-15): the Setup page has one "Download latest" (Wahapedia: units, rules and stratagems;
   the job is `wahapedia`), the BSData folder, browse, download and re-import routes and their page sections
   are gone with `bsdata_download.py` and `folder_dialog.py` (the build now excludes tkinter, and no route is
   `@desktop_only` any more); the `bsdata_dir` and `download` settings are ignored; skipping setup is
   `POST /api/setup/skip`. `/api/data/status` gives `units_from` and, for the host only, `carry_over` (the
   report, with the time it ran), shown on the Setup page as "Moved to Wahapedia's data". The footer credits
   Wahapedia for units, rules and stratagems (`reference.label`: "updated <date>"). `reference.load(app,
   wahapedia_too=True)` reloads both; units come from Wahapedia, or, only when its folder has no datasheets
   and `BSDATA_DIR` is set, from the tests' BSData fixtures (no user setting reaches that: it goes in step 6
   with `bsdata.py`). No datasheet files yet isn't an error (`load_wahapedia_units`). Tests:
   `tests/test_setup.py` rewritten for this. Checked on copies of the owner's data with the real export.
   **Left for step 5**: the Data page's "BSData" source labels and read-only messages, the `bsdata-status`
   CSS class names, `paths.move_old_folder`'s handling of the old `bsdata_dir` setting.
5. **Pages**: Armies, Match view, Analytics, Simulator and Play read loadouts and options the simple way;
   remove wargear tree UI and conditions (`ability_conditions`, `hidden_when` where Wahapedia has none).
   **Done** (2026-11-15): `loadouts.py` is simple wargear. An army entry's `wargear` is how many models carry
   each weapon, `{'ranged:<id>': n, 'melee:<id>': n}` (None: the datasheet's loadout scaled to the size). The
   Armies page's Wargear popup (`POST /api/armies/wargear`, for every unit now) lists the loadout and then the
   options, each with a count, under the datasheet's option text (`options_text`); there are no limits and no
   points. `price_army` turns the counts into `loadout` rows, which Analytics (the roster), Match view and
   Play already read; `match_view.unit_weapons` and `snapshot._weapons` take `entry['loadout']` first. Share
   codes (version 2) carry the counts as `weapons` by the weapons' stable keys. `wargear.default_used` also
   reads Wahapedia's "Weapon – profile" (en dash), so later profiles start unticked. The Data page, the Armies
   page and the read-only errors say "downloaded" or "Wahapedia" instead of BSData. Tests: the simple-wargear
   cases in `tests/test_wahapedia_units.py`; the BSData tree tests reach the tree through
   `conftest.tree_wargear` until step 6.
   **Left for step 6**: BSData's option tree (`wargear.py` except `default_used`, `armies.unit_wargear`, the
   tree branches in `price_army`, `army_share` and `match_view`), `ability_conditions` / `hidden_when` (always
   empty from Wahapedia) and `bsdata.py` go with the BSData fixtures. Of step 2's gaps, kill-team loadouts can
   now be set right in the popup; wargear options' points ("per Multi-melta") are still not added.
6. **Tests and fixtures**: made-up Wahapedia datasheet files in `tests/fixtures/wahapedia`
   (`make_wahapedia_fixtures.py`), replacing `tests/fixtures/bsdata`; remove `test_wargear.py`'s tree
   tests; update `CLAUDE.md`, `docs/architecture.md`, the credits, and `docs/self-hosting.md`.
   **Done** (2026-11-15): one generator, `tests/fixtures/make_wahapedia_fixtures.py`, writes the whole
   made-up export to `tests/fixtures/wahapedia` (WAHAPEDIA_FIXTURES) and the same without `Stratagems.csv`
   to `tests/fixtures/wahapedia_units` (UNIT_FIXTURES: units only, for tests that ran on BSData alone). Its
   datasheets reproduce the old BSData fixtures (same names, stats, points, IDs such as `u-void` and
   `d-vanguard`), plus the cases step 2 needed. `make_client(data, wahapedia=None)` has no `bsdata=` any
   more. Removed: `bsdata.py`, `wargear.py` (`default_used` moved to `loadouts.py`), `tests/fixtures/bsdata`
   and its generator, `make_wahapedia_unit_fixtures.py`, `test_bsdata.py`, `test_wargear.py`,
   `docs/bsdata-import-findings.md`, the option-tree code in `armies.py`, `army_share.py`, `match_view.py`
   and `play/snapshot.py`, BSData's conditions (`Unit.ability_conditions`, `Enhancement.hidden_when`,
   `armies.hidden_abilities`, `match_view.without_abilities`; Play still reads a pre-3.0 game's
   `hidden_abilities`) and `Unit.wargear`; `BSDATA_DIR` and the BSData cache. Tests of features Wahapedia
   doesn't have went with them (option trees, Unique Tags, per-enhancement limits, conditional abilities);
   the rest now expect the export's values (Void Warriors come in 5 or 10, not 5 to 10). Changed on the
   way: the importer's army rules are only the faction abilities datasheets list as 'Faction' (as
   wahapedia.py reads them); every enhancement checks Epic Heroes first; an empty base size isn't
   reported; a datasheet file missing a column is reported by name; a pre-3.0 app data file stays version
   2 until the export is downloaded (`Reference.data_version`). Updated: `CLAUDE.md`,
   `docs/architecture.md`, `docs/technical-overview.md`, `docs/user-guide.md`, `docs/self-hosting.md`,
   `docs/releasing.md`, `README.md`, the Dockerfile and compose comments. 1,062 tests pass (phone and
   JavaScript included).
   **Left**: `engagement.stat_changes` still accepts characteristic changes in requests (nothing in the
   data gives them now); wargear option points; the `bsdata_*` names (kept on purpose: renaming them would
   need a migration of saved data for no gain); old release notes and planning docs mention BSData as
   history.
7. **Release** as 3.0.0 (saved data and app data format change).

## Open questions

- Does the shipped ID map (BSData IDs only) need the owner's sign-off, or should old share codes simply
  stop working? (Default: ship it, as it holds no BSData content.)
- Wahapedia's datasheet IDs can change when a datasheet is reissued; check whether `stable_ids` should be
  keyed by ID or by faction + name.
