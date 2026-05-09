import os
import uuid
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeSerializer, BadSignature
from datetime import datetime, timedelta
from .models import db, User, Category, Report, State, City, ReportMedia, Verification, Comment, CommentMedia, CommentVote, Follow, Conversation, ChatMessage, ChatMessageMedia, FavouriteLocation, FavouriteReport, BlockedUser
from .forms import LoginForm, EmailLoginForm, SignupForm


def _active_reports_q():
    """Base query for reports still within their expiry window. Use this
    everywhere reports are rendered to a guest or non-author audience so
    expired stuff doesn't leak."""
    return Report.query.filter(Report.expires_at > datetime.utcnow())


# Track when the lazy cleanup last ran so we don't hammer the DB on every
# listing render. Module-level (per-process) state — fine for single-worker
# dev / a single gunicorn process. For multi-worker prod we'd promote this
# into the DB or a cron job.
_LAST_REPORT_CLEANUP = None
_REPORT_CLEANUP_INTERVAL_MIN = 5


def _cleanup_expired_reports():
    """Hard-delete reports whose expiry has lapsed (plus their on-disk media).
    Throttled so a burst of listing-page hits doesn't run this every request."""
    global _LAST_REPORT_CLEANUP
    now = datetime.utcnow()
    if _LAST_REPORT_CLEANUP and (now - _LAST_REPORT_CLEANUP) < timedelta(minutes=_REPORT_CLEANUP_INTERVAL_MIN):
        return
    _LAST_REPORT_CLEANUP = now

    expired = Report.query.filter(Report.expires_at <= now).all()
    if not expired:
        return

    upload_dir = app.config['UPLOAD_FOLDER']
    files_to_remove = set()
    for report in expired:
        for m in report.media:
            files_to_remove.add(m.filename)
        for c in report.comments:
            for m in c.media:
                files_to_remove.add(m.filename)

    # other users' votes / comment-votes don't cascade, so clear them first
    expired_ids = [r.id for r in expired]
    Verification.query.filter(Verification.report_id.in_(expired_ids)).delete(synchronize_session=False)
    comment_ids = [c.id for r in expired for c in r.comments]
    if comment_ids:
        CommentVote.query.filter(CommentVote.comment_id.in_(comment_ids)).delete(synchronize_session=False)
    FavouriteReport.query.filter(FavouriteReport.report_id.in_(expired_ids)).delete(synchronize_session=False)

    for report in expired:
        db.session.delete(report)
    db.session.commit()

    for fname in files_to_remove:
        try:
            os.remove(os.path.join(upload_dir, fname))
        except OSError:
            pass

# Encode/decode helpers for the public report URL.
# Hides the integer DB id behind a signed token so visitors can't iterate
# /reports/1, /reports/2, ... to enumerate the database.
def _report_serializer():
    return URLSafeSerializer(app.config['SECRET_KEY'], salt='report-id')

@app.template_filter('report_token')
def _encode_report_id(report_id):
    """Jinja filter: turn a Report.id into the opaque URL token."""
    return _report_serializer().dumps(report_id)


# whitelist of file types the upload endpoint accepts
ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
ALLOWED_VIDEO_EXTS = {'mp4', 'webm', 'mov'}
MAX_MEDIA_FILES = 5

def _media_type_for(filename):
    """Return 'image' / 'video' for a filename, or None if the extension is not allowed."""
    if not filename or '.' not in filename:
        return None
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext in ALLOWED_IMAGE_EXTS:
        return 'image'
    if ext in ALLOWED_VIDEO_EXTS:
        return 'video'
    return None

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


@app.context_processor
def inject_expiring_reports():
    """Surface the count of the user's own reports expiring in the next 24h
    so base.html can render a single site-wide banner reminding them to
    re-post the content if they want to keep it."""
    if not current_user.is_authenticated:
        return {'expiring_soon_count': 0}
    now = datetime.utcnow()
    soon = now + timedelta(hours=24)
    count = Report.query.filter(
        Report.user_id == current_user.id,
        Report.expires_at > now,
        Report.expires_at <= soon,
    ).count()
    return {'expiring_soon_count': count}


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


from email_validator import validate_email, EmailNotValidError

@app.route('/settings', methods=['GET'])
@login_required
def settings_page():
    return render_template('settings.html')


