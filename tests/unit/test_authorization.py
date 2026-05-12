"""Authorization tests — guests get 401, users can't delete other people's
comments, and authors can't vote on their own reports."""

from app.models import Report, Comment, Category, City


def test_guest_gets_401_on_api(client):
    """JSON API paths reject unauthenticated callers with 401 (not a
    303 redirect). The custom unauthorized handler in app/__init__.py
    keeps the API surface machine-friendly."""
    response = client.post('/api/follow/1', json={})
    assert response.status_code == 401
    assert response.get_json() == {'error': 'Login required.'}


def test_cant_delete_others_comment(client, make_user, login, db):
    """User B's DELETE on user A's comment returns 403 and the comment
    row stays in the DB — ownership check guards the delete endpoint."""
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
    comment = Comment(report_id=report.id, user_id=alice.id, body='alice comment')
    db.session.add(comment)
    db.session.commit()
    comment_id = comment.id

    login('bob')
    response = client.delete(f'/api/comments/{comment_id}')
    assert response.status_code == 403
    assert Comment.query.get(comment_id) is not None   # still in DB


def test_cant_vote_on_own_report(client, make_user, login, db):
    """Author voting on their own report returns 400 — prevents
    self-trumpeting credibility manipulation."""
    alice = make_user('alice')
    sydney = City.query.filter_by(name='Sydney').first()
    weather = Category.query.filter_by(name='Weather').first()
    report = Report(
        user_id=alice.id, city_id=sydney.id, category_id=weather.id,
        description='alice-report',
    )
    db.session.add(report)
    db.session.commit()

    login('alice')
    response = client.post(
        f'/api/reports/{report.id}/vote',
        json={'status': 'verify'},
    )
    assert response.status_code == 400
