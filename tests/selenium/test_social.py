"""Social-graph + chat end-to-end tests."""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from app.models import db, Follow, User


def test_follow_user_from_profile(browser, live_server, make_user, login_as, app):
    """Click the Follow button on another user's profile — the button label
    flips to 'Followed' AND a Follow row appears in the DB."""
    make_user('sel_follower')
    target = make_user('sel_follow_target')
    target_username = 'sel_follow_target'  # use string, not user object (detached)

    login_as('sel_follower')
    browser.get(f'{live_server.url()}/users/{target_username}')

    # button starts as "Follow"; click it
    btn = WebDriverWait(browser, 5).until(
        lambda d: d.find_element(By.ID, 'follow-btn')
    )
    assert btn.text.strip().startswith('Follow')
    browser.execute_script("arguments[0].click();", btn)

    # JS flips label to "Followed" — give it a moment then re-check
    WebDriverWait(browser, 5).until(
        lambda d: 'Followed' in d.find_element(By.ID, 'follow-btn').text
    )

    # And the Follow row exists in the DB
    with app.app_context():
        follower = User.query.filter_by(username='sel_follower').first()
        followed = User.query.filter_by(username='sel_follow_target').first()
        assert Follow.query.filter_by(
            follower_id=follower.id, followed_id=followed.id
        ).first() is not None


def test_send_chat_message_with_image(browser, live_server, make_user, login_as, app, tiny_png_path):
    """Send a chat message with both text + a PNG attachment via the composer.
    The text appears in the thread and the message references the uploaded
    file under /static/uploads/."""
    make_user('sel_chat_sender')
    make_user('sel_chat_recipient')

    # grab recipient id under app context (User is detached otherwise)
    with app.app_context():
        recipient_id = User.query.filter_by(username='sel_chat_recipient').first().id

    login_as('sel_chat_sender')
    browser.get(f'{live_server.url()}/messages?user={recipient_id}')

    # the thread loads via JS — wait for the composer to be ready
    composer = WebDriverWait(browser, 5).until(
        lambda d: d.find_element(By.ID, 'thread-input')
    )
    msg_text = 'sel-chat-marker-bbb'
    composer.send_keys(msg_text)
    # attach the PNG via the hidden file input
    browser.find_element(By.ID, 'thread-media').send_keys(tiny_png_path)

    send_btn = browser.find_element(By.ID, 'thread-send-btn')
    browser.execute_script("arguments[0].click();", send_btn)

    # wait for the message text to appear in the thread
    WebDriverWait(browser, 5).until(lambda d: msg_text in d.page_source)
    assert msg_text in browser.page_source
    assert '/static/uploads/' in browser.page_source
