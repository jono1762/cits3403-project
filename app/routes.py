import os
import uuid
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from .models import db, User, Category, Report, State, City, ReportMedia, Verification, Comment, CommentMedia, CommentVote, Follow, Conversation, ChatMessage, ChatMessageMedia, FavouriteLocation, FavouriteReport, BlockedUser
# Report-related helpers live in the reports blueprint now. The remaining
# routes in this file (favourites, comments, chat) still need a few of them,
# so we re-import here rather than duplicating the logic.
from .blueprints.reports import (
    _active_reports_q,
    _encode_report_id,
    _media_type_for,
    MAX_MEDIA_FILES,
    TRENDING_LIMIT,
    COMMENT_MAX_LENGTH,
)
 
@app.route('/')
def index():
    # / is just an alias for /intro — keep one canonical URL for the home page.
    return redirect(url_for('home_intro'))
 
# single source of truth for the category-name → emoji map.
# Injected into every template via the context processor below so the same
# emoji shows up consistently on the listing chips, profile cards, trending
# stat card, etc. — change once, applies everywhere.
CATEGORY_EMOJI = {
    'Weather':   '☁️',
    'Noisiness': '🔊',
    'Hazards':   '⚠️',
    'Traffic':   '🚦',
    'Emergency': '🚨',
}
 
@app.context_processor
def inject_category_emoji():
    return {'CATEGORY_EMOJI': CATEGORY_EMOJI}
 
@app.context_processor
def inject_unread_messages():
    """Make the chat unread count available to every template (used by the
    sidebar 'Messages' link to render the small red notification badge).
    Returns 0 for guests so the badge cleanly hides itself."""
    if current_user.is_authenticated:
        return {'unread_message_count': current_user.unread_message_count}
    return {'unread_message_count': 0}
 
 
# mapping each city to its state code (lowercase, used as the flag dictionary key)
CITY_TO_STATE = {
    'Sydney': 'nsw', 'Newcastle': 'nsw', 'Wollongong': 'nsw', 'Central Coast': 'nsw',
    'Melbourne': 'vic', 'Geelong': 'vic', 'Ballarat': 'vic',
    'Brisbane': 'qld', 'Gold Coast': 'qld', 'Sunshine Coast': 'qld', 'Cairns': 'qld', 'Townsville': 'qld',
    'Perth': 'wa', 'Fremantle': 'wa', 'Mandurah': 'wa', 'Bunbury': 'wa',
    'Adelaide': 'sa', 'Mount Gambier': 'sa',
    'Hobart': 'tas', 'Launceston': 'tas',
    'Canberra': 'act',
    'Darwin': 'nt', 'Alice Springs': 'nt',
}
 
# state code -> local flag image path served from /static/images/flags/
STATE_FLAG_URL = {
    'nsw': '/static/images/flags/nsw.png',
    'vic': '/static/images/flags/vic.png',
    'qld': '/static/images/flags/qld.png',
    'wa':  '/static/images/flags/wa.png',
    'sa':  '/static/images/flags/sa.png',
    'tas': '/static/images/flags/tas.png',
    'act': '/static/images/flags/act.png',
    'nt':  '/static/images/flags/nt.png',
}
 
