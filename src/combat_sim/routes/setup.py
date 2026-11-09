"""
The Setup page: choosing, downloading and re-importing BSData, downloading Wahapedia, and the import status the
Setup and Data pages show. Downloads and re-imports run as jobs (jobs.py).
"""

from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, render_template, request

from .. import access, bsdata_download, folder_dialog, jobs, reference, wahapedia_download
from ..access import desktop_only, host_only
from ..models import Faction, FactionRule, Stratagem, Unit, db
from ..settings import load_settings, update_settings


def register(app):
    """The setup routes."""

    @app.route('/api/data/status')
    def api_data_status():
        """The BSData folder and import: where, whether it loaded, revisions and report."""
        status = reference.current(app).bsdata_status
        report = status.get('report') or []
        counts = {}
        for item in report:
            counts[item['kind']] = counts.get(item['kind'], 0) + 1
        return jsonify(without_paths({
            'folder': status.get('folder'),
            'loaded': bool(status.get('loaded')),
            'error': status.get('error'),
            'from_cache': bool(status.get('from_cache')),
            'source': status.get('source'),
            'report_counts': counts,
            'report': report if request.args.get('report') else None,
            'factions': Faction.query.filter_by(source='bsdata').count(),
            'units': Unit.query.join(Faction).filter(Faction.source == 'bsdata').count(),
            'label': reference.label(app),
            'download': load_settings(app.config['SETTINGS_JSON']).get('download'),
            'download_folder': app.config['DOWNLOAD_DIR'],
            'hosted': not access.principal().local,  # No folder dialog or paths
            'default_folder': app.config['DEFAULT_BSDATA_DIR'],
            'wahapedia': wahapedia_status(bool(request.args.get('report'))),
        }))

    PATH_KEYS = ('folder', 'download_folder', 'default_folder')

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
        job.step = 'Reading the rules and stratagems'
        status = reference.load(app, wahapedia_too=True).wahapedia_status
        if status.get('error'):
            raise jobs.JobError(status['error'], 400)

    @app.route('/api/wahapedia/download', methods=['POST'])
    @host_only
    def api_wahapedia_download():
        """Download the latest rules and stratagems from Wahapedia and use them (a job)."""
        return job_answer(jobs.of(app).submit('wahapedia', wahapedia_job))

    # --- Setup: choosing, downloading and re-importing the BSData folder -------------

    def hosted_refusal(what):
        return jsonify({'error': f'{what} is turned off on a self-hosted copy (hosted mode).'}), 403

    @app.route('/setup')
    @host_only
    def setup_page():
        return render_template('setup.html')

    @app.route('/api/bsdata/folder', methods=['POST'])
    @host_only
    def api_bsdata_folder():
        """Use the BSData folder {'path'} (null = back to the default), if it loads."""
        path = (request.get_json() or {}).get('path')
        if path and not access.principal().local:
            return hosted_refusal('Choosing a BSData folder by path')
        settings_file = app.config['SETTINGS_JSON']
        previous = load_settings(settings_file).get('bsdata_dir')
        if path:
            folder = Path(str(path).strip()).expanduser()
            if not folder.is_dir():
                return jsonify({'error': f'{folder} is not a folder.'}), 400
            if not any(folder.glob('*.json')):
                return jsonify({'error': f'{folder} holds no .json files. Choose the folder with the BSData '
                                         'catalogues (e.g. "Warhammer 40,000.json").'}), 400
            update_settings(settings_file, bsdata_dir=str(folder.resolve()))
        else:
            update_settings(settings_file, bsdata_dir=None)
        status = reference.load(app, bsdata=True).bsdata_status
        if status.get('error'):  # Keep the folder that worked
            update_settings(settings_file, bsdata_dir=previous)
            reference.load(app, bsdata=True)
            return jsonify({'error': status['error']}), 400
        return api_data_status()

    @app.route('/api/bsdata/browse', methods=['POST'])
    @desktop_only
    def api_bsdata_browse():
        """Open the computer's folder dialog; {'path'} or {'path': null} if cancelled or unavailable."""
        return jsonify({'path': folder_dialog.choose_folder(initial=reference.current(app).bsdata_dir)})

    def bsdata_download_job(job):
        job.step = 'Finding the latest catalogues on GitHub'
        try:
            commit = bsdata_download.latest_commit()
            job.step = 'Downloading the catalogues'
            count = bsdata_download.install_zip(bsdata_download.download_zip(commit['sha']), app.config['DOWNLOAD_DIR'])
        except bsdata_download.DownloadError as err:
            raise jobs.JobError(str(err), 502) from err
        update_settings(app.config['SETTINGS_JSON'], bsdata_dir=app.config['DOWNLOAD_DIR'], download={
            'sha': commit['sha'], 'date': commit['date'], 'files': count, 'folder': app.config['DOWNLOAD_DIR'],
            'downloaded_at': datetime.now(timezone.utc).isoformat(timespec='seconds')})
        job.step = 'Importing the catalogues'
        status = reference.load(app, bsdata='fresh').bsdata_status
        if status.get('error'):
            raise jobs.JobError(status['error'], 400)

    def bsdata_reimport_job(job):
        job.step = 'Importing the catalogues'
        reference.load(app, bsdata='fresh')

    @app.route('/api/bsdata/download', methods=['POST'])
    @host_only
    def api_bsdata_download():
        """Download the latest catalogues from GitHub into the download folder and use it (a job)."""
        return job_answer(jobs.of(app).submit('bsdata', bsdata_download_job))

    @app.route('/api/bsdata/reimport', methods=['POST'])
    @host_only
    def api_bsdata_reimport():
        """Import the BSData folder again (after changing its files), ignoring the cache (a job)."""
        return job_answer(jobs.of(app).submit('bsdata', bsdata_reimport_job))

    @app.route('/api/bsdata/skip-setup', methods=['POST'])
    @host_only
    def api_bsdata_skip_setup():
        """Use the app without BSData for now: the Simulator stops redirecting to Setup."""
        update_settings(app.config['SETTINGS_JSON'], setup_skipped=True)
        return jsonify({'message': 'Setup skipped'})
