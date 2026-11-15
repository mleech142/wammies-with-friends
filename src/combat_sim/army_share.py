"""
Share codes: an army list as a short text code that another install of the app can import.

A saved army refers to units and weapons by database ID, which are local to one install. A code
(version 2) carries Wahapedia's IDs instead, so it means the same list on any install with the
game data downloaded:

- the faction by its Wahapedia ID, each unit by its datasheet ID (with its faction when that isn't
  the army's), detachments and enhancements by their Wahapedia IDs (as armies already store them);
- a unit's weapon counts (loadouts.py) as `weapons`, {weapon's stable key: models carrying it};
- attachments and the Warlord by position in the list (uids are rebuilt on import);
- the force disposition by name, when one is chosen.

Codes made before 3.0 (version 1) carry BSData's IDs; carry_over.share_payload translates them
through the shipped ID map, leaving out their wargear choices.

Lists with units from custom factions can't be shared: those units live in the sharer's own
app data. A code is `PREFIX` + URL-safe base64 of zlib-compressed JSON. On import anything not
found in this install's data is left out and named in `notes`; the page then prices the list
as usual, so points follow the importer's own data.
"""

import base64
import binascii
import json
import zlib

from . import carry_over, loadouts
from .armies import ArmyError, clean_army, price_army
from .models import db, Detachment, Enhancement, Faction, StableId, Unit

PREFIX = '40KCS1:'
VERSION = 2  # 2: Wahapedia's IDs; 1: BSData's (made before 3.0; translated by carry_over.share_payload)
BSDATA_VERSION = 1
MAX_CODE_LENGTH = 100_000
MAX_JSON_BYTES = 1_000_000  # Decompressed: guards against a code that inflates without end


def _weapons_out(choices):
    """Simple wargear (loadouts.py) by the weapons' stable keys, which mean the same weapon on every install; a priced
    item that isn't a weapon ('wargear:stormshield') as it is."""
    tables = {'ranged': 'ranged_weapons', 'melee': 'melee_weapons'}
    wanted, out = {}, {}
    for k, count in choices.items():
        kind, _, ident = k.partition(':')
        if kind in tables:
            wanted[(tables[kind], int(ident))] = count
        else:
            out[k] = count
    rows = StableId.query.filter(StableId.id.in_({i for _, i in wanted}), StableId.table.in_(tables.values()))
    out.update({r.key: wanted[(r.table, r.id)] for r in rows if (r.table, r.id) in wanted})
    return out


def _weapons_in(unit, weapons, models):
    """A code's weapon counts as this install's (loadouts.py), and how many weapons it doesn't have."""
    tables = {'ranged_weapons': 'ranged', 'melee_weapons': 'melee'}
    rows = {r.key: r for r in StableId.query.filter(StableId.key.in_([str(k) for k in weapons]))}
    listed = loadouts.weapons(unit, models)
    carried = {loadouts.key(kind, w.id) for kind, w, _, _ in listed}
    carried |= {c['key'] for c in loadouts.costs(unit, listed) if c['keys'] is None}
    found, missing = {}, 0
    for k, count in weapons.items():
        row = rows.get(str(k))
        key = loadouts.key(tables.get(row.table), row.id) if row else str(k)
        if key in carried and isinstance(count, int):
            found[key] = count
        else:
            missing += 1
    return found, missing


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode(army):
    """The share code for an army (as clean_army gives it). Raises ArmyError for lists that can't be shared."""
    faction = db.session.get(Faction, army['faction_id'])
    if faction is None:
        raise ArmyError('Choose a faction first.')
    if faction.source != 'bsdata' or not faction.bsdata_id:
        raise ArmyError(f'{faction.name} is a custom faction: only lists of downloaded units can be shared.')
    priced = price_army(army)  # Sizes filled in, wargear in full, attachments to removed units dropped
    entries = priced['units']
    units = {u.id: u for u in Unit.query.filter(Unit.id.in_({e['unit_id'] for e in entries}))} if entries else {}
    custom = sorted({units[e['unit_id']].name for e in entries
                     if e['unit_id'] in units and (units[e['unit_id']].faction.source != 'bsdata' or not units[e['unit_id']].bsdata_id)})
    if custom:
        raise ArmyError(f'Lists with custom units can\'t be shared: {", ".join(custom)} '
                        f'{"is" if len(custom) == 1 else "are"} only in your data.')
    if any(e['unit_id'] not in units for e in entries):
        raise ArmyError('Remove the units that are no longer in the data before sharing this list.')

    position = {e['uid']: i for i, e in enumerate(entries)}
    out_units = []
    for e in entries:
        unit = units[e['unit_id']]
        row = {'id': unit.bsdata_id, 'name': unit.name, 'models': e['models']}
        if unit.faction.bsdata_id != faction.bsdata_id:
            row['cat'] = unit.faction.bsdata_id
        if e.get('attached_to') in position:
            row['joins'] = position[e['attached_to']]
        if e.get('enhancement'):
            row['enh'] = e['enhancement']
        if e.get('wargear'):
            row['weapons'] = _weapons_out(e['wargear'])
        out_units.append(row)
    payload = {'v': VERSION, 'faction': faction.bsdata_id, 'faction_name': faction.name, 'name': army['name'],
               'limit': army['points_limit'], 'detachments': army['detachment_keys'],
               'warlord': position.get(priced['warlord']), 'units': out_units}
    if army.get('disposition'):  # Optional: codes made before force dispositions were shared lack it
        payload['disposition'] = army['disposition']
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode('ascii').rstrip('=')


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def _payload(code):
    bad = ArmyError('That isn\'t an army share code (or part of it is missing).')
    code = ''.join(str(code or '').split())  # Line breaks and spaces picked up when pasting
    if not code.startswith(PREFIX) or len(code) > MAX_CODE_LENGTH:
        raise bad
    body = code[len(PREFIX):]
    try:
        packed = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
        inflater = zlib.decompressobj()
        raw = inflater.decompress(packed, MAX_JSON_BYTES)
        if inflater.unconsumed_tail or not inflater.eof:
            raise bad
        payload = json.loads(raw.decode('utf-8'))
    except (binascii.Error, ValueError, zlib.error, UnicodeDecodeError):
        raise bad
    if not isinstance(payload, dict) or not isinstance(payload.get('units'), list):
        raise bad
    if payload.get('v') not in (BSDATA_VERSION, VERSION):
        raise ArmyError('This code was made by a newer version of the app: update the app to import it.')
    return payload


