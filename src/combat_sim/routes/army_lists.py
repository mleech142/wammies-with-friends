"""
Army lists (armies.py): built and priced on the Armies page, shared as codes, shown in Match view, used in Analytics
and Play.
"""

from flask import jsonify, render_template, request

from .. import access, armies, army_share, match_view
from ..models import Faction, SavedArmy, Unit, db


def register(app):
    """The army lists routes."""

    # --- Army lists (armies.py): built on the Armies page, used in Analytics ----------------

    @app.route('/armies')
    def armies_page():
        factions = Faction.query.order_by(Faction.name).all()
        return render_template('armies.html', factions=[{'id': f.id, 'name': f.name} for f in factions],
                               battle_sizes=armies.BATTLE_SIZES)

    def army_from_request():
        try:
            return armies.clean_army(request.get_json(silent=True)), None
        except armies.ArmyError as err:
            return None, (jsonify({'error': str(err)}), 400)

    def saved_army_response(saved):
        """A saved army with its prices and problems (its units priced too)."""
        army = saved.to_dict()
        whose = access.owner_names().get(saved.owner_id) if access.principal().shared else None
        return jsonify(dict(army, **armies.price_army(army), mine=access.can_write(saved), owner=whose))


    @app.route('/api/armies')
    def api_list_armies():
        """Saved armies, newest first, with their faction and points. On a self-hosted copy, every player's: 'mine'
        says which are yours, 'owner' whose the others are (read-only; a copy is yours)."""
        names = {f.id: f.name for f in Faction.query}
        players = access.owner_names() if access.principal().shared else None
        out = []
        for saved in SavedArmy.query.order_by(SavedArmy.updated_at.desc(), SavedArmy.id.desc()):
            priced = armies.price_army(saved.to_dict())
            out.append({'id': saved.id, 'name': saved.name, 'faction': names.get(saved.faction_id),
                        'detachment': priced['detachment'], 'total': priced['total'],
                        'points_limit': saved.points_limit, 'unit_count': len(saved.units or []),
                        'problem_count': len(priced['problems']), 'mine': access.can_write(saved),
                        'owner': players.get(saved.owner_id) if players is not None else None})
        out.sort(key=lambda a: not a['mine'])  # Yours first
        return jsonify(out)

    @app.route('/api/armies/price', methods=['POST'])
    def api_price_army():
        """Price and check an army as it is being built (nothing is saved)."""
        army, error = army_from_request()
        if error:
            return error
        return jsonify(armies.price_army(army))

    @app.route('/api/armies/wargear', methods=['POST'])
    def api_army_wargear():
        """
        One unit's wargear for the Armies page's popup: {unit_id, faction_id, models, wargear} ->
        {models, points, problems, wargear (the full choices), loadout, form, summary, sizes}.
        """
        data = request.get_json(silent=True) or {}
        unit = db.session.get(Unit, int(data.get('unit_id') or 0))
        if unit is None or unit.wargear is None:
            return jsonify({'error': 'This unit has no wargear to choose.'}), 404
        try:
            choices = armies.clean_wargear(data.get('wargear'))
            models = int(data.get('models') or 0) or None
        except (armies.ArmyError, TypeError, ValueError) as err:
            return jsonify({'error': str(err)}), 400
        faction = db.session.get(Faction, int(data.get('faction_id') or unit.faction_id))
        result = armies.unit_wargear(unit, choices, models, faction.bsdata_id if faction else None)
        return jsonify(dict(result, wargear=result.pop('choices'), sizes=armies.sizes_of(unit), name=unit.name))

    @app.route('/api/armies/text', methods=['POST'])
    def api_army_text():
        """An army as plain text, to share."""
        army, error = army_from_request()
        if error:
            return error
        return jsonify({'text': armies.army_text(army, armies.price_army(army))})

    @app.route('/api/armies/share', methods=['POST'])
    def api_army_share_code():
        """An army as a share code another install can import (army_share.py); lists with custom units can't be shared."""
        army, error = army_from_request()
        if error:
            return error
        try:
            return jsonify({'code': army_share.encode(army)})
        except armies.ArmyError as err:
            return jsonify({'error': str(err)}), 400

    @app.route('/api/armies/import', methods=['POST'])
    def api_army_import_code():
        """{code} -> {army (in this install's IDs, not saved), notes (what wasn't found in this install's data)}."""
        try:
            return jsonify(army_share.decode((request.get_json(silent=True) or {}).get('code')))
        except armies.ArmyError as err:
            return jsonify({'error': str(err)}), 400

    @app.route('/api/armies', methods=['POST'])
    def api_create_army():
        army, error = army_from_request()
        if error:
            return error
        saved = SavedArmy(**army, owner_id=access.stamp())
        db.session.add(saved)
        db.session.commit()
        return saved_army_response(saved)

    @app.route('/api/armies/<int:army_id>')
    def api_get_army(army_id):
        return saved_army_response(access.get(SavedArmy, army_id))

    @app.route('/armies/<int:army_id>/match')
    def army_match_page(army_id):
        saved = access.get(SavedArmy, army_id)
        return render_template('match.html', army_id=saved.id, army_name=saved.name)

    @app.route('/api/armies/<int:army_id>/match')
    def api_army_match(army_id):
        """A saved army's Match view: its units' datasheets, rules, enhancements and stratagems (match_view.py)."""
        return jsonify(match_view.match_view(access.get(SavedArmy, army_id).to_dict()))

    @app.route('/api/armies/<int:army_id>', methods=['PUT'])
    def api_update_army(army_id):
        saved = access.get(SavedArmy, army_id, write=True)
        army, error = army_from_request()
        if error:
            return error
        for key, value in army.items():
            setattr(saved, key, value)
        db.session.commit()
        return saved_army_response(saved)

    @app.route('/api/armies/<int:army_id>/copy', methods=['POST'])
    def api_copy_army(army_id):
        saved = access.get(SavedArmy, army_id)
        copy = SavedArmy(name=f'{saved.name} (copy)'[:200], faction_id=saved.faction_id,
                         detachment_keys=saved.to_dict()['detachment_keys'], points_limit=saved.points_limit,
                         warlord=saved.warlord, disposition=saved.disposition,
                         units=list(saved.units or []), owner_id=access.stamp())
        db.session.add(copy)
        db.session.commit()
        return saved_army_response(copy)

    @app.route('/api/armies/<int:army_id>', methods=['DELETE'])
    def api_delete_army(army_id):
        saved = access.get(SavedArmy, army_id, write=True)
        db.session.delete(saved)
        db.session.commit()
        return jsonify({'message': 'Army deleted'})
