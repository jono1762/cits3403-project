"""Business-logic tests — trending excludes expired reports, the trust_score
ratio is computed correctly, and vote toggling switches verify ↔ dispute
without leaving stale rows behind."""

from datetime import datetime, timedelta

from app.models import Report, Verification, Category, City, User
from app.blueprints.reports import _trending_report_ids


def test_expired_report_not_in_trending(make_user, db):
    """A report past its expires_at is filtered out of the trending top-N
    even if it has a high score — listing query and trending query agree
    on the active-only filter so trending never picks an invisible report."""
    alice = make_user('alice')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()

    expired = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='expired-but-loved',
        expires_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.session.add(expired)
    db.session.commit()

    # pile on verifications — the score formula would otherwise rank it top
    for i in range(20):
        voter = User(username=f'voter{i}', email=f'voter{i}@test.com')
        voter.set_password('Test@1234')
        db.session.add(voter)
        db.session.flush()
        db.session.add(Verification(
            report_id=expired.id, user_id=voter.id, status='verify',
        ))
    db.session.commit()

    assert expired.id not in _trending_report_ids()


def test_trust_score_calculation(make_user, db):
    """trust_score = verifies / (verifies + disputes) × 100, rounded. With
    3 verifies and 1 dispute on the author's reports, the credibility comes
    out to 75. Returns None when no votes exist so the UI can show '—'."""
    alice = make_user('alice')
    bob = make_user('bob')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()

    report = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='alice-report',
    )
    db.session.add(report)
    db.session.flush()

    # need real voter user ids — Verification.user_id is a FK
    voters = [User(username=f'v{i}', email=f'v{i}@t.com') for i in range(4)]
    for v in voters:
        v.set_password('x')
    db.session.add_all(voters)
    db.session.flush()

    db.session.add_all([
        Verification(report_id=report.id, user_id=voters[0].id, status='verify'),
        Verification(report_id=report.id, user_id=voters[1].id, status='verify'),
        Verification(report_id=report.id, user_id=voters[2].id, status='verify'),
        Verification(report_id=report.id, user_id=voters[3].id, status='dispute'),
    ])
    db.session.commit()

    assert alice.trust_score == 75
    assert bob.trust_score is None   # no votes received


def test_vote_switch_verify_to_dispute(client, make_user, login, db):
    """Posting verify then dispute on the same report leaves exactly one
    Verification row with status='dispute' — the API toggles in place
    rather than appending a second row."""
    alice = make_user('alice')
    bob = make_user('bob')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()
    report = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='alice-report',
    )
    db.session.add(report)
    db.session.commit()

    login('bob')
    client.post(f'/api/reports/{report.id}/vote', json={'status': 'verify'})
    client.post(f'/api/reports/{report.id}/vote', json={'status': 'dispute'})

    rows = Verification.query.filter_by(report_id=report.id, user_id=bob.id).all()
    assert len(rows) == 1
    assert rows[0].status == 'dispute'