# Lat/lng for every city in the DB. Single source of truth — fed to the
# map JS via the template so adding a city only means editing this dict
# (until we eventually move these onto the City model itself).
CITY_COORDS = {
    'Sydney':         (-33.8688, 151.2093),
    'Newcastle':      (-32.9283, 151.7817),
    'Wollongong':     (-34.4278, 150.8931),
    'Central Coast':  (-33.4248, 151.3408),
    'Melbourne':      (-37.8136, 144.9631),
    'Geelong':        (-38.1499, 144.3617),
    'Ballarat':       (-37.5622, 143.8503),
    'Brisbane':       (-27.4698, 153.0251),
    'Gold Coast':     (-28.0167, 153.4000),
    'Sunshine Coast': (-26.6500, 153.0667),
    'Cairns':         (-16.9203, 145.7710),
    'Townsville':     (-19.2589, 146.8169),
    'Perth':          (-31.9523, 115.8613),
    'Mandurah':       (-32.5269, 115.7217),
    'Bunbury':        (-33.3267, 115.6411),
    'Adelaide':       (-34.9285, 138.6007),
    'Mount Gambier':  (-37.8281, 140.7822),
    'Hobart':         (-42.8821, 147.3272),
    'Launceston':     (-41.4391, 147.1358),
    'Canberra':       (-35.2809, 149.1300),
    'Darwin':         (-12.4634, 130.8456),
    'Alice Springs':  (-23.6980, 133.8807),
}
 
 
@app.route('/favourites')
@app.route('/favourites/locations')
@login_required
def favourites_page():
    # load saved city favourites for the current user
    fav_rows = FavouriteLocation.query.filter_by(user_id=current_user.id).all()
    saved_cities = []
    for f in fav_rows:
        city = f.city
        if not city:
            continue
        # small convenience stat: how many non-expired reports exist for this city
        reports_today = _active_reports_q().filter(Report.city_id == city.id).count()
        # latest non-expired report time (for "Last Update")
        last_report = _active_reports_q().filter(Report.city_id == city.id).order_by(Report.created_at.desc()).first()
        if last_report and last_report.created_at:
            delta = datetime.utcnow() - last_report.created_at
            minutes = int(delta.total_seconds() // 60)
            if minutes < 1:
                last_update = 'just now'
            elif minutes < 60:
                last_update = f"{minutes} minute{'s' if minutes!=1 else ''} ago"
            elif minutes < 60*24:
                hours = minutes // 60
                last_update = f"{hours} hour{'s' if hours!=1 else ''} ago"
            else:
                days = minutes // (60*24)
                last_update = f"{days} day{'s' if days!=1 else ''} ago"
        else:
            last_update = '—'
 
        # trending heuristic: many reports today
        trending = reports_today >= 20
 
        saved_cities.append({
            'id': city.id,
            'name': city.name,
            'country': 'Australia',
            'state_code': city.state.code if getattr(city, 'state', None) else '',
            'reports_today': reports_today,
            'last_update': last_update,
            'trending': trending,
        })
 
    # locations-only page (report favourites are on /favourites/reports)
    return render_template('favourites.html', saved_cities=saved_cities)
 
 
@app.route('/favourites/reports')
@login_required
def favourite_reports_page():
    fav_rows = (
        FavouriteReport.query
        .filter_by(user_id=current_user.id)
        .order_by(FavouriteReport.created_at.desc())
        .all()
    )
 
    fav_reports = []
    for row in fav_rows:
        report = row.report
        if not report:
            continue
        fav_reports.append({
            'id': report.id,
            'category': report.category.name if report.category else 'Unknown',
            'category_color': report.category.marker_color if report.category else '#94a3b8',
            'city': report.city.name if report.city else 'Unknown city',
            'state': report.city.state.code if report.city and report.city.state else '',
            'author': report.author.username if report.author else 'unknown',
            'created_at': report.created_at.strftime('%d %b %Y · %H:%M') if report.created_at else '—',
            'description': report.description or '',
            'token': _encode_report_id(report.id),
        })
 
    return render_template('favourite_reports.html', fav_reports=fav_reports)
 
 
@app.route('/api/favourites/locations', methods=['GET'])
@login_required
def api_get_favourite_locations():
    fav_rows = FavouriteLocation.query.filter_by(user_id=current_user.id).all()
    data = []
    for f in fav_rows:
        city = f.city
        if not city:
            continue
        data.append({
            'city_id': city.id,
            'name': city.name,
            'state_code': city.state.code if getattr(city, 'state', None) else '',
        })
    return jsonify(data)
 
 
@app.route('/api/favourites/location/<int:city_id>', methods=['POST'])
@login_required
def api_add_favourite_location(city_id):
    city = City.query.get_or_404(city_id)
    existing = FavouriteLocation.query.filter_by(user_id=current_user.id, city_id=city.id).first()
    if not existing:
        fav = FavouriteLocation(user_id=current_user.id, city_id=city.id)
        db.session.add(fav)
        db.session.commit()
    return jsonify({'added': True})
 
 
@app.route('/api/favourites/location/<int:city_id>', methods=['DELETE'])
@login_required
def api_remove_favourite_location(city_id):
    fav = FavouriteLocation.query.filter_by(user_id=current_user.id, city_id=city_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
    return jsonify({'removed': True})
 
 
@app.route('/api/favourites/reports', methods=['GET'])
@login_required
def api_get_favourite_reports():
    fav_rows = FavouriteReport.query.filter_by(user_id=current_user.id).all()
    return jsonify([
        {'report_id': row.report_id}
        for row in fav_rows
    ])
 
 
@app.route('/api/favourites/report/<int:report_id>', methods=['POST'])
@login_required
def api_add_favourite_report(report_id):
    report = Report.query.get_or_404(report_id)
    existing = FavouriteReport.query.filter_by(user_id=current_user.id, report_id=report.id).first()
    if not existing:
        db.session.add(FavouriteReport(user_id=current_user.id, report_id=report.id))
        db.session.commit()
    return jsonify({'added': True})
 
 
@app.route('/api/favourites/report/<int:report_id>', methods=['DELETE'])
@login_required
def api_remove_favourite_report(report_id):
    fav = FavouriteReport.query.filter_by(user_id=current_user.id, report_id=report_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
    return jsonify({'removed': True})
 
 
# Auth + settings + profile-edit routes moved to app/blueprints/auth.py
 
 
# /help — static FAQ page, public
@app.route('/help')
def help_page():
    return render_template('help.html')
 
# /about — static team / project info page, public
@app.route('/about')
def about_page():
    return render_template('about.html')
 
 
@app.route('/map')
def map_page():
    # public map view — used by the "Start as guest" button on the home page
    return render_template('map.html', **_map_page_context())
 
 
def _map_page_context():
    city_ids = {s.name: s.id for s in City.query.all()}
    category_ids = {c.name: c.id for c in Category.query.all()}
    now = datetime.utcnow()
 
    # Top trending city / category derived from the global Trending top N.
    # Group the top-N reports by city (or category), and rank groups by:
    #   1. how many of the top-N are in that city (descending)
    #   2. the highest-scoring single report within that city (tiebreaker)
    # Only non-expired reports are considered (Report.expires_at > now).
    from sqlalchemy import case
    verify_sum = db.func.coalesce(
        db.func.sum(case((Verification.status == 'verify', 1), else_=0)), 0)
    dispute_sum = db.func.coalesce(
        db.func.sum(case((Verification.status == 'dispute', 1), else_=0)), 0)
    days_old_expr = db.func.julianday('now') - db.func.julianday(Report.created_at)
    score_expr = (verify_sum - dispute_sum - days_old_expr).label('score')
    trending_rows = (
        db.session.query(
            Report.id, Report.city_id, Report.category_id, score_expr,
        )
        .filter(Report.expires_at > now)
        .outerjoin(Verification, Verification.report_id == Report.id)
        .group_by(Report.id)
        .order_by(score_expr.desc(), Report.created_at.desc())
        .limit(TRENDING_LIMIT)
        .all()
    )
    total_in_top = len(trending_rows)
 
    def _top_group(get_key):
        """For each report in the trending top-N, bucket by `get_key(row)`,
        track count and best score per bucket, then pick the bucket with the
        highest count (tiebreak by best score)."""
        buckets = {}  # key -> {'count': int, 'best_score': float}
        for row in trending_rows:
            key = get_key(row)
            if key is None:
                continue
            b = buckets.setdefault(key, {'count': 0, 'best_score': float('-inf')})
            b['count'] += 1
            if row.score > b['best_score']:
                b['best_score'] = row.score
        if not buckets:
            return None
        winner_key = max(buckets, key=lambda k: (buckets[k]['count'], buckets[k]['best_score']))
        return winner_key, buckets[winner_key]['count']
 
    top_city = None
    city_pick = _top_group(lambda r: r.city_id)
    if city_pick:
        cid, cnt = city_pick
        c = City.query.get(cid)
        if c:
            top_city = {'name': c.name, 'count': cnt, 'total': total_in_top}
 
    top_category = None
    cat_pick = _top_group(lambda r: r.category_id)
    if cat_pick:
        cat_id, cnt = cat_pick
        cat = Category.query.get(cat_id)
        if cat:
            top_category = {'name': cat.name, 'count': cnt, 'total': total_in_top}
 
    # Third bubble — the user's "most important" pinned report, picked from
    # everything they've saved (favourited reports + reports in favourited
    # cities). Highest engagement score across that pool wins. Falls back to
    # None for guests / users with no saves; the template shows a stub then.
    top_pinned_report = _top_pinned_report_for(current_user)
 
    # Build the map-pin list from the DB cities, joined with our hardcoded
    # CITY_COORDS lookup. Cities missing from CITY_COORDS just don't get a
    # pin (rather than crashing the map).
    db_cities = City.query.order_by(City.name).all()
    map_cities = []
    for c in db_cities:
        coords = CITY_COORDS.get(c.name)
        if not coords:
            continue
        state_name = c.state.name if c.state else ''
        map_cities.append({
            'id': c.id,
            'name': f'{c.name}, {state_name}' if state_name else c.name,
            'short_name': c.name,
            'state': state_name,
            'lat': coords[0],
            'lng': coords[1],
        })
 
    return {
        'city_ids_by_name': city_ids,
        'category_ids_by_name': category_ids,
        'city_to_state': CITY_TO_STATE,
        'state_flag_url': STATE_FLAG_URL,
        'top_city': top_city,
        'top_category': top_category,
        'top_pinned_report': top_pinned_report,
        'map_cities': map_cities,
    }
 
 
def _top_pinned_report_for(user):
    """Highest-scoring report across the user's saved reports + reports in
    their saved cities. Returns the Report object or None."""
    if not getattr(user, 'is_authenticated', False):
        return None
    fav_report_ids = {row.report_id for row in FavouriteReport.query.filter_by(user_id=user.id).all()}
    fav_city_ids = {row.city_id for row in FavouriteLocation.query.filter_by(user_id=user.id).all()}
    candidate_ids = set(fav_report_ids)
    if fav_city_ids:
        candidate_ids.update(
            r.id for r in Report.query.filter(Report.city_id.in_(fav_city_ids)).all()
        )
    if not candidate_ids:
        return None
 
    from sqlalchemy import case
    verify_sum = db.func.coalesce(
        db.func.sum(case((Verification.status == 'verify', 1), else_=0)), 0)
    dispute_sum = db.func.coalesce(
        db.func.sum(case((Verification.status == 'dispute', 1), else_=0)), 0)
    days_old = db.func.julianday('now') - db.func.julianday(Report.created_at)
    score_expr = (verify_sum - dispute_sum - days_old).label('score')
    row = (
        db.session.query(Report.id)
        .filter(Report.id.in_(candidate_ids))
        .outerjoin(Verification, Verification.report_id == Report.id)
        .group_by(Report.id)
        .order_by(score_expr.desc(), Report.created_at.desc())
        .first()
    )
    return Report.query.get(row[0]) if row else None
 
 
# /intro — same content as / but always rendered in the marketing/intro
# style (no navbar / sidebar). Lets logged-in users revisit the public-facing
# home page (linked from the navbar home icon).
@app.route('/intro')
def home_intro():
    return render_template('index.html')
 
 
# login / signup / login_email / logout moved to app/blueprints/auth.py
 
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
@app.route('/profile')
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
@app.route('/users/<username>')
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
 
 
@app.route('/profile/following-privacy', methods=['POST'])
@login_required
def profile_toggle_following_privacy():
    """Flip the visibility of the current user's Following list. Only the
    profile owner can toggle their own setting (enforced by current_user).
    Redirects with #following so the JS keeps the user on the Following tab."""
    current_user.following_list_public = not current_user.following_list_public
    db.session.commit()
    return redirect(url_for('profile_page') + '#following')
 
 
@app.route('/profile/followers-privacy', methods=['POST'])
@login_required
def profile_toggle_followers_privacy():
    """Flip the visibility of the current user's Followers list. Same shape
    as the Following privacy toggle — owner-only, redirects with #followers."""
    current_user.followers_list_public = not current_user.followers_list_public
    db.session.commit()
    return redirect(url_for('profile_page') + '#followers')
 
# /search — find users by username substring (case-insensitive)
@app.route('/search')
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
@app.route('/api/search-users')
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
            'profile_url': url_for('user_profile_page', username=u.username),
        }
        for u in users
    ])
 
 
