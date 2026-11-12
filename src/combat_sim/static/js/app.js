/**
 * Wammies With Friends - Frontend Application
 */

/**
 * Page setup that survives switching tabs but not restarting the app.
 * Stored in sessionStorage (cleared when the browser tab closes) and tagged with
 * the server's boot ID (new on every start), so stale state from a previous run is ignored.
 * Shared by every page, since base.html loads this script everywhere.
 */
const PageState = Core.createPageState(
    (() => { try { return window.sessionStorage; } catch (err) { return null; } })(),
    document.querySelector('meta[name="app-boot-id"]')?.content || ''
);

const SIMULATOR_STATE_KEY = 'simulatorState';

// A self-hosted copy (docs/self-hosting.md): when the login has run out, go to the login page
if (document.querySelector('meta[name="app-hosted"]') && !/^\/(login|welcome|join)(\/|$)/.test(location.pathname)) {
    const plainFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await plainFetch(...args);
        if (response.status === 401) location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        return response;
    };
}

/** Short buzz on a phone that has it (Android; iOS has no vibration API): a long-press that worked, a run started. */
const Haptics = {
    tap() { try { if (navigator.vibrate && matchMedia('(pointer: coarse)').matches) navigator.vibrate(10); } catch (err) { /* not allowed */ } },
};

/**
 * Sheets that slide up from the bottom of a phone's screen (the More menu, action sheets, tips, Analytics' cell detail,
 * Play's unit sheet): a dimmed page behind (tap it to close), and a drag down on the handle or the top of the sheet
 * closes it, as phone apps do.
 */
const Sheets = (() => {
    /** Drag `sheet` down to close it (calls close()): from its handle, or anywhere while it is scrolled to the top. */
    function swipeToClose(sheet, close) {
        let start = null;
        sheet.addEventListener('touchstart', e => {
            if (e.touches.length !== 1) return;
            const fromHandle = e.target.closest('.sheet-handle');
            if (!fromHandle && sheet.scrollTop > 0) return;
            if (!fromHandle && e.target.closest('input, select, textarea, .table-scroll, .matrix-scroll, .js-plotly-plot')) return;
            start = { y: e.touches[0].clientY, t: Date.now() };
        }, { passive: true });
        sheet.addEventListener('touchmove', e => {
            if (!start) return;
            const dy = e.touches[0].clientY - start.y;
            if (dy <= 0) { sheet.style.transform = ''; return; }
            sheet.style.transition = 'none';
            sheet.style.transform = `translateY(${dy}px)`;
        }, { passive: true });
        const end = e => {
            if (!start) return;
            const dy = (e.changedTouches?.[0]?.clientY ?? start.y) - start.y;
            const fast = dy > 40 && Date.now() - start.t < 250;
            start = null;
            sheet.style.transition = '';
            sheet.style.transform = '';
            if (dy > 90 || fast) close();
        };
        sheet.addEventListener('touchend', end);
        sheet.addEventListener('touchcancel', end);
    }

    /** A grip at the top of `sheet` (once), for a phone user to drag. */
    function addHandle(sheet) {
        if (sheet.querySelector(':scope > .sheet-handle')) return;
        const handle = document.createElement('div');
        handle.className = 'sheet-handle';
        handle.setAttribute('aria-hidden', 'true');
        sheet.prepend(handle);
    }

    return { swipeToClose, addHandle };
})();

/**
 * The More tab (phones and tablets) and the header's menu button: open and close the header's links, which show as
 * a sheet over the bottom of the screen there.
 */
(() => {
    const nav = document.getElementById('header-nav');
    const scrim = document.getElementById('nav-scrim');
    const toggles = ['nav-toggle', 'more-tab'].map(id => document.getElementById(id)).filter(Boolean);
    if (!nav || !toggles.length) return;
    Sheets.addHandle(nav);
    const show = open => {
        toggles.forEach(t => t.setAttribute('aria-expanded', String(open)));
        nav.classList.toggle('open', open);
        if (scrim) scrim.hidden = !open;
        const icon = document.querySelector('#nav-toggle i');
        if (icon) icon.className = open ? 'fa-solid fa-xmark' : 'fa-solid fa-bars';
    };
    toggles.forEach(t => t.addEventListener('click', e => { e.stopPropagation(); show(!nav.classList.contains('open')); }));
    document.addEventListener('click', e => { if (nav.classList.contains('open') && !e.target.closest('#header-nav, #nav-toggle, #more-tab')) show(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && nav.classList.contains('open')) { show(false); toggles[0].focus(); } });
    Sheets.swipeToClose(nav, () => show(false));
})();

/**
 * Tips: what a hover title says, for fingers and for clicks. Anything with a `title` (or `data-tip`) explains itself:
 *   - tap or click it when it is plain text (a keyword, a column heading, a badge): its explanation opens;
 *   - press and hold it when tapping does something else (a button, a tick row, a dropdown): the same, and the tap
 *     that ends the hold is swallowed so the button isn't pressed;
 *   - the ⓘ buttons (Core.infoButton) open theirs on a tap, as before.
 * A short tip is a bubble beside what was touched; on a phone a long one, or one with a name of its own (a keyword),
 * is a sheet at the bottom of the screen with the name as its heading, as look-ups in phone apps are. With a mouse
 * the title still shows on hover too. Not on the Play board (its own long-press shows a datasheet) or charts.
 */
