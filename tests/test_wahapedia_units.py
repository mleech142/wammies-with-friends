"""
Units, weapons, detachments and enhancements from Wahapedia's export (wahapedia_units.py), on the made-up export
in tests/fixtures/wahapedia (make_wahapedia_fixtures.py); simple wargear (loadouts.py); and the carry-over of saved
data from BSData's IDs when an app saved before 3.0 starts on Wahapedia (reference.load, carry_over.py).
"""

import pytest

from conftest import UNIT_FIXTURES, WAHAPEDIA_FIXTURES
from combat_sim import carry_over, reference, wahapedia_units
from combat_sim.models import Faction, SavedArmy, StableId, Unit, db

APP_DATA = {'schema_version': 3, 'source': None, 'factions': [], 'units': [], 'ranged_weapons': [], 'melee_weapons': [],
            'faction_rules': [], 'stratagems': [], 'unit_modifiers': [], 'keywords': [], 'target_profiles': []}


@pytest.fixture(scope='module')
def imported():
    return wahapedia_units.import_folder(WAHAPEDIA_FIXTURES)


def unit(imported, name):
    return next(u for u in imported.data['units'] if u['name'] == name)


def weapons(imported, entries, kind):
    names = {w['id']: w['name'] for w in imported.data[f'{kind}_weapons']}
    return {names[e['weapon_id']]: e['qty'] for e in entries}


def test_factions_and_units(imported):
    assert [f['name'] for f in imported.data['factions']] == ['Starfarers', 'Allies', 'Neutral Forces', 'Ghost Legion']
    names = [u['name'] for u in imported.data['units']]
    assert 'Summoned Echo' not in names  # A virtual datasheet
    walker = unit(imported, 'Star Walker [Legends]')
    assert walker['legends'] and walker['feel_no_pain'] == 6
    marksmen = unit(imported, 'Void Marksmen')
    assert marksmen['invulnerable_save'] is None and marksmen['modifiers'] == ['Ranged Invulnerable Save 5+']
    assert unit(imported, 'Field Medic')['modifiers'] == ['Melee Invulnerable Save 4+']
    assert unit(imported, 'Spectre')['feel_no_pain'] == 5  # From its ability's text
    assert unit(imported, 'Scout Drone')['modifiers'] == ['Damage Modifier -1']
    captain = unit(imported, 'Star Captain')
    assert (captain['toughness'], captain['save'], captain['wounds'], captain['invulnerable_save']) == (4, 2, 5, 4)
    assert captain['feel_no_pain'] == 5 and captain['move'] == '6' and captain['leadership'] == 6
    assert captain['_key'] == 'wh-unit:u-captain' and captain['bsdata_id'] == 'u-captain'
    assert 'Character' in captain['keywords']
    assert unit(imported, 'Void Warriors')['base']['length_mm'] == 32


def test_army_rules_are_the_faction_abilities_datasheets_list(imported):
    rules = {f['name']: [r['name'] for r in f['army_rules']] for f in imported.data['factions']}
    assert rules['Starfarers'] == ['Star Oath', 'Star Pact']  # Not Super-heavy Walker (core too) or Star Lore
    assert rules['Ghost Legion'] == ['Ghostly']


def test_points_sizes_and_later_copies(imported):
    warriors = unit(imported, 'Void Warriors')
    assert warriors['default_models'] == 5
    assert warriors['points_by_size'] == [{'models': 5, 'points': 80}, {'models': 10, 'points': 160}]
    assert warriors['copy_points'] == [0, 0, 10]  # "Your 3rd+ unit costs" 10 more
    assert unit(imported, 'Star Captain')['points_by_size'] == [{'models': 1, 'points': 70}]  # Repeated block once
    assert warriors['wargear_costs'] == [{'name': 'Heavy laser', 'points': 5}]
    assert unit(imported, 'Shield Brutes')['wargear_costs'] == [{'name': 'Brute shield', 'points': 10}]


