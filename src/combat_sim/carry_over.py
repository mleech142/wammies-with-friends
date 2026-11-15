"""
Carrying saved data over from BSData to Wahapedia (docs/wahapedia-migration.md, step 3).

BSData was taken down in November 2026; the app's units, weapons, detachments and enhancements now
come from Wahapedia. Everything saved with BSData refers to it in one of two ways:
- by **database ID** (saved armies' and comparisons' units, factions and weapons; games' units),
  given to each BSData record through the stable_ids table under a BSData key ('unit:<catalogue>/<entry>');
- by **BSData ID** (armies' detachments and enhancements, app data's faction_key, unit_modifiers,
  leader_buffs, detachment_key and linked_bsdata_id, share codes).

The ID map (data/bsdata_id_map.json, made once from the last BSData import by
scripts/make_bsdata_id_map.py) says which Wahapedia record each BSData record became. With it:
- carry_over_database() re-keys stable_ids to Wahapedia's keys (wahapedia.stable_key / weapon_key),
  so a record keeps its database ID. Where several BSData records became one Wahapedia record (each
  Space Marine chapter's copy of a unit, the chapters themselves), the lowest ID is kept and saved
  records using the others are changed to it. Rows of BSData records with no match stay as they are,
  so their IDs are never given to another record; a saved army's unit with no match is flagged
  ('missing': its name) and priced as a unit no longer in the data.
- upgrade_app_data() turns an app data JSON's BSData IDs into Wahapedia ones (schema_version 3; the
  fields keep their names, as the package keeps its own).
- share_payload() turns a share code made with BSData (version 1) into one made with Wahapedia.
Wargear choices made with BSData's option tree are dropped: Wahapedia's options are simple ticks.
Everything run twice changes nothing the second time.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from . import paths
from .models import db, Proposal, SavedArmy, SavedComparison, SavedGame, StableId, Unit
from .wahapedia import KEY_PREFIX, KEY_TABLES, stable_key, weapon_id, weapon_key

MAP_FILE = 'bsdata_id_map.json'  # Shipped in the bundle's data folder (combat_sim.spec)
APP_DATA_VERSION = 3  # App data JSON with Wahapedia IDs (2: BSData's)


def shipped_map():
    """The ID map shipped with the app."""
    return IdMap.load(paths.bundle_root() / 'data' / MAP_FILE)


class IdMap:
    """The BSData → Wahapedia ID map (see make_bsdata_id_map.py for its sections)."""

    def __init__(self, data):
        self.data = data
        # By BSData ID alone (app data and armies don't say which catalogue): its most common target
        self.bare = {}
        for section in ('factions', 'units', 'detachments', 'enhancements', 'ranged_weapons', 'melee_weapons'):
            found = defaultdict(Counter)
            for key, target in data.get(section, {}).items():
                found[key.rsplit('/', 1)[-1]][json.dumps(target, sort_keys=True)] += 1
            self.bare[section] = {bare: json.loads(c.most_common(1)[0][0]) for bare, c in found.items()}
        self.targets = {section: {t for t in found.values() if isinstance(t, str)} for section, found in self.bare.items()}

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def new_key(self, old_key):
        """The Wahapedia stable key for a BSData stable key, or None (not matched, or not a BSData key)."""
        kind, _, rest = old_key.partition(':')
        section = KEY_TABLES.get(kind)
        if old_key.startswith(KEY_PREFIX) or section is None:
            return None
        target = self.data.get(section, {}).get(rest)
        if target is None:
            return None
        if kind in ('ranged', 'melee'):
            return weapon_key(kind, target['faction'], target['name'], target.get('profile'))
        return stable_key(kind, target)

    def find(self, section, bsdata_id, catalogue=None):
        """The Wahapedia target of a BSData ID (in `catalogue` if given and mapped there), or None."""
        if bsdata_id is None:
            return None
        if catalogue is not None:
            target = self.data.get(section, {}).get(f'{catalogue}/{bsdata_id}')
            if target is not None:
                return target
        return self.bare[section].get(str(bsdata_id))


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------

def carry_over_database(id_map):
    """
    Re-key stable_ids and change saved armies, comparisons, games and proposals to match (one
    transaction, committed). Answers {'rekeyed', 'merged', 'armies', 'comparisons', 'games',
    'proposals', 'notes'}, or None when there is nothing left to carry over.
    """
    rows = StableId.query.all()
    have = {r.key: r for r in rows if r.key.startswith(KEY_PREFIX)}
    groups = defaultdict(list)  # new key -> BSData rows that became it
    unmatched_units = set()  # BSData units with no Wahapedia datasheet
    for row in rows:
        new = id_map.new_key(row.key)
        if new is not None:
            groups[new].append(row)
        elif row.table == 'units' and not row.key.startswith(KEY_PREFIX):
            unmatched_units.add(row.id)
    if not groups:
        return None

    names = _unit_names()  # Read before the units table is rebuilt from Wahapedia
    remap = defaultdict(dict)  # table -> {old database ID: kept database ID}
    for new, members in groups.items():
        table = members[0].table
        keep = have[new].id if new in have else min(m.id for m in members)
        for m in members:
            if m.id != keep:
                remap[table][m.id] = keep
            db.session.delete(m)
        if new not in have:
            db.session.add(StableId(key=new, table=table, id=keep))
    db.session.flush()

    notes, changed = [], Counter()
    for army in SavedArmy.query.all():
        if _army(army, id_map, remap, unmatched_units, names, notes):
            changed['armies'] += 1
    walk = _Walker(id_map, remap)
    for model, fields, label in ((SavedComparison, ('attackers', 'defenders', 'battle_conditions', 'results'),
                                  'comparisons'),
                                 (SavedGame, ('armies',), 'games'),
                                 (Proposal, ('body', 'before', 'edit'), 'proposals')):
        for record in model.query.all():
            if _rewrite_fields(record, fields, walk):
                changed[label] += 1
    db.session.commit()
    return {'rekeyed': sum(len(m) for m in groups.values()), 'merged': sum(len(r) for r in remap.values()),
            **{k: changed[k] for k in ('armies', 'comparisons', 'games', 'proposals')}, 'notes': notes}


def _unit_names():
    try:
        return dict(db.session.query(Unit.id, Unit.name))
    except Exception:  # No units table yet (a new database): nothing saved refers to one
        db.session.rollback()
        return {}


def _army(army, id_map, remap, unmatched_units, names, notes):
    """Change one saved army to Wahapedia's IDs; answers whether anything changed."""
    before = json.dumps([army.faction_id, army.detachment_key, army.detachment_keys, army.units], sort_keys=True)
    army.faction_id = remap['factions'].get(army.faction_id, army.faction_id)

    keys = army.detachment_keys if army.detachment_keys is not None else ([army.detachment_key] if army.detachment_key else [])
    new_keys = []
    for key in keys:
        target = key if _is_wahapedia(key, id_map, 'detachments') else id_map.find('detachments', key)
        if target is None:
            notes.append(f'{army.name}: a detachment that isn\'t on Wahapedia was left out.')
        elif target not in new_keys:
            new_keys.append(target)
    army.detachment_keys, army.detachment_key = new_keys, None

    units, dropped = [], 0
    for entry in army.units or []:
        entry = dict(entry)
        old = entry.get('unit_id')
        entry['unit_id'] = remap['units'].get(old, old)
        if old in unmatched_units and not entry.get('missing'):
            entry['missing'] = names.get(old) or 'A unit'
            notes.append(f'{army.name}: {entry["missing"]} isn\'t on Wahapedia; it stays in the list, flagged.')
        enhancement = entry.get('enhancement')
        if enhancement and not _is_wahapedia(enhancement, id_map, 'enhancements'):
            entry['enhancement'] = id_map.find('enhancements', enhancement)
            if entry['enhancement'] is None:
                notes.append(f'{army.name}: an enhancement that isn\'t on Wahapedia was left out.')
        if entry.get('wargear'):
            dropped += 1
        entry['wargear'] = None
        units.append(entry)
    army.units = units
    if dropped:
        notes.append(f'{army.name}: wargear choices on {dropped} unit{"s" if dropped != 1 else ""} were reset '
                     'to the datasheet\'s (Wahapedia\'s options are ticked weapons).')
    flag_modified(army, 'units')
    flag_modified(army, 'detachment_keys')
    return json.dumps([army.faction_id, army.detachment_key, army.detachment_keys, army.units], sort_keys=True) != before