const Tips = (() => {
    const PHONE = window.matchMedia('(max-width: 600px)');
    const TIP = '[data-tip], [title]:not([title=""])';
    const INTERACTIVE = 'a[href], button, input, select, textarea, label, summary, option, [role="button"], [role="tab"], [contenteditable]';
    // A tap explains plain text only, and nothing inside these, which have a click of their own
    const TAP_TEXT = 'span, abbr, dfn, th, small, em, strong, b, i, sup, li, code, h3, h4';
    const OWN_CLICK = '.matrix-cell, .matrix-row-header, .play-unit, .play-die, [data-unit], [data-no-tip], svg, .js-plotly-plot';
    let box = null, scrim = null, owner = null, press = null, swallowClick = false;

    function textOf(el) {
        return el.dataset.info || el.dataset.tip || el.getAttribute('title') || el.dataset.tipTitle || '';
    }

    /** Its own name, when short and not the start of the explanation itself (a keyword, a column heading). */
    function headingOf(el, text) {
        if (el.classList.contains('info-btn')) return '';
        const own = (el.dataset.tipHeading || el.textContent || '').replace(/\s+/g, ' ').trim();
        return own && own.length <= 40 && own !== text && !text.startsWith(own) ? own : '';
    }

    function make() {
        box = document.createElement('div');
        box.id = 'info-popover';
        box.setAttribute('role', 'tooltip');
        box.hidden = true;
        scrim = document.createElement('div');
        scrim.className = 'sheet-scrim tip-scrim';
        scrim.hidden = true;
        document.body.append(scrim, box);
        Sheets.swipeToClose(box, hide);
    }

    function hide() {
        if (!box) return;
        box.hidden = true;
        scrim.hidden = true;
        if (owner) owner.setAttribute('aria-expanded', 'false');
        owner = null;
    }

    function show(el) {
        const text = textOf(el);
        if (!text) return;
        if (!box) make();
        // Its hover title would show over the bubble: kept aside (and still read from there) once it has been opened
        if (el.hasAttribute('title') && !el.classList.contains('info-btn')) { el.dataset.tipTitle = el.title; el.removeAttribute('title'); }
        if (owner && owner !== el) owner.setAttribute('aria-expanded', 'false');
        owner = el;
        el.setAttribute('aria-expanded', 'true');
        const heading = headingOf(el, text);
        const asSheet = PHONE.matches && (!!heading || text.length > 110);
        box.className = 'info-popover' + (asSheet ? ' tip-sheet' : '');
        box.replaceChildren();
        if (asSheet) Sheets.addHandle(box);
        if (heading && asSheet) {
            const h = document.createElement('div');
            h.className = 'tip-heading';
            h.textContent = heading;
            box.append(h);
        }
        const body = document.createElement('div');
        body.className = 'tip-body';
        body.textContent = text;
        box.append(body);
        box.style.left = box.style.top = box.style.maxWidth = '';
        box.hidden = false;
        scrim.hidden = !asSheet;
        if (asSheet) return;
        // A bubble: under what was touched (above it when there's no room), its arrow pointing at it
        const r = el.getBoundingClientRect(), width = document.documentElement.clientWidth;
        box.style.maxWidth = Math.min(320, width - 16) + 'px';
        const shown = box.getBoundingClientRect();
        const left = Math.max(8, Math.min(r.left + r.width / 2 - shown.width / 2, width - shown.width - 8));
        const above = r.bottom + 10 + shown.height > window.innerHeight && r.top - 10 - shown.height > 0;
        box.classList.toggle('above', above);
        box.style.setProperty('--arrow-x', Math.max(12, Math.min(r.left + r.width / 2 - left, shown.width - 12)) + 'px');
        box.style.left = left + window.scrollX + 'px';
        box.style.top = (above ? r.top - 10 - shown.height : r.bottom + 10) + window.scrollY + 'px';
    }

    /** What a tap on `target` explains: plain text with a tip, not inside anything with a click of its own. */
    function tapTarget(target) {
        const el = target.closest(TIP);
        if (!el || !el.matches(TAP_TEXT) || el.closest(OWN_CLICK) || el.closest(INTERACTIVE)) return null;
        return el;
    }

    // Taps and clicks: ⓘ buttons and plain text with a tip
    document.addEventListener('click', e => {
        if (swallowClick) {  // The tap that ends a long-press: not a press of the button under it
            swallowClick = false;
            e.preventDefault();
            e.stopPropagation();
            return;
        }
        if (box && !box.hidden && (e.target === scrim || box.contains(e.target))) {
            e.stopPropagation();
            if (e.target === scrim) hide();
            return;
        }
        const el = e.target.closest('.info-btn') || tapTarget(e.target);
        if (el) {
            e.preventDefault();
            e.stopPropagation();  // Not the row's own click (ticking a rule, opening a card)
            if (el === owner) hide(); else show(el);
            return;
        }
        if (owner) hide();
    }, true);

    // Press and hold (touch and pen): anything with a tip, buttons and rows included
    document.addEventListener('pointerdown', e => {
        if (e.pointerType === 'mouse' || !e.isPrimary) return;
        const el = e.target.closest(TIP);
        if (!el || e.target.closest('svg, .js-plotly-plot, #play-board, input:not([type="checkbox"]):not([type="radio"]), textarea')) return;
        press = { el, x: e.clientX, y: e.clientY, timer: setTimeout(() => {
            press = null;
            swallowClick = true;
            setTimeout(() => { swallowClick = false; }, 800);  // No click followed (the finger slid off): forget it
            Haptics.tap();
            show(el);
        }, 480) };
    }, true);
    const cancel = () => { if (press) { clearTimeout(press.timer); press = null; } };
    document.addEventListener('pointermove', e => { if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > 10) cancel(); }, true);
    document.addEventListener('pointerup', cancel, true);
    document.addEventListener('pointercancel', cancel, true);
    document.addEventListener('contextmenu', e => { if (swallowClick || press) e.preventDefault(); }, true);

    document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
    window.addEventListener('scroll', () => { if (box && !box.hidden && !box.classList.contains('tip-sheet')) hide(); }, { passive: true });
    return { show, hide };
})();
const InfoPopover = Tips;  // Its old name

/**
 * Action sheets (phones): less-used buttons behind one "More" button (class overflow, see style.css). On a wider
 * screen the group shows its buttons in place, as before; on a phone they open as a list at the bottom of the screen.
 * The buttons keep their ids and handlers: a tap on one does what it always did, then the sheet closes.
 */
