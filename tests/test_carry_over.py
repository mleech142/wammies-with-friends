"""Carrying saved data over from BSData to Wahapedia (carry_over.py). All IDs here are made up."""

import json

import pytest

from combat_sim import carry_over
from combat_sim.models import db, Proposal, SavedArmy, SavedComparison, SavedGame, StableId
from combat_sim.wahapedia import stable_key, weapon_key

BASE = 1_000_000

# Two catalogues: a chapter (cat-ch) and its parent (cat-sm). Both copies of 'Squad' and both factions become
# one Wahapedia record; 'Relic Tank' has no match.
ID_MAP = {
    'factions': {'cat-sm': 'SM', 'cat-ch': 'SM'},
    'units': {'cat-sm/u-squad': '0001', 'cat-ch/u-squad': '0001', 'cat-sm/u-captain': '0002'},
    'ranged_weapons': {'cat-sm/w-rifle': {'faction': 'SM', 'name': 'boltrifle'},
                       'cat-ch/w-rifle': {'faction': 'SM', 'name': 'boltrifle'},
                       'cat-sm/w-plasma': {'faction': 'SM', 'name': 'plasmagun', 'profile': '1|3|7|2|1|24'}},
    'melee_weapons': {'cat-sm/w-sword': {'faction': 'SM', 'name': 'powersword'}},
    'detachments': {'cat-sm/d-gladius': '0100', 'cat-ch/d-gladius': '0100'},
    'enhancements': {'cat-sm/e-relic': '0200'},
}
STABLE = [
    ('faction:cat-sm', 'factions', BASE), ('faction:cat-ch', 'factions', BASE + 1),
    ('unit:cat-sm/u-squad', 'units', BASE + 10), ('unit:cat-ch/u-squad', 'units', BASE + 11),
    ('unit:cat-sm/u-captain', 'units', BASE + 12), ('unit:cat-sm/u-relic-tank', 'units', BASE + 13),
    ('ranged:cat-sm/w-rifle', 'ranged_weapons', BASE + 20), ('ranged:cat-ch/w-rifle', 'ranged_weapons', BASE + 21),
    ('ranged:cat-sm/w-plasma', 'ranged_weapons', BASE + 22), ('melee:cat-sm/w-sword', 'melee_weapons', BASE + 21),
    ('detachment:cat-sm/d-gladius', 'detachments', BASE + 30), ('detachment:cat-ch/d-gladius', 'detachments', BASE + 31),
    ('enhancement:cat-sm/e-relic', 'enhancements', BASE + 40),
]


@pytest.fixture
def app(make_client):
    client, _ = make_client({'schema_version': 2})
    app = client.application
    with app.app_context():
        StableId.query.delete()
        db.session.add_all([StableId(key=k, table=t, id=i) for k, t, i in STABLE])
        db.session.commit()
        yield app


def stable():
    return {r.key: r.id for r in StableId.query.all()}


def test_stable_ids_are_rekeyed_and_merged(app):
    report = carry_over.carry_over_database(carry_over.IdMap(ID_MAP))
    keys = stable()
    assert keys[stable_key('faction', 'SM')] == BASE  # The lowest of the two chapters' IDs
    assert keys[stable_key('unit', '0001')] == BASE + 10
    assert keys[stable_key('unit', '0002')] == BASE + 12
    assert keys[weapon_key('ranged', 'SM', 'Bolt rifle')] == BASE + 20
    assert keys[weapon_key('ranged', 'SM', 'Plasma gun', '1|3|7|2|1|24')] == BASE + 22
    assert keys[weapon_key('melee', 'SM', 'Power sword')] == BASE + 21  # Melee IDs are their own table's
    assert keys[stable_key('detachment', '0100')] == BASE + 30
    assert keys[stable_key('enhancement', '0200')] == BASE + 40
    assert keys['unit:cat-sm/u-relic-tank'] == BASE + 13  # No match: kept, so its ID is never reused
    assert 'unit:cat-ch/u-squad' not in keys and 'faction:cat-ch' not in keys
    assert report['merged'] == 4  # Faction, unit, weapon and detachment copies


