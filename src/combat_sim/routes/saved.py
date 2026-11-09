"""
Saved scenarios and comparisons (each player's own: access.py).
"""

from flask import jsonify, render_template, request

from .. import access
from ..models import SavedComparison, SavedScenario, db


def register(app):
    """The saved routes."""

    @app.route('/api/scenarios', methods=['POST'])
    def api_save_scenario():
        """Save a new scenario."""
        data = request.get_json()

        scenario = SavedScenario(
            name=data['name'],
            attacker_config=data['attacker'],
            defender_config=data['defender'],
            battle_conditions=data['conditions'],
            results=data.get('results'),
            owner_id=access.stamp(),
        )
        db.session.add(scenario)
        db.session.commit()

        return jsonify({'id': scenario.id, 'message': 'Scenario saved'})

    @app.route('/api/scenarios/<int:scenario_id>', methods=['DELETE'])
    def api_delete_scenario(scenario_id):
        """Delete a scenario."""
        scenario = access.get(SavedScenario, scenario_id, write=True)
        db.session.delete(scenario)
        db.session.commit()
        return jsonify({'message': 'Scenario deleted'})

    @app.route('/scenarios')
    def scenarios_page():
        """Saved scenarios page."""
        return render_template('scenarios.html')

    @app.route('/api/scenarios/<int:scenario_id>', methods=['PUT'])
    def api_update_scenario(scenario_id):
        """Update a scenario."""
        scenario = access.get(SavedScenario, scenario_id, write=True)
        data = request.get_json()

        if 'name' in data:
            scenario.name = data['name']
        if 'results' in data:
            scenario.results = data['results']
        if 'attacker' in data:
            scenario.attacker_config = data['attacker']
        if 'defender' in data:
            scenario.defender_config = data['defender']
        if 'conditions' in data:
            scenario.battle_conditions = data['conditions']

        db.session.commit()
        return jsonify({'id': scenario.id, 'message': 'Scenario updated'})

    @app.route('/api/scenarios')
    def api_get_scenarios():
        """Get all scenarios with full config."""
        scenarios = access.listed(SavedScenario, SavedScenario.query.order_by(SavedScenario.created_at.desc()))
        return jsonify([{
            'id': s.id,
            'name': s.name,
            'created_at': s.created_at.isoformat(),
            'attacker_config': s.attacker_config,
            'defender_config': s.defender_config,
            'battle_conditions': s.battle_conditions,
            'results': s.results,
        } for s in scenarios])

    @app.route('/api/comparisons', methods=['GET'])
    def api_list_comparisons():
        """List saved matrix comparisons."""
        comparisons = access.listed(SavedComparison, SavedComparison.query.order_by(SavedComparison.created_at.desc()))
        return jsonify([{
            'id': c.id,
            'name': c.name,
            'created_at': c.created_at.isoformat(),
            'attacker_count': len(c.attackers) if c.attackers else 0,
            'defender_count': len(c.defenders) if c.defenders else 0,
        } for c in comparisons])

    @app.route('/api/comparisons', methods=['POST'])
    def api_save_comparison():
        """Save a new matrix comparison."""
        data = request.get_json()

        comparison = SavedComparison(
            name=data['name'],
            attackers=data['attackers'],
            defenders=data['defenders'],
            battle_conditions=data['conditions'],
            results=data.get('results'),
            owner_id=access.stamp(),
        )
        db.session.add(comparison)
        db.session.commit()

        return jsonify({'id': comparison.id, 'message': 'Comparison saved'})

    @app.route('/api/comparisons/<int:comparison_id>')
    def api_get_comparison(comparison_id):
        """Get a specific comparison with full config."""
        c = access.get(SavedComparison, comparison_id)
        return jsonify({
            'id': c.id,
            'name': c.name,
            'created_at': c.created_at.isoformat(),
            'attackers': c.attackers,
            'defenders': c.defenders,
            'battle_conditions': c.battle_conditions,
            'results': c.results,
        })

    @app.route('/api/comparisons/<int:comparison_id>', methods=['DELETE'])
    def api_delete_comparison(comparison_id):
        """Delete a comparison."""
        comparison = access.get(SavedComparison, comparison_id, write=True)
        db.session.delete(comparison)
        db.session.commit()
        return jsonify({'message': 'Comparison deleted'})
