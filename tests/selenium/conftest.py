"""Selenium-test fixtures.

A real Chrome browser drives a real Flask server (pytest-flask's live_server
fixture). The server uses a file-based SQLite DB (NOT in-memory) so the
server's worker thread and the test thread see the same data. Each test
module gets a fresh DB.

Browser is session-scoped to avoid 3+ seconds of WebDriver startup per test.
"""

import os
import socket
import tempfile
import threading

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from werkzeug.serving import make_server

from app import create_app
from app.models import db as _db, Category, State, City, User
from seed.initial_data import DEFAULT_CATEGORIES, DEFAULT_LOCATIONS


@pytest.fixture(scope='session')
def browser():
    """One Chrome instance for the whole test session — re-used between tests."""
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--window-size=1280,900')
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)
    yield driver
    driver.quit()


@pytest.fixture(scope='session')
def app():
    """One Flask app shared across the whole Selenium session. File-based
    SQLite so the live-server thread and the test thread see the same data.
    Seeded with reference data only — each test creates its own users with
    unique names so tests don't collide on shared DB state."""
    db_fd, db_path = tempfile.mkstemp(suffix='.db', prefix='selenium_test_')
    os.close(db_fd)
    upload_dir = tempfile.mkdtemp(prefix='selenium_uploads_')

    app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'WTF_CSRF_ENABLED': False,
        'UPLOAD_FOLDER': upload_dir,
    })

    with app.app_context():
        _db.create_all()
        _seed_reference_data()

    yield app

    try:
        os.unlink(db_path)
    except OSError:
        pass


class _LiveServer:
    """Threading-based replacement for pytest-flask's live_server fixture,
    which uses multiprocessing and breaks on Windows + Python 3.13."""

    def __init__(self, app, port):
        self.app = app
        self.port = port
        self._server = make_server('127.0.0.1', port, app, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()

    def url(self):
        return f'http://127.0.0.1:{self.port}'


@pytest.fixture(scope='session')
def live_server(app):
    """Run the Flask app on a real port in a background thread so Selenium
    can drive it. Reuses one server for the whole session."""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()

    server = _LiveServer(app, port)
    server.start()
    yield server
    server.stop()


def _seed_reference_data():
    for name, color in DEFAULT_CATEGORIES:
        _db.session.add(Category(name=name, marker_color=color))
    for (code, name), city_names in DEFAULT_LOCATIONS.items():
        state = State(code=code, name=name)
        _db.session.add(state)
        _db.session.flush()
        for cn in city_names:
            _db.session.add(City(name=cn, state_id=state.id))
    _db.session.commit()


@pytest.fixture(scope='session')
def make_user(app):
    """Factory: make_user('alice') → committed User, password 'Test@1234'."""
    def _make(username, email=None, password='Test@1234'):
        with app.app_context():
            u = User(username=username, email=email or f'{username}@test.com')
            u.set_password(password)
            _db.session.add(u)
            _db.session.commit()
            return u
    return _make


# Smallest valid PNG — 8-byte signature + minimal IHDR + IDAT + IEND chunks.
# Big enough to pass _sniff_media_type's magic-byte check but barely 67 bytes
# on disk. Hex source: en.wikipedia.org/wiki/Portable_Network_Graphics#File_header
_TINY_PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n'
    b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
    b'\x00\x00\x00\x00IEND\xaeB`\x82'
)


@pytest.fixture()
def tiny_png_path():
    """Path to a tiny but VALID PNG on disk. Selenium can pass this to a
    file input via send_keys() and the magic-byte sniffer will accept it
    as a real image. File is cleaned up after the test."""
    fd, path = tempfile.mkstemp(suffix='.png', prefix='selenium_tiny_')
    with os.fdopen(fd, 'wb') as f:
        f.write(_TINY_PNG_BYTES)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture()
def login_as(browser, live_server):
    """Drive the browser through the login form. Logs out first to clear any
    leftover session from a previous test, then logs in as the named user."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    def _login(username, password='Test@1234'):
        base = live_server.url()
        browser.get(f'{base}/logout')
        browser.get(f'{base}/login')
        WebDriverWait(browser, 5).until(
            lambda d: d.find_element(By.ID, 'username')
        )
        browser.find_element(By.ID, 'username').send_keys(username)
        browser.find_element(By.ID, 'password').send_keys(password)
        old_url = browser.current_url
        browser.find_element(By.CSS_SELECTOR, 'input[type="submit"]').click()
        WebDriverWait(browser, 5).until(lambda d: d.current_url != old_url)

    return _login
