"""
Shared test setup.

`make_client(data)` starts the app on its own temporary data JSON and database, so tests
never touch data/app_data.json, data/combat_sim.db or data/wahapedia. Pass `wahapedia=<folder>`
for a Wahapedia export: WAHAPEDIA_FIXTURES (made-up units, rules and stratagems) or UNIT_FIXTURES
(the same units without the rules and stratagems), both written by
fixtures/make_wahapedia_fixtures.py; without one the app runs on the data JSON alone.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from combat_sim.app import create_app  # noqa: E402

WAHAPEDIA_FIXTURES = ROOT / 'tests' / 'fixtures' / 'wahapedia'
UNIT_FIXTURES = ROOT / 'tests' / 'fixtures' / 'wahapedia_units'  # Without Stratagems.csv: units only


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """Factory: make_client(data_dict, wahapedia=None) -> (test client, path of the data JSON the app reads and writes)."""
    def _make(data, wahapedia=None):
        data_file = tmp_path / 'data.json'
        data_file.write_text(json.dumps(data), encoding='utf-8')
        monkeypatch.setenv('DATA_JSON', str(data_file))
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'test.db').replace('\\', '/'))
        monkeypatch.setenv('WAHAPEDIA_DIR', str(wahapedia or tmp_path / 'no-wahapedia'))
        app = create_app()
        app.config['PLAY_STATE_CHECK'] = True  # every cached Play state checked against a full replay (session.py)
        app.config['JOBS'] = 'inline'  # Long work runs inside the request (jobs.py), so answers come at once
        return app.test_client(), data_file
    return _make


def welcome(client, fields):
    """POST the Welcome form of a self-hosted copy (accounts.py) with its setup code, as the host would."""
    return client.post('/api/auth/welcome', json=dict(fields, setup_code=client.application.config['SETUP_CODE']))

