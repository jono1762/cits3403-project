import os
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import inspect
from .models import db, User, Category, State, City, Report, Comment
from .blueprints.auth import bp as auth_bp
from .blueprints.reports import bp as reports_bp
from .blueprints.users import bp as users_bp
from .blueprints.api import bp as api_bp
 
login_manager = LoginManager()
# Schema-versioning helper. Tracks every model change as a script in
# migrations/versions/. Teammates run `flask db upgrade` after pulling
# instead of deleting their local DB.
migrate = Migrate()
 
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
 
# the 5 report categories + marker colour for each
DEFAULT_CATEGORIES = [
    ('Weather',   '#3498db'),
    ('Noisiness', '#9b59b6'),
    ('Hazards',   '#e67e22'),
    ('Traffic',   '#f1c40f'),
    ('Emergency', '#e74c3c'),
]
 
# fill the categories table on first run so the Report form has valid Foreign Keys
def seed_categories():
    if Category.query.first() is not None:
        return  # already seeded, skip
    for name, color in DEFAULT_CATEGORIES:
        db.session.add(Category(name=name, marker_color=color))
    db.session.commit()
 
# 8 AU states/territories + a handful of major cities per state
DEFAULT_LOCATIONS = {
    ('NSW', 'New South Wales'):       ['Sydney', 'Newcastle', 'Wollongong', 'Central Coast'],
    ('VIC', 'Victoria'):              ['Melbourne', 'Geelong', 'Ballarat'],
    ('QLD', 'Queensland'):            ['Brisbane', 'Gold Coast', 'Sunshine Coast', 'Cairns', 'Townsville'],
    ('WA',  'Western Australia'):     ['Perth', 'Mandurah', 'Bunbury'],
    ('SA',  'South Australia'):       ['Adelaide', 'Mount Gambier'],
    ('TAS', 'Tasmania'):              ['Hobart', 'Launceston'],
    ('ACT', 'Australian Capital Territory'): ['Canberra'],
    ('NT',  'Northern Territory'):    ['Darwin', 'Alice Springs'],
}
 
# fill states + cities tables so the Location dropdowns have options
def seed_locations():
    if State.query.first() is not None:
        return  # already seeded, skip
    for (code, name), city_names in DEFAULT_LOCATIONS.items():
        state = State(code=code, name=name)
        db.session.add(state)
        db.session.flush()  # get state.id before adding cities
        for city_name in city_names:
            db.session.add(City(name=city_name, state_id=state.id))
    db.session.commit()
 
# a few arbitrary test users so the search feature has something to find
# password for all of them is 'Test@1234' — move this to a real fixture later
DEFAULT_TEST_USERS = [
    ('alice',   'alice@test.com'),
    ('bob',     'bob@test.com'),
    ('charlie', 'charlie@test.com'),
]
 
# one sample report per test user so viewing their profile actually shows content
# (city_name, category_name, description)
DEFAULT_TEST_REPORTS = [
    ('alice',   'Sydney',   'Weather', 'Heavy rain at George St, watch out for puddles.'),
    ('bob',     'Melbourne','Traffic', 'Tram line blocked near Flinders Station.'),
    ('charlie', 'Perth',    'Hazards', 'Fallen branch on the Kings Park path.'),
]
 
def seed_test_users_and_reports():
    # add missing test users; skip any that already exist
    for username, email in DEFAULT_TEST_USERS:
        if User.query.filter_by(username=username).first():
            continue
        u = User(username=username, email=email)
        u.set_password('Test@1234')
        db.session.add(u)
    db.session.commit()
 
    # add sample reports — only if the user has none, to stay idempotent
    for username, city_name, category_name, description in DEFAULT_TEST_REPORTS:
        user = User.query.filter_by(username=username).first()
        if not user or user.reports:
            continue
        city = City.query.filter_by(name=city_name).first()
        category = Category.query.filter_by(name=category_name).first()
        if not (city and category):
            continue
        db.session.add(Report(
            user_id=user.id,
            city_id=city.id,
            category_id=category.id,
            description=description,
        ))
    db.session.commit()
 
 
# A set of canned comments from the test users. Used to seed any report that
# currently has zero comments, so the dev can see (and click) the verify /
# dispute pills on someone else's comment without juggling logins.
DEFAULT_TEST_COMMENTS = [
    ('alice',   "Just walked past, can confirm — situation matches the report."),
    ('bob',     "Looks different from where I'm standing — might be outdated?"),
    ('charlie', "Thanks for the heads-up, useful info."),
]
 
def seed_test_comments():
    """Drop a few dummy comments onto any report that has no comments yet.
    Idempotent: reports that already have any comment are left untouched, so
    real conversations are never overwritten on app restart."""
    for report in Report.query.all():
        # skip reports that already have any comments — keeps real threads intact
        if Comment.query.filter_by(report_id=report.id).first():
            continue
        for username, body in DEFAULT_TEST_COMMENTS:
            commenter = User.query.filter_by(username=username).first()
            # don't have a user comment on their own report
            if not commenter or commenter.id == report.user_id:
                continue
            db.session.add(Comment(
                report_id=report.id,
                user_id=commenter.id,
                body=body,
            ))
    db.session.commit()
 
def create_app():
    app = Flask(__name__)
 
    app.config['SECRET_KEY'] = 'dev-secret-key-change-later'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
 
    # media upload config
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024   # 20 MB max per request
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
 
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
 
    # Register the four route groups. Each blueprint owns one slice of
    # the URL map (auth flows, report pages, user / profile pages, JSON API).
    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(api_bp)
 
    with app.app_context():
        from . import routes
        # Schema is owned by Flask-Migrate — fresh checkouts must run
        # `flask db upgrade` once before booting. The seeders below skip
        # silently if (a) the tables don't exist yet, or (b) the schema
        # has drifted ahead of the model (which happens during
        # `flask db migrate` after a model change but before upgrade).
        if inspect(db.engine).has_table('categories'):
            try:
                seed_categories()              # default categories
                seed_locations()               # states + cities
                seed_test_users_and_reports()  # arbitrary users so search has something to find
                seed_test_comments()           # canned comments on any report missing them
            except Exception:
                # schema not in sync — user needs to run `flask db upgrade`
                db.session.rollback()
 
    return app
 
 