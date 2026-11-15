"""
Simple wargear (docs/wahapedia-migration.md, step 5): a unit's weapons are its datasheet loadout plus its wargear
options, each with how many of its models carry it. The player follows the datasheet's own option text
(`Unit.wargear_options`, shown beside the counts); the app sets no limits and adds no points for options.

An army entry's `wargear` for such a unit is {'ranged:<weapon id>': count, 'melee:<weapon id>': count} with every
weapon the unit can carry; None is the datasheet's loadout at the unit's size. `evaluate` gives what the Armies
page's popup, Analytics, Match view and Play read (`loadout` rows of {'weapon_id', 'weapon_type', 'name', 'qty',
'default_use'}).
"""

from .models import MeleeWeapon, RangedWeapon

KINDS = ('ranged', 'melee')
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


def key(kind, weapon_id):
    return f'{kind}:{weapon_id}'


def is_simple(choices):
    """True for this module's choices ({'ranged:12': 2}), False for a BSData option tree's ({'3': 1})."""
    return not choices or all(':' in str(k) for k in choices)


def has_choices(unit):
    """A unit with something to choose: wargear options (weapons or the datasheet's option text)."""
    return bool(unit.ranged_options or unit.melee_options or unit.wargear_options)


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


def evaluate(unit, choices, models):
    """
    {'models', 'points': None (options cost nothing here), 'choices' (None when they are the datasheet's),
    'loadout', 'summary', 'form', 'options_text', 'problems': [], 'effects': None} for a unit at `models` models.
    """
    models = models or unit.default_models or 1
    listed = weapons(unit, models)
    counts = {}
    for kind, weapon, default, _ in listed:
        value = (choices or {}).get(key(kind, weapon.id), default)
        try:
            counts[key(kind, weapon.id)] = max(0, min(int(value), MAX_COUNT))
        except (TypeError, ValueError):
            counts[key(kind, weapon.id)] = default
    changed = any(counts[key(kind, w.id)] != default for kind, w, default, _ in listed)
    rows, form, summary = [], [], []
    for kind, weapon, default, option in listed:
        count = counts[key(kind, weapon.id)]
        form.append({'key': key(kind, weapon.id), 'kind': kind, 'name': weapon.name, 'count': count,
                     'default': default, 'option': option})
        if count:
            rows.append({'weapon_id': weapon.id, 'weapon_type': kind, 'name': weapon.name, 'qty': count})
        if count != default:
            summary.append(f'{count} × {weapon.name}')
    for row, used in zip(rows, default_used([r['name'] for r in rows])):
        row['default_use'] = used
    return {'models': models, 'points': None, 'choices': counts if changed else None, 'loadout': rows,
            'summary': ', '.join(summary), 'form': form, 'options_text': list(unit.wargear_options or []),
            'problems': [], 'effects': None}


def clean(value):
    """Simple choices from a request, or None; raises ValueError for anything else."""
    out = {}
    for k, v in value.items():
        kind, _, ident = str(k).partition(':')
        if kind not in KINDS:
            raise ValueError(k)
        out[key(kind, int(ident))] = max(0, min(int(v), MAX_COUNT))
    return out or None

