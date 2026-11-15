"""
Factions, units, weapons, detachments and enhancements from Wahapedia's data export
(docs/wahapedia-migration.md, step 2), in the records bsdata.import_folder made, so the reference
tables are filled the same way (data_store.merge_data). Each record's `bsdata_id` holds its Wahapedia
ID (the field keeps its name, as the package does), and `_key` its stable_ids key (wahapedia.stable_key,
weapon_key). The files are those in DATASHEET_FILES, downloaded with the rest of the export
(wahapedia_download.py); nothing here is shipped.

How the export maps onto the app:

- **Factions** are Factions.csv's with datasheets (Space Marine chapters are all "Space Marines").
  Army rules are the faction's own abilities (Abilities.csv with its faction).
- **Units** are the datasheets (`virtual` ones left out). Legends datasheets (from a "Legends" source)
  get " [Legends]" after their name, as BSData's did. Stats come from the model line with the most models
  at the smallest size (Datasheets_models.csv, Datasheets_unit_composition.csv); an invulnerable save
  "against ranged attacks only" is a modifier, as BSData's was.
- **Points** are the "YOUR UNIT COSTS" (or "YOUR 1ST ... UNITS COST") block of Datasheets_models_cost.csv,
  one size per row; a later block ("YOUR 3RD+ UNIT COSTS") is the surcharge for later copies
  (`copy_points`). Wargear option costs ("per Multi-melta") aren't priced yet, and are reported.
- **Weapons** are Datasheets_wargear.csv's rows, one record per faction, kind, name and profile; a name
  with several profiles in one faction keeps its profile in its key. A unit's loadout is read from its
  "... is equipped with: ..." text against its composition (how many models each line covers); its
  other weapons are options. The option text (Datasheets_options.csv) is kept for the pages.
- **Abilities**: core ones by name and parameter ("Feel No Pain 5+", "Deep Strike"), faction ones by name,
  the rest as "Name: text". Feel No Pain, Stealth and the defensive texts the maths reads
  (DEFENSIVE_TEXT) become modifiers, as BSData's did. Wargear abilities are options, so they don't count.
- **Leaders and support units** (Datasheets_leader.csv) name the units they can join; leader buffs are
  parsed from the abilities (rules_text.parse_leader_buffs).
- **Detachments** are Detachments.csv's of no special type (Boarding Actions left out), with their
  abilities, DP and force dispositions; Wahapedia has no Unique Tags.
- **Enhancements** (Enhancements.csv) go on the datasheets Datasheets_enhancements.csv lists for them
  (`bearer_bsdata_ids`); an Upgrade for one datasheet is that unit's (`unit_bsdata_id`).
"""

import re
from collections import Counter, defaultdict
from pathlib import Path

from .rules_text import parse_enhancement, parse_leader_buffs, plain_text
from .simulation import check_keywords
from .wahapedia import (WahapediaError, markup, name_key, read_table, stable_key, weapon_id, weapon_key,
                        weapon_profile)

DATASHEET_FILES = ['Source.csv', 'Datasheets.csv', 'Datasheets_models.csv', 'Datasheets_wargear.csv',
                   'Datasheets_options.csv', 'Datasheets_unit_composition.csv', 'Datasheets_models_cost.csv',
                   'Datasheets_keywords.csv', 'Datasheets_leader.csv', 'Datasheets_enhancements.csv', 'Enhancements.csv']
NEEDED = DATASHEET_FILES + ['Factions.csv', 'Detachments.csv', 'Detachment_abilities.csv', 'Abilities.csv',
                            'Datasheets_abilities.csv', 'Last_update.csv']
FORCE_DISPOSITIONS = ('Take and Hold', 'Purge the Foe', 'Disruption', 'Reconnaissance', 'Priority Assets')
SPECIAL_DETACHMENTS = ('Boarding Actions',)  # Detachment types for other ways of playing

DEFENSIVE_TEXT = [
    (re.compile(r'^(?:this model|models in this unit|this unit) ha(?:s|ve) the feel no pain (\d)\+ ability\.?$', re.I),
     'fnp'),
    (re.compile(r'^each time an attack is allocated to (?:this model|a model in this unit), subtract 1 from the '
                r'damage characteristic of that attack\.?$', re.I),
     'Damage Modifier -1'),
    (re.compile(r'^(?:this model|models in this unit|this unit) ha(?:s|ve) an? (\d)\+ invulnerable save '
                r'against (melee|ranged) attacks\.?$', re.I),
     'only against'),
]