# ---------------- Follow / Unfollow ----------------
# POST creates the edge (idempotent — re-following is a no-op).
# DELETE removes it. Self-follow is rejected at the API; the UI hides the
# button on own profiles, but defence-in-depth never hurts.
 
@app.route('/api/follow/<int:user_id>', methods=['POST'])
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
 
@app.route('/api/follow/<int:user_id>', methods=['DELETE'])
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
 
 
@app.route('/api/block/<int:user_id>', methods=['POST'])
@login_required
def api_block_user(user_id):
    if user_id == current_user.id:
        return jsonify({'error': "You can't block yourself."}), 400
    target = User.query.get_or_404(user_id)
    if not _is_blocked(current_user.id, target.id):
        db.session.add(BlockedUser(blocker_id=current_user.id, blocked_id=target.id))
        db.session.commit()
    return jsonify({'is_blocked': True})
 
 
@app.route('/api/blocked-users')
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
            'profile_url': url_for('user_profile_page', username=u.username),
        })
    return jsonify(out)
 
 
@app.route('/api/block/<int:user_id>', methods=['DELETE'])
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
 
 
# ---------------- Chat ----------------
# 1-on-1 messaging. Conversation rows store the per-pair state (accepted vs
# request); ChatMessage rows store the actual messages.
# Body is plain text — same XSS-safe pattern as comments (Jinja auto-escape +
# textContent on the JS side).
 