def _is_wahapedia(value, id_map, section):
    """Already a Wahapedia ID (carried over before): a target of the map, not a BSData ID."""
    return str(value) not in id_map.bare[section] and str(value) in id_map.targets[section]


def _rewrite_fields(record, fields, walk):
    changed = False
    for name in fields:
        value = getattr(record, name)
        if value is None:
            continue
        new = walk(value)
        if new != value:
            setattr(record, name, new)
            flag_modified(record, name)
            changed = True
    return changed


class _Walker:
    """
    A saved JSON value (a comparison's page state, a game's frozen armies, a proposal's edit) in Wahapedia's
    IDs: database IDs under unit_id / leader_id / faction_id, weapon_id (with its weapon_type) and an
    enhancement's id ({id, bearer}) through `remap`; BSData detachment and enhancement IDs anywhere, and the
    app data fields upgrade_app_data changes, through the map.
    """

    def __init__(self, id_map, remap=None):
        self.map = id_map
        self.remap = remap or defaultdict(dict)
        self.strings = {**id_map.bare['detachments'], **id_map.bare['enhancements']}

    def _id(self, table, value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return value
        new = self.remap[table].get(number, number)
        return new if isinstance(value, int) else str(new)

    def __call__(self, value, section=None):
        if isinstance(value, list):
            return [self(v, section) for v in value]
        if isinstance(value, str):
            return self.strings.get(value, value)
        if not isinstance(value, dict):
            return value
        kind = value.get('weapon_type') or value.get('type')
        out = {}
        for key, item in value.items():
            if key in ('unit_id', 'leader_id'):
                out[key] = self._id('units', item)
            elif key == 'faction_id':
                out[key] = self._id('factions', item)
            elif key == 'weapon_id' and kind in ('ranged', 'melee'):
                out[key] = self._id(f'{kind}_weapons', item)
            elif key == 'id' and 'bearer' in value:
                out[key] = self._id('enhancements', item)
            elif key == 'faction_key' and item:
                out[key] = self.map.find('factions', item) or item
            elif key == 'bsdata_id' and section in ('unit_modifiers', 'leader_buffs'):
                out[key] = self.map.find('units', item) or item
            elif key == 'linked_bsdata_id' and item:
                target = self.map.find(section or 'ranged_weapons', item) or self.map.find('ranged_weapons', item) \
                    or self.map.find('melee_weapons', item)
                out[key] = weapon_id(target['faction'], target['name'], target.get('profile')) if target else item
            else:
                out[key] = self(item, key if key in APP_DATA_SECTIONS else section)
        return out


APP_DATA_SECTIONS = ('unit_modifiers', 'leader_buffs', 'ranged_weapons', 'melee_weapons', 'faction_rules', 'stratagems')


# ---------------------------------------------------------------------------
# The app data JSON and share codes
# ---------------------------------------------------------------------------

def upgrade_app_data(data, id_map):
    """
    A version 2 app data JSON (BSData IDs) as version 3 (Wahapedia's), its fields named as before: faction_key
    a Wahapedia faction ID, unit_modifiers' and leader_buffs' bsdata_id a datasheet ID, detachment_key a
    Wahapedia detachment ID, and a custom weapon's linked_bsdata_id a Wahapedia weapon's (wahapedia.weapon_id).
    A reference with no match keeps its BSData ID (it then matches nothing, and is kept in the file). Other
    versions come back unchanged.
    """
    if not isinstance(data, dict) or data.get('schema_version') != 2:
        return data
    upgraded = _Walker(id_map)(data)
    upgraded['schema_version'] = APP_DATA_VERSION
    return upgraded


def share_payload(payload, id_map):
    """
    A share code's payload made with BSData (version 1) in Wahapedia's IDs (version 2), and notes on what
    couldn't be carried over: units, detachments and enhancements with no match are left out, and wargear
    choices dropped. A version 2 payload comes back unchanged.
    """
    if payload.get('v') != 1:
        return payload, []
    catalogue = str(payload.get('faction'))
    notes, units, position = [], [], {}
    for i, row in enumerate(payload.get('units') or []):
        if not isinstance(row, dict):
            continue
        datasheet = id_map.find('units', row.get('id'), str(row.get('cat') or catalogue))
        if datasheet is None:
            notes.append(f'{row.get("name") or "A unit"} isn\'t on Wahapedia, so it was left out.')
            continue
        position[i] = len(units)
        new = {'id': datasheet, 'name': row.get('name'), 'models': row.get('models')}
        if row.get('enh'):
            new['enh'] = id_map.find('enhancements', row['enh'])
            if new['enh'] is None:
                notes.append(f'{row.get("name")}: its enhancement isn\'t on Wahapedia, so it was left out.')
                del new['enh']
        if row.get('wargear'):
            notes.append(f'{row.get("name")}: its wargear choices were reset to the datasheet\'s.')
        if isinstance(row.get('joins'), int):
            new['joins'] = row['joins']
        units.append(new)
    for new in units:  # Positions count only the units kept
        if 'joins' in new:
            new['joins'] = position.get(new['joins'])
            if new['joins'] is None:
                del new['joins']
    detachments = []
    for key in payload.get('detachments') or []:
        target = id_map.find('detachments', key)
        if target is None:
            notes.append('A detachment in this list isn\'t on Wahapedia, so it was left out.')
        elif target not in detachments:
            detachments.append(target)
    warlord = payload.get('warlord')
    out = {'v': 2, 'faction': id_map.find('factions', catalogue), 'faction_name': payload.get('faction_name'),
           'name': payload.get('name'), 'limit': payload.get('limit'), 'detachments': detachments,
           'warlord': position.get(warlord) if isinstance(warlord, int) else None, 'units': units}
    if payload.get('disposition'):
        out['disposition'] = payload['disposition']
    return out, notes
