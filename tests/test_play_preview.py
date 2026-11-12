"""
Play mode's previews (src/combat_sim/play/game.py, routes.py): what an attack would likely do before it's rolled
(attack_preview), a charge's chance to reach each enemy unit (charge_chance, charge_options' `reach`), and a dry run of
a move while it's dragged (session.GameSession.check, /check).
"""

import copy

import pytest

from combat_sim.play.game import ActionError, attack_preview, charge_chance, charge_options, new_game
from test_play_api import client, game, place, ROW  # noqa: F401  (fixtures)
from test_play_fight import MOB, SQUAD as CHARGERS, battle, fighters, to_step
from test_play_game import army, gun, part
from test_play_turns import put
from test_play_shooting import BASE, SQUAD, game as shooting_game, gunner

# Ten automatic hits at Strength 20 against Toughness 4 (wounds on 2+), no save: the three-model squad is all but
# certain to die
CANNON = gun('Cannon', attacks='10', skill=None, strength=20, ap=6, range=24)
PEASHOOTER = gun('Peashooter', attacks='1', skill=6, strength=1, ap=0, range=24)


def unsaved(name, models, wounds=1, **extra):
    return part(name, models, wounds, base=BASE, save=7, **extra)


def test_a_preview_says_how_many_models_would_likely_die_and_the_chances():
    squad = (unsaved('Squad', 3), (10, 10), (11.5, 10), (13, 10))
    state = shooting_game([squad], [gunner(CANNON)])
    before = copy.deepcopy(state)
    preview = attack_preview(state, 'p2-gunner', [{'part': 0, 'weapon': 0, 'target': 'p1-squad'}])
    target = preview['targets']['p1-squad']
    assert target['models'] == 3 and target['kills'] > 2.9
    assert target['wipe_chance'] >= 99 and target['kill_chance'] == 100
    assert target['hits'] == 10  # Torrent-like: every attack hits
    assert state == before  # Nothing changes and no game dice are rolled


def test_a_weak_attack_previews_low_chances():
    state = shooting_game([SQUAD], [gunner(PEASHOOTER)])
    target = attack_preview(state, 'p2-gunner', [{'part': 0, 'weapon': 0, 'target': 'p1-squad'}])['targets']['p1-squad']
    assert target['wipe_chance'] == 0 and target['kill_chance'] < 10


def test_a_preview_refuses_what_the_attack_would_refuse():
    far = (unsaved('Squad', 3), (10, 10), (11.5, 10), (13, 10))
    state = shooting_game([far], [gunner(gun('Pistol', range=3))])
    with pytest.raises(ActionError, match='in range'):
        attack_preview(state, 'p2-gunner', [{'part': 0, 'weapon': 0, 'target': 'p1-squad'}])


def test_a_led_unit_shows_the_chance_its_leader_dies():
    bodyguard = unsaved('Squad', 2, role='bodyguard')
    leader = unsaved('Hero', 1, 3, role='leader')
    state = new_game([army('Red', (bodyguard, leader)), army('Blue', (gunner(CANNON)[0],))])
    put(state, 'p1-squad', (10, 10), (11.5, 10), (13, 10))
    put(state, 'p2-gunner', (11.5, 20))
    state['turn'] = {'phase': 'shooting', 'round': 1, 'player': 1}
    target = attack_preview(state, 'p2-gunner', [{'part': 0, 'weapon': 0, 'target': 'p1-squad'}])['targets']['p1-squad']
    assert target['models'] == 3 and target['leader']['name'] == 'Hero'
    assert 0 < target['leader']['chance'] <= 100  # 10 shots: the bodyguards first, then the leader's 3 wounds


def test_a_fight_preview_uses_the_models_engaged_with_the_target():
    state = to_step(fighters(), 'fight')
    preview = attack_preview(state, 'p1-squad', None, 'fight')
    target = preview['targets']['p2-mob']
    assert target['models'] == 3 and 0 <= target['kills'] <= 3


def test_charge_chances_on_2d6():
    assert charge_chance(1.5) == 100  # Any roll
    assert charge_chance(7) == 58  # 21 of 36
    assert charge_chance(6.2) == 58  # A 7 is needed for 6.2"
    assert charge_chance(12) == 3  # Only double six
    assert charge_chance(7, skies=True) == 28  # 2" less: a 9 is needed


def test_charge_options_give_the_chance_to_reach_each_unit_before_the_roll():
    options = charge_options(battle([CHARGERS], [MOB]), 'p1-squad')
    reach = options['reach']['p2-mob']
    assert reach['distance'] == pytest.approx(6.74, abs=0.01) and reach['chance'] == 58


# --- Through the API -------------------------------------------------------------------------------------

def test_a_move_can_be_checked_without_making_it(client, game):  # noqa: F811
    models = [m['id'] for u in game['state']['units'] if u['id'] == 'p1-w' for m in u['models']]
    spots = lambda y: [{'id': m, 'x': x, 'y': y, 'angle': 0} for m, (x, _) in zip(models, ROW)]  # noqa: E731
    check = lambda body: client.post(f'/api/play/games/{game["id"]}/check', json=body).get_json()  # noqa: E731
    assert check({'type': 'place', 'unit': 'p1-w', 'models': spots(6)}) == {'ok': True, 'error': None}
    refused = check({'type': 'place', 'unit': 'p1-w', 'models': spots(20)})  # Out of its deployment zone
    assert refused['ok'] is False and refused['error']
    assert check({'type': 'next_phase'})['ok'] is False  # Only moves
    assert client.get(f'/api/play/games/{game["id"]}').get_json()['events'] == []  # Nothing was made


def test_the_games_list_says_where_each_game_stands(client, game):  # noqa: F811
    listed = client.get('/api/play/games').get_json()
    entry = next(g for g in listed if g['id'] == game['id'])
    assert entry['phase'] == 'deployment' and entry['score'] == [0, 0]
    assert entry['your_move'] is None  # Hot-seat: both players are here


def test_a_shot_can_be_previewed_through_the_api(client, game):  # noqa: F811
    act = lambda body: client.post(f'/api/play/games/{game["id"]}/actions', json=body)  # noqa: E731
    place(client, game, 'p1-w', ROW)
    place(client, game, 'p2-g', [(10, 38), (11.5, 38)])
    place(client, game, 'p1-c', [(30, 6)])
    assert act({'type': 'end_deployment'}).status_code == 200
    for _ in range(9):  # To Blue's Shooting phase
        assert act({'type': 'next_phase'}).status_code == 200
    events = len(client.get(f'/api/play/games/{game["id"]}').get_json()['events'])
    body = {'unit': 'p2-g', 'weapons': [{'part': 0, 'weapon': 0, 'target': 'p1-w'}]}
    preview = client.post(f'/api/play/games/{game["id"]}/preview', json=body)
    assert preview.status_code == 200, preview.get_json()
    target = preview.get_json()['targets']['p1-w']
    assert target['models'] == 5 and 0 <= target['kill_chance'] <= 100
    assert len(client.get(f'/api/play/games/{game["id"]}').get_json()['events']) == events
    wrong = client.post(f'/api/play/games/{game["id"]}/preview', json={'unit': 'p2-g', 'weapons': 'all'})
    assert wrong.status_code == 400
