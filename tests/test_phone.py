"""
Every page on a phone (docs/phone-plan.md): each page opened at 360px wide with touch, as the smallest phone we
support, must not scroll sideways, must have tap targets big enough for a finger and inputs big enough that iOS
doesn't zoom into them.

Runs the app on its own scratch data (the made-up BSData fixtures) in a live server, and a real browser through
Playwright (`pip install -r requirements-dev.txt`, then `playwright install chromium`; Chrome or Edge already on
the PC are used when Playwright's own browser isn't installed). Skipped when neither is there.

A page not yet made phone-ready is listed in NOT_YET (strict: once it passes, the test fails until it is taken off).
"""

import contextlib
import json
import os
import threading

import pytest

from conftest import BSDATA_FIXTURES, create_app

playwright_api = pytest.importorskip('playwright.sync_api')

PHONE = {'viewport': {'width': 360, 'height': 780}, 'device_scale_factor': 2, 'is_mobile': True, 'has_touch': True}
TAP = 44  # px: buttons, links styled as buttons, selects and text fields (Apple's and Material's minimum)
TICK = 24  # px: checkboxes and radios (their label is tappable too)
INPUT_TEXT = 16  # px: smaller and iOS zooms into the field when it is focused

APP_DATA = {'schema_version': 2, 'source': None, 'factions': [], 'units': [], 'ranged_weapons': [], 'melee_weapons': [],
            'faction_rules': [], 'stratagems': [], 'unit_modifiers': [], 'keywords': [], 'target_profiles': []}

# Pages (and states of them) not yet made phone-ready: taken off as each step of the plan is done
NOT_YET = set()

# What the page measures: anything wider than the screen that isn't inside something scrolling sideways on purpose,
# and the tap targets and fields that are too small
MEASURE = """({tap, tick, inputText}) => {
    const width = document.documentElement.clientWidth;
    const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0
        && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[hidden], .modal:not(.show)'); };
    const scrolls = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
        const x = getComputedStyle(p).overflowX; if (x === 'auto' || x === 'scroll' || x === 'hidden') return true; } return false; };
    const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim()
        ? '.' + e.className.trim().split(/\\s+/).join('.') : '') + (e.textContent.trim() ? ` "${e.textContent.trim().slice(0, 30)}"` : '');
    const wide = [...document.body.querySelectorAll('*')].filter(e => shown(e) && !scrolls(e)
        && e.getBoundingClientRect().right > width + 1 && !(e.parentElement && e.parentElement.getBoundingClientRect().right > width + 1
            && !scrolls(e.parentElement) && e.parentElement !== document.body));
    const small = [];
    const sized = (selector, min, both) => document.querySelectorAll(selector).forEach(e => {
        if (!shown(e) || e.closest('.no-tap-check')) return;
        const r = e.getBoundingClientRect();
        if (r.height < min - 0.5 || (both && r.width < min - 0.5)) small.push(`${name(e)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    });
    sized('button, a.btn, .nav-link, select, [role=button]', tap, true);
    sized('input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=range]):not([type=file]), textarea', tap, false);
    sized('input[type=checkbox], input[type=radio]', tick, true);
    const zooms = [...document.querySelectorAll('input, select, textarea')].filter(e => shown(e)
        && parseFloat(getComputedStyle(e).fontSize) < inputText).map(name);
    return {scroll: document.documentElement.scrollWidth - width, wide: wide.slice(0, 8).map(name), small, zooms};
}"""


