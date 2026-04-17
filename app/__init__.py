from flask import Flask
from flask_login import LoginManager
from .models import db, User, Category

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

def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = 'dev-secret-key-change-later'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    with app.app_context():
        from . import routes
        db.create_all()
        seed_categories()  # make sure default categories exist

    return app