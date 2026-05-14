"""End-to-end auth: signup auto-logs-in, log out then log in works."""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def _wait_for_url_change(browser, old_url, timeout=5):
    WebDriverWait(browser, timeout).until(lambda d: d.current_url != old_url)


def test_signup_auto_logs_in(browser, live_server):
    """Submitting the signup form creates the user AND logs them in — the
    redirect lands them on /intro with their username shown in the page."""
    base = live_server.url()
    browser.get(f'{base}/signup')

    browser.find_element(By.ID, 'username').send_keys('sel_signup_user')
    browser.find_element(By.ID, 'email').send_keys('sel_signup_user@test.com')
    browser.find_element(By.ID, 'password').send_keys('Test@1234')
    browser.find_element(By.ID, 'confirm_password').send_keys('Test@1234')

    old_url = browser.current_url
    browser.find_element(By.CSS_SELECTOR, 'input[type="submit"]').click()
    _wait_for_url_change(browser, old_url)

    assert '/intro' in browser.current_url
    assert 'sel_signup_user' in browser.page_source


def test_login_with_valid_credentials(browser, live_server, make_user):
    """An existing user can log in via the form and end up on /intro
    with their username rendered in the navbar/hero."""
    make_user('sel_login_user')

    base = live_server.url()
    # ensure not logged in
    browser.get(f'{base}/logout')

    browser.get(f'{base}/login')
    WebDriverWait(browser, 5).until(EC.element_to_be_clickable((By.ID, 'username')))
    browser.find_element(By.ID, 'username').send_keys('sel_login_user')
    browser.find_element(By.ID, 'password').send_keys('Test@1234')

    old_url = browser.current_url
    WebDriverWait(browser, 5).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="submit"]'))
    ).click()
    _wait_for_url_change(browser, old_url)

    assert '/intro' in browser.current_url
    assert 'sel_login_user' in browser.page_source