@contextlib.contextmanager
def live_server(folder, seed, hosted=False):
    """The app on scratch data in `folder` in a live server, `seed(app)` run first. Yields (address, what seed gave)."""
    from werkzeug.serving import make_server
    (folder / 'data.json').write_text(json.dumps(APP_DATA), encoding='utf-8')
    with pytest.MonkeyPatch.context() as env:
        env.setenv('DATA_JSON', str(folder / 'data.json'))
        env.setenv('DATABASE_URL', 'sqlite:///' + (folder / 'test.db').as_posix())
        env.setenv('BSDATA_DIR', str(BSDATA_FIXTURES))
        env.setenv('WAHAPEDIA_DIR', str(folder / 'no-wahapedia'))
        if hosted:
            env.setenv('COMBAT_SIM_HOSTED', '1')
        else:
            env.delenv('COMBAT_SIM_HOSTED', raising=False)
        app = create_app()
        app.config['JOBS'] = 'inline'
        seeded = seed(app)
        httpd = make_server('127.0.0.1', 0, app, threaded=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f'http://127.0.0.1:{httpd.server_port}', seeded
        finally:
            httpd.shutdown()


@pytest.fixture(scope='module')
def server(tmp_path_factory):
    """A desktop copy with two saved armies and a game. Yields its address and the IDs."""
    with live_server(tmp_path_factory.mktemp('phone'), lambda app: seed(app.test_client())) as running:
        yield running


def seed(client):
    """Two saved armies of the made-up Starfarers and a game between them; Play in the menu."""
    factions = {f['name']: f['id'] for f in client.get('/api/data/factions').get_json()}
    units = {u['name']: u['id'] for u in client.get(f'/api/units?faction_id={factions["Starfarers"]}').get_json()}

    def army(name, *entries):
        body = {'name': name, 'faction_id': factions['Starfarers'], 'points_limit': 2000,
                'units': [{'uid': f'u{i}', 'unit_id': units[unit]} for i, unit in enumerate(entries)]}
        response = client.post('/api/armies', json=body)
        assert response.status_code == 200, response.get_json()
        return response.get_json()['id']

    red = army('Red', 'Void Warriors', 'Star Captain')
    blue = army('Blue', 'Gun Crew')
    game = client.post('/api/play/games', json={'name': 'Phone game', 'armies': [red, blue], 'setup': False}).get_json()
    client.post('/api/play/setting', json={'enabled': True})
    return {'army': red, 'game': game['id']}


@pytest.fixture(scope='module')
def browser():
    with playwright_api.sync_playwright() as p:
        launched = None
        for options in ({}, {'channel': 'chrome'}, {'channel': 'msedge'}):
            try:
                launched = p.chromium.launch(**options)
                break
            except Exception:  # noqa: BLE001  (that browser isn't installed: try the next)
                continue
        if launched is None:
            pytest.skip('no browser for Playwright: run "playwright install chromium"')
        yield launched
        launched.close()


@pytest.fixture
def phone(browser):
    context = browser.new_context(**PHONE)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.errors = errors
    yield page
    context.close()


def open_menu(page):
    page.click('#more-tab')


def pick_unit(page, field, text):
    page.fill(field, text)
    page.click(f'{field}-dropdown .autocomplete-item[data-id]', timeout=5000)
    page.wait_for_load_state('networkidle')


def simulate(page):
    """The Simulator with an attacker and a defender chosen and a run done."""
    pick_unit(page, '#attacker-unit', 'Void')
    pick_unit(page, '#defender-unit', 'Gun')
    page.click('#btn-simulate')
    page.wait_for_load_state('networkidle')


def open_army(page):
    page.click('.army-open:has-text("Red")')
    page.wait_for_load_state('networkidle')


def open_wargear(page):
    open_army(page)
    page.click('.army-wargear-btn')
    page.wait_for_load_state('networkidle')


def data_tab(tab, faction_filter=None):
    """The Data page on one of its tabs, the made-up faction chosen in its filter."""
    def show(page):
        page.click(f'.data-tab:has-text("{tab}")')
        if faction_filter:
            page.select_option(faction_filter, label='Starfarers')
        page.wait_for_load_state('networkidle')
    show.__name__ = f'data_tab_{tab}'
    return show


def open_faction(page):
    page.click('#factions-table .faction-row:has-text("Starfarers") .btn-expand')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector('.faction-detail table')


def click_then(selector):
    def act(page):
        page.click(selector)
        page.wait_for_load_state('networkidle')
    act.__name__ = f'click {selector}'
    return act


def assert_fits(page):
    """The page as it is now: no sideways scrolling, finger-sized targets, no script errors."""
    found = page.evaluate(MEASURE, {'tap': TAP, 'tick': TICK, 'inputText': INPUT_TEXT})
    assert not page.errors, page.errors
    assert found['scroll'] <= 1, f"scrolls {found['scroll']}px sideways: {found['wide']}"
    assert not found['small'], f"tap targets under {TAP}px (ticks {TICK}px): {found['small']}"
    assert not found['zooms'], f"fields with text under {INPUT_TEXT}px (iOS zooms in): {found['zooms']}"


def matrix(page):
    """Analytics with the saved Red army attacking the Blue army, the matrix run."""
    address = page.url.split('/analytics')[0]
    blue = page.evaluate("fetch('/api/armies').then(r => r.json()).then(a => a.find(x => x.name === 'Blue').id)")
    page.goto(f'{address}/analytics?army={blue}&side=defender', wait_until='networkidle')
    page.click('#btn-run-matrix')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(500)


def cell_detail(page):
    matrix(page)
    page.locator('.matrix-cell').first.click()
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(500)


def select_unit(page):
    if not page.is_visible('#army-0'):  # The phone game screen: the army opens as a sheet from its tab
        page.click('#phone-tabs [data-phone-tab="0"]')
    page.click('#army-0 .play-unit[data-unit="p1-u0"]')
    page.wait_for_timeout(300)


# name -> (path, what to do once it has loaded)
PAGES = {
    'simulator': ('/', None),
    'simulator-run': ('/', simulate),
    'analytics': ('/analytics', None),
    'analytics-matrix': ('/analytics?army={army}&side=attacker', matrix),
    'analytics-cell': ('/analytics?army={army}&side=attacker', cell_detail),
    'armies': ('/armies', None),
    'armies-open': ('/armies', open_army),
    'armies-wargear': ('/armies', open_wargear),
    'match': ('/armies/{army}/match', None),
    'data': ('/data', None),
    'data-faction': ('/data', open_faction),
    'data-units': ('/data', data_tab('Units', '#filter-faction')),
    'data-weapons': ('/data', data_tab('Weapons', '#filter-weapon-faction')),
    'data-profiles': ('/data', data_tab('Target Profiles')),
    'data-keywords': ('/data', data_tab('Keywords')),
    'data-add-faction': ('/data', click_then('button:has-text("Add Faction")')),
    'data-add-stratagem': ('/data', click_then('button:has-text("Add Core Stratagem")')),
    'setup': ('/setup', None),
    'play': ('/play?game={game}', None),
    'play-selected': ('/play?game={game}', select_unit),
    'play-empty': ('/play', None),  # No game open: the board's empty state
    'play-games': ('/play', click_then('#play-empty-btn')),  # The Games pop-up
    'play-battlefields': ('/play', lambda page: (page.click('#play-empty-btn'), click_then('#battlefields-btn')(page))),
    'menu': ('/setup', open_menu),
    'armies-actions': ('/armies', lambda page: (open_army(page), page.tap('.army-actions .overflow-toggle'))),
    'armies-add': ('/armies', lambda page: (open_army(page), page.tap('#add-units-fab'))),
    'simulator-tip': ('/', lambda page: (simulate(page), page.tap('.weapon-table th[title="Models with this weapon"]'))),
}


@pytest.mark.parametrize('name', PAGES)
def test_the_page_fits_a_phone(name, server, phone, request):
    if name in NOT_YET:
        request.applymarker(pytest.mark.xfail(strict=True, reason='not yet phone-ready (docs/phone-plan.md)'))
    address, ids = server
    path, then = PAGES[name]
    phone.goto(address + path.format(**ids), wait_until='networkidle')
    if then:
        then(phone)
        phone.wait_for_timeout(300)
    assert_fits(phone)


def test_a_desktop_window_keeps_the_full_menu(server, browser):
    """A mouse at desktop width: the links in the header, no menu button, no tab bar, actions in place."""
    context = browser.new_context(viewport={'width': 1400, 'height': 900})
    page = context.new_page()
    page.goto(server[0] + '/setup', wait_until='networkidle')
    assert page.is_visible('.header-nav .nav-link[href="/analytics"]')
    assert not page.is_visible('#nav-toggle') and not page.is_visible('.tab-bar')
    page.goto(server[0] + '/armies', wait_until='networkidle')
    assert page.is_visible('#attackers-btn') and not page.is_visible('.army-actions .overflow-toggle') and not page.is_visible('#add-units-fab')
    # Copying and sharing the list are in the Export menu
    assert not page.is_visible('#share-btn')
    page.click('.army-actions .dropdown-toggle')
    assert page.is_visible('.dropdown-menu [data-click="share-btn"]')
    assert page.is_visible('#unit-search')
    context.close()


# PHONE_REPORT=1 pytest tests/test_phone.py -s -k report: what each page still has to fix; with PHONE_SHOTS=<folder>
# as well, each page's screenshot is saved there
if os.environ.get('PHONE_REPORT'):
    @pytest.mark.parametrize('name', PAGES)
    def test_report(name, server, phone):
        address, ids = server
        path, then = PAGES[name]
        phone.goto(address + path.format(**ids), wait_until='networkidle')
        if then:
            try:
                then(phone)
            except Exception as error:  # noqa: BLE001
                print(name, 'could not', then.__name__, error)
        phone.wait_for_timeout(300)
        found = phone.evaluate(MEASURE, {'tap': TAP, 'tick': TICK, 'inputText': INPUT_TEXT})
        if os.environ.get('PHONE_SHOTS'):  # A folder: each page's screenshot there, the whole page long
            phone.screenshot(path=os.path.join(os.environ['PHONE_SHOTS'], name + '.png'), full_page=not phone.is_visible('.modal.show'))  # A pop-up: just the screen
        print(f"\n== {name}: scroll {found['scroll']}px, errors {phone.errors}\n  wide: {found['wide']}"
              f"\n  small ({len(found['small'])}): {found['small'][:25]}\n  zooms ({len(found['zooms'])}): {found['zooms'][:10]}")


def test_the_tab_bar_and_more_go_to_every_page(server, phone):
    """Phones: the main pages in the tab bar at the bottom, the rest in the More sheet over it."""
    phone.goto(server[0] + '/setup', wait_until='networkidle')
    assert not phone.is_visible('#nav-toggle')
    assert phone.inner_text('.brand-page') == 'Setup'
    assert phone.is_visible('.tab-bar a[href="/armies"]') and 'active' in phone.get_attribute('#more-tab', 'class')
    assert not phone.is_visible('.header-nav .nav-link[href="/data"]')
    phone.tap('#more-tab')
    assert phone.get_attribute('#more-tab', 'aria-expanded') == 'true'
    assert phone.is_visible('.header-nav .nav-link[href="/data"]')
    assert not phone.is_visible('.header-nav .nav-link[href="/armies"]')  # In the tab bar already
    phone.tap('#nav-scrim')  # A tap on the page behind closes it
    assert not phone.is_visible('.header-nav .nav-link[href="/data"]')
    phone.tap('#more-tab')
    phone.tap('.header-nav .nav-link[href="/data"]')
    phone.wait_for_url('**/data')
    phone.tap('.tab-bar a[href="/armies"]')
    phone.wait_for_url('**/armies')
    assert 'active' in phone.get_attribute('.tab-bar a[href="/armies"]', 'class')


def test_an_info_button_explains_on_a_tap_without_ticking_its_row(server, phone):
    phone.goto(server[0] + '/', wait_until='networkidle')
    phone.evaluate("""() => document.querySelector('main').insertAdjacentHTML('afterbegin',
        `<label id="row"><input type="checkbox" id="tick"> A rule ${Core.infoButton('Tick it only when: charging')}</label>`)""")
    phone.tap('#row .info-btn')
    assert phone.is_visible('#info-popover') and phone.inner_text('#info-popover') == 'Tick it only when: charging'
    assert not phone.is_checked('#tick')
    phone.tap('#row .info-btn')  # Again: closes
    assert not phone.is_visible('#info-popover')
    phone.tap('#tick')  # The row itself still ticks
    assert phone.is_checked('#tick')


def test_running_a_simulation_on_a_phone_shows_the_results(server, phone):
    phone.goto(server[0] + '/', wait_until='networkidle')
    simulate(phone)
    phone.wait_for_timeout(800)  # The smooth scroll
    top = phone.evaluate("document.getElementById('results-panel').getBoundingClientRect().top")
    assert -2 <= top < 100


def test_adding_a_unit_on_a_phone_keeps_the_picker_where_it_was(server, phone):
    """Issue #26: the army's table grows while units are added. On a phone the picker is a sheet over the page, which
    stays open and doesn't move; a toast says what was added. Scroll anchoring switched off, as in Safari."""
    phone.goto(server[0] + '/armies', wait_until='networkidle')
    open_army(phone)
    phone.add_style_tag(content='html, body, * { overflow-anchor: none !important; }')
    assert not phone.is_visible('.unit-picker-item')
    phone.tap('#add-units-fab')
    picked = phone.locator('.unit-picker-item').last
    picked.scroll_into_view_if_needed()
    top = picked.evaluate('el => el.getBoundingClientRect().top')
    rows = phone.locator('#army-units tr').count()
    picked.tap()
    phone.wait_for_function(f"document.querySelectorAll('#army-units tr').length > {rows}")
    phone.wait_for_timeout(300)
    assert abs(picked.evaluate('el => el.getBoundingClientRect().top') - top) <= 2
    assert phone.is_visible('.toast.show') and 'Added' in phone.inner_text('.toast')
    phone.tap('#army-add-done')
    assert not phone.is_visible('.unit-picker-item')


def test_opening_a_saved_army_keeps_its_force_disposition(server, phone):
    """Issue #28: the page dropped the saved disposition, showed the first one and saved that over it."""
    phone.goto(server[0] + '/armies', wait_until='networkidle')
    phone.evaluate("""async () => {
        const factions = await fetch('/api/data/factions').then(r => r.json());
        const body = {name: 'Holders', faction_id: factions.find(f => f.name === 'Starfarers').id, points_limit: 2000,
                      detachment_keys: ['d-vanguard', 'd-bastion'], disposition: 'Take and Hold', units: []};
        await fetch('/api/armies', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    }""")
    phone.reload(wait_until='networkidle')
    phone.click('.army-open:has-text("Holders")')
    phone.wait_for_selector('#army-disposition option', state='attached')
    assert phone.input_value('#army-disposition') == 'Take and Hold'  # Not the first option, Purge the Foe
    assert not phone.is_visible('#army-disposition-confirm')


def test_the_matrix_on_a_phone_is_one_attacker_at_a_time(server, phone):
    address, ids = server
    phone.goto(f'{address}/analytics?army={ids["army"]}&side=attacker', wait_until='networkidle')
    matrix(phone)
    picked = lambda: phone.eval_on_selector('#matrix-attacker', 'el => el.selectedOptions[0].textContent')  # noqa: E731
    assert picked() == 'Void Warriors' and phone.locator('.matrix-list .matrix-unit-row').count() == 1  # One defender
    phone.tap('[data-step="1"]')
    assert picked() == 'Star Captain'
    phone.tap('[data-step="1"]')
    assert phone.locator('.matrix-list .matrix-total-cell').count() == 1  # The army's total
    phone.tap('[data-view="grid"]')
    assert phone.locator('.matrix-scroll .matrix-table').count() == 1 and phone.locator('.matrix-list').count() == 0
    phone.tap('[data-view="list"]')
    phone.locator('.matrix-list .matrix-cell').first.tap()
    assert phone.is_visible('.matchups-detail-panel')


def test_play_on_a_phone_is_a_game_screen(server, phone):
    """The phone game screen: the board takes the screen (no site header or tab bar); the armies and the log open as
    sheets from the tabs; a unit picked shows its actions under the board, and its datasheet on request."""
    address, ids = server
    phone.goto(f'{address}/play?game={ids["game"]}', wait_until='networkidle')
    assert phone.evaluate('document.documentElement.dataset.layout') == 'phone'
    assert not phone.is_visible('.header') and not phone.is_visible('.tab-bar')
    assert phone.is_visible('#play-board') and not phone.is_visible('#army-0') and not phone.is_visible('.play-log')
    phone.tap('#phone-tabs [data-phone-tab="1"]')
    assert phone.is_visible('#army-1') and not phone.is_visible('#army-0')
    phone.tap('#phone-tabs [data-phone-tab="log"]')
    assert phone.is_visible('.play-log') and not phone.is_visible('#army-1')
    phone.tap('#phone-tabs [data-phone-tab="log"]')  # The same tab again: closed
    assert not phone.is_visible('.play-log')
    phone.tap('#phone-tabs [data-phone-tab="0"]')
    phone.tap('#army-0 .play-unit[data-unit="p1-u0"]')  # Picking a unit closes the army's sheet
    assert not phone.is_visible('#army-0')
    assert phone.is_visible('#action-bar') and 'Void Warriors' in phone.inner_text('#action-head')
    assert not phone.is_visible('#unit-sheet')
    phone.tap('#sheet-open')
    assert phone.is_visible('#unit-sheet') and 'base 32mm' in phone.inner_text('#unit-sheet')
    phone.tap('#sheet-close')
    assert not phone.is_visible('#unit-sheet') and phone.is_visible('#action-bar')  # Still selected
    phone.tap('#action-close')
    assert not phone.is_visible('#action-bar')


def test_play_on_a_phone_held_sideways_is_still_a_phone(server, browser):
    """Wider than 600px, but a phone: the phone game screen, the board in the first screen, the actions beside it."""
    address, ids = server
    context = browser.new_context(**dict(PHONE, viewport={'width': 844, 'height': 390}, screen={'width': 390, 'height': 844}))
    page = context.new_page()
    page.goto(f'{address}/play?game={ids["game"]}', wait_until='networkidle')
    assert page.evaluate('document.documentElement.dataset.layout') == 'phone'
    board = page.locator('#play-board').bounding_box()
    assert board['y'] < 390 and board['height'] > 150  # On the first screen, not under the header
    page.tap('#phone-tabs [data-phone-tab="0"]')
    page.tap('#army-0 .play-unit[data-unit="p1-u0"]')
    bar = page.locator('#action-bar').bounding_box()
    board = page.locator('#play-board').bounding_box()
    assert bar['x'] >= board['x'] + board['width'] - 1  # Beside the board
    assert page.evaluate('document.documentElement.scrollWidth') <= 844
    context.close()


def test_play_on_a_desktop_fills_the_window_with_the_armies_beside_the_board(server, browser):
    address, ids = server
    context = browser.new_context(viewport={'width': 1400, 'height': 900})
    page = context.new_page()
    page.goto(f'{address}/play?game={ids["game"]}', wait_until='networkidle')
    assert page.evaluate('document.documentElement.dataset.layout') == 'desktop'
    assert page.is_visible('#army-0') and page.is_visible('#army-1')
    assert not page.is_visible('#phone-tabs') and not page.is_visible('.play-log')  # The log is a drawer
    assert page.evaluate('document.documentElement.scrollHeight') <= 900  # One screen: no scrolling to the board
    page.click('#army-0 .play-unit[data-unit="p1-u0"]')
    assert page.is_visible('#army-detail-0 #unit-info') and page.is_visible('#action-bar') and not page.is_visible('#unit-sheet')
    page.keyboard.press('l')
    page.wait_for_timeout(400)
    assert page.is_visible('.play-log')
    page.keyboard.press('Escape')
    page.wait_for_timeout(400)
    assert not page.is_visible('.play-log')
    context.close()


# --- The Play board by touch (step g): real touches through Chrome's DevTools protocol, as a phone sends them ---

def board_to_screen(page, x, y):
    """A board point (inches, y up from the bottom edge) as a point on the screen."""
    return page.evaluate("""([x, y]) => { const svg = document.getElementById('play-board');
        const root = document.getElementById('board-root');  // The board's drawing, turned for the screen
        const pt = svg.createSVGPoint(); pt.x = x; pt.y = 44 - y;
        const p = pt.matrixTransform(root.getScreenCTM()); return [p.x, p.y]; }""", [x, y])


def touch(cdp, kind, *points):
    cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [{'x': x, 'y': y, 'id': i} for i, (x, y) in enumerate(points)]})


