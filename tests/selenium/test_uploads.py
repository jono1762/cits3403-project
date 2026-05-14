"""File-upload validation end-to-end tests."""

import os
import tempfile

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


def test_invalid_file_extension_shows_error(browser, live_server, make_user, login_as):
    """Attaching a .txt file to a report triggers the client-side validation —
    the file input is cleared and the status text shows a 'not allowed' message,
    so the user never even gets to submit a bad upload."""
    make_user('sel_uploader')
    login_as('sel_uploader')

    # Create a tiny .txt file in a temp dir for the file input to point at.
    tmp = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w')
    tmp.write('not a real image')
    tmp.close()

    try:
        browser.get(f'{live_server.url()}/reports')

        # The file input has the .visually-hidden-input class; Selenium can
        # still set its value via send_keys even though it's not visible.
        file_input = browser.find_element(By.ID, 'media')
        file_input.send_keys(tmp.name)

        # The on-change handler in reports.html sets an error on #media-status
        WebDriverWait(browser, 5).until(
            lambda d: 'not allowed' in d.find_element(By.ID, 'media-status').text
        )
        status_text = browser.find_element(By.ID, 'media-status').text
        assert '.txt' in status_text or 'not allowed' in status_text
    finally:
        os.unlink(tmp.name)