@app.route('/settings/account', methods=['POST'])
@login_required
def settings_update_account():
    """Update username and email. Re-uses the existing uniqueness rules on
    User.username / User.email; same email-validator check as the signup form."""
    username = (request.form.get('username') or '').strip()
    raw_email = (request.form.get('email') or '').strip()

    # field-level validation
    if not username or len(username) > 80:
        flash('Username must be 1-80 characters.', 'error')
        return redirect(url_for('settings_page'))

    # email-validator does the real work: rejects garbage like "aaaa@aaaa",
    # checks domain has a TLD, normalizes Unicode + uppercase. We disable the
    # DNS deliverability check because it makes a real network call (slow + fails
    # offline). Format-only check is plenty for a school project.
    try:
        valid = validate_email(raw_email, check_deliverability=False)
        email = valid.normalized.lower()
    except EmailNotValidError:
        flash('Invalid email address.', 'error')
        return redirect(url_for('settings_page'))
    if len(email) > 120:
        flash('Email is too long (max 120 characters).', 'error')
        return redirect(url_for('settings_page'))

    # uniqueness — only check if the value actually changed (otherwise we'd
    # always trip the constraint against the user's own row)
    if username != current_user.username:
        if User.query.filter_by(username=username).first():
            flash('That username is already taken.', 'error')
            return redirect(url_for('settings_page'))
    if email != current_user.email:
        if User.query.filter_by(email=email).first():
            flash('That email is already in use.', 'error')
            return redirect(url_for('settings_page'))

    current_user.username = username
    current_user.email = email
    db.session.commit()
    flash('Account details updated.', 'success')
    return redirect(url_for('settings_page'))


@app.route('/settings/password', methods=['POST'])
@login_required
def settings_update_password():
    """Change password — requires the current password and a matching confirmation."""
    current_pw = request.form.get('current_password') or ''
    new_pw = request.form.get('new_password') or ''
    confirm_pw = request.form.get('confirm_password') or ''

    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('settings_page'))
    if len(new_pw) < 8:
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('settings_page'))
    if new_pw != confirm_pw:
        flash("New password and confirmation don't match.", 'error')
        return redirect(url_for('settings_page'))

    current_user.set_password(new_pw)
    db.session.commit()
    flash('Password updated.', 'success')
    return redirect(url_for('settings_page'))


ALLOWED_AVATAR_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5MB — generous for an avatar, blocks oversized uploads early

# Magic-byte signatures for the formats we accept. Reading the actual file
# header lets us reject "evil.exe → renamed to evil.png" — extension-only
# checks would let that slip through.
_IMAGE_MAGIC = (
    (b'\xff\xd8\xff',                            'jpg'),
    (b'\x89PNG\r\n\x1a\n',                       'png'),
    (b'GIF87a',                                  'gif'),
    (b'GIF89a',                                  'gif'),
)

def _sniff_image_type(stream):
    """Return one of {'jpg', 'png', 'gif', 'webp'} if the stream's first bytes
    look like a real image, else None. Stream position is restored so the
    caller can still .save() the full content afterwards."""
    pos = stream.tell()
    head = stream.read(12)
    stream.seek(pos)
    for sig, kind in _IMAGE_MAGIC:
        if head.startswith(sig):
            return kind
    # WebP wraps its magic inside a RIFF container
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    return None

BIO_MAX_LENGTH = 500

@app.route('/profile/edit', methods=['GET'])
@login_required
def profile_edit_page():
    """Profile-public details (avatar, bio, ...). Account / security stuff
    (email, password, delete) lives on /settings instead."""
    return render_template('profile_edit.html', bio_max_length=BIO_MAX_LENGTH)


@app.route('/profile/edit/bio', methods=['POST'])
@login_required
def profile_edit_bio():
    """Update the profile bio. Empty string clears it (falls back to the
    'add a bio' prompt on the user's own profile)."""
    bio = (request.form.get('bio') or '').strip() or None
    if bio and len(bio) > BIO_MAX_LENGTH:
        flash(f'Bio must be {BIO_MAX_LENGTH} characters or fewer.', 'error')
        return redirect(url_for('profile_edit_page'))
    current_user.bio = bio
    db.session.commit()
    flash('Bio updated.', 'success')
    return redirect(url_for('profile_edit_page'))


