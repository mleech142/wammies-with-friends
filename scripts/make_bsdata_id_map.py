"""
Write data/bsdata_id_map.json: which Wahapedia record each BSData record became, so saved armies,
comparisons, games, app data and share codes made with BSData keep working after the move to
Wahapedia (docs/wahapedia-migration.md, step 1). Run once, from the last BSData import:

    python scripts/make_bsdata_id_map.py BSDATA_CACHE.json WAHAPEDIA_FOLDER [REPORT.txt]

BSDATA_CACHE.json is the app's bsdata_cache.json (the imported catalogues); WAHAPEDIA_FOLDER holds the
full Wahapedia export (Datasheets*.csv as well as the files the app downloads). Neither is committed.

The map holds IDs and names only, never BSData's text or profiles. Its sections are keyed by the
BSData record's stable key without its kind (stable_ids: '<catalogue>/<entry>'; factions by catalogue):
- factions: Wahapedia faction ID. Space Marine chapters are all 'SM', as on Wahapedia.
- units, detachments, enhancements: Wahapedia's ID of the datasheet, detachment or enhancement.
- ranged_weapons, melee_weapons: {'faction', 'name'} (Wahapedia faction ID and the weapon's name as
  wahapedia.name_key reads it): Wahapedia lists weapons per datasheet, and a faction's weapons with
  the same name become one record. 'profile' is added when the faction has the name with different
  profiles, picking the one that matches (wahapedia.weapon_key makes the record's key from these).
Records are matched by faction and name (wahapedia.name_key), Legends by Legends; what doesn't match
is left out and listed in the report.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from combat_sim.wahapedia import name_key, profile_text, read_table, weapon_profile  # noqa: E402

# BSData factions whose name isn't a Wahapedia faction's (by name_key). Chapters are handled by
# chapter_faction; anything else unlisted goes to the faction holding most of its units.
FACTION_NAMES = {
    'agentsoftheimperium': 'AoI',
    'unalignedforces': 'UA',
}
CHAPTERS = {'blacktemplars', 'bloodangels', 'darkangels', 'deathwatch', 'imperialfists', 'ironhands',
            'ravenguard', 'salamanders', 'spacewolves', 'ultramarines', 'whitescars'}


def unit_key(name):
    """A unit's name without BSData's ' [Legends]'."""
    return name_key(name.replace('[Legends]', ''))


def bsdata_profile(weapon, kind):
    """wahapedia.profile_text of a BSData weapon (BSData writes AP as a positive number)."""
    skill = weapon.get('ballistic_skill') if kind == 'ranged' else weapon.get('weapon_skill')
    range_ = (weapon.get('range_inches') or 'n/a') if kind == 'ranged' else None
    return profile_text(weapon.get('attacks'), skill, weapon.get('strength'), weapon.get('armor_penetration'),
                        weapon.get('damage'), range_)


def load_wahapedia(folder):
    folder = Path(folder)
    table = {name: read_table(folder / f'{name}.csv') for name in (
        'Factions', 'Source', 'Datasheets', 'Datasheets_wargear', 'Detachments', 'Enhancements', 'Last_update')}
    legends_sources = {s['id'] for s in table['Source'] if 'legends' in s['name'].lower()}
    for d in table['Datasheets']:
        d['is_legends'] = d['source_id'] in legends_sources
    wargear = defaultdict(list)
    for w in table['Datasheets_wargear']:
        wargear[w['datasheet_id']].append(w)
    table['wargear'] = wargear
    return table


def choose(candidates, faction, legends=None):
    """The best of several Wahapedia records with the right name: the right faction, then Legends."""
    def score(record):
        return (record.get('faction_id') == faction,
                legends is None or record.get('is_legends') == legends,
                record.get('virtual') != 'true')
    return max(candidates, key=score) if candidates else None


def make_map(cache, wahapedia):
    data = cache['result']['data']
    report = []
    catalogue = {f['id']: f['bsdata_id'] for f in data['factions']}
    names = {f['bsdata_id']: f['name'] for f in data['factions']}
    wfactions = {name_key(f['name']): f['id'] for f in wahapedia['Factions']}

    datasheets = defaultdict(list)
    for d in wahapedia['Datasheets']:
        datasheets[name_key(d['name'])].append(d)

    # Factions: by name, chapters as Space Marines, then the rest by where their units are
    factions = {}
    for f in data['factions']:
        key = name_key(f['name'])
        factions[f['bsdata_id']] = 'SM' if key in CHAPTERS else (wfactions.get(key) or FACTION_NAMES.get(key))
    for f in data['factions']:
        if factions[f['bsdata_id']] is None:
            found = Counter(d['faction_id'] for u in data['units'] if u['faction_id'] == f['id']
                            for d in datasheets.get(unit_key(u['name']), []))
            if found:
                factions[f['bsdata_id']] = found.most_common(1)[0][0]
                report.append(f'faction {f["name"]}: no Wahapedia faction of that name; its units are in '
                              f'{found.most_common(1)[0][0]}')
            else:
                report.append(f'faction {f["name"]}: NOT MATCHED')
    factions = {k: v for k, v in factions.items() if v}

    def stable(record):
        return f'{catalogue[record["faction_id"]]}/{record["bsdata_id"]}'

    def faction_of(record):
        return factions.get(catalogue[record['faction_id']])

    # Units: by name in the faction (any faction if it isn't there, such as allies' datasheets)
    units, unit_sheet = {}, {}
    for u in data['units']:
        legends = str(u.get('legends')) == 'True' or '[Legends]' in u['name']
        sheet = choose(datasheets.get(unit_key(u['name']), []), faction_of(u), legends)
        if sheet is None:  # A variant Wahapedia folds into one datasheet: 'Spore Mines (Biovore)', 'Khorne Soul Grinder'
            plain = unit_key(re.sub(r'\s*\([^)]*\)\s*$', '', u['name'].replace('[Legends]', '')))
            sheet = choose(datasheets.get(plain, []), faction_of(u), legends)
            if sheet is None and not legends:  # Legends variants ('Deredeo Dreadnought') are other units
                sheet = choose([d for key, found in datasheets.items() if len(key) > 4 and plain.endswith(key)
                                for d in found if d['faction_id'] == faction_of(u)], faction_of(u), legends)
            if sheet is not None:
                report.append(f'unit {names[catalogue[u["faction_id"]]]} / {u["name"]}: taken as {sheet["name"]}')
        if sheet is None:
            report.append(f'unit {names[catalogue[u["faction_id"]]]} / {u["name"]}: NOT MATCHED')
            continue
        if sheet['faction_id'] != faction_of(u):
            report.append(f'unit {names[catalogue[u["faction_id"]]]} / {u["name"]}: found in {sheet["faction_id"]}')
        units[stable(u)] = sheet['id']
        unit_sheet[u['id']] = sheet

    # Weapons: through the units carrying them, else by name anywhere in the faction
    weapons = {}
    sheet_faction = {s['id']: s['faction_id'] for s in wahapedia['Datasheets']}
    for kind, section in (('ranged', 'ranged_weapons'), ('melee', 'melee_weapons')):
        carried = defaultdict(list)
        for u in data['units']:
            for field in (f'{kind}_weapons', f'{kind}_options'):
                for entry in u.get(field) or []:
                    carried[entry['weapon_id'] if isinstance(entry, dict) else entry].append(u['id'])
        by_faction = defaultdict(list)  # (faction, name_key) -> Wahapedia rows
        for sheet in wahapedia['Datasheets']:
            for row in wahapedia['wargear'][sheet['id']]:
                if (row['type'] == 'Melee') == (kind == 'melee'):
                    by_faction[(sheet['faction_id'], name_key(row['name']))].append(row)
        mapped = {}
        for w in data[section]:
            key, faction = name_key(w['name']), faction_of(w)
            rows = [r for uid in carried.get(w['id'], []) if uid in unit_sheet
                    for r in wahapedia['wargear'][unit_sheet[uid]['id']]
                    if name_key(r['name']) == key and (r['type'] == 'Melee') == (kind == 'melee')]
            rows = rows or by_faction.get((faction, key), [])
            if not rows:  # Named differently ('Multi-melta HUNTER:Monster/Vehicle'): the carriers' one weapon with its profile
                mine = bsdata_profile(w, kind)
                same = [r for uid in carried.get(w['id'], []) if uid in unit_sheet
                        for r in wahapedia['wargear'][unit_sheet[uid]['id']]
                        if (r['type'] == 'Melee') == (kind == 'melee') and weapon_profile(r) == mine]
                if len({name_key(r['name']) for r in same}) == 1:
                    rows = same
                    report.append(f'{kind} weapon {names[catalogue[w["faction_id"]]]} / {w["name"]}: taken as '
                                  f'{same[0]["name"]} (same profile)')
            if rows:
                faction = sheet_faction[rows[0]['datasheet_id']]
                key = name_key(rows[0]['name'])
            else:
                orphan = not any(uid in unit_sheet for uid in carried.get(w['id'], []))
                report.append(f'{kind} weapon {names[catalogue[w["faction_id"]]]} / {w["name"]}: NOT MATCHED'
                              + (' (only on unmatched units)' if orphan else ''))
                continue
            entry = {'faction': faction, 'name': key}
            profiles = {weapon_profile(r) for r in by_faction.get((faction, key), rows)}
            if len(profiles) > 1:
                mine = bsdata_profile(w, kind)
                entry['profile'] = mine if mine in profiles else weapon_profile(rows[0])
                if mine not in profiles:
                    report.append(f'{kind} weapon {names[catalogue[w["faction_id"]]]} / {w["name"]}: profile '
                                  f'{mine} not on Wahapedia, took {entry["profile"]}')
            mapped[stable(w)] = entry
        weapons[section] = mapped

    # Detachments: by faction and name (any faction if not there); enhancements within them
    wdetachments = defaultdict(list)
    for d in wahapedia['Detachments']:
        wdetachments[name_key(d['name'])].append(d)
    detachments, detachment_of = {}, {}
    for d in data['detachments']:
        found = choose(wdetachments.get(name_key(d['name']), []), faction_of(d))
        if found is None:
            report.append(f'detachment {names[catalogue[d["faction_id"]]]} / {d["name"]}: NOT MATCHED')
            continue
        detachments[stable(d)] = found['id']
        detachment_of[d['bsdata_id']] = found['id']

    wenhancements = defaultdict(list)
    for e in wahapedia['Enhancements']:
        wenhancements[name_key(e['name'])].append(e)
    enhancements = {}
    for e in data['enhancements']:
        candidates = wenhancements.get(name_key(e['name']), [])
        wanted = {detachment_of.get(k) for k in e.get('detachment_keys') or []} - {None}
        in_detachment = [c for c in candidates if c['detachment_id'] in wanted]
        found = choose(in_detachment or candidates, faction_of(e))
        if found is None:
            report.append(f'enhancement {names[catalogue[e["faction_id"]]]} / {e["name"]}: NOT MATCHED')
            continue
        enhancements[stable(e)] = found['id']

    result = {
        'made_from': {
            'bsdata_catalogues': sorted(cache['result']['source'].get('catalogues', {})),
            'wahapedia_last_update': wahapedia['Last_update'][0]['last_update'],
        },
        'factions': factions,
        'units': units,
        'ranged_weapons': weapons['ranged_weapons'],
        'melee_weapons': weapons['melee_weapons'],
        'detachments': detachments,
        'enhancements': enhancements,
    }
    totals = {section: (len(result[section]), len(data[source])) for section, source in (
        ('factions', 'factions'), ('units', 'units'), ('ranged_weapons', 'ranged_weapons'),
        ('melee_weapons', 'melee_weapons'), ('detachments', 'detachments'), ('enhancements', 'enhancements'))}
    return result, report, totals


def main(argv):
    if len(argv) not in (3, 4):
        sys.exit(__doc__)
    cache = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    result, report, totals = make_map(cache, load_wahapedia(argv[2]))
    out = Path(__file__).resolve().parent.parent / 'data' / 'bsdata_id_map.json'
    out.write_text(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    for section, (done, of) in totals.items():
        print(f'{section:15} {done:5} of {of:5} matched')
    if len(argv) == 4:
        Path(argv[3]).write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(f'{sum("NOT MATCHED" in line for line in report)} not matched; wrote {out}')


if __name__ == '__main__':
    main(sys.argv)
