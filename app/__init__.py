import os
from flask import Flask
from flask_login import LoginManager
from .models import db, User, Category, State, Suburb

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
        seed_locations()   # make sure states + cities exist

    return app