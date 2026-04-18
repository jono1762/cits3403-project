from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    trust_score = db.Column(db.Integer, default=0)

    reports = db.relationship('Report', backref='author', lazy=True)
    verifications = db.relationship('Verification', backref='verifier', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    marker_color = db.Column(db.String(7), nullable=False)

    reports = db.relationship('Report', backref='category', lazy=True)

class State(db.Model):
    __tablename__ = 'states'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(3), unique=True, nullable=False)   # e.g. NSW, VIC, WA
    name = db.Column(db.String(50), nullable=False)               # e.g. New South Wales

    suburbs = db.relationship('Suburb', backref='state', lazy=True)

class Suburb(db.Model):
    __tablename__ = 'suburbs'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    state_id = db.Column(db.Integer, db.ForeignKey('states.id'), nullable=False)

    reports = db.relationship('Report', backref='suburb', lazy=True)

class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    suburb_id = db.Column(db.Integer, db.ForeignKey('suburbs.id'), nullable=False)
    # optional free-text for extra detail like street name or landmark
    address = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    verifications = db.relationship('Verification', backref='report', lazy=True)
    # cascade so deleting a report also deletes its attached images/videos
    media = db.relationship('ReportMedia', backref='report', lazy=True, cascade='all, delete-orphan')

class ReportMedia(db.Model):
    __tablename__ = 'report_media'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    filename = db.Column(db.String(64), nullable=False)        # stored UUID-based name on disk
    original_name = db.Column(db.String(255), nullable=False)  # what the user called it
    media_type = db.Column(db.String(10), nullable=False)      # 'image' or 'video'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class Verification(db.Model):
    __tablename__ = 'verifications'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)