"""
Flask application for Wammies With Friends: create_app() configures the app and registers every area's routes
(routes/, play/routes.py, accounts.py, proposals.py), then access.py's gate.
"""

import mimetypes
import os
import secrets
import uuid
from pathlib import Path

from flask import Flask, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from . import __version__, access, reference, routes
from .accounts import register_account_routes, secret_key
from .models import Proposal, db, init_db
from .paths import (BSDATA_CACHE_FILE, BSDATA_FOLDER, DATA_FILE, DATABASE_FILE, WAHAPEDIA_FOLDER, bundle_root, is_hosted,
                    prepare_data_dir)
from .play.routes import register_play_routes
from .proposals import register_proposal_routes
from .settings import settings_path
from .wargear import default_used  # noqa: F401  (tests import it from here)

mimetypes.add_type('application/manifest+json', '.webmanifest')  # The home-screen manifest (static/)


def create_app(config=None):
    """Application factory."""
    app = Flask(__name__)

    # Configuration. The app data JSON (custom factions, rules, stratagems, references) and the
    # database default to the folder from paths.data_dir(): the repository's data/ from source,
    # a per-user folder in the packaged exe. Settings, the import cache and "Download latest"
    # sit next to the app data JSON. The BSData folder is the one chosen on the Setup page,
    # else BSDATA_DIR, else the bsdata folder next to the app data JSON. Wahapedia's files
    # (rules and stratagems) are in WAHAPEDIA_DIR, else the wahapedia folder next to it.
    data_json = os.environ.get('DATA_JSON')
    database_url = os.environ.get('DATABASE_URL')
    # The shipped app data, whose keyword glossary entries the user's copy lacks are added on every load (a
    # release's new modifiers). Not for a harness's own DATA_JSON unless it names one in SHIPPED_DATA_JSON.
    shipped = os.environ.get('SHIPPED_DATA_JSON') or (None if data_json else str(bundle_root() / 'data' / DATA_FILE))
    if not (data_json and database_url):
        folder = prepare_data_dir()
        data_json = data_json or str(folder / DATA_FILE)
        database_url = database_url or 'sqlite:///' + (folder / DATABASE_FILE).as_posix()
    app.config['DATA_JSON'] = data_json
    app.config['SHIPPED_DATA_JSON'] = shipped
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['DOWNLOAD_DIR'] = str(Path(data_json).parent / BSDATA_FOLDER)
    app.config['DEFAULT_BSDATA_DIR'] = os.environ.get('BSDATA_DIR') or app.config['DOWNLOAD_DIR']
    app.config['BSDATA_CACHE'] = str(Path(data_json).parent / BSDATA_CACHE_FILE)
    app.config['WAHAPEDIA_DIR'] = os.environ.get('WAHAPEDIA_DIR') or str(Path(data_json).parent / WAHAPEDIA_FOLDER)
    app.config['SETTINGS_JSON'] = str(settings_path(data_json))
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = MAX_REQUEST_BYTES  # Bigger requests are refused (413) before they're read
    # Hosted mode (docs/self-hosting.md): other people's browsers reach this copy, so what only makes sense on
    # your own computer is refused (the folder dialog, BSData folders by path, the relay's address)
    app.config['HOSTED'] = is_hosted()
    if app.config['HOSTED'] and not os.environ.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = secret_key(Path(data_json).parent)  # logins survive restarts

    # New on every start. Pages tag saved page state with it, so state survives
    # switching tabs but is discarded after the app is restarted.
    app.config['BOOT_ID'] = uuid.uuid4().hex

    @app.after_request
    def safety_headers(response):
        """No other site may show these pages in a frame (and trick a click on them), and browsers take each answer
        as the type it says it is."""
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'same-origin')  # join links never leave in a Referer
        return response

    @app.errorhandler(HTTPException)
    def api_http_error(err):
        """API answers stay JSON when they fail (not found, too large, wrong method): the pages show 'error'."""
        if not request.path.startswith('/api/') or (err.code or 0) < 400:  # redirects stay redirects
            return err
        return jsonify({'error': err.description or err.name}), err.code

    def bad_api_request(err):
        """An API request with a field missing or of the wrong kind: 400 with what was wrong, not a crash. Logged, in
        case it was the app's own mistake."""
        if not request.path.startswith('/api/'):
            raise err
        db.session.rollback()
        app.logger.warning('Bad request to %s', request.path, exc_info=err)
        detail = f"'{err.args[0]}' is missing" if isinstance(err, KeyError) and err.args else str(err)[:200]
        what = 'That change' if request.path.startswith('/api/data/') else 'That request'
        return jsonify({'error': f'{what} has a field missing or wrong: {detail}.'}), 400

    for kind in (KeyError, ValueError, TypeError):
        app.register_error_handler(kind, bad_api_request)

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(err):
        db.session.rollback()
        return jsonify({'error': 'That would create a duplicate or break a link between records.'}), 400

    @app.context_processor
    def inject_page_globals():
        who = access.principal()  # Pages ask who is acting, never whether the copy is self-hosted
        return {'boot_id': app.config['BOOT_ID'], 'app_version': __version__,
                'bsdata_label': reference.label(app),
                'who': who,
                'user': who.user,
                'can_setup': who.is_host,
                'pending_proposals': (Proposal.query.filter_by(status='pending').count()
                                      if who.shared and who.is_host else 0),
                'show_play': bool(who.preferences().get('show_play')),
                'layout_pref': who.preferences().get('layout') or 'auto',  # Core.layoutFor, set on <html> by base.html
                'wahapedia_label': reference.wahapedia_label(app)}

    if config:
        app.config.update(config)

    # Initialize database, then rebuild the reference tables from BSData, Wahapedia and the app data JSON
    init_db(app)
    with app.app_context():
        reference.load(app, bsdata=True, wahapedia_too=True)

    # Register routes
    routes.register(app)
    register_play_routes(app)
    register_account_routes(app)
    register_proposal_routes(app)
    access.register(app)  # last: it checks every route is labelled

    return app


MAX_REQUEST_BYTES = 16 * 1024 * 1024  # Largest request (an app data JSON or game file is far smaller)
