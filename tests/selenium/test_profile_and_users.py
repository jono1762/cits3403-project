"""Profile-page + user-search end-to-end tests."""

from selenium.webdriver.common.by import By

from app.models import db, Report, Category, City, User


def _make_report(app, username, description='selenium test report'):
    """Create a report for the user with this username — does everything in
    one app context so detached-instance issues don't bite."""
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


def test_my_reports_visible_on_profile(browser, live_server, make_user, login_as, app):
    """User who created reports sees them under 'Recent reports' on /profile."""
    make_user('sel_profile_reports')
    _make_report(app, 'sel_profile_reports', description='sel-unique-marker-zzz')

    login_as('sel_profile_reports')
    browser.get(f'{live_server.url()}/profile')

    assert 'sel-unique-marker-zzz' in browser.page_source


def test_edit_profile_bio(browser, live_server, make_user, login_as):
    """User edits their bio via /profile/edit, the new bio appears on /profile."""
    make_user('sel_bio_user')
    login_as('sel_bio_user')

    base = live_server.url()
    browser.get(f'{base}/profile/edit')

    textarea = browser.find_element(By.ID, 'profile-edit-bio')
    textarea.clear()
    textarea.send_keys('Hello from Selenium — unique-bio-marker-xyz.')
    browser.find_element(By.CSS_SELECTOR, 'form button[type="submit"], form input[type="submit"]').click()

    browser.get(f'{base}/profile')
    assert 'unique-bio-marker-xyz' in browser.page_source


def test_search_users(browser, live_server, make_user, login_as):
    """Search page returns the matching user when their username substring is queried."""
    make_user('sel_searcher')
    make_user('sel_findable_target')
    login_as('sel_searcher')

    browser.get(f'{live_server.url()}/search?q=findable_target')
    assert 'sel_findable_target' in browser.page_source
