"""Pytest fixtures shared across the suite.

Every test gets a fresh Flask app bound to an in-memory SQLite DB so tests
don't leak state into each other or touch the dev DB. Reference data
(categories / states / cities) is seeded once per test; users and reports
are created inline by each test that needs them.
"""

import tempfile

import pytest

from app import create_app, DEFAULT_CATEGORIES, DEFAULT_LOCATIONS
from app.models import db as _db, Category, State, City, User


@pytest.fixture()
def app():
    """Fresh app with an in-memory SQLite DB and seeded reference data."""
    upload_dir = tempfile.mkdtemp(prefix='test_uploads_')
    app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'UPLOAD_FOLDER': upload_dir,
    })

    with app.app_context():
        _db.create_all()
        _seed_reference_data()
        yield app
        _db.session.remove()
        _db.drop_all()


def _seed_reference_data():
    """Minimal seed — just the lookup tables the FK constraints need.
    Tests that need users / reports create them inline."""
    for name, color in DEFAULT_CATEGORIES:
        _db.session.add(Category(name=name, marker_color=color))
    for (code, name), city_names in DEFAULT_LOCATIONS.items():
        state = State(code=code, name=name)
        _db.session.add(state)
        _db.session.flush()
        for cn in city_names:
            _db.session.add(City(name=cn, state_id=state.id))
    _db.session.commit()


@pytest.fixture()
def client(app):
    """Flask test client for making HTTP requests without starting a server."""
    return app.test_client()


@pytest.fixture()
def db(app):
    """Direct DB session for tests that insert / query rows."""
    return _db


@pytest.fixture()
def make_user(app):
    """Factory: make_user('alice') → committed User with password 'Test@1234'."""
    def _make(username, email=None, password='Test@1234'):
        u = User(username=username, email=email or f'{username}@test.com')
        u.set_password(password)
        _db.session.add(u)
        _db.session.commit()
        return u
    return _make


@pytest.fixture()
def login(client):
    """Log a user in via the test client. Returns the response."""
    def _login(username, password='Test@1234'):
        return client.post(
            '/login',
            data={'username': username, 'password': password},
            follow_redirects=True,
        )
    return _login