def tap(cdp, page, x, y, jitter=0):
    touch(cdp, 'touchStart', (x, y))
    if jitter:
        touch(cdp, 'touchMove', (x + jitter, y))
    touch(cdp, 'touchEnd')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(200)


def placed(page, game, unit):
    state = page.evaluate(f"fetch('/api/play/games/{game}').then(r => r.json()).then(g => g.state)")
    return [m['position'] for u in state['units'] if u['id'] == unit for m in u['models']]


def model_box(page, unit):
    return page.evaluate(f"""(() => {{ const r = document.querySelector('#play-board .play-model[data-unit="{unit}"]').getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2, r.width / 2]; }})()""")


def test_the_play_board_by_touch(tmp_path_factory, browser):
    """A fresh game: place a unit by tapping, then taps, a press, a near miss and a pinch on the board."""
    with live_server(tmp_path_factory.mktemp('touch'), lambda app: seed(app.test_client())) as (address, ids):
        context = browser.new_context(**PHONE)
        page = context.new_page()
        page.goto(f'{address}/play?game={ids["game"]}', wait_until='networkidle')
        cdp = context.new_cdp_session(page)
        game = ids['game']

        # Select Void Warriors (from Red's sheet), tap the board in Red's deployment zone (the bottom 12"), press OK
        page.tap('#phone-tabs [data-phone-tab="0"]')
        page.tap('#army-0 .play-unit[data-unit="p1-u0"]')
        page.wait_for_timeout(300)
        board = page.locator('#play-board').bounding_box()
        x, y = board_to_screen(page, 30, 6)
        assert board['x'] <= x <= board['x'] + board['width'] and board['y'] <= y <= board['y'] + board['height']  # In view
        tap(cdp, page, x, y)
        assert page.is_visible('#place-bar')
        page.tap('#place-ok')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(300)
        before = placed(page, game, 'p1-u0')
        assert all(before)

        # A tap that wobbles a few pixels on a model: no move, no setting up again
        x, y, r = model_box(page, 'p1-u0')
        tap(cdp, page, x, y, jitter=4)
        assert placed(page, game, 'p1-u0') == before and not page.is_visible('#place-bar')

        # Press and hold: the unit's card, nothing moved
        page.wait_for_timeout(600)  # Any scroll from selecting it has finished
        x, y, r = model_box(page, 'p1-u0')
        touch(cdp, 'touchStart', (x, y))
        page.wait_for_timeout(800)
        touch(cdp, 'touchEnd')
        page.wait_for_timeout(300)
        assert page.is_visible('#play-card') and 'Void Warriors' in page.inner_text('#play-card')
        assert placed(page, game, 'p1-u0') == before and not page.is_visible('#place-bar')

        # A finger just off a base still picks the model (nothing selected first)
        if page.is_visible('#action-close'):
            page.tap('#action-close')
        assert not page.is_visible('#action-bar')
        page.wait_for_timeout(300)
        x, y, r = model_box(page, 'p1-u0')
        tap(cdp, page, x, y + r + 12)
        assert page.is_visible('#action-bar') and 'Void Warriors' in page.inner_text('#action-head')

        # Two fingers apart: zoomed in about them; together again: back out
        width = lambda: page.evaluate("document.getElementById('play-board').viewBox.baseVal.width")  # noqa: E731
        start = width()
        cx, cy = board_to_screen(page, 30, 30)
        touch(cdp, 'touchStart', (cx - 20, cy), (cx + 20, cy))
        touch(cdp, 'touchMove', (cx - 60, cy), (cx + 60, cy))
        touch(cdp, 'touchEnd')
        assert width() < start * 0.5
        assert placed(page, game, 'p1-u0') == before  # Nothing moved

        # The zoom buttons and Fit
        page.tap('#zoom-out-btn')
        assert width() > start * 0.4
        page.tap('#fit-btn')
        assert width() == start
        context.close()