COLUMNS = {  # Each datasheet file's columns the import reads by name
    'Datasheets': ('id', 'name', 'faction_id', 'source_id', 'loadout', 'virtual'),
    'Datasheets_models': ('datasheet_id', 'line', 'name', 'M', 'T', 'Sv', 'inv_sv', 'W', 'Ld', 'OC', 'base_size'),
    'Datasheets_wargear': ('datasheet_id', 'line', 'name', 'description', 'range', 'type', 'A', 'BS_WS', 'S', 'AP', 'D'),
    'Datasheets_models_cost': ('datasheet_id', 'line', 'description', 'cost'),
    'Datasheets_unit_composition': ('datasheet_id', 'line', 'description'),
    'Datasheets_options': ('datasheet_id', 'line', 'description'),
    'Datasheets_keywords': ('datasheet_id', 'keyword'),
    'Datasheets_abilities': ('datasheet_id', 'line', 'ability_id', 'name', 'description', 'type', 'parameter'),
    'Datasheets_leader': ('leader_id', 'attached_id'),
}


def has_datasheets(folder):
    """True if the folder holds the export's datasheet files (not only the stratagems and rules)."""
    return folder is not None and all((Path(folder) / name).is_file() for name in DATASHEET_FILES)


class Result:
    """Like bsdata.ImportResult: data (the sections), report ([{'kind', 'faction', 'unit', 'detail'}]), source."""

    def __init__(self, data, report, source):
        self.data, self.report, self.source = data, report, source


# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------

def _int(text):
    """'5"' -> 5, '3+' -> 3, '-2' -> -2; None when not a number ('N/A', '-', '*')."""
    m = re.match(r'^\s*(-?\d+)', text or '')
    return int(m.group(1)) if m else None


def _plus(text):
    """'4+' or '4' -> 4; '', '-' or 'N/A' -> None."""
    return _int(text)


def _mm(value):
    size = float(value)
    return int(size) if size.is_integer() else size


def parse_base(text):
    """
    A base size ('32mm', '120 x 92mm', '60mm flying', 'Hull') as {'shape', 'length_mm', 'width_mm', 'text'}
    (plus 'flying'), as bsdata.parse_base gave; None when unreadable.
    """
    text = re.sub(r'\s+', ' ', (text or '').strip())
    if text.lower().startswith('hull') or text.lower().startswith('use model'):
        return {'shape': 'hull', 'text': text}
    m = re.match(r'^~?(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?))?\s*mm(?: oval)?( flying)?', text, re.I)
    if not m:
        return None
    length, width, flying = m.groups()
    length, width = _mm(length), _mm(width or length)
    base = {'shape': 'round' if length == width else 'oval', 'length_mm': length, 'width_mm': width}
    if flying:
        base['flying'] = True
    return {**base, 'text': text}


def _text(html_text):
    """Wahapedia's HTML as plain words, line breaks kept."""
    return plain_text(markup(html_text))


def singulars(key):
    """A name_key and what it is without a plural ending: 'disciples' -> {'disciples', 'disciple', 'discipl'}."""
    found = {key}
    for ending, keep in (('men', 'man'), ('ies', 'y'), ('es', ''), ('s', '')):
        if key.endswith(ending) and len(key) > len(ending) + 2:
            found.add(key[:-len(ending)] + keep)
    return found


def singular(key):
    """The shortest singular of a name_key that is still a word's stem ('intercessors' -> 'intercessor')."""
    return key[:-1] if key.endswith('s') and len(key) > 3 else key


def same_name(a, b):
    """Two names the same, ignoring case, punctuation, a plural and a trailing 'model(s)'."""
    a, b = (re.sub(r'models?$', '', name_key(x)) for x in (a, b))
    return bool(singulars(a) & singulars(b))


