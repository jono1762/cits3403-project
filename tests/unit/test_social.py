"""Social-graph tests — self-follow rejection, block-prevents-message,
and the From-Following feed only showing posts from followed users."""

from app.models import Follow, BlockedUser, Report, Category, City


def test_cant_follow_self(client, make_user, login):
    """POST /api/follow/<own_id> returns 400 and creates no Follow row.
    A follower_id == followed_id edge would be a degenerate self-loop."""
    alice = make_user('alice')
    login('alice')

    response = client.post(f'/api/follow/{alice.id}', json={})
    assert response.status_code == 400
    assert Follow.query.filter_by(follower_id=alice.id, followed_id=alice.id).count() == 0


def test_blocked_user_cant_message(client, make_user, login, db):
    """If A has blocked B in BlockedUser, B's POST to /api/conversations/A/messages
    returns 403 — the chat block is enforced on send, not on read."""
    alice = make_user('alice')
    bob = make_user('bob')
    db.session.add(BlockedUser(blocker_id=alice.id, blocked_id=bob.id))
    db.session.commit()

    login('bob')
    response = client.post(
        f'/api/conversations/{alice.id}/messages',
        json={'body': 'hello?'},
    )
    assert response.status_code == 403


def test_following_feed_excludes_strangers(client, make_user, login, db):
    """/listing/following shows only reports from users the viewer follows.
    A creates a report, C creates a report, viewer (B) follows A but not C
    → B sees A's report but not C's on the From-Following feed."""
    alice = make_user('alice')
    bob = make_user('bob')
    charlie = make_user('charlie')

    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()

    alice_report = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='alice-only-marker-xyz',
    )
    charlie_report = Report(
        user_id=charlie.id, city_id=sydney.id, category_id=weather.id,
        description='charlie-only-marker-abc',
    )
    db.session.add_all([alice_report, charlie_report])
    db.session.add(Follow(follower_id=bob.id, followed_id=alice.id))
    db.session.commit()

    login('bob')
    response = client.get('/listing/following')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'alice-only-marker-xyz' in body
    assert 'charlie-only-marker-abc' not in body
