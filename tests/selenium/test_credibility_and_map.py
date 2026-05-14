"""Live AJAX updates: voting on a report increments the count without a
page reload, and the map renders city markers a user can click."""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.models import db, Report, Category, City, User
from app.blueprints.reports import _encode_report_id


def _make_report_and_token(app, username, description='credibility report'):
    """Insert a report and return its opaque URL token — that's how
    /reports/<token> is keyed."""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        sydney = City.query.filter_by(name='Sydney').first()
        weather = Category.query.filter_by(name='Weather').first()
        r = Report(
            user_id=user.id, city_id=sydney.id, category_id=weather.id,
            description=description,
        )
        db.session.add(r)
        db.session.commit()
        return _encode_report_id(r.id)


def test_verify_increments_count_without_reload(browser, live_server, make_user, login_as, app):
    """Click ✓ Verify on someone else's report → the count in the same
    button increments via AJAX (no page reload). Tests that the JSON-API
    response is wired into the live UI."""
    make_user('sel_credibility_author')
    make_user('sel_credibility_voter')
    token = _make_report_and_token(app, 'sel_credibility_author')

    login_as('sel_credibility_voter')
    browser.get(f'{live_server.url()}/reports/{token}')

    btn = WebDriverWait(browser, 5).until(
        lambda d: d.find_element(By.CSS_SELECTOR, '.vote-btn.vote-verify')
    )
    before = btn.find_element(By.CSS_SELECTOR, '.vote-count').text.strip()
    browser.execute_script("arguments[0].click();", btn)

    # AJAX swaps the count text — wait until it's different
    WebDriverWait(browser, 5).until(
        lambda d: d.find_element(
            By.CSS_SELECTOR, '.vote-btn.vote-verify .vote-count'
        ).text.strip() != before
    )
    after = browser.find_element(
        By.CSS_SELECTOR, '.vote-btn.vote-verify .vote-count'
    ).text.strip()
    assert int(after) == int(before) + 1


def test_map_marker_popup_shows_three_actions(browser, live_server, make_user, login_as):
    """Clicking a city marker opens a Leaflet popup with three actions —
    Save location, View reports, View weather. Each is the real entry point
    a user uses to interact with that city."""
    make_user('sel_map_user')
    login_as('sel_map_user')

    browser.get(f'{live_server.url()}/map')
    # Leaflet initialises asynchronously — wait for the marker layer to populate
    WebDriverWait(browser, 10).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, '.leaflet-marker-icon')) > 0
    )
    markers = browser.find_elements(By.CSS_SELECTOR, '.leaflet-marker-icon')
    assert len(markers) > 5    # seeded 23 cities; expect plenty of markers

    # JS-click the first marker (headless Chrome won't always honour a real
    # click on a Leaflet icon, but firing the click event directly does)
    browser.execute_script("arguments[0].click();", markers[0])

    # Wait for the popup to render, then assert each of the three actions
    WebDriverWait(browser, 5).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, '.leaflet-popup-content')
    )
    popup = browser.find_element(By.CSS_SELECTOR, '.leaflet-popup-content')

    assert popup.find_element(By.CSS_SELECTOR, '.popup-save-location') is not None
    actions = popup.find_elements(By.CSS_SELECTOR, '.popup-action')
    action_texts = ' '.join(a.text for a in actions)
    assert 'View reports' in action_texts
    assert 'View weather' in action_texts