const ActionSheets = (() => {
    let open = null, scrim = null;
    function close() {
        if (!open) return;
        open.classList.remove('open');
        open.querySelector('.overflow-toggle')?.setAttribute('aria-expanded', 'false');
        open = null;
        if (scrim) scrim.hidden = true;
    }
    function show(group) {
        close();
        if (!scrim) {
            scrim = document.createElement('div');
            scrim.className = 'sheet-scrim overflow-scrim';
            document.body.appendChild(scrim);
        }
        open = group;
        group.classList.add('open');
        group.querySelector('.overflow-toggle')?.setAttribute('aria-expanded', 'true');
        const items = group.querySelector('.overflow-items');
        if (items) {
            Sheets.addHandle(items);
            if (!items.dataset.swipe) { items.dataset.swipe = '1'; Sheets.swipeToClose(items, close); }
        }
        scrim.hidden = false;
    }
    document.addEventListener('click', e => {
        const toggle = e.target.closest('.overflow-toggle');
        if (toggle) {
            e.preventDefault();
            const group = toggle.closest('.overflow');
            group === open ? close() : show(group);
            return;
        }
        if (!open) return;
        if (e.target === scrim || e.target.closest('.overflow-cancel')) { close(); return; }
        // A button in the sheet: it has done its job (this runs after its own handlers); close the sheet
        if (e.target.closest('.overflow-items button, .overflow-items a')) setTimeout(close, 0);
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    return { close };
})();

/**
 * A button that started something slow (a simulation, a save): disabled, with a spinner in place of its icon, until
 * the work is done. Busy.during(button, promise) returns the promise.
 */
const Busy = (() => {
    function during(button, promise) {
        if (!button) return promise;
        button.classList.add('is-busy');
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        const done = () => {
            button.classList.remove('is-busy');
            button.disabled = false;
            button.removeAttribute('aria-busy');
        };
        return Promise.resolve(promise).finally(done);
    }
    return { during };
})();

/**
 * Dropdown menus on wider screens (class dropdown: a .dropdown-toggle and a .dropdown-menu). A menu item with
 * data-click="id" presses that button, so a menu can offer buttons that live elsewhere on the page (such as those in
 * a phone's action sheet) without copying their handlers.
 */
const Dropdowns = (() => {
    let open = null;
    function close() {
        if (!open) return;
        open.classList.remove('open');
        open.querySelector('.dropdown-toggle')?.setAttribute('aria-expanded', 'false');
        open = null;
    }
    document.addEventListener('click', e => {
        const toggle = e.target.closest('.dropdown-toggle');
        if (toggle) {
            const menu = toggle.closest('.dropdown');
            const wasOpen = menu === open;
            close();
            if (!wasOpen) {
                open = menu;
                menu.classList.add('open');
                toggle.setAttribute('aria-expanded', 'true');
                menu.querySelector('.dropdown-menu [role=menuitem]')?.focus();
            }
            return;
        }
        const item = e.target.closest('.dropdown-menu [role=menuitem]');
        if (item && item.dataset.click) document.getElementById(item.dataset.click)?.click();
        if (open && (item || !e.target.closest('.dropdown-menu'))) close();
    });
    document.addEventListener('keydown', e => {
        if (!open) return;
        const items = [...open.querySelectorAll('.dropdown-menu [role=menuitem]')];
        const at = items.indexOf(document.activeElement);
        if (e.key === 'Escape') { const toggle = open.querySelector('.dropdown-toggle'); close(); toggle?.focus(); }
        else if (e.key === 'ArrowDown') { items[(at + 1) % items.length]?.focus(); e.preventDefault(); }
        else if (e.key === 'ArrowUp') { items[(at - 1 + items.length) % items.length]?.focus(); e.preventDefault(); }
    });
    return { close };
})();

/**
 * The command palette (Ctrl+K, or ⌘K on a Mac; also the search button in the header): jump to a page or a saved army,
 * or do what the page offers (buttons marked data-command="What it does"), by typing a few letters of it. The pages
 * come from the menu, so a player sees only those the menu shows them.
 */
const CommandPalette = (() => {
    let box = null, input = null, list = null, items = [], shown = [], at = 0, armies = null, back = null;

    function pageItems() {
        return [...document.querySelectorAll('#header-nav a.nav-link')].map(a => ({
            group: 'Go to', label: a.textContent.trim(), icon: a.querySelector('.fa-solid')?.className || 'fa-solid fa-arrow-right',
            run: () => { location.href = a.href; },
        }));
    }

    function actionItems() {
        return [...document.querySelectorAll('[data-command]')].filter(el => !el.disabled).map(el => ({
            group: 'This page', label: el.dataset.command, icon: el.querySelector('.fa-solid')?.className || 'fa-solid fa-bolt',
            run: () => el.click(),
        }));
    }

    function armyItems() {
        return (armies || []).flatMap(a => {
            const hint = [a.faction, a.total != null ? `${a.total} pts` : ''].filter(Boolean).join(' · ');
            const go = url => () => { location.href = url; };
            return [
                { group: 'Armies', label: a.name, hint, icon: 'fa-solid fa-chess-rook', run: go(`/armies?army=${a.id}`) },
                { group: 'Armies', label: `${a.name}: Match view`, hint, icon: 'fa-solid fa-book-open', run: go(`/armies/${a.id}/match`), use: true },
                { group: 'Armies', label: `${a.name}: analyse as attackers`, hint, icon: 'fa-solid fa-crosshairs', run: go(`/analytics?army=${a.id}&side=attacker`), use: true },
                { group: 'Armies', label: `${a.name}: analyse as defenders`, hint, icon: 'fa-solid fa-shield-halved', run: go(`/analytics?army=${a.id}&side=defender`), use: true },
            ];
        });
    }

    /** Every word typed is found in the label, hint or group, in any order */
    function matches(item, words) {
        const text = `${item.label} ${item.hint || ''} ${item.group}`.toLowerCase();
        return words.every(w => text.includes(w));
    }

    function render() {
        const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
        // Before anything is typed, each army is offered once (not its three uses)
        shown = items.filter(i => words.length ? matches(i, words) : !i.use);
        at = Math.min(at, Math.max(0, shown.length - 1));
        let group = null;
        list.innerHTML = shown.length ? shown.map((item, i) => {
            const head = item.group !== group ? `<li class="cmdk-group" role="presentation">${Core.escapeHtml(item.group)}</li>` : '';
            group = item.group;
            return `${head}<li class="cmdk-item ${i === at ? 'active' : ''}" role="option" id="cmdk-${i}" data-i="${i}" aria-selected="${i === at}">
                <i class="${Core.escapeHtml(item.icon)}" aria-hidden="true"></i><span class="cmdk-label">${Core.escapeHtml(item.label)}</span>
                ${item.hint ? `<span class="cmdk-hint">${Core.escapeHtml(item.hint)}</span>` : ''}</li>`;
        }).join('') : '<li class="cmdk-empty">Nothing matches</li>';
        input.setAttribute('aria-activedescendant', shown.length ? `cmdk-${at}` : '');
        list.querySelector('.cmdk-item.active')?.scrollIntoView({ block: 'nearest' });
    }

    function build() {
        box = document.createElement('div');
        box.className = 'cmdk';
        box.hidden = true;
        box.innerHTML = `<div class="cmdk-panel" role="dialog" aria-modal="true" aria-label="Command palette">
            <div class="cmdk-search"><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i>
                <input type="text" class="cmdk-input" placeholder="Go to a page, open an army or run an action…" autocomplete="off"
                       role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-label="Command"></div>
            <ul class="cmdk-list" id="cmdk-list" role="listbox"></ul>
            <div class="cmdk-foot"><span><kbd>↑</kbd><kbd>↓</kbd> choose</span><span><kbd>Enter</kbd> go</span><span><kbd>Esc</kbd> close</span></div>
        </div>`;
        document.body.appendChild(box);
        input = box.querySelector('.cmdk-input');
        list = box.querySelector('.cmdk-list');
        input.addEventListener('input', () => { at = 0; render(); });
        input.addEventListener('keydown', e => {
            const n = Math.max(1, shown.length);
            if (e.key === 'ArrowDown') { at = (at + 1) % n; render(); e.preventDefault(); }
            else if (e.key === 'ArrowUp') { at = (at - 1 + n) % n; render(); e.preventDefault(); }
            else if (e.key === 'Enter') { choose(at); e.preventDefault(); }
        });
        list.addEventListener('mousemove', e => {
            const li = e.target.closest('.cmdk-item');
            if (li && +li.dataset.i !== at) { at = +li.dataset.i; render(); }
        });
        list.addEventListener('click', e => { const li = e.target.closest('.cmdk-item'); if (li) choose(+li.dataset.i); });
        box.addEventListener('click', e => { if (e.target === box) close(); });
    }

    function choose(i) {
        const item = shown[i];
        if (!item) return;
        close(false);
        item.run();
    }

    function gather() {
        items = [...actionItems(), ...pageItems(), ...armyItems()];
    }

    async function open() {
        if (!box) build();
        back = document.activeElement;
        gather();
        input.value = '';
        at = 0;
        box.hidden = false;
        document.body.classList.add('cmdk-open');
        render();
        input.focus();
        if (armies === null) {  // The saved armies, once per page (none for a visitor, who may not list them)
            armies = [];
            try {
                const resp = await fetch('/api/armies');
                if (resp.ok) armies = await resp.json();
            } catch (err) { /* Offline: pages and actions only */ }
            if (!box.hidden) { gather(); render(); }
        }
    }

    function close(refocus = true) {
        if (!box || box.hidden) return;
        box.hidden = true;
        document.body.classList.remove('cmdk-open');
        if (refocus) back?.focus?.();
    }

    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
            if (!document.querySelector('#header-nav a.nav-link')) return;  // Logged out: nothing to offer
            e.preventDefault();
            box && !box.hidden ? close() : open();
        } else if (e.key === 'Escape' && box && !box.hidden) {
            e.stopPropagation();
            close();
        }
    }, true);
    document.addEventListener('DOMContentLoaded', () => {
        const button = document.getElementById('cmdk-btn');
        if (!button) return;
        if (/Mac|iPhone|iPad/.test(navigator.platform)) button.querySelector('kbd').textContent = '⌘K';
        button.addEventListener('click', open);
    });
    return { open, close };
})();

/** A short message over the bottom of the screen for a moment ("Added Gun Crew"), as phone apps confirm an action. */
const Toast = (() => {
    let el = null, timer = null;
    /** kind 'error': the message is drawn as a problem (and stays longer) */
    function show(text, kind) {
        if (!el) {
            el = document.createElement('div');
            el.className = 'toast';
            el.setAttribute('role', 'status');
            document.body.appendChild(el);
        }
        el.textContent = text;
        el.classList.toggle('toast-error', kind === 'error');
        el.classList.remove('show');
        void el.offsetWidth;  // Restart its animation
        el.classList.add('show');
        clearTimeout(timer);
        timer = setTimeout(() => el.classList.remove('show'), kind === 'error' ? 4500 : 2200);
    }
    return { show };
})();

/**
 * The Layout setting (Setup, Account and Play pages: a <select data-layout-setting>): phone, tablet, desktop or
 * automatic. Saved as your preference, and applied at once (base.html's window.applyLayout, Core.layoutFor).
 */
document.querySelectorAll('select[data-layout-setting]').forEach(select => {
    const root = document.documentElement;
    select.value = root.dataset.layoutPref || 'auto';
    select.addEventListener('change', async () => {
        const response = await fetch('/api/preferences/layout', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layout: select.value }),
        }).catch(() => null);
        if (!response || !response.ok) {
            Toast.show('The layout could not be saved.', 'error');
            return;
        }
        root.dataset.layoutPref = select.value;
        document.querySelectorAll('select[data-layout-setting]').forEach(other => { other.value = select.value; });
        if (window.applyLayout) window.applyLayout();  // Says 'layout-changed' if the layout is now another
        Toast.show(`Layout: ${select.options[select.selectedIndex].text}`);
    });
});