def test_saved_army_is_carried_over_with_missing_units_flagged(app):
    # The units table still holds BSData's names when the carry-over runs (before the rebuild); stand in for it
    army = SavedArmy(name='Chapter list', faction_id=BASE + 1, detachment_keys=['d-gladius'], units=[
        {'uid': 'u1', 'unit_id': BASE + 11, 'models': 5, 'attached_to': None, 'enhancement': None,
         'wargear': {'3': 1}},
        {'uid': 'u2', 'unit_id': BASE + 12, 'models': 1, 'attached_to': 'u1', 'enhancement': 'e-relic', 'wargear': None},
        {'uid': 'u3', 'unit_id': BASE + 13, 'models': 1, 'attached_to': None, 'enhancement': None, 'wargear': None},
        {'uid': 'u4', 'unit_id': 7, 'models': 1, 'attached_to': None, 'enhancement': None, 'wargear': None},  # Custom
    ])
    db.session.add(army)
    db.session.commit()
    report = carry_over.carry_over_database(carry_over.IdMap(ID_MAP))

    army = db.session.get(SavedArmy, army.id)
    assert army.faction_id == BASE
    assert army.detachment_keys == ['0100']
    squad, captain, tank, custom = army.units
    assert squad['unit_id'] == BASE + 10 and squad['wargear'] is None
    assert captain['enhancement'] == '0200' and captain['attached_to'] == 'u1'
    assert tank['unit_id'] == BASE + 13 and tank['missing']
    assert 'missing' not in custom and custom['unit_id'] == 7
    assert report['armies'] == 1
    assert any('wargear' in n for n in report['notes'])
    assert any('flagged' in n for n in report['notes'])


def test_comparisons_games_and_proposals_are_carried_over(app):
    comparison = SavedComparison(
        name='Matrix', battle_conditions={'rules_ticked': {'detachments': {'attacker': ['d-gladius'], 'defender': []}}},
        attackers=[{'unit_id': BASE + 11, 'leader_id': BASE + 12, 'faction_id': BASE + 1,
                    'enhancements': [{'id': BASE + 40, 'bearer': 'leader'}],
                    'weapons': [{'weapon_id': BASE + 21, 'weapon_type': 'ranged'},
                                {'weapon_id': BASE + 21, 'weapon_type': 'melee'}]}],
        defenders=[{'unit_id': str(BASE + 11), 'model_count': 10}])
    game = SavedGame(name='Game', events=[], armies=[{'units': [{'parts': [{'unit_id': BASE + 11, 'bsdata_id': 'u-squad'}]}]}])
    proposal = Proposal(owner_id=1, method='POST', path='/api/data/x', summary='x',
                        body={'faction_key': 'cat-ch', 'detachment_key': 'd-gladius'})
    db.session.add_all([comparison, game, proposal])
    db.session.commit()
    report = carry_over.carry_over_database(carry_over.IdMap(ID_MAP))

    comparison = db.session.get(SavedComparison, comparison.id)
    attacker = comparison.attackers[0]
    assert (attacker['unit_id'], attacker['leader_id'], attacker['faction_id']) == (BASE + 10, BASE + 12, BASE)
    assert [w['weapon_id'] for w in attacker['weapons']] == [BASE + 20, BASE + 21]  # Ranged merged; melee its own
    assert comparison.defenders[0]['unit_id'] == str(BASE + 10)
    assert comparison.battle_conditions['rules_ticked']['detachments']['attacker'] == ['0100']
    part = db.session.get(SavedGame, game.id).armies[0]['units'][0]['parts'][0]
    assert part == {'unit_id': BASE + 10, 'bsdata_id': 'u-squad'}  # A frozen game keeps its own record
    assert db.session.get(Proposal, proposal.id).body == {'faction_key': 'SM', 'detachment_key': '0100'}
    assert (report['comparisons'], report['games'], report['proposals']) == (1, 1, 1)


