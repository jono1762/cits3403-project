from flask import Flask
from .models import db

def create_app():
    app = Flask(__name__)
    
    # 1. The Correct URI! 
    # Flask automatically knows to put this in your 'instance' folder.
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # 2. Initialize the database with the app
    db.init_app(app)
    
    # 3. Import routes (We do this down here to avoid circular imports)
    with app.app_context():
        from . import routes
        
        # This will create your tables in instance/app.db if they don't exist
        db.create_all() 
        
    return app