class Report:
    def __init__(self):
        self.items = []

    def add(self, kind, faction, unit, detail):
        self.items.append({'kind': kind, 'faction': faction, 'unit': unit, 'detail': detail})


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def composition(lines):
    """
    [(name, smallest count)] from a datasheet's composition lines ('1 Intercessor Sergeant', '4-9 Intercessors',
    '1 Shock Trooper Sergeant and 9 Shock Troopers'). Of alternatives ('OR', 'One of the following:'), the first.
    """
    found, choosing = [], False
    for line in lines:
        text = _text(line).strip()
        if text.upper() == 'OR':
            break
        if text.lower().startswith('one of the following'):
            choosing = True
            continue
        for part in re.split(r',\s*|\s+and\s+(?=\d)', text):
            m = re.match(r'^\s*(\d+)(?:\s*-\s*\d+)?\s+(.+?)\s*$', part)
            if m:
                name = re.sub(r'\s+[-–—]\s+.*$', '', re.sub(r'\s+models?$', '', m.group(2), flags=re.I))
                found.append((name, int(m.group(1))))
        if choosing and found:
            break
    return found


def points_blocks(rows):
    """
    (sizes, copy_points, wargear rows) from a datasheet's Datasheets_models_cost.csv rows: sizes
    [{'models', 'points'}] of the first unit-cost block; copy_points as bsdata.copy_surcharges gave
    ([0, 0, 15]: the third and later copies cost 15 more; [] when none); the "per X" wargear rows.
    """
    blocks, current, seen = [], None, set()
    for row in rows:
        text = _text(row['description']).strip()
        upper = text.upper()
        if upper.startswith('YOUR ') or upper == 'WARGEAR OPTIONS' or not row['cost'].strip():
            current = {'title': upper, 'rows': []}
            blocks.append(current)
            continue
        if current is None:
            current = {'title': 'YOUR UNIT COSTS', 'rows': []}
            blocks.append(current)
        if (current['title'], text) in seen:
            continue  # The export repeats a datasheet's blocks
        seen.add((current['title'], text))
        current['rows'].append((text, _int(row['cost'])))

    def sizes_of(block):
        out = []
        for text, cost in block['rows']:
            m = re.match(r'^(\d+)\s+models?', text, re.I)
            if m and cost is not None and int(m.group(1)) not in {s['models'] for s in out}:
                out.append({'models': int(m.group(1)), 'points': cost})
        return sorted(out, key=lambda s: s['models'])

    units = [b for b in blocks if b['title'].startswith('YOUR') and sizes_of(b)]
    sizes = sizes_of(units[0]) if units else []
    copies = []
    for block in units[1:]:
        m = re.match(r'^YOUR (\d+)(?:ST|ND|RD|TH)\+', block['title'])
        later = sizes_of(block)
        if m and sizes and later:
            extra = later[0]['points'] - sizes[0]['points']
            copies = [0] * (int(m.group(1)) - 1) + [extra]
    wargear = [r for b in blocks if b['title'] == 'WARGEAR OPTIONS' for r in b['rows']]
    return sizes, (copies if any(copies) else []), wargear


def _loadout(text, parts, total, rows, report, faction, unit):
    """{row index: models carrying it} from a datasheet's loadout text (see the module docstring)."""
    carried = Counter()
    words = _text(text)
    for m in re.finditer(r'([^.:;\n]*?)\s+(?:is|are)\s+equipped\s+with\s*:\s*([^\n]*)', words, re.I):
        subject, items = m.group(1).strip(), m.group(2)
        carriers = _carriers(subject, parts, total)
        if carriers is None:
            report.add('loadout', faction, unit, f'can\'t tell how many models "{subject}" is; counted as 1')
            carriers = 1
        for item in re.split(r';|,\s|\.(?=\s|$)', items):
            item = item.strip().strip('.').strip()
            if not item:
                continue
            n = re.match(r'^(\d+)\s+(.*)$', item)
            count, name = (int(n.group(1)), n.group(2)) if n else (1, item)
            matched = [i for i, row in enumerate(rows) if _weapon_matches(name, row['name'])]
            if not matched:
                report.add('loadout', faction, unit, f'"{name}" isn\'t one of its weapons')
            for i in matched:
                carried[i] += carriers * count
    return carried


def _weapon_matches(item, row_name):
    """An item of a loadout ('2 heavy stubbers', 'Kombi-rokkit') names this weapon row (or its profile)."""
    base = re.split(r'\s+[-–—]\s+', row_name, maxsplit=1)[0]
    return same_name(item, row_name) or same_name(item, base)