def test_running_twice_changes_nothing(app):
    db.session.add(SavedArmy(name='List', faction_id=BASE, detachment_keys=['d-gladius'], units=[]))
    db.session.commit()
    id_map = carry_over.IdMap(ID_MAP)
    carry_over.carry_over_database(id_map)
    keys = stable()
    assert carry_over.carry_over_database(id_map) is None
    assert stable() == keys
    assert SavedArmy.query.one().detachment_keys == ['0100']


def test_app_data_is_upgraded():
    data = {
        'schema_version': 2,
        'faction_rules': [{'name': 'Oath', 'faction_key': 'cat-ch', 'detachment_key': 'd-gladius'}],
        'unit_modifiers': [{'bsdata_id': 'u-squad', 'name': 'Squad', 'modifiers': ['+1 Hit']},
                           {'bsdata_id': 'u-relic-tank', 'name': 'Relic Tank', 'modifiers': []}],
        'leader_buffs': [{'bsdata_id': 'u-captain', 'name': 'Captain', 'buffs': []}],
        'ranged_weapons': [{'name': 'My rifle', 'linked_bsdata_id': 'w-plasma'}],
    }
    upgraded = carry_over.upgrade_app_data(data, carry_over.IdMap(ID_MAP))
    assert upgraded['schema_version'] == 3
    assert upgraded['faction_rules'][0] == {'name': 'Oath', 'faction_key': 'SM', 'detachment_key': '0100'}
    assert upgraded['unit_modifiers'][0]['bsdata_id'] == '0001'
    assert upgraded['unit_modifiers'][1]['bsdata_id'] == 'u-relic-tank'  # No match: kept as it was
    assert upgraded['leader_buffs'][0] == {'bsdata_id': '0002', 'name': 'Captain', 'buffs': []}
    assert upgraded['ranged_weapons'][0]['linked_bsdata_id'] == 'SM/plasmagun@1|3|7|2|1|24'
    assert carry_over.upgrade_app_data(upgraded, carry_over.IdMap(ID_MAP)) == upgraded


def test_share_code_payload_is_translated():
    payload = {'v': 1, 'faction': 'cat-ch', 'faction_name': 'Chapter', 'name': 'List', 'limit': 1000,
               'detachments': ['d-gladius', 'd-unknown'], 'warlord': 2, 'disposition': 'Take and Hold',
               'units': [{'id': 'u-relic-tank', 'name': 'Relic Tank', 'models': 1},
                         {'id': 'u-squad', 'name': 'Squad', 'models': 5, 'wargear': {'opt': 1}},
                         {'id': 'u-captain', 'cat': 'cat-sm', 'name': 'Captain', 'models': 1, 'joins': 1,
                          'enh': 'e-relic'}]}
    out, notes = carry_over.share_payload(payload, carry_over.IdMap(ID_MAP))
    assert out['v'] == 2 and out['faction'] == 'SM' and out['detachments'] == ['0100']
    assert [u['id'] for u in out['units']] == ['0001', '0002']
    assert out['units'][1] == {'id': '0002', 'name': 'Captain', 'models': 1, 'enh': '0200', 'joins': 0}
    assert out['warlord'] == 1  # Positions count only the units kept
    assert len(notes) == 3  # The tank, the squad's wargear and the unknown detachment


def test_shipped_map_holds_ids_only():
    """The shipped map names Wahapedia records and carries no BSData text."""
    id_map = carry_over.shipped_map()
    assert id_map.data['factions'] and id_map.data['units']
    for section in ('units', 'detachments', 'enhancements'):
        assert all(isinstance(v, str) and v.isdigit() for v in id_map.data[section].values())
    for section in ('ranged_weapons', 'melee_weapons'):
        assert all(set(v) <= {'faction', 'name', 'profile'} for v in id_map.data[section].values())
    assert json.dumps(id_map.data['made_from']).count('wahapedia_last_update') == 1
