"""
The Layout preference (Setup, Account and Play pages): phone, tablet, desktop or automatic, saved as the person's own
preference (settings.PREFERENCES) and put on every page's <html> for base.html's Core.layoutFor.
"""


import pytest

APP_DATA = {'schema_version': 2, 'source': None, 'factions': [], 'units': [], 'ranged_weapons': [], 'melee_weapons': [],
            'faction_rules': [], 'stratagems': [], 'unit_modifiers': [], 'keywords': [], 'target_profiles': []}


@pytest.fixture
def client(make_client):
    return make_client(APP_DATA)[0]


def test_the_layout_is_saved_and_every_page_carries_it(client, tmp_path):
    assert 'data-layout-pref="auto"' in client.get('/setup').get_data(as_text=True)
    answer = client.post('/api/preferences/layout', json={'layout': 'phone'})
    assert answer.status_code == 200 and answer.get_json() == {'layout': 'phone'}
    for page in ('/setup', '/armies', '/play'):
        assert 'data-layout-pref="phone"' in client.get(page).get_data(as_text=True)
    assert client.post('/api/preferences/layout', json={'layout': 'auto'}).status_code == 200
    assert 'data-layout-pref="auto"' in client.get('/setup').get_data(as_text=True)


def test_only_known_layouts_are_saved(client):
    answer = client.post('/api/preferences/layout', json={'layout': 'watch'})
    assert answer.status_code == 400 and 'automatic' in answer.get_json()['error']
    assert 'data-layout-pref="auto"' in client.get('/setup').get_data(as_text=True)


def test_the_setup_page_offers_the_layout_setting(client):
    assert 'data-layout-setting' in client.get('/setup').get_data(as_text=True)