/**
 * Segmented controls: a <select data-segmented> shows as a row of buttons (as the Simulator's re-rolls), the select
 * kept, hidden, so the page's code reads and sets it as before. Call SegmentedSelect.sync(select) after setting its
 * value in code.
 */
const SegmentedSelect = (() => {
    function sync(select) {
        const group = select.nextElementSibling;
        if (!group || !group.classList.contains('segmented')) return;
        group.querySelectorAll('.btn-option').forEach(b => {
            const on = b.dataset.value === select.value;
            b.classList.toggle('active', on);
            b.setAttribute('aria-checked', String(on));
        });
    }
    function build(select) {
        if (select.dataset.segmentedBuilt) return;
        select.dataset.segmentedBuilt = '1';
        const group = document.createElement('div');
        group.className = 'btn-group segmented';
        group.setAttribute('role', 'radiogroup');
        group.setAttribute('aria-label', select.dataset.segmented || select.getAttribute('aria-label') || '');
        group.innerHTML = [...select.options].map(o =>
            `<button type="button" class="btn-option" role="radio" data-value="${Core.escapeHtml(o.value)}">${Core.escapeHtml(o.textContent)}</button>`).join('');
        select.classList.add('segmented-source');
        select.after(group);
        group.addEventListener('click', e => {
            const b = e.target.closest('.btn-option');
            if (!b || select.value === b.dataset.value) return;
            select.value = b.dataset.value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            sync(select);
        });
        select.addEventListener('change', () => sync(select));
        sync(select);
    }
    document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('select[data-segmented]').forEach(build));
    return { sync };
})();

/**
 * Long explanations on a phone (data-read-more): two lines, then "More" for the rest, as app stores show
 * descriptions. Wider screens show them whole (the button is hidden there).
 */
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-read-more]').forEach(el => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'read-more-btn';
        button.textContent = 'More';
        button.setAttribute('aria-expanded', 'false');
        button.addEventListener('click', () => {
            const open = el.classList.toggle('expanded');
            button.textContent = open ? 'Less' : 'More';
            button.setAttribute('aria-expanded', String(open));
        });
        el.after(button);
    });
});

/**
 * Weapon abilities as chips that explain themselves (the keyword glossary's summary, from the server as
 * `ability_hints` with a unit): tap one, or hover with a mouse.
 */
const AbilityHints = (() => {
    const hints = new Map();
    function add(map) { Object.entries(map || {}).forEach(([k, v]) => { if (v) hints.set(k, v); }); }
    function chips(abilities, cls = 'kw-chip') {
        return (abilities || []).map(a => {
            const hint = hints.get(a);
            return `<span class="${cls}"${hint ? ` title="${Core.escapeHtml(hint)}"` : ''}>${Core.escapeHtml(a)}</span>`;
        }).join('');
    }
    return { add, chips };
})();

/**
 * Tables that show as cards on phones and are drawn by script (class cards-on-phone with data-auto-labels): each
 * cell is labelled with its column's heading (Core.cellLabels), again whenever rows are redrawn, including tables
 * drawn inside them later. Cells that already have a label keep it.
 */
const TableCards = (() => {
    function label(table) {
        const headings = [...table.querySelectorAll(':scope > thead > tr > th')].map(th => th.textContent);
        table.querySelectorAll(':scope > tbody > tr').forEach(tr => {
            const cells = [...tr.children];
            const labels = Core.cellLabels(headings, cells.map(td => td.colSpan));
            if (labels) cells.forEach((td, i) => { if (labels[i] && !td.hasAttribute('data-label')) td.setAttribute('data-label', labels[i]); });
            // Nothing in it (only spaces): no "label:" line with nothing after it
            cells.forEach(td => td.classList.toggle('cell-empty', !td.textContent.trim() && !td.querySelector('input, select, button, img, svg, i')));
        });
    }
    function watch(root) {
        root.querySelectorAll('table.cards-on-phone[data-auto-labels]').forEach(table => {
            label(table);
            if (table.dataset.cardsWatched) return;
            table.dataset.cardsWatched = '1';
            new MutationObserver(() => { label(table); watch(table); }).observe(table, { childList: true, subtree: true });
        });
    }
    watch(document);
    return { watch };
})();

/**
 * As-you-type warnings for keyword/modifier text boxes (same rules as the Data page forms).
 * Usage: KeywordHints.attach(inputElement, hintElement, 'unit')
 * mode 'unit': plain words are fine (they are unit keywords used by Anti); only entries with values are checked.
 */
const KeywordHints = {
    /** Ask the server to check the box's keywords and show the result under it. */
    async check(input, hint, mode = '') {
        const text = input.value;
        try {
            const response = await fetch('/api/keywords/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, mode }),
            });
            const result = await response.json();
            if (input.value !== text) return;  // a newer check is on its way
            hint.innerHTML = Core.keywordHintHtml(result);
        } catch (err) {
            hint.innerHTML = '';
        }
    },

    attach(input, hint, mode = '') {
        let timer;
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => this.check(input, hint, mode), 200);
        });
        if (input.value) this.check(input, hint, mode);
    },
};

// State management
const state = {
    attacker: {
        unit: null,
        weapons: { ranged: [], melee: [] },
        weaponType: 'ranged',
        leaders: [],  // Leaders that can join the unit: [{id, name, points, leader_buffs}]
        leader: null,  // The attached one (its weapons are in `weapons`, marked leader: true)
    },
    defender: {
        unit: null,
        extraModifiers: '',  // One-off target modifiers for this run (never saved to the datasheet)
        leaders: [],
        leader: null,  // Its buffs apply to the target; its stats aren't part of the target (yet)
    },
    conditions: {
        half_range: false,
        charged: false,
        stationary: false,
        cover: false,
        damaged: false,
        reroll_hits: 'none',
        reroll_wounds: 'none',
        attacker_afflicted: '',  // Death Guard's Nurgle's Gift: '' (not Afflicted), 'none' (no Plague) or a Plague
        defender_afflicted: '',
    },
    simulation: {
        method: 'analytical',
        iterations: 1000,
    },
    // Rules & stratagems that can be ticked for each side, which are ticked ('rule:3', 'stratagem:7'),
    // and the side's chosen detachments (BSData keys; none = faction-wide rules only)
    rules: {
        attacker: { available: [], ticked: new Set(), factionId: null, chosen: [], detachments: [] },
        target: { available: [], ticked: new Set(), factionId: null, chosen: [], detachments: [] },
    },
};

// Last simulation result for saving
let lastSimulationResult = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
    // app.js is loaded on every page; the rest is for the simulator page only
    if (!document.getElementById('attacker-unit')) return;

    initAutocomplete();
    initWeaponTypeToggle();
    initToggles();
    initRerollButtons();
    initAfflictionSelects();
    initSimulationOptions();
    initSimulateButton();
    initExtraModifiers();
    initDetachmentSelects();
    initLeaderSelects();
    loadRulesFor('attacker', null);
    loadRulesFor('target', null);

    await restoreSimulatorState();
    window.addEventListener('pagehide', saveSimulatorState);
});

/**
 * Extra modifiers: one-off target modifiers for this defender, e.g. "Stealth, Feel No Pain 5+"
 */
function initExtraModifiers() {
    const input = document.getElementById('defender-extra-modifiers');
    if (!input) return;
    input.addEventListener('input', () => { state.defender.extraModifiers = input.value; });
    KeywordHints.attach(input, document.getElementById('defender-extra-modifiers-hint'), 'unit');
}

function setExtraModifiers(text) {
    state.defender.extraModifiers = text;
    const input = document.getElementById('defender-extra-modifiers');
    if (input) {
        input.value = text;
        input.dispatchEvent(new Event('input'));
    }
}

/**
 * Remember the simulator setup for when the user comes back to this tab
 */
