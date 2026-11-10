"""
Adding the app to a phone's home screen (docs/phone-plan.md, step h): every page links the manifest, and the
manifest and its icons load without a login (browsers fetch them without the login cookie).
"""

import json
import struct

from combat_sim import paths

APP_DATA = {'schema_version': 2, 'source': None, 'factions': [], 'units': [], 'ranged_weapons': [], 'melee_weapons': [],
            'faction_rules': [], 'stratagems': [], 'unit_modifiers': [], 'keywords': [], 'target_profiles': []}


def png_size(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', data[16:24])


def test_the_manifest_and_icons_load_without_a_login(make_client, monkeypatch):
    monkeypatch.setenv(paths.HOSTED_ENV, '1')
    client, _ = make_client(APP_DATA)
    page = client.get('/welcome').get_data(as_text=True)  # A new copy's first page
    assert 'rel="manifest" href="/static/manifest.webmanifest"' in page and 'rel="apple-touch-icon"' in page
    response = client.get('/static/manifest.webmanifest')
    assert response.status_code == 200 and response.mimetype == 'application/manifest+json'
    manifest = json.loads(response.get_data(as_text=True))
    assert manifest['start_url'] == '/' and manifest['display'] == 'standalone'
    for icon in manifest['icons']:
        image = client.get(icon['src'])
        assert image.status_code == 200 and image.mimetype == 'image/png'
        assert png_size(image.get_data()) == tuple(int(n) for n in icon['sizes'].split('x'))
    assert png_size(client.get('/static/img/icons/apple-touch-icon.png').get_data()) == (180, 180)