def _carriers(subject, parts, total):
    """How many models a loadout line's subject is: 'This model', 'Every model', 'Every Nob', 'The Sergeant'..."""
    words = subject.lower()
    if 'added to this unit' in words:  # Models a rule adds during the battle (Pink Horrors' Split)
        return 0
    if re.fullmatch(r'(this|the) (model|unit)', words):
        return 1 if total == 1 else total if words.endswith('unit') else 1
    if re.fullmatch(r'(every|each) model( in this unit)?', words) or words in ('all models', 'models in this unit'):
        return total
    if ' and ' in words:  # 'Every Corsair Voidscarred and Voidscarred Felarch'
        found = [_carriers(p, parts, total) for p in re.split(r'\s+and\s+', subject, flags=re.I)]
        return sum(found) if None not in found else None
    name = re.sub(r'\s+models?$', '', re.sub(r'^((every|each|the|this|all|a|an|one|other|\d+)\s+)+', '', subject, flags=re.I),
                  flags=re.I)
    one = re.match(r'^(a|an|one|1)\s', words) is not None  # 'A Shade Runner': one of them
    for part, count in parts:
        if same_name(name, part) or name_key(part).endswith(name_key(name)) or singular(name_key(part)).endswith(singular(name_key(name))):
            return 1 if one else count
    return 1 if one else None