function saveSimulatorState() {
    PageState.save(SIMULATOR_STATE_KEY, {
        attackerUnit: state.attacker.unit,
        attackerUnitText: document.getElementById('attacker-unit').value,
        weapons: state.attacker.weapons,
        weaponType: state.attacker.weaponType,
        defenderUnit: state.defender.unit,
        defenderUnitText: document.getElementById('defender-unit').value,
        modelCount: document.getElementById('model-count').value,
        extraModifiers: state.defender.extraModifiers,
        conditions: state.conditions,
        simulation: state.simulation,
        result: lastSimulationResult,
        rulesTicked: {
            attacker: [...state.rules.attacker.ticked],
            target: [...state.rules.target.ticked],
        },
        detachments: { attacker: state.rules.attacker.chosen, target: state.rules.target.chosen },
        leaders: { attacker: state.attacker.leader?.id ?? null, defender: state.defender.leader?.id ?? null },
        legends: {
            attacker: document.getElementById('attacker-legends').checked,
            defender: document.getElementById('defender-legends').checked,
        },
    });
}

async function restoreSimulatorState() {
    const saved = PageState.load(SIMULATOR_STATE_KEY);
    if (!saved) return;

    applyConditions(saved.conditions || {});

    state.simulation = { ...state.simulation, ...(saved.simulation || {}) };
    const monteCarlo = document.getElementById('monte-carlo');
    monteCarlo.checked = state.simulation.method === 'monte_carlo';
    monteCarlo.closest('.toggle')?.classList.toggle('active', monteCarlo.checked);
    document.getElementById('iterations').value = state.simulation.iterations;
    document.getElementById('model-count').value = saved.modelCount || 5;
    setExtraModifiers(saved.extraModifiers || '');

    document.getElementById('attacker-legends').checked = !!saved.legends?.attacker;
    document.getElementById('defender-legends').checked = !!saved.legends?.defender;
    state.rules.attacker.chosen = Core.detachmentKeys(saved.detachments?.attacker);
    state.rules.target.chosen = Core.detachmentKeys(saved.detachments?.target);

    document.getElementById('defender-unit').value = saved.defenderUnitText || '';
    if (saved.defenderUnit) {
        state.defender.unit = saved.defenderUnit;
        showUnitStats('defender', saved.defenderUnit);
        if (saved.defenderUnit.id) await loadDefenderLeaders(saved.defenderUnit.id, saved.leaders?.defender);
    }

    document.getElementById('attacker-unit').value = saved.attackerUnitText || '';
    if (saved.attackerUnit) {
        state.attacker.unit = saved.attackerUnit;
        showUnitStats('attacker', saved.attackerUnit);
    }

    // Reload the unit's weapons so edits made on the Data tab show up; fall back to the saved list
    let restored = false;
    if (saved.attackerUnit?.id) {
        try {
            await loadWeaponsForUnit(saved.attackerUnit.id);
            if (saved.leaders?.attacker) await attachAttackerLeader(saved.leaders.attacker);
            for (const t of ['ranged', 'melee']) {
                for (const w of state.attacker.weapons[t]) {
                    const before = (saved.weapons?.[t] || []).find(s => s.id === w.id);
                    if (before?.qty) w.qty = before.qty;
                    if (typeof before?.use === 'boolean') w.use = before.use;
                }
            }
            setWeaponType(saved.weaponType || 'ranged');
            restored = true;
        } catch (err) {
            console.error('Error reloading weapons:', err);
        }
    }
    if (!restored && saved.weapons) {
        state.attacker.weapons = saved.weapons;
        setWeaponType(saved.weaponType || 'ranged');
    }

    loadRulesFor('attacker', saved.attackerUnit?.faction_id ?? null, saved.rulesTicked?.attacker);
    loadRulesFor('target', saved.defenderUnit?.faction_id ?? null, saved.rulesTicked?.target);

    if (saved.result) {
        lastSimulationResult = saved.result;
        displayResults(saved.result);
    }
}

// =========================
// Rules & stratagems panels
// =========================

const PHASE_FOR_WEAPON = { ranged: 'Shooting', melee: 'Fighting' };
const RULE_GROUPS = [
    ['rule', 'Faction rules'],
    ['stratagem', 'Faction stratagems'],
    ['core', 'Core stratagems'],
];

/** The detachment checklists reload their side's rules when changed. */
function initDetachmentSelects() {
    for (const side of ['attacker', 'target']) {
        const picker = document.getElementById(`${side}-detachment`);
        if (!picker) continue;
        picker.style.display = 'none';
        picker.addEventListener('change', () => {
            state.rules[side].chosen = [...picker.querySelectorAll('input:checked')].map(cb => cb.dataset.key);
            loadRulesFor(side, state.rules[side].factionId);
        });
    }
}

/** Fill a side's detachment checklist for its faction (hidden when the faction has none). */
async function loadDetachments(side, factionId) {
    const panel = state.rules[side];
    const select = document.getElementById(`${side}-detachment`);
    if (factionId !== panel.factionId || !panel.detachments.length) {
        panel.detachments = factionId
            ? await fetch(`/api/detachments?faction_id=${factionId}`).then(r => r.json()).catch(() => [])
            : [];
    }
    panel.factionId = factionId;
    panel.chosen = (panel.chosen || []).filter(key => panel.detachments.some(d => d.key === key));
    if (select) {
        const open = select.open;
        select.innerHTML = Core.detachmentPickerHtml(panel.detachments, panel.chosen);
        select.open = open;
        select.style.display = panel.detachments.length ? '' : 'none';
    }
}

/**
 * Load the rules/stratagems one side can tick (its faction's, those of its detachment, and core);
 * keep ticks that still exist.
 */
async function loadRulesFor(side, factionId, ticked = null) {
    await loadDetachments(side, factionId);
    const params = new URLSearchParams({ side: side === 'attacker' ? 'Attacker' : 'Target' });
    if (factionId) params.append('faction_id', factionId);
    (state.rules[side].chosen || []).forEach(key => params.append('detachment', key));
    try {
        const available = await fetch(`/api/rules/available?${params}`).then(r => r.json());
        const panel = state.rules[side];
        const keys = new Set(available.map(e => e.key));
        panel.available = available;
        panel.ticked = new Set([...(ticked || panel.ticked)].filter(k => keys.has(k)));
        renderRulesPanel(side);
    } catch (err) {
        console.error('Error loading rules:', err);
    }
}

/** Entries usable in the current phase (from the attacker's Shooting/Melee choice). */
function visibleRules(side) {
    return Core.rulesForFilter(state.rules[side].available, state.attacker.weaponType);
}

function renderRulesPanel(side) {
    const listEl = document.getElementById(`${side}-rules-list`);
    if (!listEl) return;
    const panel = state.rules[side];
    const visible = visibleRules(side);

    let html = '';
    for (const [kind, title] of RULE_GROUPS) {
        const group = visible.filter(e => e.kind === kind);
        if (!group.length) continue;
        html += `<div class="rules-group-title">${title}</div>`;
        html += group.map(e => `
            <label class="rule-row${e.has_effect ? '' : ' rule-no-effect'}"
                   title="${escapeHtml(Core.ruleRowTitle(e))}">
                <input type="checkbox" data-key="${e.key}" ${panel.ticked.has(e.key) ? 'checked' : ''}>
                <span class="rule-name">${escapeHtml(e.name)}${Core.infoButton(Core.ruleConditions(e), 'When to tick it')}</span>
                ${e.detachment ? `<span class="rule-detachment">${escapeHtml(e.detachment)}</span>` : ''}
                ${e.cp ? `<span class="rule-cp">${escapeHtml(e.cp)} CP</span>` : ''}
                <span class="rule-modifier">${e.has_effect ? escapeHtml(e.modifier) : 'No effect on the calculations'}</span>
            </label>`).join('');
    }
    listEl.innerHTML = html || '<div class="rules-empty">No rules or stratagems for this phase</div>';

    listEl.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => {
            cb.checked ? panel.ticked.add(cb.dataset.key) : panel.ticked.delete(cb.dataset.key);
            updateRulesSummary(side);
        });
    });
    updateRulesSummary(side);
}

