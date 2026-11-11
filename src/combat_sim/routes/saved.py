"""
Saved matrix comparisons (each player's own: access.py).
"""

from flask import jsonify, request

from .. import access
from ..models import SavedComparison, db


def register(app):
    """The saved routes."""

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
