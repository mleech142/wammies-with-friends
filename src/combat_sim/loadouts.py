"""
Simple wargear (docs/wahapedia-migration.md, step 5): a unit's weapons are its datasheet loadout plus its wargear
options, each with how many of its models carry it. The player follows the datasheet's own option text
(`Unit.wargear_options`, shown beside the counts); the app sets no limits.

Wargear is priced by the datasheet's "per X" costs (`Unit.wargear_costs`, [{'name', 'points'}]): a cost naming one
of the unit's weapons (by name, its profiles counting once) is paid for each one carried beyond the datasheet's
loadout; a cost naming anything else (a storm shield, a banner, a weapon the datasheet names differently) is a
count of its own in the form, `wargear:<name key>`, paid for each one taken.

An army entry's `wargear` is {'ranged:<weapon id>': count, 'melee:<weapon id>': count, 'wargear:<name key>': count}
with everything the unit can take; None is the datasheet's loadout at the unit's size. `evaluate` gives what the
Armies page's popup, pricing, Analytics, Match view and Play read (`loadout` rows of {'weapon_id', 'weapon_type',
'name', 'qty', 'default_use'}).
"""

import re

from .models import MeleeWeapon, RangedWeapon
from .wahapedia import name_key

KINDS = ('ranged', 'melee')
WARGEAR = 'wargear'  # A priced item that isn't a weapon
MAX_COUNT = 100


def default_used(names):
    """
    Which weapons are used by default: all, except later profiles of a "Weapon - Profile" family
    (alternative profiles of one gun; Wahapedia writes "Weapon – profile"). Same rule as the Simulator and
    Analytics pages.
    """
    families, used = set(), []
    for name in names:
        name = name.replace(' – ', ' - ')
        family = name.split(' - ')[0].strip().lower() if ' - ' in name else None
        used.append(not family or family not in families)
        if family:
            families.add(family)
    return used


def family(name):
    """A weapon's name without its profile, compared loosely: 'Plasma cannon – supercharge' -> 'plasmacannon'."""
    return name_key(re.split(r'\s+[-–]\s+', name)[0])


def key(kind, ident):
    return f'{kind}:{ident}'


def is_simple(choices):
    """True for this module's choices ({'ranged:12': 2}), False for a BSData option tree's ({'3': 1})."""
    return not choices or all(':' in str(k) for k in choices)


def has_choices(unit):
    """A unit with something to choose: wargear options (weapons, the datasheet's option text or priced wargear)."""
    return bool(unit.ranged_options or unit.melee_options or unit.wargear_options or unit.wargear_costs)


def scaled(qty, unit, models):
    """A datasheet loadout count at another unit size (as Analytics scales it)."""
    if not unit.default_models or not models:
        return qty
    return max(1, round(qty * models / unit.default_models))


def weapons(unit, models):
    """[(kind, weapon, default count at this size, option?)]: the loadout first, then the options not in it."""
    out, seen = [], set()
    for kind in KINDS:
        for weapon, qty in unit.loadout(kind):
            if (kind, weapon.id) not in seen:
                seen.add((kind, weapon.id))
                out.append((kind, weapon, scaled(qty, unit, models), False))
    for kind, model in (('ranged', RangedWeapon), ('melee', MeleeWeapon)):
        ids = [i for i in (getattr(unit, f'{kind}_options') or []) if (kind, i) not in seen]
        found = {w.id: w for w in model.query.filter(model.id.in_(ids))} if ids else {}
        for i in ids:
            if i in found and (kind, i) not in seen:
                seen.add((kind, i))
                out.append((kind, found[i], 0, True))
    return out


def costs(unit, listed):
    """
    The unit's wargear costs, each with what it counts: [{'name', 'points', 'keys': [weapon keys]}] for a weapon
    (all its profiles), or 'keys': None and 'key' for a priced item of its own.
    """
    out = []
    for cost in unit.wargear_costs or []:
        want = name_key(cost['name'])
        matched = [key(kind, w.id) for kind, w, _, _ in listed if family(w.name) == want]
        if matched:
            out.append({'name': cost['name'], 'points': cost['points'], 'keys': matched})
        elif want:
            out.append({'name': cost['name'], 'points': cost['points'], 'keys': None, 'key': key(WARGEAR, want)})
    return out


def _count(value, fallback):
    try:
        return max(0, min(int(value), MAX_COUNT))
    except (TypeError, ValueError):
        return fallback


def evaluate(unit, choices, models):
    """
    {'models', 'points' (what the wargear taken adds), 'choices' (None when they are the datasheet's), 'loadout',
    'summary', 'form' (each row: key, kind, name, count, default, option, points per one or None),
    'options_text', 'problems': [], 'effects': None} for a unit at `models` models.
    """
    models = models or unit.default_models or 1
    choices = choices or {}
    listed = weapons(unit, models)
    priced = costs(unit, listed)
    defaults = {key(kind, w.id): default for kind, w, default, _ in listed}
    counts = {k: _count(choices.get(k, default), default) for k, default in defaults.items()}
    items = [c for c in priced if c['keys'] is None]
    for item in items:
        defaults[item['key']] = 0
        counts[item['key']] = _count(choices.get(item['key'], 0), 0)
    each = {k: c['points'] for c in priced for k in (c['keys'] or [c['key']])}

    points = 0
    for c in priced:
        keys = c['keys'] or [c['key']]
        taken = max(counts[k] for k in keys) - max(defaults[k] for k in keys)
        points += max(0, taken) * c['points']

    rows, form, summary = [], [], []
    for kind, weapon, default, option in listed:
        k = key(kind, weapon.id)
        form.append({'key': k, 'kind': kind, 'name': weapon.name, 'count': counts[k], 'default': default,
                     'option': option, 'points': each.get(k)})
        if counts[k]:
            rows.append({'weapon_id': weapon.id, 'weapon_type': kind, 'name': weapon.name, 'qty': counts[k]})
        if counts[k] != default:
            summary.append(f'{counts[k]} × {weapon.name}')
    for item in items:
        k = item['key']
        form.append({'key': k, 'kind': WARGEAR, 'name': item['name'], 'count': counts[k], 'default': 0,
                     'option': True, 'points': item['points']})
        if counts[k]:
            summary.append(f'{counts[k]} × {item["name"]}')
    for row, used in zip(rows, default_used([r['name'] for r in rows])):
        row['default_use'] = used
    changed = any(counts[k] != defaults[k] for k in counts)
    return {'models': models, 'points': points, 'choices': counts if changed else None, 'loadout': rows,
            'summary': ', '.join(summary), 'form': form, 'options_text': list(unit.wargear_options or []),
            'problems': [], 'effects': None}


def clean(value):
    """Simple choices from a request, or None; raises ValueError for anything else."""
    out = {}
    for k, v in value.items():
        kind, _, ident = str(k).partition(':')
        if kind in KINDS:
            out[key(kind, int(ident))] = max(0, min(int(v), MAX_COUNT))
        elif kind == WARGEAR and re.fullmatch(r'[a-z0-9]{1,80}', ident):
            out[key(kind, ident)] = max(0, min(int(v), MAX_COUNT))
        else:
            raise ValueError(k)
    return out or None