function updateRulesSummary(side) {
    const summaryEl = document.getElementById(`${side}-rules-summary`);
    if (!summaryEl) return;
    const active = visibleRules(side).filter(e => state.rules[side].ticked.has(e.key) && e.has_effect);
    summaryEl.textContent = active.length
        ? 'Active: ' + active.map(e => e.modifier).join(', ')
        : (state.rules[side].ticked.size ? 'Ticked, but no effect in this phase' : 'None ticked');
    summaryEl.classList.toggle('rules-summary-active', active.length > 0);
}

/** {rule_ids, stratagem_ids} for the request (the server applies only those matching side/phase). */
function rulesSelection(side) {
    return Core.rulesSelection(state.rules[side].ticked);
}

/**
 * Set the battle condition toggles and re-roll buttons (and state) to match `conditions`
 */
function applyConditions(conditions) {
    ['half_range', 'charged', 'stationary', 'cover', 'damaged'].forEach(cond => {
        const toggle = document.querySelector(`[data-condition="${cond}"]`);
        const on = !!conditions[cond];
        if (toggle) {
            const input = toggle.querySelector('input');
            if (input) input.checked = on;
            toggle.classList.toggle('active', on);
        }
        state.conditions[cond] = on;
    });

    ['hits', 'wounds'].forEach(type => {
        const value = conditions[`reroll_${type}`] || 'none';
        const group = document.querySelector(`[data-reroll="${type}"]`);
        if (group) {
            group.querySelectorAll('.btn-option').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.value === value);
            });
        }
        state.conditions[`reroll_${type}`] = value;
    });

    document.querySelectorAll('[data-affliction]').forEach(select => {
        const key = select.dataset.affliction;
        select.value = conditions[key] || '';
        if (select.selectedIndex < 0) select.value = '';  // A choice this version doesn't have
        state.conditions[key] = select.value;
    });
}

/**
 * Initialize autocomplete inputs
 */
function initAutocomplete() {
    // Attacker unit autocomplete
    setupAutocomplete('attacker-unit', async (search) => {
        const response = await fetch(unitSearchUrl(search, 'attacker'));
        return response.json();
    }, (item) => {
        state.attacker.unit = item;
        showUnitStats('attacker', item);
        loadWeaponsForUnit(item.id);  // Also lists the leaders that can join it
        loadRulesFor('attacker', item.faction_id);
    }, formatUnitItem);

    // Defender unit autocomplete
    setupAutocomplete('defender-unit', async (search) => {
        const response = await fetch(unitSearchUrl(search, 'defender'));
        return response.json();
    }, (item) => {
        state.defender.unit = item;
        showUnitStats('defender', item);
        loadDefenderLeaders(item.id);
        document.getElementById('model-count').value = item.default_models || 5;
        loadRulesFor('target', item.faction_id);
    }, formatUnitItem);
}

/** Unit search URL; Legends units only when that side's "Show Legends" box is ticked. */
function unitSearchUrl(search, side) {
    const legends = document.getElementById(`${side}-legends`)?.checked ? '&legends=1' : '';
    return `/api/units?search=${encodeURIComponent(search)}${legends}`;
}

/**
 * Setup autocomplete for an input
 */
function setupAutocomplete(inputId, fetchFn, onSelect, formatFn) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(`${inputId}-dropdown`);

    if (!input || !dropdown) return;

    let debounceTimer;

    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            const search = input.value.trim();
            if (search.length < 1) {
                dropdown.classList.remove('show');
                return;
            }

            const items = await fetchFn(search);
            renderDropdown(dropdown, items, formatFn, (item) => {
                input.value = item.name;
                dropdown.classList.remove('show');
                onSelect(item);
            });
        }, 200);
    });

    input.addEventListener('focus', async () => {
        if (input.value.length >= 1) {
            const items = await fetchFn(input.value);
            renderDropdown(dropdown, items, formatFn, (item) => {
                input.value = item.name;
                dropdown.classList.remove('show');
                onSelect(item);
            });
        }
    });

    input.addEventListener('blur', () => {
        setTimeout(() => dropdown.classList.remove('show'), 200);
    });
}

/**
 * Render dropdown items
 */
function renderDropdown(dropdown, items, formatFn, onClick) {
    if (items.length === 0) {
        dropdown.innerHTML = '<div class="autocomplete-item"><em>No results</em></div>';
    } else {
        dropdown.innerHTML = items.map(item => formatFn(item)).join('');
    }
    dropdown.classList.add('show');

    dropdown.querySelectorAll('.autocomplete-item').forEach((el, idx) => {
        el.addEventListener('click', () => onClick(items[idx]));
    });
}

/**
 * Format unit item for dropdown
 */
function formatUnitItem(unit) {
    return `
        <div class="autocomplete-item" data-id="${unit.id}">
            <div class="item-name">${escapeHtml(unit.name)}</div>
            <div class="item-faction">${escapeHtml(unit.faction)}</div>
        </div>
    `;
}

/**
 * Show unit stats in the panel
 */
function showUnitStats(side, unit) {
    const prefix = side === 'attacker' ? 'att' : 'def';
    const statsEl = document.getElementById(`${side}-stats`);

    if (!statsEl) return;

    statsEl.style.display = 'grid';
    document.getElementById(`${prefix}-t`).textContent = unit.toughness;
    document.getElementById(`${prefix}-sv`).textContent = unit.save + '+';
    document.getElementById(`${prefix}-w`).textContent = unit.wounds;
    document.getElementById(`${prefix}-inv`).textContent = Core.invulnerableLabel(unit) || '-';
    document.getElementById(`${prefix}-fnp`).textContent = unit.feel_no_pain ? unit.feel_no_pain + '+' : '-';
}

const escapeHtml = Core.escapeHtml;

/** A colour token from style.css's :root (e.g. themeColor('--accent')), so charts follow the theme. */
function themeColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Load weapons for selected unit and show them in the weapon list
 */

/**
 * Load the unit's loadout and wargear options. qty = models carrying the weapon (pre-filled from
 * the loadout, editable per run); use = ticked for the simulation. Neither is saved to the data.
 */
async function loadWeaponsForUnit(unitId) {
    const response = await fetch(`/api/units/${unitId}`);
    const unitData = await response.json();
    AbilityHints.add(unitData.ability_hints);

    // default_use: the server's default ticks (only the first "Weapon - Profile" variant of a gun); options start unticked
    state.attacker.weapons = Core.simulatorWeapons(unitData);
    state.attacker.leaders = unitData.leaders || [];
    state.attacker.leader = null;
    renderLeaderSelect('attacker');
    setWeaponType(state.attacker.weapons.ranged.length ? 'ranged' : 'melee');
}

// =========================
// Leaders
// =========================

function initLeaderSelects() {
    document.getElementById('attacker-leader')?.addEventListener('change', async (e) => {
        await attachAttackerLeader(e.target.value ? parseInt(e.target.value) : null);
    });
    document.getElementById('defender-leader')?.addEventListener('change', (e) => {
        const id = e.target.value ? parseInt(e.target.value) : null;
        state.defender.leader = state.defender.leaders.find(l => l.id === id) || null;
        renderLeaderSelect('defender');
    });
}

/** "Led by" dropdown for a side: hidden when no leader can join its unit; shows what the chosen one grants. */
function renderLeaderSelect(side) {
    const group = document.getElementById(`${side}-leader-group`);
    const select = document.getElementById(`${side}-leader`);
    const hint = document.getElementById(`${side}-leader-buffs`);
    if (!group || !select) return;
    const { leaders, leader } = state[side];
    group.style.display = leaders.length ? '' : 'none';
    select.innerHTML = '<option value="">No leader</option>' + leaders.map(l =>
        `<option value="${l.id}" ${leader?.id === l.id ? 'selected' : ''}>${escapeHtml(l.name)}${l.points ? ` (+${l.points} pts)` : ''}</option>`).join('');
    const summary = leader ? Core.leaderBuffSummary(leader.leader_buffs) : '';
    hint.textContent = !leader ? ''
        : (summary ? `Grants: ${summary}.` : 'Grants nothing the calculations use (buffs can be added on the Data tab).') +
          (side === 'defender' ? ' Attacks go to the bodyguard models first, then the leader (with its own profile).' : '');
}

