import os
from flask import Flask
from flask_login import LoginManager
from .models import db, User, Category, State, Suburb, Report

login_manager = LoginManager()

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

# 8 AU states/territories + a handful of major suburbs per state
# team can add more suburbs later — this is enough to demo the dropdown
DEFAULT_LOCATIONS = {
    ('NSW', 'New South Wales'):       ['Sydney', 'Newcastle', 'Wollongong', 'Central Coast'],
    ('VIC', 'Victoria'):              ['Melbourne', 'Geelong', 'Ballarat'],
    ('QLD', 'Queensland'):            ['Brisbane', 'Gold Coast', 'Sunshine Coast', 'Cairns', 'Townsville'],
    ('WA',  'Western Australia'):     ['Perth', 'Fremantle', 'Mandurah', 'Bunbury'],
    ('SA',  'South Australia'):       ['Adelaide', 'Mount Gambier'],
    ('TAS', 'Tasmania'):              ['Hobart', 'Launceston'],
    ('ACT', 'Australian Capital Territory'): ['Canberra'],
    ('NT',  'Northern Territory'):    ['Darwin', 'Alice Springs'],
}

# fill states + suburbs tables so the Location dropdowns have options
def seed_locations():
    if State.query.first() is not None:
        return  # already seeded, skip
    for (code, name), suburb_names in DEFAULT_LOCATIONS.items():
        state = State(code=code, name=name)
        db.session.add(state)
        db.session.flush()  # get state.id before adding suburbs
        for suburb_name in suburb_names:
            db.session.add(Suburb(name=suburb_name, state_id=state.id))
    db.session.commit()

# a few arbitrary test users so the search feature has something to find
# password for all of them is 'Test@1234' — move this to a real fixture later
DEFAULT_TEST_USERS = [
    ('alice',   'alice@test.com'),
    ('bob',     'bob@test.com'),
    ('charlie', 'charlie@test.com'),
]

# one sample report per test user so viewing their profile actually shows content
# (suburb_name, category_name, description)
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
    for username, suburb_name, category_name, description in DEFAULT_TEST_REPORTS:
        user = User.query.filter_by(username=username).first()
        if not user or user.reports:
            continue
        suburb = Suburb.query.filter_by(name=suburb_name).first()
        category = Category.query.filter_by(name=category_name).first()
        if not (suburb and category):
            continue
        db.session.add(Report(
            user_id=user.id,
            suburb_id=suburb.id,
            category_id=category.id,
            description=description,
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
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    with app.app_context():
        from . import routes
        db.create_all()
        seed_categories()  # make sure default categories exist
        seed_locations()   # make sure states + suburbs exist
        seed_test_users_and_reports()  # arbitrary users so search has something to find

    return app