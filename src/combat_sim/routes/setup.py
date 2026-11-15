"""
The Setup page: downloading Wahapedia's export (units, rules and stratagems), the import status the Setup and Data
pages show, and what was carried over from BSData's IDs (carry_over.py). Downloads run as jobs (jobs.py).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, render_template, request

from .. import access, jobs, reference, wahapedia_download
from ..access import host_only
from ..models import Faction, FactionRule, Stratagem, Unit, db
from ..settings import load_settings, update_settings


def register(app):
    """The setup routes."""

    @app.route('/api/data/status')
    def api_data_status():
        """The game data: whether the units loaded (and from where), their import notes, the rules and stratagems
        (`wahapedia`) and, for the host, what was carried over from BSData's IDs (`carry_over`)."""
        now = reference.current(app)
        status = now.bsdata_status
        report = status.get('report') or []
        counts = {}
        for item in report:
            counts[item['kind']] = counts.get(item['kind'], 0) + 1
        return jsonify(without_paths({
            'folder': status.get('folder') or app.config['WAHAPEDIA_DIR'],
            'loaded': bool(status.get('loaded')),
            'error': status.get('error'),
            'units_from': now.units_source,
            'source': status.get('source'),
            'from_cache': bool(status.get('from_cache')),
            'report_counts': counts,
            'report': report if request.args.get('report') else None,
            'factions': Faction.query.filter_by(source='bsdata').count(),
            'units': Unit.query.join(Faction).filter(Faction.source == 'bsdata').count(),
            'label': reference.label(app),
            'hosted': not access.principal().local,
            'wahapedia': wahapedia_status(bool(request.args.get('report'))),
            'carry_over': carry_over_report() if access.is_host() else None,
        }))

    def carry_over_report():
        """What the first start on Wahapedia changed in saved data (reference._carry_over), or None."""
        try:
            return json.loads(Path(app.config['CARRY_OVER_JSON']).read_text(encoding='utf-8'))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    PATH_KEYS = ('folder',)

    def without_paths(status):
        """A self-hosted copy shows where its files are on the server to the host alone."""
        if access.is_host():
            return status
        def strip(d):
            return {k: (strip(v) if isinstance(v, dict) else v) for k, v in d.items() if k not in PATH_KEYS}
        return strip(status)

    def wahapedia_status(with_report=False):
        """The Wahapedia import: whether it loaded, when Wahapedia last updated it, counts and report."""
        status = reference.current(app).wahapedia_status
        report = status.get('report') or []
        counts = {}
        for item in report:
            counts[item['kind']] = counts.get(item['kind'], 0) + 1
        # Each Wahapedia record once (it is copied into every BSData faction that has it)
        parsed, unique = {}, {}
        for kind, model in (('stratagems', Stratagem), ('rules', FactionRule)):
            records = dict(db.session.query(model.wahapedia_id, model.parse).filter(model.source == 'wahapedia'))
            unique[kind] = len(records)
            for parse in records.values():
                key = (parse or {}).get('status') or 'not_modelled'
                parsed[key] = parsed.get(key, 0) + 1
        return {
            'folder': status.get('folder'),
            'loaded': bool(status.get('loaded')),
            'error': status.get('error'),
            'last_update': (status.get('source') or {}).get('last_update'),
            'stratagems': unique['stratagems'],
            'rules': unique['rules'],
            'parsed': parsed,
            'report_counts': counts,
            'report': report if with_report else None,
            'download': load_settings(app.config['SETTINGS_JSON']).get('wahapedia_download'),
        }

    # --- Long Setup work runs as a job (jobs.py): the answer is the data status when it finished at once, else
    # 202 with the job for the page to poll (/api/jobs/<id>)

    def job_answer(job):
        if not job.finished:
            return jsonify({'job': job.to_dict()}), 202
        if job.state == jobs.FAILED:
            return jsonify({'error': job.error, 'job': job.to_dict()}), job.status or 500
        return api_data_status()

    @app.route('/api/jobs/<int:job_id>')
    @host_only
    def api_job(job_id):
        """A Setup job's progress: {'id', 'kind', 'state' (running, done, failed), 'step', 'error', 'seconds'}."""
        job = jobs.of(app).get(job_id)
        if job is None:
            return jsonify({'error': 'That job is no longer known (the app may have restarted).'}), 404
        return jsonify(job.to_dict())

    def wahapedia_job(job):
        job.step = 'Downloading from Wahapedia'
        try:
            info = wahapedia_download.download(app.config['WAHAPEDIA_DIR'])
        except wahapedia_download.DownloadError as err:
            raise jobs.JobError(str(err), 502) from err
        update_settings(app.config['SETTINGS_JSON'], wahapedia_download=dict(
            info, downloaded_at=datetime.now(timezone.utc).isoformat(timespec='seconds')))
        job.step = 'Reading the units, rules and stratagems'
        now = reference.load(app, wahapedia_too=True)
        error = now.wahapedia_status.get('error') or now.bsdata_status.get('error')
        if error:
            raise jobs.JobError(error, 400)

    @app.route('/api/wahapedia/download', methods=['POST'])
    @host_only
    def api_wahapedia_download():
        """Download Wahapedia's latest export (units, rules and stratagems) and use it (a job)."""
        return job_answer(jobs.of(app).submit('wahapedia', wahapedia_job))

    # --- Setup ---------------------------------------------------------------------

    @app.route('/setup')
    @host_only
    def setup_page():
        return render_template('setup.html')

    @app.route('/api/preferences/layout', methods=['POST'])
    def api_layout_preference():
        """Your layout: 'phone', 'tablet', 'desktop' or 'auto' (Core.layoutFor works it out from the device). From the
        Setup, Account and Play pages; it is one of your own preferences (settings.PREFERENCES)."""
        layout = str((request.get_json(silent=True) or {}).get('layout') or 'auto')
        if layout not in ('auto', 'phone', 'tablet', 'desktop'):
            return jsonify({'error': 'Choose automatic, phone, tablet or desktop.'}), 400
        access.principal().set_preferences(layout=None if layout == 'auto' else layout)
        return jsonify({'layout': layout})

    @app.route('/api/setup/skip', methods=['POST'])
    @host_only
    def api_skip_setup():
        """Use the app without the game data for now: the Simulator stops redirecting to Setup."""
        update_settings(app.config['SETTINGS_JSON'], setup_skipped=True)
        return jsonify({'message': 'Setup skipped'})
