"""Model-level tests — password hashing, follow graph, expiry filtering,
and the is_expiring_soon banner trigger."""

from datetime import datetime, timedelta

from app.models import Follow, Report, Category, City
from app.blueprints.reports import _active_reports_q


def test_password_hash_roundtrip(make_user, db):
    """set_password stores a salted hash; check_password verifies the right
    password and rejects wrong ones. The stored hash is NEVER the plaintext."""
    user = make_user('alice')
    assert user.password_hash != 'Test@1234'   # not stored in plaintext
    assert user.check_password('Test@1234') is True
    assert user.check_password('wrong-password') is False


def test_follow_relationship(make_user, db):
    """A follows B → A.following_count == 1, B.follower_count == 1.
    Locks down the directed-edge follow model."""
    alice = make_user('alice')
    bob = make_user('bob')
    db.session.add(Follow(follower_id=alice.id, followed_id=bob.id))
    db.session.commit()

    assert alice.following_count == 1
    assert alice.follower_count == 0
    assert bob.follower_count == 1
    assert bob.following_count == 0


def test_report_expiry_filtered(make_user, db):
    """_active_reports_q() excludes reports whose expires_at is in the past.
    This filter is the gatekeeper for everything users see in the UI."""
    alice = make_user('alice')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()

    active = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='active', expires_at=datetime.utcnow() + timedelta(days=3),
    )
    expired = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='expired', expires_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.session.add_all([active, expired])
    db.session.commit()

    ids = {r.id for r in _active_reports_q().all()}
    assert active.id in ids
    assert expired.id not in ids


def test_is_expiring_soon_within_24h(make_user, db):
    """Report.is_expiring_soon is True only when expiry is in the next 24h
    AND the report hasn't already expired. Drives the orange banner."""
    alice = make_user('alice')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()

    soon = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='soon', expires_at=datetime.utcnow() + timedelta(hours=5),
    )
    far = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='far', expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    expired = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='expired', expires_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.session.add_all([soon, far, expired])
    db.session.commit()

    assert soon.is_expiring_soon is True
    assert far.is_expiring_soon is False
    assert expired.is_expiring_soon is False
