"""
Helpers more than one area's routes use.
"""

from flask import request

from ..models import Unit, db
from ..simulation import BattleConditions


def conditions_from_request(conditions_data):
    return BattleConditions(
        half_range=bool(conditions_data.get('half_range', False)),
        charged=bool(conditions_data.get('charged', False)),
        stationary=bool(conditions_data.get('stationary', False)),
        cover=bool(conditions_data.get('cover', False)),
        damaged=bool(conditions_data.get('damaged', False)),
        reroll_hits=conditions_data.get('reroll_hits', 'none'),
        reroll_wounds=conditions_data.get('reroll_wounds', 'none')
    )


def legends_filter(query):
    """Legends units only with ?legends=1."""
    if request.args.get('legends') in ('1', 'true'):
        return query
    return query.filter(db.or_(Unit.legends.is_(None), Unit.legends.is_(False)))
