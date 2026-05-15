import os
from dotenv import load_dotenv

# Load .env BEFORE importing Config so os.environ.get inside Config sees the
# values. Falls through silently if .env doesn't exist.
load_dotenv()

from flask import Flask, flash, redirect, request, url_for, jsonify, render_template
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from markupsafe import Markup
from .config import Config
from .models import db, User
from .blueprints.auth import bp as auth_bp
from .blueprints.reports import bp as reports_bp
from .blueprints.users import bp as users_bp
from .blueprints.api import bp as api_bp
from .blueprints.main import bp as main_bp

login_manager = LoginManager()
# Schema-versioning helper. Tracks every model change as a script in
# migrations/versions/. Teammates run `flask db upgrade` after pulling
# instead of deleting their local DB.
migrate = Migrate()
# CSRF protection on all POST/PUT/PATCH/DELETE — applies to both WTForms-
# rendered forms (auto-included via {{ form.hidden_tag() }}) and JSON-API
# calls (header X-CSRFToken, supplied by the csrfFetch wrapper in base.html).
csrf = CSRFProtect()
 
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Per-endpoint friendly labels for the unauthorized flash — names the action
# the guest tried to take so the prompt reads naturally instead of generic.
LOGIN_REQUIRED_ACTIONS = {
    'reports.reports_page':            'create a report',
    'reports.edit_report_page':        'edit a report',
    'users.profile_page':              'view your profile',
    'users.user_profile_page':         "view this user's profile",
    'users.search_users_page':         'search for users',
    'auth.settings_page':              'open settings',
    'auth.profile_edit_page':          'edit your profile',
    'main.favourites_page':            'view your saved locations',
    'main.favourite_reports_page':     'view your saved reports',
    'main.messages_page':              'open your messages',
}


# Custom unauthorized handler — guests clicking a @login_required link get a
# flash with an inline "log in" link and stay on the page they came from,
# instead of being yanked off to /login (the default Flask-Login behaviour).
# AJAX / JSON callers still get a clean 401 so frontend code can react.
@login_manager.unauthorized_handler
def _unauthorized():
    wants_json = (
        request.is_json
        or 'application/json' in (request.headers.get('Accept') or '')
        or request.path.startswith('/api/')
    )
    if wants_json:
        return jsonify({'error': 'Login required.'}), 401
    action = LOGIN_REQUIRED_ACTIONS.get(request.endpoint, 'do that')
    flash(
        Markup(f'<a href="{url_for("auth.login")}" class="alert-link">Log in</a> to {action}.'),
        'warning'
    )
    return redirect(request.referrer or url_for('main.home_intro'))


def create_app(test_config=None):
    app = Flask(__name__)

    # All config lives in app/config.py — env vars feed into it from .env.
    app.config.from_object(Config)

    # Test hook — pytest passes an override dict to swap the DB to in-memory
    # and disable CSRF. Skips the dev-data seeders below.
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)
 
    # Register the five route groups. Each blueprint owns one slice of
    # the URL map (top-level pages, auth flows, report pages, user /
    # profile pages, JSON API).
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(api_bp)

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403
 
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404
 
    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    return app