def test_stat_line_and_loadout_of_a_mixed_unit(imported):
    warriors = unit(imported, 'Void Warriors')
    assert (warriors['save'], warriors['wounds']) == (3, 2)  # The four Void Warriors, not their Sergeant
    assert 'Stealth' in warriors['modifiers']
    assert weapons(imported, warriors['ranged_weapons'], 'ranged') == {
        'Laser pistol': 1, 'Laser rifle - standard': 4, 'Laser rifle - overcharge': 4}
    assert weapons(imported, warriors['melee_weapons'], 'melee') == {'Blade': 1, 'Close combat weapon': 4}
    ranged = {w['id']: w['name'] for w in imported.data['ranged_weapons']}
    melee = {w['id']: w['name'] for w in imported.data['melee_weapons']}
    assert [ranged[i] for i in warriors['ranged_options']] == ['Heavy laser']
    assert [melee[i] for i in warriors['melee_options']] == ['Power axe']
    assert 'heavy laser' in warriors['wargear_options'][0]
    assert weapons(imported, unit(imported, 'Beast Pack')['melee_weapons'], 'melee') == {'Close combat weapon': 1, 'Claws': 3}


def test_weapons_are_one_per_faction_name_and_profile(imported):
    pistols = [w for w in imported.data['ranged_weapons'] if w['name'] == 'Laser pistol']
    assert {w['_key'] for w in pistols} == {'wh-ranged:SF/laserpistol', 'wh-ranged:AL/laserpistol'}  # One per faction
    blades = [w for w in imported.data['melee_weapons'] if w['name'] == 'Close combat weapon']
    assert len(blades) == 1 and blades[0]['_key'] == 'wh-melee:SF/closecombatweapon'  # Shared by three datasheets
    flamer = next(w for w in imported.data['ranged_weapons'] if w['name'] == 'Walker flamer')
    assert (flamer['attacks'], flamer['ballistic_skill'], flamer['strength'], flamer['armor_penetration'],
            flamer['damage'], flamer['range_inches']) == ('D6', None, 5, 1, '1', 12)
    assert flamer['abilities'] == ['Ignores Cover', 'Torrent', 'Twin-linked']
    assert not any(w['name'] == 'Broken gun' for w in imported.data['ranged_weapons'])  # S 'User'


def test_leaders_detachments_and_enhancements(imported):
    captain = unit(imported, 'Star Captain')
    assert captain['can_lead'] == ['Void Warriors']
    assert captain['leader_buffs'] == [{'applies_to': 'Attacker', 'phase': 'Shooting', 'modifier': 'Lethal Hits'},
                                       {'applies_to': 'Target', 'phase': 'Both', 'modifier': 'Hit Modifier -1'}]
    assert unit(imported, 'Field Medic')['can_support'] == ['Void Warriors', 'Gun Crew']
    detachments = {d['name']: d for d in imported.data['detachments']}
    assert 'Hull Breach' not in detachments  # A Boarding Actions one
    assert (detachments['Void Vanguard']['dp'], detachments['Void Vanguard']['dispositions']) == (2, ['Purge the Foe'])
    assert [r['name'] for r in detachments['Star Bastion']['rules']] == ['Hold Fast']
    enhancements = {e['name']: e for e in imported.data['enhancements']}
    assert 'Boarding Hook' not in enhancements
    assert enhancements['Void Blade']['bearer_bsdata_ids'] == ['u-captain', 'u-herald']
    assert enhancements['Void Blade']['detachment_keys'] == ['d-vanguard']
    assert enhancements['Targeting Sights']['unit_bsdata_id'] == 'u-crew'  # An Upgrade for one datasheet
    assert enhancements['Line Banner']['unit_bsdata_id'] is None  # For two: an enhancement those two can take


