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

    reports = db.relationship('Report', backref='author', lazy=True)
    verifications = db.relationship('Verification', backref='verifier', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ---- Aggregated reputation stats (computed live from related rows) ----
    # These run sums in Python over the `reports` relationship. Fine at the
    # current data scale; if the app grows, swap each one for a single SQL
    # aggregate against the verifications table.

    @property
    def verifications_received(self):
        """How many ✓ verify votes this user's reports have collected in total."""
        return sum(r.verify_count for r in self.reports)

    @property
    def disputes_received(self):
        """How many ✗ dispute votes this user's reports have collected in total."""
        return sum(r.dispute_count for r in self.reports)

    @property
    def trust_score(self):
        """Credibility percentage — share of incoming votes that are ✓ Verify.
        Returns None when the user has received no votes yet, so the UI can
        show "—" instead of a misleading 0%."""
        total = self.verifications_received + self.disputes_received
        if total == 0:
            return None
        return round(self.verifications_received / total * 100)

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

    @property
    def verify_count(self):
        return sum(1 for v in self.verifications if v.status == 'verify')

    @property
    def dispute_count(self):
        return sum(1 for v in self.verifications if v.status == 'dispute')

    def vote_by(self, user):
        """Return the given user's vote on this report — 'verify', 'dispute', or None."""
        if not getattr(user, 'is_authenticated', False):
            return None
        for v in self.verifications:
            if v.user_id == user.id:
                return v.status
        return None

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
    # 'verify' = user confirms the report is accurate; 'dispute' = user denies it.
    # Each (user, report) pair has at most one row — flipping vote updates this.
    status = db.Column(db.String(10), nullable=False, default='verify')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)