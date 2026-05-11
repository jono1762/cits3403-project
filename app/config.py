# app.config values — kept out of __init__.py so create_app stays small
import os
 
 
class Config:
    # Path of this file's directory — same as Flask's app.root_path since
    # this module lives at the root of the app/ package.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
 
    SECRET_KEY = 'dev-secret-key-change-later'
 
    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
 
    # Media upload config — files saved to app/static/uploads/, served as /static/uploads/<filename>
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024   # 20 MB max per request
 
 