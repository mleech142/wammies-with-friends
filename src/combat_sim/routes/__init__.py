"""
The app's routes, one module per area. Each module's `register(app)` adds its routes to the app (plain routes,
not blueprints, so endpoint names stay as access.py labels them and url_for finds them). Play mode's are in
play/routes.py, logins' in accounts.py and proposals' in proposals.py.

- simulator: the Simulator page and /api/simulate
- catalogue: what the pages choose from (units, rules and stratagems to tick, detachments, enhancements, keywords)
- analytics: the matrix, a cell's detail, Army Analysis and reverse durability
- army_lists: the Armies page, pricing, wargear, share codes and Match view
- saved: scenarios and comparisons
- data_tab: the Data tab (app data, read and changed through app_data_edits.py)
- setup: the Setup page (BSData and Wahapedia downloads and re-imports, as jobs) and the import status
- shared: helpers more than one area uses
"""

from . import analytics, army_lists, catalogue, data_tab, saved, setup, simulator


def register(app):
    for area in (simulator, catalogue, analytics, army_lists, saved, data_tab, setup):
        area.register(app)
