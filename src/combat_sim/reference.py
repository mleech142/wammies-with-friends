"""
The reference data (architecture review, candidate 4): Wahapedia's export (units, weapons, points, detachments and
enhancements from its datasheet files; rules and stratagems) and the app data JSON, merged into the reference tables.
One module owns loading them, rebuilding the tables and saving the app data, and publishes what was loaded as one
`Reference` snapshot:

- `load(app, wahapedia_too=..., data=...)`: (re)import what's asked, merge it with the app data, rebuild the tables
  in one transaction (data_store.rebuild_reference_tables) and publish the new snapshot. Other players' requests see
  the old tables and snapshot until it's done; a failed rebuild changes neither.
- `current(app)`: the snapshot now (the status of each import, the folder in use, what was merged).
- `save_app_data(app)`: commit a Data-tab change and rewrite the app data JSON from the tables.

Loads and saves hold data_store.REFERENCE_LOCK, so a save never exports half-built tables and two loads never mix.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import json
import logging

from . import carry_over, wahapedia
from .data_store import (BSDATA_SCHEMA_VERSION, REFERENCE_LOCK, SCHEMA_VERSION, export_data,
                         load_wahapedia_units, merge_data, read_data_file, rebuild_reference_tables,
                         with_shipped_keywords, write_data_file)
from .models import db


@dataclass(frozen=True)
class Reference:
    units_dir: str = None
    # The units, weapons, detachments and enhancements from the export's datasheet files (units_source 'wahapedia'
    # once they loaded). The field names are from before 3.0, when they came from BSData.
    bsdata_result: object = None
    bsdata_status: dict = field(default_factory=dict)
    units_source: str = None
    wahapedia_result: object = None
    wahapedia_status: dict = field(default_factory=dict)
    data_source: object = None  # the app data JSON's 'source'
    data_version: int = None  # its schema_version as read (after any upgrade)
    unmatched: object = None  # app data records that matched nothing imported (kept in the file)


EMPTY = Reference()


def current(app):
    return app.extensions.get('reference', EMPTY)


def load(app, wahapedia_too=False, data=None):
    """
    Rebuild the reference tables and publish the new snapshot. `wahapedia_too`: import the Wahapedia folder again
    (units and rules); `data`: the app data to merge (else the app data JSON). Answers the new snapshot; on a
    failure the tables and the published snapshot stay as they were and the error is raised.
    """
    with REFERENCE_LOCK:
        now = current(app)
        if data is None:
            data = read_data_file(app.config['DATA_JSON'])
        data = with_shipped_keywords(data, app.config.get('SHIPPED_DATA_JSON'), app.config['DATA_JSON'])
        if wahapedia_too:
            folder = app.config['WAHAPEDIA_DIR']
            result, status = wahapedia.load_folder(folder)
            now = replace(now, wahapedia_result=result, wahapedia_status=status)
            known = [k['name'] for k in data.get('keywords', [])] or None
            result, status = load_wahapedia_units(folder, known)
            now = replace(now, units_dir=folder, bsdata_result=result, bsdata_status=status,
                          units_source='wahapedia' if result is not None else None)
        upgraded = False
        if now.units_source == 'wahapedia':
            data, upgraded = _carry_over(app, data)
        report = []
        merged, unmatched = merge_data(data, now.bsdata_result, now.wahapedia_result, report)
        try:
            rebuild_reference_tables(merged)
        except Exception:
            db.session.rollback()
            raise
        now = replace(now, data_source=data.get('source'), unmatched=unmatched, data_version=data.get('schema_version'),
                      wahapedia_status=dict(now.wahapedia_status, report=report))
        app.extensions['reference'] = now  # one assignment: readers see the old snapshot or this one
        if upgraded:  # The app data JSON in Wahapedia's IDs from now on
            write_data_file(app.config['DATA_JSON'], export_data(now.data_source, now.unmatched, schema_version(now)))
        return now


def schema_version(now):
    """The app data JSON's version: 3 (Wahapedia's IDs), or 2 for a file from before 3.0 kept as it was until the
    export is downloaded (its IDs are BSData's until then)."""
    return BSDATA_SCHEMA_VERSION if now.units_source is None and now.data_version == BSDATA_SCHEMA_VERSION \
        else SCHEMA_VERSION


def _carry_over(app, data):
    """
    Before the first rebuild from Wahapedia: saved records and the app data in Wahapedia's IDs (carry_over.py).
    Answers (app data, whether it was upgraded). What was carried over is written to CARRY_OVER_JSON for the
    Setup page; doing it again changes nothing.
    """
    try:
        id_map = carry_over.shipped_map()
    except (OSError, ValueError) as err:  # Not in this build: start all the same, carrying nothing over
        logging.getLogger(__name__).warning('No BSData ID map (%s): saved data is not carried over', err)
        return data, False
    found = carry_over.carry_over_database(id_map)
    if found is not None:
        logging.getLogger(__name__).info('Carried saved data over from BSData to Wahapedia: %s',
                                         {k: v for k, v in found.items() if k != 'notes'})
        path = app.config.get('CARRY_OVER_JSON')
        if path:
            found['at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            Path(path).write_text(json.dumps(found, indent=1, ensure_ascii=False), encoding='utf-8')
    if data.get('schema_version') == BSDATA_SCHEMA_VERSION:
        return carry_over.upgrade_app_data(data, id_map), True
    return data, False


def save_app_data(app):
    """Commit the session's Data-tab change and rewrite the app data JSON (never while the tables are rebuilt)."""
    with REFERENCE_LOCK:
        db.session.commit()
        now = current(app)
        write_data_file(app.config['DATA_JSON'], export_data(now.data_source, now.unmatched, schema_version(now)))


def export(app):
    """The app data as the app data JSON would hold it now."""
    now = current(app)
    return export_data(now.data_source, now.unmatched)


def label(app):
    """For the footer: when Wahapedia last updated its export ('updated 2026-11-10'), 'loaded' when that isn't known,
    or None when nothing of it is loaded."""
    now = current(app)
    status = now.wahapedia_status
    if not status.get('loaded'):
        return 'loaded' if now.units_source == 'wahapedia' and now.bsdata_status.get('loaded') else None
    date = ((status.get('source') or {}).get('last_update') or '')[:10]
    return f'updated {date}' if date else 'loaded'