def test_has_datasheets():
    assert wahapedia_units.has_datasheets(WAHAPEDIA_FIXTURES) and wahapedia_units.has_datasheets(UNIT_FIXTURES)
    assert not wahapedia_units.has_datasheets(None)


def test_the_app_takes_its_units_from_wahapedia(make_client):
    client, _ = make_client(APP_DATA, wahapedia=WAHAPEDIA_FIXTURES)
    app = client.application
    assert reference.current(app).units_source == 'wahapedia'
    with app.app_context():
        starfarers = Faction.query.filter_by(name='Starfarers').one()
        assert starfarers.bsdata_id == 'SF' and starfarers.source == 'bsdata'
        assert StableId.query.filter_by(key='wh-unit:u-void').one().id == \
            Unit.query.filter_by(name='Void Warriors').one().id
    units = {u['name']: u['id'] for u in client.get(f'/api/units?faction_id={starfarers.id}').get_json()}
    assert 'Star Captain' in units and 'Star Walker [Legends]' not in units  # Legends only when asked
    body = {'name': 'List', 'faction_id': starfarers.id, 'detachment_keys': ['d-vanguard'],
            'units': [{'uid': u, 'unit_id': units['Void Warriors']} for u in 'abc']}
    priced = client.post('/api/armies/price', json=body).get_json()
    assert [e['points'] for e in priced['units']] == [80, 80, 90]
    assert priced['detachment'] == 'Void Vanguard'


def test_saved_data_is_carried_over_from_bsdata_on_start(make_client, monkeypatch):
    # A database saved before 3.0: BSData's keys in stable_ids, an army using their IDs
    base = 1_000_000
    client, _ = make_client(dict(APP_DATA, schema_version=2))
    with client.application.app_context():
        db.session.add_all([StableId(key='faction:cat-star', table='factions', id=base),
                            StableId(key='unit:cat-star/old-void', table='units', id=base + 10),
                            StableId(key='unit:cat-star/old-lord', table='units', id=base + 11)])
        db.session.add(SavedArmy(name='Old list', faction_id=base, detachment_keys=['old-vanguard'], units=[
            {'uid': 'a', 'unit_id': base + 10, 'models': 5, 'attached_to': None, 'enhancement': None, 'wargear': {'3': 1}},
            {'uid': 'b', 'unit_id': base + 11, 'models': 1, 'attached_to': None, 'enhancement': None, 'wargear': None}]))
        db.session.commit()
        army_id = SavedArmy.query.one().id
    id_map = {'factions': {'cat-star': 'SF'}, 'units': {'cat-star/old-void': 'u-void'},
              'ranged_weapons': {}, 'melee_weapons': {}, 'detachments': {'cat-star/old-vanguard': 'd-vanguard'},
              'enhancements': {}}

    # Started again with Wahapedia's export
    monkeypatch.setattr(carry_over, 'shipped_map', lambda: carry_over.IdMap(id_map))
    client, data_file = make_client(dict(APP_DATA, schema_version=2), wahapedia=WAHAPEDIA_FIXTURES)
    with client.application.app_context():
        saved = db.session.get(SavedArmy, army_id)
        assert saved.faction_id == base and saved.detachment_keys == ['d-vanguard']  # Database IDs kept
        assert [e['unit_id'] for e in saved.units] == [base + 10, base + 11]
        assert saved.units[0]['wargear'] is None  # The option tree's choices reset
        assert saved.units[1]['missing']  # No Wahapedia datasheet: flagged
        assert Unit.query.filter_by(name='Void Warriors').one().id == base + 10
        assert Faction.query.filter_by(name='Starfarers').one().id == base
    priced = client.post('/api/armies/price', json=client.get(f'/api/armies/{army_id}').get_json()).get_json()
    assert priced['units'][0]['name'] == 'Void Warriors' and priced['detachment'] == 'Void Vanguard'
    assert '"schema_version": 3' in data_file.read_text(encoding='utf-8')  # The app data in Wahapedia's IDs now
    assert client.get('/api/data/status').get_json()['carry_over']['armies'] == 1