def in_movement(app):
    """The seeded game with every unit deployed, in Red's Movement phase."""
    client = app.test_client()
    ids = seed(client)
    act = lambda body: client.post(f'/api/play/games/{ids["game"]}/actions', json=body)  # noqa: E731
    game = client.get(f'/api/play/games/{ids["game"]}').get_json()
    for unit, spots in (('p1-u0', [(10 + 1.5 * i, 6) for i in range(5)]), ('p2-u0', [(10, 38), (11.5, 38)]), ('p1-u1', [(30, 6)])):
        models = [m['id'] for u in game['state']['units'] if u['id'] == unit for m in u['models']]
        body = {'type': 'place', 'unit': unit, 'models': [{'id': m, 'x': x, 'y': y, 'angle': 0} for m, (x, y) in zip(models, spots)]}
        assert act(body).status_code == 200, act(body).get_json()
    for body in ({'type': 'end_deployment'}, {'type': 'next_phase'}):
        assert act(body).status_code == 200, act(body).get_json()
    assert client.get(f'/api/play/games/{ids["game"]}').get_json()['state']['turn']['phase'] == 'movement'
    return ids


def test_one_model_at_a_time_and_spinning_it_by_touch(tmp_path_factory, browser):
    with live_server(tmp_path_factory.mktemp('one'), in_movement) as (address, ids):
        context = browser.new_context(**PHONE)
        page = context.new_page()
        errors, messages = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'{address}/play?game={ids["game"]}', wait_until='networkidle')
        cdp = context.new_cdp_session(page)
        game = ids['game']
        before = placed(page, game, 'p1-u0')

        page.tap('#one-btn')
        assert page.get_attribute('#one-btn', 'aria-pressed') == 'true'
        page.tap('#phone-tabs [data-phone-tab="0"]')
        page.tap('#army-0 .play-unit[data-unit="p1-u0"]')
        page.wait_for_timeout(600)
        x, y, r = model_box(page, 'p1-u0')
        touch(cdp, 'touchStart', (x - 10, y), (x + 10, y))  # Pinch in about 4 times around it, for a short move
        touch(cdp, 'touchMove', (x - 40, y), (x + 40, y))
        touch(cdp, 'touchEnd')
        x, y, r = model_box(page, 'p1-u0')  # Still under the fingers, bigger
        assert r > 8
        # Drag it 1" forward (up the board, however the board is turned on screen): the finger ends a lift below where
        # the model goes, as a dragged model is held above the finger (play.js LIFT_PX); the move waits for Confirm
        first = page.evaluate("document.querySelector('#play-board .play-model[data-unit=p1-u0]').dataset.model")
        units = page.evaluate(f"fetch('/api/play/games/{game}').then(r => r.json()).then(g => g.state.units)")
        start = next(m['position'] for u in units if u['id'] == 'p1-u0' for m in u['models'] if m['id'] == first)
        tx, ty = board_to_screen(page, start['x'], start['y'] + 1)
        steps = 8
        touch(cdp, 'touchStart', (x, y))
        for step in range(1, steps + 1):
            touch(cdp, 'touchMove', (x + (tx - x) * step / steps, y + (ty + 52 - y) * step / steps))
        touch(cdp, 'touchEnd')
        page.wait_for_timeout(500)
        assert page.is_visible('#move-ok'), page.inner_text('#play-message')
        assert placed(page, game, 'p1-u0') == before  # Not sent until Confirm
        page.wait_for_selector('#place-bar .play-check-ok')  # The server has said the move is allowed
        page.tap('#move-ok')
        for _ in range(40):  # Until it is saved (a slow CI runner can take longer than a fixed pause)
            after = placed(page, game, 'p1-u0')
            if after != before:
                break
            page.wait_for_timeout(250)
        moved = [i for i, (a, b) in enumerate(zip(after, before)) if a != b]
        assert len(moved) == 1 and after[moved[0]]['y'] == pytest.approx(before[moved[0]]['y'] + 1, abs=0.3), \
            page.inner_text('#play-message')  # Just it, 1" forward

        page.wait_for_selector('#unit-detail [data-spin]')
        page.tap('#unit-detail [data-spin="15"]')
        messages.append(page.inner_text('#play-message'))  # "Turning ...": the spin is waiting to be sent
        page.tap('#zoom-in-btn')  # Anything else: the spin is sent
        for _ in range(40):  # Until it is saved (a slow CI runner can take longer than a fixed pause)
            spun = placed(page, game, 'p1-u0')[moved[0]]
            if spun['angle']:
                break
            page.wait_for_timeout(250)
        messages.append(page.inner_text('#play-message'))
        assert spun['angle'] == 15 and (spun['x'], spun['y']) == (after[moved[0]]['x'], after[moved[0]]['y']), \
            {'messages': messages, 'errors': errors, 'spun': spun}
        context.close()