/** Attach a leader to the attacker (its weapons join the list) or detach (null). */
async function attachAttackerLeader(leaderId) {
    const choice = state.attacker.leaders.find(l => l.id === leaderId) || null;
    const detail = choice ? await fetch(`/api/units/${choice.id}`).then(r => r.json()) : null;
    AbilityHints.add(detail?.ability_hints);
    state.attacker.leader = choice;
    state.attacker.weapons = Core.withLeaderWeapons(state.attacker.weapons, detail);
    renderLeaderSelect('attacker');
    renderWeaponList();
}

/** The leaders that can join the defender unit; keep `keepId` attached if it is one of them. */
async function loadDefenderLeaders(unitId, keepId = null) {
    const detail = await fetch(`/api/units/${unitId}`).then(r => r.json()).catch(() => ({}));
    state.defender.leaders = detail.leaders || [];
    state.defender.leader = state.defender.leaders.find(l => l.id === keepId) || null;
    renderLeaderSelect('defender');
}

/**
 * Initialize the shooting / melee toggle above the weapon list
 */
function initWeaponTypeToggle() {
    document.querySelectorAll('#weapon-type-toggle .toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => setWeaponType(btn.dataset.type));
    });
}

/**
 * Switch the weapon list to ranged or melee, selecting a weapon of that type
 */
function setWeaponType(type) {
    state.attacker.weaponType = type;
    renderRulesPanel('attacker');
    renderRulesPanel('target');
    document.querySelectorAll('#weapon-type-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === type);
    });
    renderWeaponList();
}

/** Ticked weapons of the current phase. */
function usedWeapons() {
    return Core.usedWeapons(state.attacker.weapons, state.attacker.weaponType);
}

function weaponPayload(w) {
    return Core.weaponPayload(w, state.attacker.weaponType);
}

/**
 * Render the attacker's weapons of the active type, one per row
 */