def decode(code):
    """
    An army from a share code, in this install's IDs: {'army' (as clean_army gives it, not saved),
    'notes' (what wasn't found in this install's data)}. Raises ArmyError for codes it can't read.
    """
    payload, notes = _payload(code), []
    if payload.get('v') == BSDATA_VERSION:  # Made with BSData: its IDs in Wahapedia's
        payload, notes = carry_over.share_payload(payload, carry_over.shipped_map())
    faction = Faction.query.filter_by(bsdata_id=str(payload.get('faction')), source='bsdata').first()
    if faction is None:
        name = payload.get('faction_name') or 'its faction'
        raise ArmyError(f'This list is for {name}, which isn\'t in your data. '
                        'Download the latest game data on the Setup page, then try again.')
    factions = {f.bsdata_id: f.id for f in Faction.query.filter_by(source='bsdata')}
    enhancements = {e.bsdata_id for e in Enhancement.query.filter_by(faction_id=faction.id)}
    units, kept = [], {}
    for i, row in enumerate(payload['units']):
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or 'A unit')[:200]
        faction_id = factions.get(str(row.get('cat') or faction.bsdata_id))
        unit = Unit.query.filter_by(faction_id=faction_id, bsdata_id=str(row.get('id'))).first() if faction_id else None
        if unit is None:
            notes.append(f'{name} isn\'t in your data, so it was left out.')
            continue
        uid = f'u{i + 1}'
        kept[i] = uid
        wargear = None
        if isinstance(row.get('weapons'), dict):
            models = row.get('models') if isinstance(row.get('models'), int) else None
            wargear, missing = _weapons_in(unit, row['weapons'], models)
            if missing:
                notes.append(f"{unit.name}: {missing} of its weapons {'isn' if missing == 1 else 'aren'}'t in your data; "
                             'check its wargear.')
        enhancement = row.get('enh')
        if enhancement and str(enhancement) not in enhancements:
            notes.append(f'{unit.name}: its enhancement isn\'t in your data, so it was left out.')
            enhancement = None
        units.append({'uid': uid, 'unit_id': unit.id, 'models': row.get('models'), 'joins': row.get('joins'),
                      'enhancement': enhancement, 'wargear': wargear or None})
    for entry in units:
        joins = entry.pop('joins')
        entry['attached_to'] = kept.get(joins) if isinstance(joins, int) else None
    known = {d.bsdata_id for d in Detachment.query.filter_by(faction_id=faction.id)}
    detachments = [k for k in (payload.get('detachments') or []) if isinstance(k, str)]
    if any(k not in known for k in detachments):
        notes.append('A detachment in this list isn\'t in your data, so it was left out.')
        detachments = [k for k in detachments if k in known]
    warlord = payload.get('warlord')
    army = clean_army({'name': payload.get('name'), 'faction_id': faction.id, 'points_limit': payload.get('limit'),
                       'detachment_keys': detachments, 'units': units,
                       'disposition': payload.get('disposition') if isinstance(payload.get('disposition'), str) else None,
                       'warlord': kept.get(warlord) if isinstance(warlord, int) else None})
    return {'army': army, 'notes': notes}