def import_folder(folder, known_keywords=None):
    """Read the export's datasheet files into the reference sections (see the module docstring)."""
    folder = Path(folder)
    missing = [name for name in NEEDED if not (folder / name).is_file()]
    if missing:
        raise WahapediaError(f'The Wahapedia folder is missing {", ".join(missing)}: download it again.')
    t = {name[:-4]: read_table(folder / name) for name in NEEDED}
    for name, columns in COLUMNS.items():
        header = (folder / f'{name}.csv').read_text(encoding='utf-8-sig').splitlines()[:1]
        header = header[0].split('|') if header else []
        lacking = [c for c in columns if c not in header]
        if lacking:
            raise WahapediaError(f'{name}.csv lacks the columns {", ".join(lacking)}: download it again.')
    report = Report()
    by_sheet = {}
    for table in ('Datasheets_models', 'Datasheets_wargear', 'Datasheets_options', 'Datasheets_unit_composition',
                  'Datasheets_models_cost', 'Datasheets_keywords', 'Datasheets_abilities'):
        groups = defaultdict(list)
        for row in t[table]:
            groups[row['datasheet_id']].append(row)
        for rows in groups.values():
            rows.sort(key=lambda r: int(r.get('line') or 0))
        by_sheet[table] = groups
    abilities = {}
    for a in t['Abilities']:
        abilities.setdefault(a['id'], a)
    legends_sources = {s['id'] for s in t['Source'] if 'legends' in s['name'].lower()}
    sheets = [d for d in t['Datasheets'] if d.get('virtual') != 'true']
    names = {d['id']: d['name'] for d in sheets}

    data = {'factions': [], 'units': [], 'ranged_weapons': [], 'melee_weapons': [], 'detachments': [], 'enhancements': []}
    faction_ids = {}
    with_sheets = {d['faction_id'] for d in sheets}
    # Army rules: faction abilities datasheets list as 'Faction' and none lists as 'Core' (as wahapedia.py reads them)
    types = defaultdict(set)
    for row in t['Datasheets_abilities']:
        if row['ability_id']:
            types[row['ability_id']].add(row['type'])
    core_names = {a['name'] for a in t['Abilities'] if 'Core' in types[a['id']]}
    army_rule_ids = {a['id'] for a in t['Abilities'] if 'Faction' in types[a['id']] and a['name'] not in core_names}
    for f in t['Factions']:
        if f['id'] not in with_sheets:
            continue
        faction_ids[f['id']] = len(data['factions']) + 1
        rules = [{'name': a['name'], 'text': markup(a['description'])} for a in t['Abilities']
                 if a['faction_id'] == f['id'] and a['description'].strip() and a['id'] in army_rule_ids]
        data['factions'].append({'id': faction_ids[f['id']], 'bsdata_id': f['id'], 'name': f['name'],
                                 '_key': stable_key('faction', f['id']), 'army_rules': rules})
    faction_name = {f['bsdata_id']: f['name'] for f in data['factions']}

    leads, supports = defaultdict(list), defaultdict(list)
    support_ids = {d['id'] for d in sheets if d.get('is_support') == 'true'}
    for row in t['Datasheets_leader']:
        if row['leader_id'] in names and row['attached_id'] in names:
            target = supports if row['leader_id'] in support_ids else leads
            if names[row['attached_id']] not in target[row['leader_id']]:
                target[row['leader_id']].append(names[row['attached_id']])

    # Weapons: one record per faction, kind, name and profile
    profiles = defaultdict(set)  # (faction, kind, name_key) -> profiles
    for d in sheets:
        for row in by_sheet['Datasheets_wargear'].get(d['id'], []):
            profiles[(d['faction_id'], _kind(row), name_key(row['name']))].add(weapon_profile(row))
    weapons = {}  # (faction, kind, name_key, profile) -> record
    taken = Counter()

    def weapon_for(faction, row):
        kind = _kind(row)
        profile = weapon_profile(row)
        key = (faction, kind, name_key(row['name']), profile)
        if key not in weapons:
            several = len(profiles[(faction, kind, name_key(row['name']))]) > 1
            record = _weapon_record(row, kind)
            if record is None:
                report.add('weapon_stats', faction_name.get(faction), None, f'{row["name"]}: unreadable strength, skipped')
                weapons[key] = None
                return None
            table = data[f'{kind}_weapons']
            wid = weapon_id(faction, row['name'], profile if several else None)
            record.update(id=len(table) + 1, faction_id=faction_ids[faction], bsdata_id=wid,
                          _key=weapon_key(kind, faction, row['name'], profile if several else None))
            table.append(record)
            weapons[key] = record
            if known_keywords is not None and record['abilities']:
                for keyword in check_keywords(', '.join(record['abilities']), known_keywords)['unknown']:
                    report.add('unknown_keyword', faction_name.get(faction), None, f'{record["name"]}: "{keyword}"')
        return weapons[key]

    for d in sorted(sheets, key=lambda d: (d['faction_id'], d['name'].lower())):
        if d['faction_id'] not in faction_ids:
            continue
        unit = _unit(d, by_sheet, abilities, legends_sources, report, faction_name[d['faction_id']],
                     leads.get(d['id'], []), supports.get(d['id'], []))
        if unit is None:
            continue
        rows = by_sheet['Datasheets_wargear'].get(d['id'], [])
        parts = composition(r['description'] for r in by_sheet['Datasheets_unit_composition'].get(d['id'], []))
        total = unit['default_models']
        carried = _loadout(d['loadout'], parts, total, rows, report, unit['faction'], unit['name']) if d['loadout'].strip() else None
        if carried is None:
            carried = Counter({i: total for i in range(len(rows))})
            if rows:
                report.add('loadout', unit['faction'], unit['name'], 'no loadout given: every weapon counted as carried')
        for kind in ('ranged', 'melee'):
            unit[f'{kind}_weapons'], unit[f'{kind}_options'] = [], []
        for i, row in enumerate(rows):
            record = weapon_for(d['faction_id'], row)
            if record is None:
                continue
            kind = _kind(row)
            if carried.get(i):
                entries = unit[f'{kind}_weapons']
                same = next((e for e in entries if e['weapon_id'] == record['id']), None)
                if same:
                    same['qty'] = max(same['qty'], carried[i])
                else:
                    entries.append({'weapon_id': record['id'], 'qty': carried[i]})
            elif record['id'] not in unit[f'{kind}_options']:
                unit[f'{kind}_options'].append(record['id'])
        unit.pop('faction')
        taken[(d['faction_id'], unit['name'])] += 1
        if taken[(d['faction_id'], unit['name'])] > 1:
            report.add('duplicate_unit', faction_name[d['faction_id']], unit['name'], 'two datasheets of this name')
        unit.update(id=len(data['units']) + 1, faction_id=faction_ids[d['faction_id']])
        data['units'].append(unit)

    # Detachments and enhancements
    rules_of = defaultdict(list)
    for a in t['Detachment_abilities']:
        rules_of[a['detachment_id']].append({'name': a['name'], 'text': markup(a['description'])})
    kept = set()
    for d in t['Detachments']:
        if d['type'] in SPECIAL_DETACHMENTS or d['faction_id'] not in faction_ids:
            continue
        kept.add(d['id'])
        dispositions = [p.strip() for p in d['force_disposition'].split(',') if p.strip() in FORCE_DISPOSITIONS]
        data['detachments'].append({'id': len(data['detachments']) + 1, 'faction_id': faction_ids[d['faction_id']],
                                    'bsdata_id': d['id'], '_key': stable_key('detachment', d['id']),
                                    'name': d['name'], 'rules': rules_of[d['id']], 'dp': _int(d['dp']),
                                    'dispositions': dispositions, 'tags': []})
    bearers = defaultdict(list)
    for row in t['Datasheets_enhancements']:
        if row['datasheet_id'] in names and row['datasheet_id'] not in bearers[row['enhancement_id']]:
            bearers[row['enhancement_id']].append(row['datasheet_id'])
    for e in t['Enhancements']:
        if e['faction_id'] not in faction_ids or (e['detachment_id'] and e['detachment_id'] not in kept):
            continue
        parsed = parse_enhancement(markup(e['description']))
        who = bearers.get(e['id'], [])
        upgrade = e.get('upgrade') == 'true'
        if upgrade and len(who) > 1:
            report.add('enhancement', faction_name[e['faction_id']], None,
                       f'{e["name"]}: an Upgrade for {len(who)} datasheets, counted as an enhancement')
        data['enhancements'].append({
            'id': len(data['enhancements']) + 1, 'faction_id': faction_ids[e['faction_id']],
            'bsdata_id': e['id'], '_key': stable_key('enhancement', e['id']), 'name': e['name'],
            'points': _int(e['cost']) or 0, 'text': markup(e['description']), 'buffs': parsed['buffs'],
            'detachment_keys': [e['detachment_id']] if e['detachment_id'] else [],
            'unit_bsdata_id': who[0] if upgrade and len(who) == 1 else None,
            'bearer_bsdata_ids': [] if upgrade and len(who) == 1 else who,
            'max_taken': None, 'counts_once': False})

    source = {'last_update': (t['Last_update'][0]['last_update'] if t['Last_update'] else None)}
    return Result(data, report.items, source)