function renderWeaponList() {
    const listEl = document.getElementById('attacker-weapon-list');
    if (!listEl) return;

    const type = state.attacker.weaponType;
    const weapons = state.attacker.weapons[type];

    if (!state.attacker.unit && weapons.length === 0) {
        listEl.innerHTML = '<div class="weapon-list-empty">Select a unit to see its weapons</div>';
        return;
    }

    if (weapons.length === 0) {
        listEl.innerHTML = `<div class="weapon-list-empty">No ${type === 'ranged' ? 'shooting' : 'melee'} weapons</div>`;
        return;
    }

    const isRanged = type === 'ranged';
    const columns = isRanged ? 9 : 8;
    const firstOption = weapons.findIndex(w => w.option);
    const rows = weapons.map((w, idx) => {
        const abilities = w.abilities?.length
            ? `<div class="weapon-row-abilities">${AbilityHints.chips(w.abilities)}</div>`
            : '';
        const optionsHeader = idx === firstOption
            ? `<tr class="weapon-options-header"><td colspan="${columns}">Wargear options (tick to swap in; set Qty)</td></tr>`
            : '';
        return `${optionsHeader}
            <tr class="weapon-row${w.use ? ' selected' : ' excluded'}${w.option ? ' weapon-option' : ''}" data-idx="${idx}">
                <td class="weapon-use"><input type="checkbox" class="weapon-use-box" data-idx="${idx}" ${w.use ? 'checked' : ''}
                           title="Use this weapon in the simulation"></td>
                <td class="weapon-row-name">${escapeHtml(w.name)}${w.leader ? ` <span class="option-tag" title="${escapeHtml(w.leader_name)}'s weapon">leader</span>` : ''}${abilities}</td>
                ${isRanged ? `<td>${w.range ? escapeHtml(w.range) + '"' : '-'}</td>` : ''}
                <td>${escapeHtml(w.attacks)}</td>
                <td>${w.skill ? escapeHtml(w.skill) + '+' : '-'}</td>
                <td>${escapeHtml(w.strength)}</td>
                <td>${w.ap === 0 ? '0' : '-' + escapeHtml(w.ap)}</td>
                <td>${escapeHtml(w.damage)}</td>
                <td><input type="number" class="weapon-qty" data-idx="${idx}" value="${w.qty || 1}" min="1" max="99"
                           title="Models with this weapon (this run only)"></td>
            </tr>
        `;
    }).join('');

    listEl.innerHTML = `
        <table class="weapon-table">
            <thead>
                <tr>
                    <th title="Use">Use</th>
                    <th>Weapon</th>
                    ${isRanged ? '<th>Range</th>' : ''}
                    <th>A</th>
                    <th>${isRanged ? 'BS' : 'WS'}</th>
                    <th>S</th>
                    <th>AP</th>
                    <th>D</th>
                    <th title="Models with this weapon">Qty</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;

    // Clicking a row toggles it (except on the inputs themselves)
    listEl.querySelectorAll('.weapon-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.tagName === 'INPUT') return;
            const w = weapons[parseInt(row.dataset.idx)];
            w.use = !w.use;
            renderWeaponList();
        });
    });
    listEl.querySelectorAll('.weapon-use-box').forEach(box => {
        box.addEventListener('change', () => {
            weapons[parseInt(box.dataset.idx)].use = box.checked;
            box.closest('tr').classList.toggle('selected', box.checked);
            box.closest('tr').classList.toggle('excluded', !box.checked);
        });
    });
    listEl.querySelectorAll('.weapon-qty').forEach(input => {
        input.addEventListener('change', () => {
            const qty = Math.max(1, parseInt(input.value) || 1);
            input.value = qty;
            weapons[parseInt(input.dataset.idx)].qty = qty;
        });
    });
}

/**
 * Initialize toggle buttons
 */
function initToggles() {
    document.querySelectorAll('.toggle').forEach(toggle => {
        const input = toggle.querySelector('input');
        if (!input) return;

        toggle.addEventListener('click', () => {
            input.checked = !input.checked;
            toggle.classList.toggle('active', input.checked);

            // Update state
            const condition = toggle.dataset.condition;
            if (condition) {
                state.conditions[condition] = input.checked;
            }
        });
    });
}

/** Death Guard's Afflicted choices (one per side) */
function initAfflictionSelects() {
    document.querySelectorAll('[data-affliction]').forEach(select => {
        select.addEventListener('change', () => { state.conditions[select.dataset.affliction] = select.value; });
    });
}

/**
 * Initialize re-roll button groups
 */
function initRerollButtons() {
    document.querySelectorAll('.btn-group').forEach(group => {
        const rerollType = group.dataset.reroll;

        group.querySelectorAll('.btn-option').forEach(btn => {
            btn.addEventListener('click', () => {
                group.querySelectorAll('.btn-option').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                if (rerollType === 'hits') {
                    state.conditions.reroll_hits = btn.dataset.value;
                } else if (rerollType === 'wounds') {
                    state.conditions.reroll_wounds = btn.dataset.value;
                }
            });
        });
    });
}

/**
 * Initialize simulation options
 */
function initSimulationOptions() {
    const monteCarloToggle = document.getElementById('monte-carlo');
    const iterationsInput = document.getElementById('iterations');

    if (monteCarloToggle) {
        monteCarloToggle.addEventListener('change', () => {
            state.simulation.method = monteCarloToggle.checked ? 'monte_carlo' : 'analytical';
        });
    }

    if (iterationsInput) {
        iterationsInput.addEventListener('change', () => {
            state.simulation.iterations = parseInt(iterationsInput.value) || 1000;
        });
    }
}

/**
 * Initialize simulate button
 */
function initSimulateButton() {
    const btn = document.getElementById('btn-simulate');
    if (!btn) return;

    btn.addEventListener('click', () => { Haptics.tap(); Busy.during(btn, runSimulation()); });
    document.getElementById('sim-bar-result')?.addEventListener('click', () =>
        document.getElementById('results-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}

/**
 * Run simulation
 */
async function runSimulation() {
    const weapons = usedWeapons();
    const defender = state.defender.unit;

    if (!weapons.length || !defender) {
        Toast.show('Tick at least one attacker weapon and choose a defender first', 'error');
        return;
    }

    const modelCount = parseInt(document.getElementById('model-count')?.value) || 1;

    const payload = {
        attacker: {
            faction_id: state.attacker.unit?.faction_id ?? null,
            unit_id: state.attacker.unit?.id ?? null,
            leader_id: state.attacker.leader?.id ?? null,
            weapons: weapons.map(weaponPayload),
            afflicted: state.conditions.attacker_afflicted || null,
        },
        defender: {
            toughness: defender.toughness,
            save: defender.save,
            wounds: defender.wounds,
            invulnerable_save: defender.invulnerable_save,
            feel_no_pain: defender.feel_no_pain,
            keywords: [...(defender.keywords || []), ...(defender.modifiers || [])],
            faction_id: defender.faction_id ?? null,
            model_count: modelCount,
            extra_modifiers: state.defender.extraModifiers,
            leader_id: state.defender.leader?.id ?? null,
            afflicted: state.conditions.defender_afflicted || null,
        },
        conditions: state.conditions,
        method: state.simulation.method,
        iterations: state.simulation.iterations,
        attacker_rules: rulesSelection('attacker'),
        target_rules: rulesSelection('target'),
    };

    try {
        const response = await fetch('/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Simulation failed');
        lastSimulationResult = result;
        displayResults(result);
        // One column (phones): the results are below everything else, so take the player to them
        if (window.matchMedia('(max-width: 900px)').matches) {
            document.getElementById('results-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    } catch (err) {
        console.error('Simulation error:', err);
        Toast.show('The simulation could not be run', 'error');
    }
}

/**
 * Display simulation results
 */
function displayResults(result) {
    document.getElementById('results-panel')?.classList.add('has-result');
    // Phones: the last result in the bar beside Run, a tap away from the full results
    const barResult = document.getElementById('sim-bar-result');
    if (barResult) {
        barResult.hidden = false;
        barResult.innerHTML = `<span class="bar-value">${escapeHtml(result.summary.average_damage)}</span><span class="bar-label">dmg</span>`
            + `<span class="bar-value">${escapeHtml(result.summary.models_killed)}</span><span class="bar-label">killed</span>`
            + '<i class="fa-solid fa-chevron-down" aria-hidden="true"></i>';
    }
    // Summary (totals across the ticked weapons)
    document.getElementById('res-avg-damage').textContent = result.summary.average_damage;
    document.getElementById('res-models-killed').textContent = result.summary.models_killed;
    document.getElementById('res-overkill').textContent = result.summary.overkill;

    const extra = document.getElementById('res-mc-extra');
    if (extra) {
        extra.textContent = result.summary.wipe_probability != null
            ? `Monte Carlo (${result.iterations} runs, all weapons rolled together` +
              `${result.iterations < state.simulation.iterations ? '; fewer than asked, as this many attacks would hold the app up' : ''}): ` +
              `${result.summary.kill_probability}% chance to kill at least one model, ${result.summary.wipe_probability}% to wipe the unit`
            : '';
    }

    // Attached unit: bodyguard models first, then the leader
    const attachedEl = document.getElementById('res-attached');
    if (attachedEl) {
        const a = result.attached, s = result.summary;
        // Analytical: expected damage to the leader (averages overstate "kills" near the threshold);
        // Monte Carlo: how often the leader actually dies
        attachedEl.textContent = !a ? ''
            : `Attached unit: ${s.bodyguards_killed} of ${a.bodyguard_models} bodyguard models killed; ` +
              (s.leader_kill_probability != null
                  ? `${a.leader} dies in ${s.leader_kill_probability}% of runs (average damage ${s.leader_damage} of ${a.leader_wounds} wounds)`
                  : `expected damage to ${a.leader}: ${s.leader_damage} of ${a.leader_wounds} wounds`);
    }

    // Breakdown
    document.getElementById('res-attacks').textContent = result.breakdown.attacks;
    document.getElementById('res-hits').textContent = result.breakdown.hits;
    document.getElementById('res-wounds').textContent = result.breakdown.wounds;
    document.getElementById('res-failed-saves').textContent = result.breakdown.failed_saves;
    document.getElementById('res-damage').textContent = result.breakdown.damage;

    renderWeaponResults(result.weapons || []);

    // Chart
    drawChart(result.distribution);
}

/** Per-weapon results table (Excel's Sim-sheet columns), with a total row. */
function renderWeaponResults(rows) {
    const el = document.getElementById('weapon-results');
    if (!el) return;
    if (!rows.length) {
        el.innerHTML = '';
        return;
    }

    const fmt = v => (v === null || v === undefined) ? '-' : (Math.round(v * 100) / 100).toString();
    const sum = key => rows.reduce((total, r) => total + (r[key] || 0), 0);
    const cols = [
        ['attacks', 'Attacks'], ['hits', 'Hits'], ['auto_wounds', 'Auto Wounds'], ['wounds', 'Wounds'],
        ['mortal_wounds', 'Mortal Wounds'], ['unsaved', 'Unsaved'], ['damage_per_attack', 'Dmg / Attack'],
        ['total_damage', 'Total Damage'], ['models_killed', 'Models Killed'],
    ];
    // Attached unit: weapons in order, bodyguards then leader, so their kills add up (otherwise capped, as in Excel)
    const attached = rows.some(r => r.leader_killed != null);
    if (attached) cols.push(['bodyguards_killed', 'Bodyguards killed'], ['leader_damage', 'Damage to leader']);

    el.innerHTML = `
        <h3>Per Weapon <span class="weapon-results-note">(average results)</span></h3>
        <div class="weapon-results-scroll">
            <table class="breakdown-table weapon-results-table">
                <thead><tr><th>Weapon</th><th>Qty</th>${cols.map(([, label]) => `<th>${label}</th>`).join('')}</tr></thead>
                <tbody>
                    ${rows.map(r => `<tr>
                        <td>${escapeHtml(r.name)}</td><td>${r.models}</td>
                        ${cols.map(([key]) => `<td>${fmt(r[key])}</td>`).join('')}
                    </tr>`).join('')}
                </tbody>
                ${rows.length > 1 ? `<tfoot><tr><td>Total</td><td></td>
                    ${cols.map(([key]) => `<td>${key === 'damage_per_attack' || (key === 'models_killed' && !attached) ? '' : fmt(sum(key))}</td>`).join('')}
                </tr></tfoot>` : ''}
            </table>
        </div>
    `;
}

/**
 * Draw the damage distribution chart (Monte Carlo only: the analytical engine gives averages,
 * not a spread, so the chart is hidden then).
 */
function drawChart(distribution) {
    const chartEl = document.getElementById('chart');
    if (!chartEl) return;
    const section = document.getElementById('distribution-section');
    if (!distribution?.labels?.length) {
        Plotly.purge(chartEl);
        if (section) section.style.display = 'none';
        return;
    }
    if (section) section.style.display = '';
    const marker = Core.woundsMarker(distribution, themeColor('--text-secondary'));

    Plotly.newPlot(chartEl, [{
        x: distribution.labels,
        y: distribution.probabilities,
        type: 'bar',
        marker: {
            color: themeColor('--accent'),
            line: {
                color: themeColor('--accent-hover'),
                width: 1
            }
        },
        hovertemplate: '%{x} damage: %{y:.1f}%<extra></extra>'
    }], {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: themeColor('--text-primary'), size: 11 },
        margin: { t: 30, r: 20, b: 50, l: 50 },
        xaxis: {
            title: 'Damage',
            type: 'category',
            gridcolor: themeColor('--border'),
            linecolor: themeColor('--border')
        },
        shapes: marker.shapes,
        annotations: marker.annotations,
        yaxis: {
            title: 'Probability %',
            gridcolor: themeColor('--border'),
            linecolor: themeColor('--border')
        },
        bargap: 0.15
    }, {
        responsive: true,
        displayModeBar: false
    });
}