@app.route('/settings/avatar', methods=['POST'])
@login_required
def settings_upload_avatar():
    """Upload a new profile picture. Replaces any existing avatar (the old
    file on disk is deleted to avoid orphans). Defence-in-depth checks:
      1. @login_required — guests can't upload
      2. Filename extension whitelist (cheap pre-filter)
      3. Size cap (rejects oversized uploads before we touch disk)
      4. Magic-byte sniff — rejects renamed non-images even if their
         extension passes the whitelist
      5. Filename on disk is always our own UUID, never user-supplied
         (path-traversal-proof, no overwrite of existing files)
    """
    f = request.files.get('avatar')
    if not f or not f.filename:
        flash('Please choose an image file.', 'error')
        return redirect(url_for('profile_edit_page'))

    # 2. extension whitelist
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_AVATAR_EXTS:
        flash(f'Unsupported file type. Use one of: {", ".join(sorted(ALLOWED_AVATAR_EXTS))}.', 'error')
        return redirect(url_for('profile_edit_page'))

    # 3. size cap — measure by seeking to the end, then rewind for save()
    f.stream.seek(0, os.SEEK_END)
    size = f.stream.tell()
    f.stream.seek(0)
    if size > AVATAR_MAX_BYTES:
        flash(f'Image is too large (max {AVATAR_MAX_BYTES // (1024 * 1024)}MB).', 'error')
        return redirect(url_for('profile_edit_page'))

    # 4. magic-byte sniff — confirms the file ACTUALLY is an image of an
    #    accepted format, not just something with a friendly extension
    sniffed = _sniff_image_type(f.stream)
    if sniffed is None:
        flash('That file does not look like a valid image.', 'error')
        return redirect(url_for('profile_edit_page'))

    # 5. save with a fresh UUID name + canonical extension from the sniff
    #    (so the on-disk extension always matches the actual content)
    stored_name = f'{uuid.uuid4().hex}.{sniffed}'
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
    f.save(save_path)

    # remove the previous avatar from disk before swapping the DB pointer
    old = current_user.avatar_filename
    current_user.avatar_filename = stored_name
    db.session.commit()
    if old:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old))
        except OSError:
            pass

    flash('Profile picture updated.', 'success')
    return redirect(url_for('profile_edit_page'))


@app.route('/settings/avatar/remove', methods=['POST'])
@login_required
def settings_remove_avatar():
    """Drop the current avatar. Falls back to the initial-letter avatar everywhere."""
    old = current_user.avatar_filename
    if not old:
        return redirect(url_for('profile_edit_page'))
    current_user.avatar_filename = None
    db.session.commit()
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old))
    except OSError:
        pass
    flash('Profile picture removed.', 'success')
    return redirect(url_for('profile_edit_page'))


@app.route('/api/settings/verify-password', methods=['POST'])
@login_required
def api_verify_password():
    """AJAX endpoint used by the Settings page to gate the 'change password'
    fields — JS calls this as the user types the current password and only
    unlocks the new-password inputs when the answer comes back ok=True."""
    payload = request.get_json(silent=True) or {}
    pw = payload.get('current_password') or ''
    return jsonify({'ok': bool(pw) and current_user.check_password(pw)})


@app.route('/settings/delete', methods=['POST'])
@login_required
def settings_delete_account():
    """Permanent account deletion. Requires the user's password as a final
    safety check. Reports and comments authored by the user are KEPT so other
    users' threads stay coherent — their author column is set to NULL and the
    UI renders the byline as "deleted_user". The user-specific stuff (votes,
    follows, conversations) still gets wiped.
    """
    if not current_user.check_password(request.form.get('password') or ''):
        flash('Incorrect password — account not deleted.', 'error')
        return redirect(url_for('settings_page'))

    user = current_user._get_current_object()
    upload_dir = app.config['UPLOAD_FOLDER']

    # only chat-message media gets removed from disk — reports' / comments'
    # media stays because the parent rows stay too (just anonymised)
    files_to_remove = set()
    convs = Conversation.query.filter(
        db.or_(Conversation.user_a_id == user.id,
               Conversation.user_b_id == user.id)
    ).all()
    for conv in convs:
        for msg in conv.messages:
            for media in msg.media:
                files_to_remove.add(media.filename)

    # rows that don't cascade from User get cleaned manually
    Verification.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    Follow.query.filter(
        db.or_(Follow.follower_id == user.id, Follow.followed_id == user.id)
    ).delete(synchronize_session=False)
    CommentVote.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    FavouriteLocation.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    FavouriteReport.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    # anonymise the user's posts instead of deleting them — keeps comment
    # threads readable for everyone else, byline becomes "deleted_user"
    Report.query.filter_by(user_id=user.id).update(
        {Report.user_id: None}, synchronize_session=False
    )
    Comment.query.filter_by(user_id=user.id).update(
        {Comment.user_id: None}, synchronize_session=False
    )

    # delete conversations involving this user (cascades messages + message-media DB rows)
    for conv in convs:
        db.session.delete(conv)

    db.session.delete(user)
    db.session.commit()

    # wipe disk files (chat media) after the DB transaction succeeds
    for fname in files_to_remove:
        try:
            os.remove(os.path.join(upload_dir, fname))
        except OSError:
            pass

    logout_user()
    flash('Your account and all your data have been deleted.', 'success')
    return redirect(url_for('home_intro'))


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


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')

    return render_template('login.html', form=form)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = SignupForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('index'))

    return render_template('signup.html', form=form)