def _wargear_costs(rows):
    """The "per Multi-melta: 5" rows as [{'name': 'Multi-melta', 'points': 5}], each name once."""
    out = []
    for text, points in rows:
        m = re.match(r'^per\s+(.+?)\s*$', text, re.I)
        if m and points is not None and m.group(1).lower() not in {c['name'].lower() for c in out}:
            out.append({'name': m.group(1), 'points': points})
    return out


def _kind(row):
    return 'melee' if row.get('type') == 'Melee' else 'ranged'


def _weapon_record(row, kind):
    strength = _int(row['S'])
    if strength is None:
        return None
    abilities = [a.strip() for a in markup(row['description']).replace('*', '').split(',')
                 if a.strip() and a.strip() not in ('-', '–')]
    record = {'name': re.sub(r'\s+', ' ', row['name']).strip(), 'attacks': row['A'].strip() or '0', 'strength': strength,
              'armor_penetration': abs(_int(row['AP']) or 0), 'damage': row['D'].strip() or '0', 'abilities': abilities}
    if kind == 'ranged':
        record['ballistic_skill'] = _plus(row['BS_WS'])
        record['range_inches'] = _int(row['range'])
    else:
        record['weapon_skill'] = _plus(row['BS_WS'])
    return record


def _unit(d, by_sheet, abilities, legends_sources, report, faction, can_lead, can_support):
    """A unit record without weapons or IDs (and 'faction', for the reports), or None if it has no stat line."""
    name = d['name'] + (' [Legends]' if d['source_id'] in legends_sources else '')
    models = by_sheet['Datasheets_models'].get(d['id'], [])
    if not models:
        report.add('skipped_unit', faction, name, 'no stat line')
        return None
    parts = composition(r['description'] for r in by_sheet['Datasheets_unit_composition'].get(d['id'], []))
    sizes, copy_points, wargear_costs = points_blocks(by_sheet['Datasheets_models_cost'].get(d['id'], []))
    default_models = sizes[0]['models'] if sizes else (sum(c for _, c in parts) or 1)
    if not sizes:
        report.add('points', faction, name, 'no points given')

    def weight(model):  # Models of this stat line at the smallest size
        return max((c for part, c in parts if same_name(part, model['name'])), default=0)
    stats = max(models, key=weight) if len(models) > 1 else models[0]
    if len(models) > 1 and len({(m['T'], m['Sv'], m['W']) for m in models}) > 1:
        report.add('mixed_profile', faction, name, f'{len(models)} stat lines; using {stats["name"]}\'s')
    toughness, save, wounds = _int(stats['T']), _plus(stats['Sv']), _int(stats['W'])
    if None in (toughness, save, wounds):
        report.add('skipped_unit', faction, name, f'unreadable T/Sv/W: {stats["T"]} {stats["Sv"]} {stats["W"]}')
        return None
    base = parse_base(stats.get('base_size'))
    if base is None and (stats.get('base_size') or '').strip():
        report.add('base_size', faction, name, f'unreadable base size "{stats.get("base_size")}"')

    lines, rules, modifiers, fnp = [], [], [], None
    invulnerable = _int(stats.get('inv_sv'))
    note = (stats.get('inv_sv_descr') or '').lower()
    if invulnerable and 'only' in note and ('ranged' in note or 'melee' in note):
        modifiers.append(f'{"Ranged" if "ranged" in note else "Melee"} Invulnerable Save {invulnerable}+')
        invulnerable = None
    for a in by_sheet['Datasheets_abilities'].get(d['id'], []):
        known = abilities.get(a['ability_id']) if a['ability_id'] else None
        if a['type'] == 'Core' and known:
            rule = f'{known["name"]} {a["parameter"]}'.strip()
            if rule not in rules:
                rules.append(rule)
            if known['name'] == 'Feel No Pain' and _int(a['parameter']):
                fnp = min(fnp or 7, _int(a['parameter']))
            if known['name'] == 'Stealth' and 'Stealth' not in modifiers:
                modifiers.append('Stealth')
            continue
        if known:  # A faction ability
            if known['name'] not in rules:
                rules.append(known['name'])
            continue
        title, text = a['name'].strip(), markup(a['description'])
        if not title and not text:
            continue
        lines.append(f'{title}: {text}' if title else text)
        if a['type'] in ('Wargear', 'Wargear profile'):
            continue  # Options, not the datasheet's own
        for pattern, effect in DEFENSIVE_TEXT:
            m = pattern.match(plain_text(text).strip())
            if m and effect == 'fnp':
                fnp = min(fnp or 7, int(m.group(1)))
            elif m and effect == 'only against':
                modifiers.append(f'{m.group(2).capitalize()} Invulnerable Save {m.group(1)}+')
            elif m and effect not in modifiers:
                modifiers.append(effect)

    leader_buffs = []
    if can_lead:
        for line in lines:
            buffs, skipped = parse_leader_buffs(line)
            leader_buffs.extend(b for b in buffs if b not in leader_buffs)
            for sentence in skipped:
                report.add('leader_buff', faction, name, f'not modelled: "{sentence[:120]}"')

    keywords = []
    for k in by_sheet['Datasheets_keywords'].get(d['id'], []):
        if k['keyword'].strip() and k['keyword'].strip() not in keywords:
            keywords.append(k['keyword'].strip())
    options = [markup(o['description']) for o in by_sheet['Datasheets_options'].get(d['id'], []) if o['description'].strip()]
    move = (stats.get('M') or '').replace('"', '').strip()
    return {
        'bsdata_id': d['id'], '_key': stable_key('unit', d['id']), 'faction': faction,
        'name': name, 'legends': d['source_id'] in legends_sources,
        'toughness': toughness, 'save': save, 'wounds': wounds, 'invulnerable_save': invulnerable,
        'feel_no_pain': fnp, 'move': move if re.search(r'\d', move) else None, 'oc': _int(stats.get('OC')),
        'leadership': _plus(stats.get('Ld')), 'base': base,
        'points_cost': sizes[0]['points'] if sizes else None, 'default_models': default_models,
        'points_by_size': sizes, 'keywords': keywords, 'modifiers': modifiers,
        'can_lead': can_lead, 'can_support': can_support, 'max_in_army': None, 'copy_points': copy_points,
        'leader_buffs': leader_buffs,
        'abilities': '\n\n'.join(lines + [r for r in rules if r != 'Leader']),
        'wargear_options': options or None, 'wargear_costs': _wargear_costs(wargear_costs) or None,
    }