CHAT_MESSAGE_MAX_LENGTH = 2000
 
def _find_or_create_conversation(sender, recipient):
    """Look up the canonical (smaller-id-first) Conversation row between
    sender + recipient, creating it on demand. New conversations auto-accept
    when the two users are mutual followers; otherwise they start as a
    pending message-request."""
    me, them = sorted([sender.id, recipient.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first()
    if conv is None:
        conv = Conversation(
            user_a_id=me,
            user_b_id=them,
            initiator_id=sender.id,
            accepted=sender.is_mutual_with(recipient),
        )
        db.session.add(conv)
        db.session.flush()
    elif (not conv.accepted) and conv.initiator_id != sender.id:
        # the recipient is replying → that auto-accepts the pending request
        conv.accepted = True
    return conv
 
def _serialize_conversation_summary(conv, viewer):
    """Compact JSON shape for the inbox list — last message preview + counts."""
    other = conv.other(viewer)
    last = ChatMessage.query.filter_by(conversation_id=conv.id) \
        .order_by(ChatMessage.created_at.desc()).first()
    unread = ChatMessage.query.filter(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_id != viewer.id,
        ChatMessage.read_at.is_(None),
    ).count()
    return {
        'user_id': other.id,
        'username': other.username,
        'avatar_initial': other.username[:1].upper(),
        'avatar_url': (url_for('static', filename=f'uploads/{other.avatar_filename}')
                       if other.avatar_filename else None),
        'profile_url': url_for('user_profile_page', username=other.username),
        'last_body': last.body if last else '',
        'last_at': conv.last_message_at.isoformat() if conv.last_message_at else None,
        'last_sender_is_me': bool(last and last.sender_id == viewer.id),
        'unread': unread,
        'is_request': conv.is_request_for(viewer),
        'accepted': conv.accepted,
    }
 
 
@app.route('/messages')
@login_required
def messages_page():
    # ?user=<id> → JS auto-opens that conversation on page load
    return render_template('messages.html')
 
 
@app.route('/api/users/<int:user_id>')
@login_required
def api_user_brief(user_id):
    """Minimal user-info endpoint used by the chat page when the inbox doesn't
    yet contain this user (fresh conversation started from a profile page)."""
    if user_id == current_user.id:
        return jsonify({'error': "That's you."}), 400
    u = User.query.get_or_404(user_id)
    return jsonify({
        'user_id': u.id,
        'username': u.username,
        'avatar_initial': u.username[:1].upper(),
        'avatar_url': (url_for('static', filename=f'uploads/{u.avatar_filename}')
                       if u.avatar_filename else None),
        'profile_url': url_for('user_profile_page', username=u.username),
        'is_blocked': _is_blocked(current_user.id, u.id),
    })
 
 
@app.route('/api/conversations')
@login_required
def api_list_conversations():
    """Return chats and requests as two separate lists, both newest-first.
    Conversations with users I've blocked are filtered out of both lists —
    they reappear in the inbox if I unblock the user later."""
    blocked_ids = {
        row.blocked_id
        for row in BlockedUser.query.filter_by(blocker_id=current_user.id).all()
    }
    convs = Conversation.query.filter(
        db.or_(Conversation.user_a_id == current_user.id,
               Conversation.user_b_id == current_user.id)
    ).order_by(Conversation.last_message_at.desc()).all()
 
    chats = []
    requests_list = []
    for conv in convs:
        other = conv.other(current_user)
        if other.id in blocked_ids:
            continue  # hide conversations with blocked users
        item = _serialize_conversation_summary(conv, current_user)
        if conv.is_request_for(current_user):
            requests_list.append(item)
        else:
            chats.append(item)
    return jsonify({
        'chats': chats,
        'requests': requests_list,
        'unread_total': current_user.unread_message_count,
    })
 
 
@app.route('/api/conversations/<int:user_id>/messages', methods=['GET'])
@login_required
def api_get_messages(user_id):
    """Fetch the message history with a specific user. Optional ?since=<iso> to
    only get messages newer than the given timestamp (used by the polling loop)."""
    other = User.query.get_or_404(user_id)
    me, them = sorted([current_user.id, other.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first()
    if conv is None:
        return jsonify({
            'messages': [], 'accepted': False, 'is_request': False,
            'is_blocked': _is_blocked(current_user.id, other.id),
        })
 
    since = request.args.get('since')
    q = ChatMessage.query.filter_by(conversation_id=conv.id)
    if since:
        try:
            cutoff = datetime.fromisoformat(since)
            q = q.filter(ChatMessage.created_at > cutoff)
        except ValueError:
            pass
    msgs = q.order_by(ChatMessage.created_at.asc()).all()
 
    return jsonify({
        'accepted': conv.accepted,
        'is_request': conv.is_request_for(current_user),
        'is_blocked': _is_blocked(current_user.id, other.id),
        'messages': [{
            'id': m.id,
            'body': m.body,
            'sender_id': m.sender_id,
            'sender_is_me': m.sender_id == current_user.id,
            'created_at': m.created_at.isoformat(),
            'media': [
                {
                    'type': mm.media_type,
                    'url': url_for('static', filename=f'uploads/{mm.filename}'),
                    'original_name': mm.original_name,
                }
                for mm in m.media
            ],
        } for m in msgs],
    })
 
 
@app.route('/api/conversations/<int:user_id>/messages', methods=['POST'])
@login_required
def api_send_message(user_id):
    """Send a message. Accepts JSON ({body}) for text-only OR multipart/form-data
    (body + media[]) when files are attached. First message creates the
    conversation; recipient replying auto-accepts a pending request."""
    if user_id == current_user.id:
        return jsonify({'error': "You can't message yourself."}), 400
    recipient = User.query.get_or_404(user_id)
 
    # Block check — recipient may have blocked the current user from messaging.
    # Show a generic "can't reach this user" message rather than confirming
    # the block (avoids leaking the recipient's privacy choice).
    if _is_blocked(blocker_id=recipient.id, blocked_id=current_user.id):
        return jsonify({'error': "This user isn't accepting messages from you."}), 403
 
    if request.content_type and 'multipart/form-data' in request.content_type:
        body = (request.form.get('body') or '').strip()
        files = [f for f in request.files.getlist('media') if f and f.filename]
    else:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body') or '').strip()
        files = []
 
    if not body and not files:
        return jsonify({'error': 'Message cannot be empty.'}), 400
    if len(body) > CHAT_MESSAGE_MAX_LENGTH:
        return jsonify({'error': f'Message too long (max {CHAT_MESSAGE_MAX_LENGTH} characters).'}), 400
    if len(files) > MAX_MEDIA_FILES:
        return jsonify({'error': f'Too many files (max {MAX_MEDIA_FILES}).'}), 400
    for f in files:
        if not _media_type_for(f.filename):
            return jsonify({'error': f'Unsupported file type: {f.filename}'}), 400
 
    conv = _find_or_create_conversation(current_user, recipient)
    msg = ChatMessage(conversation_id=conv.id, sender_id=current_user.id, body=body)
    db.session.add(msg)
    db.session.flush()  # need msg.id for ChatMessageMedia FK
 
    # save uploaded files to disk + DB; clean up disk on error
    saved_paths = []
    try:
        for f in files:
            ext = f.filename.rsplit('.', 1)[-1].lower()
            stored_name = f'{uuid.uuid4().hex}.{ext}'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
            f.save(save_path)
            saved_paths.append(save_path)
            db.session.add(ChatMessageMedia(
                message_id=msg.id,
                filename=stored_name,
                original_name=secure_filename(f.filename) or stored_name,
                media_type=_media_type_for(f.filename),
            ))
        conv.last_message_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
        for p in saved_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        raise
 
    return jsonify({
        'id': msg.id,
        'body': msg.body,
        'sender_id': msg.sender_id,
        'sender_is_me': True,
        'created_at': msg.created_at.isoformat(),
        'accepted': conv.accepted,
        'media': [
            {
                'type': m.media_type,
                'url': url_for('static', filename=f'uploads/{m.filename}'),
                'original_name': m.original_name,
            }
            for m in msg.media
        ],
    }), 201
 
 
@app.route('/api/conversations/<int:user_id>/accept', methods=['POST'])
@login_required
def api_accept_conversation(user_id):
    """Move a pending message-request into the main Chats inbox."""
    other = User.query.get_or_404(user_id)
    me, them = sorted([current_user.id, other.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first_or_404()
    # only the recipient can accept (the initiator already had it in their Chats)
    if conv.initiator_id == current_user.id:
        return jsonify({'error': "You started this conversation, nothing to accept."}), 400
    conv.accepted = True
    db.session.commit()
    return jsonify({'accepted': True})
 
 
@app.route('/api/conversations/<int:user_id>/read', methods=['POST'])
@login_required
def api_mark_read(user_id):
    """Mark every unread message addressed to me in this conversation as read.
    Called when the recipient opens the thread."""
    other = User.query.get_or_404(user_id)
    me, them = sorted([current_user.id, other.id])
    conv = Conversation.query.filter_by(user_a_id=me, user_b_id=them).first()
    if conv is None:
        return jsonify({'ok': True, 'marked': 0})
    now = datetime.utcnow()
    rows = ChatMessage.query.filter(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_id != current_user.id,
        ChatMessage.read_at.is_(None),
    ).all()
    for m in rows:
        m.read_at = now
    db.session.commit()
    return jsonify({'ok': True, 'marked': len(rows)})
 
 
# ---------------- Comments ----------------
# Body is stored as plain text and rendered with Jinja's default auto-escape, so
# HTML/JS in user input becomes inert text in the page (XSS-safe). The frontend
# also uses textContent (not innerHTML) when injecting new comments without a reload.
 
def _serialize_comment(comment, current_user_id=None):
    """Shared comment-to-JSON shape for the create endpoint and any future list endpoint."""
    author = comment.author
    return {
        'id': comment.id,
        'body': comment.body,
        'author_username': author.username if author else 'deleted_user',
        'author_url': url_for('user_profile_page', username=author.username) if author else None,
        'author_initial': (author.username[:1].upper() if author else '?'),
        'author_avatar_url': (url_for('static', filename=f'uploads/{author.avatar_filename}')
                              if author and author.avatar_filename else None),
        'created_at': comment.created_at.strftime('%d %b %Y, %H:%M'),
        'is_own': comment.user_id == current_user_id,
        'verify_count': comment.verify_count,
        'dispute_count': comment.dispute_count,
        'user_vote': None,  # fresh comments — author can't vote on their own
        'media': [
            {
                'type': m.media_type,
                'url': url_for('static', filename=f'uploads/{m.filename}'),
                'original_name': m.original_name,
            }
            for m in comment.media
        ],
    }
 
@app.route('/api/reports/<int:report_id>/comments', methods=['POST'])
@login_required
def api_create_comment(report_id):
    """Accepts either JSON ({body}) for text-only or multipart/form-data
    (body + media[]) when the user attached images / videos."""
    report = Report.query.get_or_404(report_id)
 
    if request.content_type and 'multipart/form-data' in request.content_type:
        body = (request.form.get('body') or '').strip()
        files = [f for f in request.files.getlist('media') if f and f.filename]
    else:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body') or '').strip()
        files = []
 
    # at least one of (text, media) must be present
    if not body and not files:
        return jsonify({'error': 'Comment cannot be empty.'}), 400
    if len(body) > COMMENT_MAX_LENGTH:
        return jsonify({'error': f'Comment too long (max {COMMENT_MAX_LENGTH} characters).'}), 400
    if len(files) > MAX_MEDIA_FILES:
        return jsonify({'error': f'Too many files (max {MAX_MEDIA_FILES}).'}), 400
    for f in files:
        if not _media_type_for(f.filename):
            return jsonify({'error': f'Unsupported file type: {f.filename}'}), 400
 
    comment = Comment(report_id=report.id, user_id=current_user.id, body=body)
    db.session.add(comment)
    db.session.flush()  # populate comment.id so CommentMedia rows can FK to it
 
    # save each file to disk + DB; if anything fails halfway, clean up the disk files
    saved_paths = []
    try:
        for f in files:
            ext = f.filename.rsplit('.', 1)[-1].lower()
            stored_name = f'{uuid.uuid4().hex}.{ext}'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
            f.save(save_path)
            saved_paths.append(save_path)
            db.session.add(CommentMedia(
                comment_id=comment.id,
                filename=stored_name,
                original_name=secure_filename(f.filename) or stored_name,
                media_type=_media_type_for(f.filename),
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        for p in saved_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        raise
 
    return jsonify(_serialize_comment(comment, current_user_id=current_user.id)), 201
 
 
@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def api_delete_comment(comment_id):
    """Comment author only — wipes the comment, its media (DB + disk), and any votes."""
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id:
        return jsonify({'error': "You can't delete someone else's comment."}), 403
 
    # remove disk files first; the DB rows go via cascade on the relationship
    for m in comment.media:
        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], m.filename)
        try:
            os.remove(disk_path)
        except OSError:
            pass
 
    # CommentVote has no cascade on the model, clear them by hand
    CommentVote.query.filter_by(comment_id=comment.id).delete()
 
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'ok': True})
 
 
@app.route('/api/comments/<int:comment_id>/vote', methods=['POST'])
@login_required
def api_vote_comment(comment_id):
    """Verify / dispute a comment — same toggle semantics as report-vote.
    Comment author can't vote on their own comment."""
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id == current_user.id:
        return jsonify({'error': "You can't vote on your own comment."}), 400
 
    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status') or request.form.get('status')
    if new_status not in ('verify', 'dispute'):
        return jsonify({'error': 'Invalid status.'}), 400
 
    existing = CommentVote.query.filter_by(comment_id=comment.id, user_id=current_user.id).first()
    if existing:
        if existing.status == new_status:
            db.session.delete(existing)  # click same button → un-vote
            user_vote = None
        else:
            existing.status = new_status  # flip vote
            user_vote = new_status
    else:
        db.session.add(CommentVote(comment_id=comment.id, user_id=current_user.id, status=new_status))
        user_vote = new_status
    db.session.commit()
 
    return jsonify({
        'verify_count': CommentVote.query.filter_by(comment_id=comment.id, status='verify').count(),
        'dispute_count': CommentVote.query.filter_by(comment_id=comment.id, status='dispute').count(),
        'user_vote': user_vote,
    })
 