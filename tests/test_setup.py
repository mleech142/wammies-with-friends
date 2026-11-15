"""
The Setup page: "Download latest" from Wahapedia (the download faked) bringing the units, skipping setup, the
settings file, the data version in the footer, and the report of what was carried over from BSData's IDs.
"""

import json

import pytest

from combat_sim import wahapedia_download
from combat_sim.settings import load_settings, update_settings
from conftest import WAHAPEDIA_FIXTURES

APP_DATA = {'schema_version': 3, 'source': None, 'factions': [], 'units': [], 'ranged_weapons': [],
            'melee_weapons': [], 'faction_rules': [], 'stratagems': [], 'unit_modifiers': [], 'keywords': [],
            'target_profiles': []}


@pytest.fixture
def setup(make_client, tmp_path):
    """App with no game data yet; returns (client, data folder)."""
    client, data_file = make_client(APP_DATA, wahapedia=tmp_path / 'wahapedia')
    return client, data_file.parent


@pytest.fixture
def fake_wahapedia(monkeypatch):
    files = {p.name: p.read_bytes() for p in WAHAPEDIA_FIXTURES.glob('*.csv')}
    monkeypatch.setattr(wahapedia_download, 'fetch', lambda name: files[name])
    return files


def status(client):
    return client.get('/api/data/status').get_json()


# --- Settings -----------------------------------------------------------------------------

def test_settings_file_round_trip(tmp_path):
    path = tmp_path / 'settings.json'
    assert load_settings(path) == {}
    update_settings(path, relay_url='https://x', setup_skipped=True)
    assert load_settings(path) == {'relay_url': 'https://x', 'setup_skipped': True}
    update_settings(path, relay_url=None)
    assert load_settings(path) == {'setup_skipped': True}
    path.write_text('not json', encoding='utf-8')
    assert load_settings(path) == {}


# --- First run --------------------------------------------------------------------------------

def test_simulator_sends_you_to_setup_until_the_units_load(setup, fake_wahapedia):
    client, _ = setup
    assert status(client)['loaded'] is False and status(client)['error'] is None  # Nothing yet isn't an error
    assert client.get('/').headers['Location'].endswith('/setup')
    page = client.get('/setup').get_data(as_text=True)
    assert 'Download latest' in page and '/api/bsdata' not in page and 'folder-input' not in page
    client.post('/api/wahapedia/download')
    assert client.get('/').status_code == 200


def test_skipping_setup(setup):
    client, folder = setup
    assert client.post('/api/setup/skip').status_code == 200
    assert client.get('/').status_code == 200
    assert load_settings(folder / 'settings.json')['setup_skipped'] is True


def test_footer_offers_setup_until_there_is_data(setup):
    client, _ = setup
    page = client.get('/data').get_data(as_text=True)
    assert 'Set up</a>' in page and 'powered by' not in page and 'github.com/BSData' not in page


# --- Download latest ---------------------------------------------------------------------------

def test_download_latest_brings_the_units_rules_and_stratagems(setup, fake_wahapedia):
    client, folder = setup
    result = client.post('/api/wahapedia/download').get_json()
    assert result['loaded'] and result['units_from'] == 'wahapedia'
    assert (result['factions'], result['units']) == (4, 16)
    assert result['wahapedia']['loaded'] and result['wahapedia']['stratagems'] == 7
    assert result['label'] == 'updated 2026-10-01'
    assert load_settings(folder / 'settings.json')['wahapedia_download']['last_update'] == '2026-10-01 12:00:00'
    page = client.get('/data').get_data(as_text=True)
    assert 'powered by <a href="https://wahapedia.ru/"' in page and 'updated 2026-10-01' in page
    assert 'Change</a>' in page


def test_a_failed_download_keeps_the_current_data(setup, fake_wahapedia, monkeypatch):
    client, _ = setup
    client.post('/api/wahapedia/download')

    def offline(name):
        raise wahapedia_download.DownloadError('Could not reach Wahapedia: offline')
    monkeypatch.setattr(wahapedia_download, 'fetch', offline)
    response = client.post('/api/wahapedia/download')
    assert response.status_code == 502 and 'offline' in response.get_json()['error']
    assert status(client)['units'] == 16


def test_old_bsdata_routes_are_gone(setup):
    client, _ = setup
    for route in ('/api/bsdata/download', '/api/bsdata/reimport', '/api/bsdata/folder', '/api/bsdata/browse',
                  '/api/bsdata/skip-setup'):
        assert client.post(route, json={}).status_code == 404, route


# --- What was carried over from BSData's IDs ------------------------------------------------------

def test_the_carry_over_report_is_for_the_host(setup):
    client, _ = setup
    assert status(client)['carry_over'] is None
    report = {'rekeyed': 3, 'merged': 0, 'armies': 1, 'comparisons': 0, 'games': 0, 'proposals': 0,
              'notes': ["Old list: Star Lord isn't on Wahapedia; it stays in the list, flagged."], 'at': '2026-11-15T10:00:00+00:00'}
    with open(client.application.config['CARRY_OVER_JSON'], 'w', encoding='utf-8') as f:
        json.dump(report, f)
    assert status(client)['carry_over'] == report
    assert 'carry-over-card' in client.get('/setup').get_data(as_text=True)
