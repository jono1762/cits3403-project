"""Auth + account-deletion tests — signup validation and the destructive
delete-account flow that anonymises reports rather than wiping them."""

from app.models import User, Report, Category, City


def test_signup_duplicate_username_rejected(client, make_user, db):
    """Second signup with an existing username stays on the signup page
    and shows a form-level error — never creates a duplicate row."""
    make_user('alice')   # alice already exists in DB
    response = client.post('/signup', data={
        'username': 'alice',
        'email': 'someone-else@test.com',
        'password': 'Test@1234',
        'confirm_password': 'Test@1234',
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Username already taken' in response.data
    # exactly one alice still in the DB — no duplicate slipped through
    assert User.query.filter_by(username='alice').count() == 1


def test_delete_account_wrong_password_rejected(client, make_user, login, db):
    """POSTing /settings/delete with a bad password keeps the user intact —
    the password check is the final safety gate on account destruction."""
    make_user('alice')
    login('alice')

    response = client.post(
        '/settings/delete',
        data={'password': 'wrong-password'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert User.query.filter_by(username='alice').first() is not None


def test_delete_account_anonymises_reports(client, make_user, login, db):
    """Correct password deletes the user but KEEPS their reports — the
    author column is nulled so the byline renders as 'deleted_user' and
    comment threads stay readable for other users."""
    alice = make_user('alice')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()
    report = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='alice-report',
    )
    db.session.add(report)
    db.session.commit()
    report_id = report.id

    login('alice')
    response = client.post(
        '/settings/delete',
        data={'password': 'Test@1234'},
        follow_redirects=True,
    )
    assert response.status_code == 200

    assert User.query.filter_by(username='alice').first() is None
    surviving = db.session.get(Report, report_id)
    assert surviving is not None         # report still exists
    assert surviving.user_id is None     # author anonymised