# --- Simple wargear (loadouts.py): how many models carry each weapon -------------------------------

@pytest.fixture
def wahapedia_client(make_client):
    client, _ = make_client(APP_DATA, wahapedia=UNIT_FIXTURES)
    with client.application.app_context():
        faction = Faction.query.filter_by(name='Starfarers').one()
        faction_id = faction.id
        ids = {u.name: u.id for u in Unit.query.filter_by(faction_id=faction_id)}
    form = client.post('/api/armies/wargear', json={'unit_id': ids['Void Warriors'], 'models': 5}).get_json()['form']
    return client, faction_id, ids, {w['name']: w['key'] for w in form}


def test_the_wargear_popup_lists_the_loadout_options_and_option_text(wahapedia_client):
    client, faction_id, ids, keys = wahapedia_client
    result = client.post('/api/armies/wargear', json={'unit_id': ids['Void Warriors'], 'models': 10}).get_json()
    form = {w['name']: w for w in result['form']}
    assert form['Laser rifle - standard']['count'] == 8 and form['Laser rifle - standard']['option'] is False  # 4 at 5
    assert form['Heavy laser']['count'] == 0 and form['Heavy laser']['option']
    assert 'heavy laser' in result['options_text'][0] and result['wargear'] is None
    assert result['sizes'] == [5, 10] and result['points'] == 0  # Nothing taken beyond the datasheet's
    assert form['Heavy laser']['points'] == 5 and form['Laser pistol']['points'] is None

    choices = {keys['Laser rifle - standard']: 7, keys['Heavy laser']: 1}
    result = client.post('/api/armies/wargear', json={'unit_id': ids['Void Warriors'], 'models': 10,
                                                      'wargear': choices}).get_json()
    loadout = {r['name']: r['qty'] for r in result['loadout']}
    assert loadout['Laser rifle - standard'] == 7 and loadout['Heavy laser'] == 1
    assert result['wargear'][keys['Laser rifle - standard']] == 7
    assert result['summary'] == '7 × Laser rifle - standard, 1 × Heavy laser' and result['points'] == 5
    ticked = {r['name']: r['default_use'] for r in result['loadout']}
    assert ticked['Laser rifle - standard'] and not ticked['Laser rifle - overcharge']  # Its second profile
    assert client.post('/api/armies/wargear', json={'unit_id': 999999}).status_code == 404
    assert client.post('/api/armies/wargear', json={'unit_id': ids['Void Warriors'], 'wargear': 'axe'}).status_code == 400


def test_an_armys_chosen_weapons_reach_its_price_and_match_view(wahapedia_client):
    client, faction_id, ids, keys = wahapedia_client
    choices = {keys['Laser rifle - standard']: 3, keys['Heavy laser']: 1}
    army = {'name': 'List', 'faction_id': faction_id, 'detachment_keys': ['d-vanguard'],
            'units': [{'uid': 'a', 'unit_id': ids['Void Warriors'], 'models': 5, 'wargear': choices}]}
    priced = client.post('/api/armies/price', json=army).get_json()
    entry = priced['units'][0]
    assert entry['points'] == 85 and entry['wargear_points'] == 5 and entry['has_wargear']  # 80, and its heavy laser
    assert {r['name']: r['qty'] for r in entry['loadout']} == {
        'Laser pistol': 1, 'Laser rifle - standard': 3, 'Laser rifle - overcharge': 4, 'Heavy laser': 1,
        'Blade': 1, 'Close combat weapon': 4}
    assert {r['name']: r['qty'] for r in priced['roster'][0]['loadout']}['Heavy laser'] == 1  # For Analytics
    army_id = client.post('/api/armies', json=army).get_json()['id']
    sheet = client.get(f'/api/armies/{army_id}/match').get_json()
    ranged = {w['name']: w['qty'] for w in sheet['units'][0]['weapons']['ranged']}
    assert ranged['Laser rifle - standard'] == 3 and ranged['Heavy laser'] == 1


