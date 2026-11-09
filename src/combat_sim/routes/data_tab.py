"""
The Data tab: the app data (custom factions, units, weapons, rules, stratagems, keywords, target profiles), read and
changed. Every change is an edit made by app_data_edits.py; on a self-hosted copy a player's becomes a proposal
(access.py, proposals.py).
"""

from flask import jsonify, render_template, request

from .. import app_data_edits as edits
from .. import reference
from ..access import host_only
from ..app_data_edits import WEAPON_MODELS, edit_route
from ..data_store import DataFileError, check_data
from ..models import Detachment, Faction, FactionRule, Keyword, MeleeWeapon, Stratagem, TargetProfile, Unit, db, unit_melee_weapons, unit_ranged_weapons
from .shared import legends_filter


def register(app):
    """The data tab routes."""

    @app.route('/data')
    def data_page():
        """Data management page."""
        return render_template('data.html')

    # =========================================================================
    # Data Management API
    #
    # Every change is committed to the database and then written straight to the app
    # data JSON (see data_store.py). BSData factions' units and weapons are read-only;
    # their rules and stratagems, and modifiers added to their units, are app data.
    # =========================================================================

    def save_data():
        reference.save_app_data(app)  # never while the reference tables are being rebuilt

    def run_edit(edit):
        """A Data-tab change (app_data_edits.py) as a web answer."""
        try:
            return jsonify(edits.apply(app, edit))
        except edits.EditError as error:
            return jsonify({'error': str(error)}), error.status


    @app.route('/api/data/export')
    def api_data_export():
        """The current app data JSON (BSData records are left out)."""
        return jsonify(reference.export(app))

    @app.route('/api/data/import', methods=['POST'])
    @host_only
    def api_data_import():
        """Replace all app data with an uploaded app data JSON (BSData stays as loaded)."""
        data = request.get_json()
        try:
            check_data(data)
        except DataFileError as err:
            return jsonify({'error': str(err)}), 400
        reference.load(app, data=data)
        save_data()
        return jsonify({'message': 'Data imported'})

    @app.route('/api/data/target-profiles')
    def api_data_target_profiles():
        """Generic opponent profiles and role benchmarks (read-only; from the workbook)."""
        profiles = TargetProfile.query.order_by(TargetProfile.kind, TargetProfile.id).all()
        return jsonify([t.to_dict() for t in profiles])

    @app.route('/api/data/keywords')
    def api_data_keywords():
        """The keywords reference (read-only)."""
        return jsonify([k.to_dict() for k in Keyword.query.order_by(Keyword.id).all()])

    # --- Factions -----------------------------------------------------------

    @app.route('/api/data/factions')
    def api_data_factions():
        """Get all factions with counts."""
        factions = Faction.query.order_by(Faction.name).all()
        unit_counts = dict(db.session.query(Unit.faction_id, db.func.count(Unit.id)).group_by(Unit.faction_id))
        return jsonify([{
            'id': f.id,
            'name': f.name,
            'source': f.source,
            'editable': f.editable,
            'unit_count': unit_counts.get(f.id, 0),
            'rule_count': f.faction_rules.filter_by(superseded=False).count(),
            'stratagem_count': f.stratagems.filter_by(superseded=False).count(),
        } for f in factions])

    @app.route('/api/data/factions/<int:faction_id>/reference')
    def api_data_faction_reference(faction_id):
        """BSData's text for a faction: army rules and detachments (read-only reference)."""
        faction = db.get_or_404(Faction, faction_id)
        detachments = Detachment.query.filter_by(faction_id=faction.id).order_by(Detachment.name)
        return jsonify({'army_rules': faction.army_rules or [], 'detachments': [d.to_dict() for d in detachments]})

    @app.route('/api/data/factions', methods=['POST'])
    @edit_route('faction', 'add')
    def api_data_create_faction():
        """Create a new (custom) faction."""
        return run_edit(edits.make('faction', 'add', fields=request.get_json(silent=True)))

    @app.route('/api/data/factions/<int:faction_id>', methods=['PUT'])
    @edit_route('faction', 'change')
    def api_data_update_faction(faction_id):
        """Rename a custom faction."""
        return run_edit(edits.make('faction', 'change', faction_id, fields=request.get_json(silent=True)))

    @app.route('/api/data/factions/<int:faction_id>', methods=['DELETE'])
    @edit_route('faction', 'delete')
    def api_data_delete_faction(faction_id):
        """Delete a custom faction with its units, weapons, rules and stratagems."""
        return run_edit(edits.make('faction', 'delete', faction_id, fields=request.get_json(silent=True)))

    # --- Faction rules ------------------------------------------------------

    @app.route('/api/data/rules')
    def api_data_rules():
        """Faction rules, optionally for one faction."""
        query = FactionRule.query.filter_by(superseded=False)
        if request.args.get('faction_id', type=int):
            query = query.filter_by(faction_id=request.args.get('faction_id', type=int))
        return jsonify([r.to_dict() for r in query.order_by(FactionRule.name).all()])

    @app.route('/api/data/rules', methods=['POST'])
    @edit_route('rule', 'add')
    def api_data_create_rule():
        """Add a faction rule."""
        return run_edit(edits.make('rule', 'add', fields=request.get_json(silent=True)))

    @app.route('/api/data/rules/<int:rule_id>', methods=['PUT'])
    @edit_route('rule', 'change')
    def api_data_update_rule(rule_id):
        """Change a rule (a Wahapedia one: how the maths reads it)."""
        return run_edit(edits.make('rule', 'change', rule_id, fields=request.get_json(silent=True)))

    @app.route('/api/data/rules/<int:rule_id>', methods=['DELETE'])
    @edit_route('rule', 'delete')
    def api_data_delete_rule(rule_id):
        """Delete a rule (not a Wahapedia one)."""
        return run_edit(edits.make('rule', 'delete', rule_id, fields=request.get_json(silent=True)))

    # --- Stratagems (core when faction_id is null) --------------------------

    @app.route('/api/data/stratagems')
    def api_data_stratagems():
        """Stratagems: ?core=1 for core ones, ?faction_id=N for a faction's, otherwise all."""
        query = Stratagem.query.filter_by(superseded=False)
        if request.args.get('core'):
            query = query.filter(Stratagem.faction_id.is_(None))
        elif request.args.get('faction_id', type=int):
            query = query.filter_by(faction_id=request.args.get('faction_id', type=int))
        return jsonify([s.to_dict() for s in query.order_by(Stratagem.name).all()])

    @app.route('/api/data/stratagems', methods=['POST'])
    @edit_route('stratagem', 'add')
    def api_data_create_stratagem():
        """Add a stratagem (core when faction_id is null)."""
        return run_edit(edits.make('stratagem', 'add', fields=request.get_json(silent=True)))

    @app.route('/api/data/stratagems/<int:strat_id>', methods=['PUT'])
    @edit_route('stratagem', 'change')
    def api_data_update_stratagem(strat_id):
        """Change a stratagem (a Wahapedia one: how the maths reads it)."""
        return run_edit(edits.make('stratagem', 'change', strat_id, fields=request.get_json(silent=True)))

    @app.route('/api/data/stratagems/<int:strat_id>', methods=['DELETE'])
    @edit_route('stratagem', 'delete')
    def api_data_delete_stratagem(strat_id):
        """Delete a stratagem (not a Wahapedia one)."""
        return run_edit(edits.make('stratagem', 'delete', strat_id, fields=request.get_json(silent=True)))

    # --- Units --------------------------------------------------------------

    @app.route('/api/data/units')
    def api_data_units():
        """Get all units with faction info and loadout counts."""
        faction_id = request.args.get('faction_id', type=int)
        query = legends_filter(Unit.query.join(Faction))

        if faction_id:
            query = query.filter(Unit.faction_id == faction_id)

        units = query.order_by(Faction.name, Unit.name).all()
        return jsonify([dict(
            u.to_dict(),
            ranged_weapon_count=len(u.ranged_weapons),
            melee_weapon_count=len(u.melee_weapons),
        ) for u in units])

    @app.route('/api/data/units', methods=['POST'])
    @edit_route('unit', 'add')
    def api_data_create_unit():
        """Create a new unit in a custom faction."""
        return run_edit(edits.make('unit', 'add', fields=request.get_json(silent=True)))

    @app.route('/api/data/units/<int:unit_id>', methods=['PUT'])
    @edit_route('unit', 'change')
    def api_data_update_unit(unit_id):
        """Update a custom unit and its loadout; a BSData unit only takes 'added_modifiers' and 'leader_buffs'."""
        return run_edit(edits.make('unit', 'change', unit_id, fields=request.get_json(silent=True)))

    @app.route('/api/data/units/<int:unit_id>', methods=['DELETE'])
    @edit_route('unit', 'delete')
    def api_data_delete_unit(unit_id):
        """Delete a custom unit. Its faction's weapons stay."""
        return run_edit(edits.make('unit', 'delete', unit_id, fields=request.get_json(silent=True)))

    # --- Weapons ------------------------------------------------------------

    def weapon_dict(weapon, unit_names=None):
        return dict(
            weapon.to_dict(),
            faction=weapon.faction.name if weapon.faction else None,
            unit_names=sorted(u.name for u in weapon.units) if unit_names is None else sorted(unit_names),
        )

    @app.route('/api/data/weapons')
    def api_data_weapons():
        """Weapons, filtered by ?type=ranged|melee|all and optional ?faction_id=."""
        weapon_type = request.args.get('type', 'all')
        faction_id = request.args.get('faction_id', type=int)
        weapons = []
        for type_name, model in WEAPON_MODELS.items():
            if weapon_type not in ('all', type_name):
                continue
            query = model.query
            if faction_id:
                query = query.filter(model.faction_id == faction_id)
            # Units carrying each weapon, in one query (a faction can have hundreds of weapons)
            table = unit_ranged_weapons if type_name == 'ranged' else unit_melee_weapons
            users = {}
            rows = db.session.query(table.c.weapon_id, Unit.name).join(Unit, Unit.id == table.c.unit_id)
            if faction_id:
                rows = rows.filter(Unit.faction_id == faction_id)
            for weapon_id, unit_name in rows:
                users.setdefault(weapon_id, set()).add(unit_name)
            weapons.extend(weapon_dict(w, users.get(w.id, ())) for w in query.order_by(model.name).all())
        weapons.sort(key=lambda w: ((w['faction'] or '').lower(), w['name'].lower()))
        return jsonify(weapons)

    @app.route('/api/data/weapons/bsdata')
    def api_data_bsdata_weapons():
        """BSData weapons to copy into a custom faction: ?q=name&type=ranged|melee (one per profile, 40 at most)."""
        search = request.args.get('q', '').strip()
        types = [request.args.get('type')] if request.args.get('type') in WEAPON_MODELS else list(WEAPON_MODELS)
        found, seen = [], set()
        for type_name in types:
            model = WEAPON_MODELS[type_name]
            query = model.query.join(Faction).filter(Faction.source == 'bsdata')
            if search:
                query = query.filter(model.name.ilike(f'%{search}%'))
            for w in query.order_by(model.name, model.id).limit(400):
                if (type_name, w.bsdata_id) in seen:
                    continue
                seen.add((type_name, w.bsdata_id))
                found.append(dict(w.to_dict(), faction=w.faction.name))
        found.sort(key=lambda w: w['name'].lower())
        return jsonify(found[:40])

    @app.route('/api/data/weapons', methods=['POST'])
    @edit_route('weapon', 'add')
    def api_data_create_weapon():
        """Create a new weapon for a custom faction."""
        return run_edit(edits.make('weapon', 'add', fields=request.get_json(silent=True)))

    @app.route('/api/data/weapons/<weapon_type>/<int:weapon_id>')
    def api_data_get_weapon(weapon_type, weapon_id):
        """Get a specific weapon."""
        model = WEAPON_MODELS.get(weapon_type, MeleeWeapon)
        return jsonify(weapon_dict(db.get_or_404(model, weapon_id)))

    @app.route('/api/data/weapons/<weapon_type>/<int:weapon_id>', methods=['PUT'])
    @edit_route('weapon', 'change')
    def api_data_update_weapon(weapon_type, weapon_id):
        """Update a weapon. Moving it to another faction drops it from other factions' units."""
        return run_edit(edits.make('weapon', 'change', weapon_id, fields=request.get_json(silent=True), weapon_type=weapon_type))

    @app.route('/api/data/weapons/<weapon_type>/<int:weapon_id>', methods=['DELETE'])
    @edit_route('weapon', 'delete')
    def api_data_delete_weapon(weapon_type, weapon_id):
        """Delete a weapon and remove it from every loadout."""
        return run_edit(edits.make('weapon', 'delete', weapon_id, fields=request.get_json(silent=True), weapon_type=weapon_type))
