import os
import uuid
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeSerializer, BadSignature
from datetime import datetime
from .models import db, User, Category, Report, State, City, ReportMedia, Verification, Comment, CommentMedia, CommentVote, Follow, Conversation, ChatMessage, ChatMessageMedia, FavouriteLocation, FavouriteReport
from .forms import LoginForm, EmailLoginForm, SignupForm

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
        # small convenience stat: how many reports exist for this city
        reports_today = Report.query.filter_by(city_id=city.id).count()
        # latest report time (for "Last Update")
        last_report = Report.query.filter_by(city_id=city.id).order_by(Report.created_at.desc()).first()
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
    safety check, then wipes:
      - their reports (cascade-deletes attached media DB rows + we remove
        the on-disk files manually since SQLAlchemy doesn't know about them)
      - their comments anywhere on the site (+ their media)
      - their verifications, comment-votes, follow edges (both directions)
      - every conversation they're part of (cascades messages + message media)
      - the user row itself
    """
    if not current_user.check_password(request.form.get('password') or ''):
        flash('Incorrect password — account not deleted.', 'error')
        return redirect(url_for('settings_page'))

    user = current_user._get_current_object()
    upload_dir = app.config['UPLOAD_FOLDER']

    # collect every on-disk file we'll need to remove (reports' media,
    # comments' media on others' reports, chat message media)
    files_to_remove = set()
    for report in list(user.reports):
        for m in report.media:
            files_to_remove.add(m.filename)
        for c in report.comments:
            for m in c.media:
                files_to_remove.add(m.filename)
    other_comments = Comment.query.filter_by(user_id=user.id).all()
    for c in other_comments:
        for m in c.media:
            files_to_remove.add(m.filename)
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

    # delete user's comments on other people's reports (cascade kills media DB rows)
    for c in other_comments:
        db.session.delete(c)

    # delete user's reports — but first clear other users' votes/comment-votes
    # on those reports (no cascade for Verification / CommentVote)
    for report in list(user.reports):
        Verification.query.filter_by(report_id=report.id).delete(synchronize_session=False)
        for c in report.comments:
            CommentVote.query.filter_by(comment_id=c.id).delete(synchronize_session=False)
        db.session.delete(report)

    # delete conversations involving this user (cascades messages + message-media DB rows)
    for conv in convs:
        db.session.delete(conv)

    db.session.delete(user)
    db.session.commit()

    # wipe disk files after the DB transaction succeeds
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

    # real top-trending city = city with the most reports overall
    top_city_row = (
        db.session.query(City.name, db.func.count(Report.id))
        .join(Report, Report.city_id == City.id)
        .group_by(City.id)
        .order_by(db.func.count(Report.id).desc())
        .first()
    )
    top_city = {'name': top_city_row[0], 'count': top_city_row[1]} if top_city_row else None

    # real top-trending category = category with the most reports overall
    top_cat_row = (
        db.session.query(Category.name, db.func.count(Report.id))
        .join(Report, Report.category_id == Category.id)
        .group_by(Category.id)
        .order_by(db.func.count(Report.id).desc())
        .first()
    )
    top_category = {'name': top_cat_row[0], 'count': top_cat_row[1]} if top_cat_row else None

    return {
        'city_ids_by_name': city_ids,
        'category_ids_by_name': category_ids,
        'city_to_state': CITY_TO_STATE,
        'state_flag_url': STATE_FLAG_URL,
        'top_city': top_city,
        'top_category': top_category,
    }


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
    )

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
        .order_by(User.username)
        .limit(10)
        .all()
    )
    return jsonify([
        {
            'username': u.username,
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
    })


@app.route('/api/conversations')
@login_required
def api_list_conversations():
    """Return chats and requests as two separate lists, both newest-first."""
    convs = Conversation.query.filter(
        db.or_(Conversation.user_a_id == current_user.id,
               Conversation.user_b_id == current_user.id)
    ).order_by(Conversation.last_message_at.desc()).all()

    chats = []
    requests_list = []
    for conv in convs:
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
        return jsonify({'messages': [], 'accepted': False, 'is_request': False})

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
    is_report_favourited = False
    if current_user.is_authenticated:
        is_report_favourited = FavouriteReport.query.filter_by(
            user_id=current_user.id,
            report_id=report.id,
        ).first() is not None
    return render_template(
        'report_view.html',
        report=report,
        comment_max_length=COMMENT_MAX_LENGTH,
        is_report_favourited=is_report_favourited,
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
    author = report.author
    return jsonify({
        'verify_count': Verification.query.filter_by(report_id=report.id, status='verify').count(),
        'dispute_count': Verification.query.filter_by(report_id=report.id, status='dispute').count(),
        'user_vote': user_vote,
        'author_id': author.id,
        'author_verify_total': author.verifications_received,
        'author_dispute_total': author.disputes_received,
        'author_credibility': author.trust_score,
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

# /listing — list all reports.
# Default sort = newest first. ?sort=top is the Trending page, gated to
# logged-in users whose accounts are at least 1 day old (anti-spam).
@app.route('/listing')
def listing_page():
    page = request.args.get('page', 1, type=int)
    state_id = request.args.get('state_id', type=int)
    city_id = request.args.get('city_id', type=int)
    category_id = request.args.get('category_id', type=int)
    sort = request.args.get('sort', 'recent')   # 'recent' or 'top'

    # Trending is auth-only + account-age-gated. Bounce guests + brand-new
    # accounts back to the regular listing with a friendly message instead
    # of letting them see a stripped/empty page.
    if sort == 'top':
        if not current_user.is_authenticated:
            flash('Please log in to view the Trending page.', 'error')
            return redirect(url_for('login'))
        if not current_user.can_view_trending:
            flash('Trending is available once your account is at least 1 day old.', 'error')
            return redirect(url_for('listing_page'))

    if city_id and not state_id:
        selected_city = City.query.get(city_id)
        if selected_city:
            state_id = selected_city.state_id

    query = Report.query
    # Trending shows the global top across every category and city — filters
    # don't apply. The regular listing keeps state/city/category filtering.
    if sort != 'top':
        # state filter has to go through City because Report only stores city_id, not state_id
        if state_id:
            query = query.join(City, City.id == Report.city_id).filter(City.state_id == state_id)
        if city_id:
            query = query.filter(Report.city_id == city_id)
        if category_id:
            query = query.filter(Report.category_id == category_id)
    else:
        # zero out the "selected" values so the template's filter UI (now hidden
        # on Trending anyway) doesn't reflect stale selections
        state_id = None
        city_id = None
        category_id = None

    if sort == 'top':
        # Trending score = verifies − disputes − days_old. Reports get one point
        # of decay per day, so fresh + popular reports float to the top while
        # old ones sink even if they were once highly verified.
        # SQLite julianday gives the difference in days directly.
        from sqlalchemy import case
        verify_sum = db.func.coalesce(
            db.func.sum(case((Verification.status == 'verify', 1), else_=0)), 0)
        dispute_sum = db.func.coalesce(
            db.func.sum(case((Verification.status == 'dispute', 1), else_=0)), 0)
        days_old = db.func.julianday('now') - db.func.julianday(Report.created_at)
        score = verify_sum - dispute_sum - days_old
        query = (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(score.desc(), Report.created_at.desc())
        )
    else:
        query = query.order_by(Report.created_at.desc())
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
    )

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
    return {
        'id': comment.id,
        'body': comment.body,
        'author_username': comment.author.username,
        'author_url': url_for('user_profile_page', username=comment.author.username),
        'author_initial': comment.author.username[:1].upper(),
        'author_avatar_url': (url_for('static', filename=f'uploads/{comment.author.avatar_filename}')
                              if comment.author.avatar_filename else None),
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