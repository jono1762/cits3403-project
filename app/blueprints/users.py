"""User-related routes — public profile, follow / unfollow, search, block."""
from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
 
from ..models import db, User, Report, Follow, BlockedUser
 
bp = Blueprint('users', __name__)
 
 
def _following_users_for(user):
    """Return the User rows this profile-user follows (newest follow first)."""
    rows = (
        Follow.query
        .filter_by(follower_id=user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )
    # Resolve each Follow row to the actual followed-User object
    return [User.query.get(r.followed_id) for r in rows if User.query.get(r.followed_id)]
 
 
def _follower_users_for(user):
    """Return the User rows that follow this profile-user (newest follow first)."""
    rows = (
        Follow.query
        .filter_by(followed_id=user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )
    return [User.query.get(r.follower_id) for r in rows if User.query.get(r.follower_id)]
 
 
# /profile — show the logged-in user's own basic info
@bp.route('/profile')
@login_required
def profile_page():
    recent_reports = (
        Report.query
        .filter_by(user_id=current_user.id)
        .order_by(Report.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        'profile.html',
        user=current_user,
        recent_reports=recent_reports,
        is_own_profile=True,
        following_users=_following_users_for(current_user),
        follower_users=_follower_users_for(current_user),
    )
 
 
# /users/<username> — view someone else's profile (read-only, no edit buttons)
@bp.route('/users/<username>')
@login_required
def user_profile_page(username):
    user = User.query.filter_by(username=username).first_or_404()
    recent_reports = (
        Report.query
        .filter_by(user_id=user.id)
        .order_by(Report.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        'profile.html',
        user=user,
        recent_reports=recent_reports,
        is_own_profile=(user.id == current_user.id),
        following_users=_following_users_for(user),
        follower_users=_follower_users_for(user),
    )
 
 
@bp.route('/profile/following-privacy', methods=['POST'])
@login_required
def profile_toggle_following_privacy():
    """Flip the visibility of the current user's Following list. Only the
    profile owner can toggle their own setting (enforced by current_user).
    Redirects with #following so the JS keeps the user on the Following tab."""
    current_user.following_list_public = not current_user.following_list_public
    db.session.commit()
    return redirect(url_for('users.profile_page') + '#following')
 
 
@bp.route('/profile/followers-privacy', methods=['POST'])
@login_required
def profile_toggle_followers_privacy():
    """Flip the visibility of the current user's Followers list. Same shape
    as the Following privacy toggle — owner-only, redirects with #followers."""
    current_user.followers_list_public = not current_user.followers_list_public
    db.session.commit()
    return redirect(url_for('users.profile_page') + '#followers')
 
 
# /search — find users by username substring (case-insensitive)
@bp.route('/search')
@login_required
def search_users_page():
    q = (request.args.get('q') or '').strip()
    users = []
    if q:
        users = (
            User.query
            .filter(User.username.ilike(f'%{q}%'))
            .order_by(User.username)
            .limit(20)
            .all()
        )
    return render_template('search.html', q=q, users=users)
 
 
# /api/search-users — JSON endpoint for the sidebar search panel.
# Returns top 10 username matches as you type, no full page reload needed.
@bp.route('/api/search-users')
@login_required
def api_search_users():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify([])
    users = (
        User.query
        .filter(User.username.ilike(f'%{q}%'))
        .filter(User.id != current_user.id)   # don't surface self in chat search
        .order_by(User.username)
        .limit(10)
        .all()
    )
    return jsonify([
        {
            'user_id': u.id,
            'username': u.username,
            'avatar_initial': u.username[:1].upper(),
            'profile_url': url_for('users.user_profile_page', username=u.username),
        }
        for u in users
    ])
 
 
# ---------------- Follow / Unfollow ----------------
# POST creates the edge (idempotent — re-following is a no-op).
# DELETE removes it. Self-follow is rejected at the API; the UI hides the
# button on own profiles, but defence-in-depth never hurts.
 
@bp.route('/api/follow/<int:user_id>', methods=['POST'])
@login_required
def api_follow_user(user_id):
    if user_id == current_user.id:
        return jsonify({'error': "You can't follow yourself."}), 400
    target = User.query.get_or_404(user_id)
    existing = Follow.query.filter_by(
        follower_id=current_user.id, followed_id=target.id
    ).first()
    if not existing:
        db.session.add(Follow(follower_id=current_user.id, followed_id=target.id))
        db.session.commit()
    return jsonify({
        'is_following': True,
        'follower_count': target.follower_count,
        'following_count': target.following_count,
    })
 
 
@bp.route('/api/follow/<int:user_id>', methods=['DELETE'])
@login_required
def api_unfollow_user(user_id):
    target = User.query.get_or_404(user_id)
    existing = Follow.query.filter_by(
        follower_id=current_user.id, followed_id=target.id
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
    return jsonify({
        'is_following': False,
        'follower_count': target.follower_count,
        'following_count': target.following_count,
    })
 
 
# ---------------- Block / Unblock (chat-only) ----------------
# When user A blocks user B:
#   - B can no longer send messages to A (server returns 403 in api_send_message)
#   - B's existing conversations with A are filtered out of A's inbox
#   - B can still see A's posts / comments / profile — this is chat-only
# Block button appears on the OTHER user's profile page (next to Follow / Message).
 
def _is_blocked(blocker_id, blocked_id):
    """True if blocker_id has blocked blocked_id (chat-wise)."""
    return BlockedUser.query.filter_by(
        blocker_id=blocker_id, blocked_id=blocked_id
    ).first() is not None
 
 
@bp.route('/api/block/<int:user_id>', methods=['POST'])
@login_required
def api_block_user(user_id):
    if user_id == current_user.id:
        return jsonify({'error': "You can't block yourself."}), 400
    target = User.query.get_or_404(user_id)
    if not _is_blocked(current_user.id, target.id):
        db.session.add(BlockedUser(blocker_id=current_user.id, blocked_id=target.id))
        db.session.commit()
    return jsonify({'is_blocked': True})
 
 
@bp.route('/api/blocked-users')
@login_required
def api_list_blocked_users():
    """List the users the current user has blocked, newest-first.
    Powers the 'manage blocked' modal in the chat sidebar."""
    rows = (
        BlockedUser.query
        .filter_by(blocker_id=current_user.id)
        .order_by(BlockedUser.created_at.desc())
        .all()
    )
    out = []
    for row in rows:
        u = User.query.get(row.blocked_id)
        if not u:
            continue
        out.append({
            'user_id': u.id,
            'username': u.username,
            'avatar_initial': u.username[:1].upper(),
            'profile_url': url_for('users.user_profile_page', username=u.username),
        })
    return jsonify(out)
 
 
@bp.route('/api/block/<int:user_id>', methods=['DELETE'])
@login_required
def api_unblock_user(user_id):
    target = User.query.get_or_404(user_id)
    row = BlockedUser.query.filter_by(
        blocker_id=current_user.id, blocked_id=target.id
    ).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({'is_blocked': False})
 
 