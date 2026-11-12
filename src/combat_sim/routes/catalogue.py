"""
What the pages choose from: units with their weapons and leaders, the rules and stratagems that can be ticked,
detachments, enhancements, and the keyword check.
"""

from flask import jsonify, request

from ..engagement import MAX_MODELS
from ..match_view import hint_for, keyword_hints
from ..models import Detachment, Enhancement, Faction, FactionRule, Keyword, MeleeWeapon, RangedWeapon, Stratagem, Unit, db
from ..simulation import check_keywords, keyword_name
from ..wargear import default_used
from .shared import legends_filter


MAX_UNIT_SIZE = MAX_MODELS  # Largest model count the pages' number boxes allow


def modifier_has_effect(text, modelled_names):
    """True if any entry of a modifier text is a keyword the calculations use."""
    entries = [m for m in (text or '').split(',') if m.strip() and m.strip().lower() != 'none']
    if not modelled_names:
        return bool(entries)
    return any(keyword_name(m).lower() in modelled_names for m in entries)


def register(app):
    """The catalogue routes."""

    @app.route('/api/units')
    def api_units():
        """Get units, optionally filtered by faction."""
        faction_id = request.args.get('faction_id', type=int)
        search = request.args.get('search', '').strip()

        query = legends_filter(Unit.query)

        if faction_id:
            query = query.filter(Unit.faction_id == faction_id)

        if search:
            query = query.filter(Unit.name.ilike(f'%{search}%'))

        query = query.order_by(Unit.name)
        units = query.all() if faction_id else query.limit(50).all()  # Search results are capped
        return jsonify([u.to_dict() for u in units])


    @app.route('/api/units/<int:unit_id>')
    def api_unit(unit_id):
        """Get a specific unit with its weapons."""
        unit = db.get_or_404(Unit, unit_id)
        data = unit.to_dict()
        # qty = how many models in the unit carry the weapon; default_use = ticked by default
        for weapon_type in ('ranged', 'melee'):
            loadout = unit.loadout(weapon_type)
            data[f'{weapon_type}_weapons'] = [
                dict(w.to_dict(), qty=qty, default_use=used)
                for (w, qty), used in zip(loadout, default_used([w.name for w, _ in loadout]))
            ]
        # Leaders that can join this unit (with what they grant and their points)
        data['leaders'] = [dict(id=u.id, name=u.name, leader_buffs=u.effective_leader_buffs,
                                points=u.points_for(u.default_models or 1)) for u in unit.leaders()]
        # Wargear options not in the default loadout (BSData units)
        for weapon_type, model in (('ranged', RangedWeapon), ('melee', MeleeWeapon)):
            ids = getattr(unit, f'{weapon_type}_options') or []
            weapons = {w.id: w for w in model.query.filter(model.id.in_(ids))} if ids else {}
            data[f'{weapon_type}_options'] = [weapons[i].to_dict() for i in ids if i in weapons]
        # Points for every unit size the pages offer (index = model count), from Unit.points_for
        data['points_by_model_count'] = [None] + [unit.points_for(n) for n in range(1, MAX_UNIT_SIZE + 1)]
        # What each weapon ability means (the keyword glossary's summary), for the pages to show on a tap or hover
        hints = keyword_hints()
        abilities = {a for kind in ('ranged', 'melee') for key in (f'{kind}_weapons', f'{kind}_options')
                     for w in data[key] for a in w.get('abilities') or []}
        data['ability_hints'] = {a: hint for a in sorted(abilities) if (hint := hint_for(a, hints))}
        return jsonify(data)

    @app.route('/api/rules/available')
    def api_rules_available():
        """
        Rules and stratagems that can be ticked for one side.

        ?side=Attacker|Target, one or more ?faction_id=N and any ?detachment=<BSData ID>.
        Returns the factions' rules and stratagems for that side (those for the whole faction,
        plus those for a chosen detachment) and the core stratagems, each with whether its
        modifier text changes the calculations.
        """
        side = request.args.get('side', 'Attacker')
        faction_ids = [i for i in request.args.getlist('faction_id', type=int) if i]
        chosen = set(request.args.getlist('detachment'))

        def offered(record):
            if record.superseded or (record.source == 'wahapedia' and not record.phase):
                return False  # Replaced by Wahapedia's, or used outside the Shooting and Fight phases
            return (record.applies_to or 'Attacker') == side and (
                not record.detachment_key or record.detachment_key in chosen)
        modelled = {k.name.lower() for k in Keyword.query.filter_by(modelled=True)}
        names = {f.id: f.name for f in Faction.query}

        def entry(record, kind):
            return {
                'key': f'{"rule" if kind == "rule" else "stratagem"}:{record.id}',
                'id': record.id,
                'kind': kind,
                'faction_id': record.faction_id,
                'faction': names.get(record.faction_id),
                'name': record.name,
                'cp': getattr(record, 'cp', None),
                'phase': record.phase or 'Both',
                'modifier': record.modifier,
                'has_effect': modifier_has_effect(record.modifier, modelled),
                'detachment': record.detachment_name,
                'source': record.source,
                'conditions': [] if record.edited else (record.parse or {}).get('conditions') or [],
            }

        entries = []
        if faction_ids:
            rules = FactionRule.query.filter(FactionRule.faction_id.in_(faction_ids)).order_by(FactionRule.name)
            entries += [entry(r, 'rule') for r in rules if offered(r)]
            strats = Stratagem.query.filter(Stratagem.faction_id.in_(faction_ids)).order_by(Stratagem.name)
            entries += [entry(st, 'stratagem') for st in strats if offered(st)]
        core = Stratagem.query.filter(Stratagem.faction_id.is_(None)).order_by(Stratagem.name)
        entries += [entry(st, 'core') for st in core if offered(st)]
        return jsonify(entries)

    @app.route('/api/detachments')
    def api_detachments():
        """BSData detachments of one or more ?faction_id=N, with their rule text."""
        faction_ids = [i for i in request.args.getlist('faction_id', type=int) if i]
        if not faction_ids:
            return jsonify([])
        rows = Detachment.query.filter(Detachment.faction_id.in_(faction_ids)).order_by(Detachment.name)
        return jsonify([d.to_dict() for d in rows])

    @app.route('/api/enhancements')
    def api_enhancements():
        """BSData enhancements of one or more ?faction_id=N, with their points, text and modelled effects."""
        faction_ids = [i for i in request.args.getlist('faction_id', type=int) if i]
        if not faction_ids:
            return jsonify([])
        rows = Enhancement.query.filter(Enhancement.faction_id.in_(faction_ids)).order_by(Enhancement.name)
        return jsonify([e.to_dict() for e in rows])

    @app.route('/api/keywords/check', methods=['POST'])
    def api_keywords_check():
        """As-you-type keyword hints: {'text', 'mode'} -> {'unknown': [...], 'capitals': [[entry, name]]}."""
        data = request.get_json() or {}
        names = [k.name for k in Keyword.query]
        if not names:
            return jsonify({'unknown': [], 'capitals': []})  # no keyword reference loaded
        return jsonify(check_keywords(data.get('text', ''), names, data.get('mode', '')))
