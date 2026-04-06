from flask import Flask
from .models import db

def create_app():
    app = Flask(__name__)

    # set up the database
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    # import routes inside app context to avoid circular imports
    with app.app_context():
        from . import routes
        db.create_all()

    return app