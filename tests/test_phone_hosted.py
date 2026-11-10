"""
A self-hosted copy's own pages on a phone (docs/phone-plan.md, step e): logging in, joining, the Players page, the
Proposals page and your Account, checked as tests/test_phone.py checks every other page (its own live server: hosted
mode is set when the app starts).
"""

import pytest

from conftest import welcome
from test_phone import PHONE, assert_fits, browser, live_server  # noqa: F401  (browser: the shared fixture)

HOST = {'name': 'Hosty', 'email': 'host@example.com', 'password': 'throwaway-1'}


def seed(app):
    """The host, a player who has proposed a new faction, and a join link not used yet."""
    from combat_sim import accounts
    accounts._failed.clear()
    host = app.test_client()
    assert welcome(host, HOST).status_code == 200
    link = host.post('/api/players', json={'name': 'Pat', 'email': 'pat@example.com'}).get_json()['link']
    player = app.test_client()
    assert player.post('/api/auth/join', json={'token': link.rsplit('/', 1)[1], 'password': 'another-pw'}).status_code == 200
    assert player.post('/api/data/factions', json={'name': 'Homebrew'}).status_code == 202  # Waits for the host
    unused = host.post('/api/players', json={'name': 'Sam', 'email': 'sam@example.com'}).get_json()['link']
    return {'join': '/join/' + unused.rsplit('/', 1)[1]}


@pytest.fixture(scope='module')
def hosted(tmp_path_factory):
    with live_server(tmp_path_factory.mktemp('phone-hosted'), seed, hosted=True) as running:
        yield running


def open_page(browser, address, path, as_host=True):
    context = browser.new_context(**PHONE)
    if as_host:
        assert context.request.post(address + '/api/auth/login', data={'name': HOST['name'], 'password': HOST['password']}).ok
    page = context.new_page()
    page.errors = []
    page.on('pageerror', lambda error: page.errors.append(str(error)))
    page.goto(address + path, wait_until='networkidle')
    return context, page


@pytest.mark.parametrize('path, as_host', [
    ('/login', False),
    ('{join}', False),
    ('/players', True),
    ('/proposals', True),
    ('/account', True),
    ('/setup', True),
], ids=['login', 'join', 'players', 'proposals', 'account', 'setup'])
def test_the_hosted_page_fits_a_phone(hosted, browser, path, as_host):
    address, seeded = hosted
    context, page = open_page(browser, address, path.format(**seeded), as_host)
    try:
        assert page.url.endswith(path.format(**seeded)), page.url  # Not sent to the login page
        assert_fits(page)
    finally:
        context.close()