def test_a_hover_title_explains_on_a_tap_or_a_long_press(server, phone):
    """Tips (app.js): plain text with a title opens it on a tap, as a sheet with its name on a phone; a button with
    a title opens it on a long-press, and the tap that ends the press doesn't press the button."""
    phone.goto(server[0] + '/', wait_until='networkidle')
    phone.evaluate("""() => document.querySelector('main').insertAdjacentHTML('afterbegin',
        `<span id="kw" title="Each time an attack is made with this weapon, an unmodified hit roll of 6 scores a critical hit.">Lethal Hits</span>
         <button id="pressed" title="Saves the army, then opens the Match view" onclick="this.dataset.clicked = 1">Match view</button>`)""")
    phone.tap('#kw')
    assert phone.is_visible('#info-popover.tip-sheet')
    assert phone.inner_text('#info-popover .tip-heading') == 'Lethal Hits'
    assert 'critical hit' in phone.inner_text('#info-popover .tip-body')
    phone.mouse.click(180, 100)  # The dimmed page behind closes it
    assert not phone.is_visible('#info-popover')
    box = phone.locator('#pressed').bounding_box()
    cdp = phone.context.new_cdp_session(phone)
    point = {'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2, 'id': 0}
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [point]})
    phone.wait_for_timeout(700)
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    phone.wait_for_timeout(200)
    assert phone.is_visible('#info-popover') and 'Match view' in phone.inner_text('#info-popover')
    assert phone.get_attribute('#pressed', 'data-clicked') is None
