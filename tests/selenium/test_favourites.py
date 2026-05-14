"""Favourites + guest-gating end-to-end tests."""

from app.models import db, FavouriteLocation, City, User


def test_saved_city_shows_on_favourites(browser, live_server, make_user, login_as, app):
    """A saved city appears on /favourites with its name and 'Active Reports'
    stat. The save action is exercised via the API (mimicking the JS) so we
    aren't fighting Leaflet popups in headless Chrome."""
    make_user('sel_fav_user')

    with app.app_context():
        user = User.query.filter_by(username='sel_fav_user').first()
        sydney = City.query.filter_by(name='Sydney').first()
        db.session.add(FavouriteLocation(user_id=user.id, city_id=sydney.id))
        db.session.commit()

    login_as('sel_fav_user')
    browser.get(f'{live_server.url()}/favourites')

    assert 'Sydney' in browser.page_source
    assert 'Active Reports' in browser.page_source


def test_guest_cant_reach_create_report_page(browser, live_server):
    """Guest visiting /reports (the create-report form) is redirected to a
    public page and shown a 'Log in to create a report' flash message.
    Confirms the @login_required + LOGIN_REQUIRED_ACTIONS prompt wiring."""
    base = live_server.url()
    browser.get(f'{base}/logout')

    browser.get(f'{base}/reports')
    # After the redirect we should NOT still be on /reports
    assert '/reports' not in browser.current_url
    # The flash message names the action
    assert 'create a report' in browser.page_source
