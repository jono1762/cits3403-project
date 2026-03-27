from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Just instantiate SQLAlchemy, don't pass 'app' yet
db = SQLAlchemy()

# 1. Users Table
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    trust_score = db.Column(db.Integer, default=0)
    
    # Relationships to easily fetch a user's reports and verifications
    reports = db.relationship('Report', backref='author', lazy=True)
    verifications = db.relationship('Verification', backref='verifier', lazy=True)

# 2. Categories Table
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    marker_color = db.Column(db.String(7), nullable=False) # e.g., '#FF0000'
    
    reports = db.relationship('Report', backref='category', lazy=True)

# 3. Reports Table (The Core)
class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    verifications = db.relationship('Verification', backref='report', lazy=True)

# 4. Verifications Table (The "Like" Button)
class Verification(db.Model):
    __tablename__ = 'verifications'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

if __name__ == '__main__':
    # Creates the app.db file and all tables if they don't exist
    with app.app_context():
        db.create_all()
        print("Database tables created successfully!")
    app.run(debug=True)