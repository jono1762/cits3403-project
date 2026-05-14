"""Report-create and report-edit end-to-end tests."""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.models import db, Report, Category, City, User


def _make_report(app, username, description):
    """Helper — insert a report straight into the DB so the edit test has
    something to edit. Returns the report id."""
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
        return r.id


def test_create_report_with_image(browser, live_server, make_user, login_as, tiny_png_path):
    """Fill the create-report form end-to-end including a PNG attachment.
    Verifies (1) the report submits with text + image, (2) the user is
    redirected to the single-report view, (3) the description renders, and
    (4) the page references the uploaded media (an <img> from /static/uploads/)."""
    make_user('sel_report_creator')
    login_as('sel_report_creator')

    base = live_server.url()
    browser.get(f'{base}/reports')

    # state — pick NSW, then wait for the city dropdown to be enabled
    Select(browser.find_element(By.ID, 'state_id')).select_by_visible_text('New South Wales')
    WebDriverWait(browser, 5).until(
        lambda d: not d.find_element(By.ID, 'city_id').get_attribute('disabled')
    )
    Select(browser.find_element(By.ID, 'city_id')).select_by_visible_text('Sydney')
    Select(browser.find_element(By.ID, 'category_id')).select_by_visible_text('Weather')
    browser.find_element(By.ID, 'description').send_keys('sel-create-marker-aaa')
    # attach the tiny PNG — file input is hidden but send_keys still works on it
    browser.find_element(By.ID, 'media').send_keys(tiny_png_path)

    old_url = browser.current_url
    btn = browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
    browser.execute_script("arguments[0].click();", btn)
    # JS submits via fetch and then navigates — wait for URL to leave /reports
    WebDriverWait(browser, 5).until(lambda d: d.current_url != old_url)

    assert 'sel-create-marker-aaa' in browser.page_source
    # uploaded media renders as /static/uploads/<uuid>.png on the report view
    assert '/static/uploads/' in browser.page_source


def test_edit_own_report(browser, live_server, make_user, login_as, app):
    """Editing the description of an existing report updates it. The edit
    form is a normal POST (not AJAX) so we just submit and verify."""
    make_user('sel_report_editor')
    report_id = _make_report(app, 'sel_report_editor', description='original-marker-111')
    login_as('sel_report_editor')

    base = live_server.url()
    browser.get(f'{base}/reports/{report_id}/edit')

    desc = browser.find_element(By.ID, 'description')
    desc.clear()
    desc.send_keys('edited-marker-222')
    btn = browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
    browser.execute_script("arguments[0].click();", btn)

    # post-edit redirect; give it a moment then check the user's profile lists it
    time.sleep(0.5)
    browser.get(f'{base}/profile')
    assert 'edited-marker-222' in browser.page_source
    assert 'original-marker-111' not in browser.page_source