@app.route('/login/email', methods=['GET', 'POST'])
def login_email():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = EmailLoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid email or password.', 'error')

    return render_template('login_email.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

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


# /reports/<token> — public read-only view of a single report.
# `<token>` is the signed URLSafeSerializer-encoded id, not the raw integer,
# so guests can't iterate /reports/1, /reports/2, ... to scrape the database.
@app.route('/reports/<string:token>')
def view_report(token):
    try:
        report_id = _report_serializer().loads(token)
    except BadSignature:
        abort(404)
    report = Report.query.get_or_404(report_id)
    # expired reports get hidden until cleanup deletes them — 404 the URL too
    # so direct links don't leak content scheduled for deletion
    if report.expires_at and report.expires_at <= datetime.utcnow():
        abort(404)
    is_report_favourited = False
    if current_user.is_authenticated:
        is_report_favourited = FavouriteReport.query.filter_by(
            user_id=current_user.id,
            report_id=report.id,
        ).first() is not None
    # is this report currently in the global Trending top 10?
    is_trending = report.id in _trending_report_ids()
    return render_template(
        'report_view.html',
        report=report,
        comment_max_length=COMMENT_MAX_LENGTH,
        is_report_favourited=is_report_favourited,
        is_trending=is_trending,
    )


# POST /api/reports/<id>/vote — verify or dispute a report.
# Only logged-in users; clicking the same status again removes the vote (toggle).
# Authors cannot vote on their own report. Returns updated counts as JSON.
@app.route('/api/reports/<int:report_id>/vote', methods=['POST'])
@login_required
def api_vote_report(report_id):
    report = Report.query.get_or_404(report_id)

    if report.user_id == current_user.id:
        return jsonify({'error': "You can't vote on your own report."}), 400

    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status') or request.form.get('status')
    if new_status not in ('verify', 'dispute'):
        return jsonify({'error': 'Invalid status.'}), 400

    existing = Verification.query.filter_by(
        report_id=report.id, user_id=current_user.id
    ).first()
    if existing:
        if existing.status == new_status:
            # clicked the same button again — toggle off
            db.session.delete(existing)
            user_vote = None
        else:
            existing.status = new_status
            user_vote = new_status
    else:
        db.session.add(Verification(
            report_id=report.id,
            user_id=current_user.id,
            status=new_status,
        ))
        user_vote = new_status
    db.session.commit()

    # Author-level aggregates so the profile UI can update credibility live
    # without a page reload. trust_score is None when the author has no votes
    # at all — JSON-encoded as null so the frontend can show "—".
    # Author is None when the report's owner has deleted their account; the
    # report stays visible but the credibility update has nothing to attach to.
    author = report.author
    return jsonify({
        'verify_count': Verification.query.filter_by(report_id=report.id, status='verify').count(),
        'dispute_count': Verification.query.filter_by(report_id=report.id, status='dispute').count(),
        'user_vote': user_vote,
        'author_id': author.id if author else None,
        'author_verify_total': author.verifications_received if author else 0,
        'author_dispute_total': author.disputes_received if author else 0,
        'author_credibility': author.trust_score if author else None,
    })


# /reports/<id>/edit — GET renders the edit form, POST saves changes
# only the original author can edit; everyone else gets 403
@app.route('/reports/<int:report_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_report_page(report_id):
    report = Report.query.get_or_404(report_id)
    if report.user_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        category_id = request.form.get('category_id', type=int)
        city_id = request.form.get('city_id', type=int)
        description = (request.form.get('description') or '').strip()
        address = (request.form.get('address') or '').strip() or None

        # media edits: user may delete some existing attachments and/or add new ones
        delete_ids = request.form.getlist('delete_media_ids', type=int)
        new_files = [f for f in request.files.getlist('media') if f and f.filename]

        # only allow deleting attachments that actually belong to THIS report
        media_to_delete = [m for m in report.media if m.id in delete_ids]

        # total files after delete + upload must stay under the limit
        remaining_after_delete = len(report.media) - len(media_to_delete)

        # same validation rules as create — category + city required, address optional
        errors = {}
        if not category_id or not Category.query.get(category_id):
            errors['category_id'] = 'Invalid or missing category.'
        if not city_id or not City.query.get(city_id):
            errors['city_id'] = 'Invalid or missing location.'
        if address and len(address) > 200:
            errors['address'] = 'Address must be 200 characters or fewer.'
        if remaining_after_delete + len(new_files) > MAX_MEDIA_FILES:
            errors['media'] = f'Too many attachments (max {MAX_MEDIA_FILES} total).'
        else:
            for f in new_files:
                if not _media_type_for(f.filename):
                    errors['media'] = f'Unsupported file type: {f.filename}'
                    break

        if not errors:
            report.category_id = category_id
            report.city_id = city_id
            report.address = address
            report.description = description

            # delete selected attachments: remove the DB row AND the file on disk
            for m in media_to_delete:
                disk_path = os.path.join(app.config['UPLOAD_FOLDER'], m.filename)
                db.session.delete(m)
                try:
                    os.remove(disk_path)
                except OSError:
                    pass  # file already gone, that's fine

            # save any new uploads (same pattern as the create endpoint)
            saved_paths = []
            try:
                for f in new_files:
                    ext = f.filename.rsplit('.', 1)[-1].lower()
                    stored_name = f'{uuid.uuid4().hex}.{ext}'
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
                    f.save(save_path)
                    saved_paths.append(save_path)
                    db.session.add(ReportMedia(
                        report_id=report.id,
                        filename=stored_name,
                        original_name=secure_filename(f.filename) or stored_name,
                        media_type=_media_type_for(f.filename),
                    ))
                db.session.commit()
            except Exception:
                db.session.rollback()
                for path in saved_paths:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                raise

            flash('Report updated.', 'success')
            return redirect(url_for('profile_page'))

        # validation failed — fall through and re-render the form showing errors
        for msg in errors.values():
            flash(msg, 'error')

    categories = Category.query.order_by(Category.id).all()
    states = State.query.order_by(State.name).all()
    # JS-side lookup: { state_id: [{id, name}, ...] } so the city dropdown
    # can repopulate when the user changes state without a server round-trip
    cities_by_state = {
        s.id: [{'id': c.id, 'name': c.name} for c in s.cities if c.name != 'Fremantle']
        for s in states
    }
    return render_template(
        'report_edit.html',
        report=report,
        categories=categories,
        states=states,
        cities_by_state=cities_by_state,
    )

TRENDING_LIMIT = 10
# Anti-gaming — only verifies / disputes from accounts at least this many
# days old count toward the trending score. The displayed verify_count /
# dispute_count on each card stays unchanged (still totals every vote);
# this only affects which reports rank in the top N.
TRENDING_VOTER_MIN_AGE_DAYS = 7


def _trending_score_components():
    """SQLAlchemy expressions for the trending score, factored out so
    _trending_report_ids() and the listing page sort agree on the formula.
    Counts only verifies / disputes from accounts older than the min age."""
    from sqlalchemy import case
    eligible = db.func.julianday('now') - db.func.julianday(User.created_at) >= TRENDING_VOTER_MIN_AGE_DAYS
    verify_sum = db.func.coalesce(
        db.func.sum(case(((Verification.status == 'verify') & eligible, 1), else_=0)), 0)
    dispute_sum = db.func.coalesce(
        db.func.sum(case(((Verification.status == 'dispute') & eligible, 1), else_=0)), 0)
    days_old = db.func.julianday('now') - db.func.julianday(Report.created_at)
    score_expr = (verify_sum - dispute_sum - days_old).label('score')
    return verify_sum, dispute_sum, days_old, score_expr


def _trending_report_ids():
    """Return the set of report IDs currently in the global Trending top N.
    Matches the Trending page's query exactly so the 🔥 badge on a report
    means the same thing on every page: this report is currently on Trending."""
    _, _, _, score_expr = _trending_score_components()
    rows = (
        db.session.query(Report.id)
        .outerjoin(Verification, Verification.report_id == Report.id)
        .outerjoin(User, User.id == Verification.user_id)
        .group_by(Report.id)
        .order_by(score_expr.desc(), Report.created_at.desc())
        .limit(TRENDING_LIMIT)
        .all()
    )
    return {row[0] for row in rows}


# /listing — list all reports.
# Public — guests can browse without an account.
# Default sort = newest first. ?sort=top is the Trending page.
def _build_listing_response(base_query, feed_mode=None):
    """Shared listing-page handler. base_query is the starting Report.query
    (already pre-filtered by /listing/following if applicable). feed_mode is
    'following' for the From Following page, None for the regular listing —
    template uses it to render the right title.

    Also runs the throttled lazy cleanup of expired reports — this is the
    main public listing endpoint so it's a natural place to garbage-collect."""
    _cleanup_expired_reports()

    page = request.args.get('page', 1, type=int)
    state_id = request.args.get('state_id', type=int)
    city_id = request.args.get('city_id', type=int)
    category_id = request.args.get('category_id', type=int)
    sort = request.args.get('sort', 'recent')   # 'recent' or 'top'

    # Trending is auth-only — but anyone logged in can view it. The
    # account-age requirement applies to whose VOTES count toward the
    # ranking, not who can see the page (see _trending_score_components).
    if sort == 'top' and not current_user.is_authenticated:
        flash('Please log in to view the Trending page.', 'error')
        return redirect(url_for('login'))

    if city_id and not state_id:
        selected_city = City.query.get(city_id)
        if selected_city:
            state_id = selected_city.state_id

    # Wrap base_query with the active-reports filter so expired posts never
    # show up on the listing (regardless of which feed it was called from).
    query = base_query.filter(Report.expires_at > datetime.utcnow())
    # Trending filter options surface only cities / categories that actually
    # appear in the current top 10. Empty until we compute them below.
    trending_filter_cities = []
    trending_filter_categories = []

    if sort != 'top':
        # state filter has to go through City because Report only stores city_id, not state_id
        if state_id:
            query = query.join(City, City.id == Report.city_id).filter(City.state_id == state_id)
        if city_id:
            query = query.filter(Report.city_id == city_id)
        if category_id:
            query = query.filter(Report.category_id == category_id)
    else:
        # On Trending we narrow by city / category WITHIN the top-10 set.
        # State filter doesn't apply (would be redundant with city).
        state_id = None
        trending_ids_set = _trending_report_ids()
        if not trending_ids_set:
            query = query.filter(False)
            top_reports = []
        else:
            query = query.filter(Report.id.in_(trending_ids_set))
            top_reports = (
                base_query.filter(Report.expires_at > datetime.utcnow())
                          .filter(Report.id.in_(trending_ids_set))
                          .all()
            )

        # Drop a stale selection that isn't anywhere in the trending set —
        # avoids confusing "no results" for a filter that doesn't apply.
        global_city_ids = {r.city_id for r in top_reports}
        global_category_ids = {r.category_id for r in top_reports}
        if city_id and city_id not in global_city_ids:
            city_id = None
        if category_id and category_id not in global_category_ids:
            category_id = None

        # Context-aware dropdown options. If you've picked a category, the city
        # dropdown only lists cities that have a trending report in that
        # category — and vice versa. Avoids showing combos with zero results.
        cities_visible = top_reports
        if category_id:
            cities_visible = [r for r in top_reports if r.category_id == category_id]
        cats_visible = top_reports
        if city_id:
            cats_visible = [r for r in top_reports if r.city_id == city_id]
        trending_filter_cities = (
            City.query.filter(City.id.in_({r.city_id for r in cities_visible}))
                       .order_by(City.name).all()
        )
        trending_filter_categories = (
            Category.query.filter(Category.id.in_({r.category_id for r in cats_visible}))
                          .order_by(Category.name).all()
        )

        # Apply the (now-validated) filters to the listing query
        if city_id:
            query = query.filter(Report.city_id == city_id)
        if category_id:
            query = query.filter(Report.category_id == category_id)

    if sort == 'top':
        # Trending score = eligible_verifies − eligible_disputes − days_old.
        # Only votes from accounts older than TRENDING_VOTER_MIN_AGE_DAYS
        # count toward the score; the displayed verify/dispute counts on
        # cards still show every vote.
        _, _, _, score = _trending_score_components()
        query = (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .outerjoin(User, User.id == Verification.user_id)
                 .group_by(Report.id)
                 .order_by(score.desc(), Report.created_at.desc())
        )
    elif sort == 'verifies':
        # Most-verified first — count of verify rows per report. outer-join so
        # reports with zero verifies still appear (just at the bottom).
        from sqlalchemy import case
        verify_count = db.func.count(case((Verification.status == 'verify', 1)))
        query = (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(verify_count.desc(), Report.created_at.desc())
        )
    elif sort == 'disputes':
        # Most-disputed first — same shape as verifies but counts dispute rows.
        from sqlalchemy import case
        dispute_count = db.func.count(case((Verification.status == 'dispute', 1)))
        query = (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(dispute_count.desc(), Report.created_at.desc())
        ) 
    elif sort == 'comments':
        # Most-discussed first — count of comments per report. outer-join so
        # reports with zero comments still show up (just at the bottom).
        comment_count = db.func.count(Comment.id)
        query = (
            query.outerjoin(Comment, Comment.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(comment_count.desc(), Report.created_at.desc())
        )
    elif sort == 'oldest':
        # Oldest first — inverse of the default Recent sort. Useful for users
        # who want to scroll back through historical reports in order.
        query = query.order_by(Report.created_at.asc())
    else:
        query = query.order_by(Report.created_at.desc())

    # Trending is capped to a hard top 10 — no pagination, no scroll-forever.
    # Regular listing keeps the standard 20-per-page pagination.
    if sort == 'top':
        items = query.limit(TRENDING_LIMIT).all()
        class _SinglePagePagination:
            def __init__(self, items):
                self.items = items
                self.has_prev = False
                self.has_next = False
                self.page = 1
                self.pages = 1
            def iter_pages(self, **kwargs):
                return [1]
        pagination = _SinglePagePagination(items)
    else:
        pagination = query.paginate(page=page, per_page=20, error_out=False)

    states = State.query.order_by(State.name).all()
    cities_by_state = {
        s.id: [{'id': sub.id, 'name': sub.name} for sub in s.cities if sub.name != 'Fremantle']
        for s in states
    }
    categories = Category.query.order_by(Category.id).all()

    fav_report_ids = []
    if current_user.is_authenticated:
        fav_report_ids = [
            row.report_id
            for row in FavouriteReport.query.filter_by(user_id=current_user.id).all()
        ]

    # 🔥 fire badge: each city's top-scored report (one per city). Shown on
    # both Trending and View Reports so users can spot the trending pick
    # for their city at a glance.
    trending_ids = _trending_report_ids()

    return render_template(
        'reports_listing.html',
        pagination=pagination,
        states=states,
        cities_by_state=cities_by_state,
        categories=categories,
        selected_state_id=state_id,
        selected_city_id=city_id,
        selected_category_id=category_id,
        sort=sort,
        fav_report_ids=fav_report_ids,
        trending_ids=trending_ids,
        trending_filter_cities=trending_filter_cities,
        trending_filter_categories=trending_filter_categories,
        feed_mode=feed_mode,
    )


@app.route('/listing')
def listing_page():
    return _build_listing_response(Report.query)


@app.route('/listing/following')
@login_required
def listing_following_page():
    """From Following — only reports authored by users the current user follows.
    State / city / category filters and sort still apply on top of this base."""
    followed_ids = [
        row.followed_id
        for row in Follow.query.filter_by(follower_id=current_user.id).all()
    ]
    if not followed_ids:
        # short-circuit to an empty pagination so the empty-state message renders
        # without bothering with a follow-graph join that would return nothing anyway
        base = Report.query.filter(db.literal(False))
    else:
        base = Report.query.filter(Report.user_id.in_(followed_ids))
    return _build_listing_response(base, feed_mode='following')

# /reports — page where a logged-in user fills out and submits a report
@app.route('/reports')
@login_required
def reports_page():
    categories = Category.query.order_by(Category.id).all()
    states = State.query.order_by(State.name).all()
    cities_by_state = {
        s.id: [{'id': sub.id, 'name': sub.name} for sub in s.cities if sub.name != 'Fremantle']
        for s in states
    }
    return render_template(
        'reports.html',
        categories=categories,
        states=states,
        cities_by_state=cities_by_state,
    )


@app.route('/reports/weather')
def live_weather_page():
    """Public Live Weather page — shows a city search and (future) live data."""
    # Build city list with state info (same structure as map_cities)
    db_cities = City.query.order_by(City.name).all()
    weather_cities_data = []
    for c in db_cities:
        coords = CITY_COORDS.get(c.name)
        if not coords:
            continue
        state_name = c.state.name if c.state else ''
        weather_cities_data.append({
            'id': c.id,
            'name': f'{c.name}, {state_name}' if state_name else c.name,
            'short_name': c.name,
            'state': state_name,
            'lat': coords[0],
            'lng': coords[1],
        })
    
    # prefer a requested city from the querystring if it exists in our list
    req_city = (request.args.get('city') or '').strip()
    selected_city = None
    if req_city:
        # match against short_name
        match = next((c for c in weather_cities_data if c['short_name'] == req_city), None)
        if match:
            selected_city = match
    
    return render_template('live_weather.html', weather_cities=weather_cities_data, selected_city=selected_city)

# POST /api/reports — logged-in user submits a report via AJAX
# accepts either JSON (no files) or multipart/form-data (with optional image/video files)
@app.route('/api/reports', methods=['POST'])
@login_required
def api_create_report():
    if request.content_type and 'multipart/form-data' in request.content_type:
        # browser submitted FormData — text fields + files
        data = request.form
        files = [f for f in request.files.getlist('media') if f and f.filename]
    else:
        # plain JSON body, no files
        data = request.get_json(silent=True) or {}
        files = []

    def _to_int(v):
        try:
            return int(v) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None

    category_id = _to_int(data.get('category_id'))
    city_id = _to_int(data.get('city_id'))
    description = (data.get('description') or '').strip()
    address = (data.get('address') or '').strip() or None   # store None instead of empty string

    # server-side validation — description, address, media are optional; category and city are required
    errors = {}
    if not category_id or not Category.query.get(category_id):
        errors['category_id'] = 'Invalid or missing category.'
    if not city_id or not City.query.get(city_id):
        errors['city_id'] = 'Invalid or missing location.'
    if address and len(address) > 200:
        errors['address'] = 'Address must be 200 characters or fewer.'
    if len(files) > MAX_MEDIA_FILES:
        errors['media'] = f'Too many files (max {MAX_MEDIA_FILES}).'
    else:
        for f in files:
            if not _media_type_for(f.filename):
                errors['media'] = f'Unsupported file type: {f.filename}'
                break

    if errors:
        return jsonify({'errors': errors}), 400

    report = Report(
        user_id=current_user.id,
        category_id=category_id,
        city_id=city_id,
        address=address,
        description=description,
    )
    db.session.add(report)
    db.session.flush()  # assign report.id so ReportMedia rows can reference it

    # save each file with a UUID name, then record it in report_media
    # if anything fails halfway, clean up the disk files we already wrote so we don't leak
    saved_paths = []
    try:
        for f in files:
            ext = f.filename.rsplit('.', 1)[-1].lower()
            stored_name = f'{uuid.uuid4().hex}.{ext}'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
            f.save(save_path)
            saved_paths.append(save_path)

            db.session.add(ReportMedia(
                report_id=report.id,
                filename=stored_name,
                original_name=secure_filename(f.filename) or stored_name,
                media_type=_media_type_for(f.filename),
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        for path in saved_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        raise

    # response includes media URLs so the frontend can show thumbnails immediately,
    # and view_url so the client can redirect to the single-report page when the
    # user unchecks "create another"
    return jsonify({
        'id': report.id,
        'user_id': report.user_id,
        'category_id': report.category_id,
        'city_id': report.city_id,
        'city_name': report.city.name,
        'state_code': report.city.state.code,
        'address': report.address,
        'description': report.description,
        'created_at': report.created_at.isoformat(),
        'view_url': url_for('view_report', token=_encode_report_id(report.id)),
        'media': [
            {
                'id': m.id,
                'type': m.media_type,
                'original_name': m.original_name,
                'url': url_for('static', filename=f'uploads/{m.filename}'),
            }
            for m in report.media
        ],
    }), 201


@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
@login_required
def api_delete_report(report_id):
    """Author-only — wipes the report, its media (DB rows + disk files), and any votes."""
    report = Report.query.get_or_404(report_id)
    if report.user_id != current_user.id:
        return jsonify({'error': "You can't delete someone else's report."}), 403

    # remove media files from disk first; the DB rows go via cascade on the relationship
    for m in report.media:
        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], m.filename)
        try:
            os.remove(disk_path)
        except OSError:
            pass  # file already gone — fine

    # also remove on-disk media attached to each comment, and clear comment votes
    # (comments themselves cascade-delete with the report; CommentMedia rows cascade
    # with the comment; but the disk files and CommentVote rows need manual cleanup)
    for c in report.comments:
        for m in c.media:
            disk_path = os.path.join(app.config['UPLOAD_FOLDER'], m.filename)
            try:
                os.remove(disk_path)
            except OSError:
                pass
        CommentVote.query.filter_by(comment_id=c.id).delete()

    # Verification has no cascade on the model, so clear them by hand
    Verification.query.filter_by(report_id=report.id).delete()

    db.session.delete(report)
    db.session.commit()
    return jsonify({'ok': True})


# ---------------- Comments ----------------
# Body is stored as plain text and rendered with Jinja's default auto-escape, so
# HTML/JS in user input becomes inert text in the page (XSS-safe). The frontend
# also uses textContent (not innerHTML) when injecting new comments without a reload.

COMMENT_MAX_LENGTH = 2000

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