def test_a_share_code_carries_the_weapon_counts(wahapedia_client):
    client, faction_id, ids, keys = wahapedia_client
    choices = {keys['Laser rifle - standard']: 3, keys['Heavy laser']: 1}
    army = {'name': 'List', 'faction_id': faction_id, 'detachment_keys': ['d-vanguard'],
            'units': [{'uid': 'a', 'unit_id': ids['Void Warriors'], 'models': 5, 'wargear': choices}]}
    code = client.post('/api/armies/share', json=army).get_json()['code']
    imported = client.post('/api/armies/import', json={'code': code}).get_json()
    assert imported['notes'] == []
    wargear = imported['army']['units'][0]['wargear']
    assert wargear[keys['Laser rifle - standard']] == 3 and wargear[keys['Heavy laser']] == 1


def test_wargear_is_priced_by_the_datasheets_costs(wahapedia_client):
    client, faction_id, ids, keys = wahapedia_client

    def popup(name, wargear=None, models=None):
        return client.post('/api/armies/wargear', json={'unit_id': ids[name], 'models': models, 'wargear': wargear}).get_json()

    # Two heavy lasers in ten: 5 each; their profiles would count once
    assert popup('Void Warriors', {keys['Heavy laser']: 2}, 10)['points'] == 10
    # Wargear that isn't a weapon: a count of its own, 10 each
    brutes = popup('Shield Brutes')
    shield = next(w for w in brutes['form'] if w['name'] == 'Brute shield')
    assert (shield['key'], shield['kind'], shield['count'], shield['points']) == ('wargear:bruteshield', 'wargear', 0, 10)
    taken = popup('Shield Brutes', {'wargear:bruteshield': 2})
    assert taken['points'] == 20 and taken['summary'] == '2 × Brute shield' and taken['loadout'][0]['name'] == 'Brute club'
    # A weapon the datasheet already has: paid only beyond the one it comes with
    walker = popup('Star Walker [Legends]')
    flamer = next(w for w in walker['form'] if w['name'] == 'Walker flamer')
    assert (flamer['default'], flamer['points']) == (1, 10) and walker['points'] == 0
    assert popup('Star Walker [Legends]', {flamer['key']: 2})['points'] == 10

    army = {'name': 'List', 'faction_id': faction_id, 'detachment_keys': ['d-vanguard'],
            'units': [{'uid': 'b', 'unit_id': ids['Shield Brutes'], 'wargear': {'wargear:bruteshield': 3}}]}
    priced = client.post('/api/armies/price', json=army).get_json()
    assert priced['units'][0]['points'] == 120 and priced['total'] == 120  # 90 and three shields
    assert priced['units'][0]['size_points'] == [90]  # A size's own points stay the datasheet's
    code = client.post('/api/armies/share', json=army).get_json()['code']
    imported = client.post('/api/armies/import', json={'code': code}).get_json()
    assert imported['notes'] == [] and imported['army']['units'][0]['wargear']['wargear:bruteshield'] == 3
    assert client.post('/api/armies/price', json=dict(army, units=[{'uid': 'b', 'unit_id': ids['Shield Brutes'],
                                                                    'wargear': {'wargear:no such': 1}}])).status_code == 400


def test_without_the_id_map_the_app_still_starts(make_client, monkeypatch):
    # 3.1.0's Docker image lacked data/bsdata_id_map.json and stopped on start: now nothing is carried over instead
    def missing():
        raise FileNotFoundError('bsdata_id_map.json')
    monkeypatch.setattr(carry_over, 'shipped_map', missing)
    client, _ = make_client(dict(APP_DATA, schema_version=2), wahapedia=WAHAPEDIA_FIXTURES)
    assert client.get('/api/data/status').get_json()['loaded']
