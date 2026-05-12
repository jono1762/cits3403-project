"""Auth + account-management routes — login, signup, logout, settings,
profile editing, account deletion."""
import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from email_validator import validate_email, EmailNotValidError
 
from ..models import (
    db, User, Report, Comment, Verification, Follow, CommentVote,
    FavouriteLocation, FavouriteReport, Conversation,
)
from ..forms import LoginForm, EmailLoginForm, SignupForm
 
bp = Blueprint('auth', __name__)
 
 
ALLOWED_AVATAR_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5MB
 
# Magic-byte signatures so a renamed evil.exe can't slip past the extension
# whitelist. Reading the actual file header is the real check.
_IMAGE_MAGIC = (
    (b'\xff\xd8\xff',                            'jpg'),
    (b'\x89PNG\r\n\x1a\n',                       'png'),
    (b'GIF87a',                                  'gif'),
    (b'GIF89a',                                  'gif'),
)
 
 
def _sniff_image_type(stream):
    """Return one of {'jpg', 'png', 'gif', 'webp'} if the stream's first bytes
    look like a real image, else None. Stream position is restored."""
    pos = stream.tell()
    head = stream.read(12)
    stream.seek(pos)
    for sig, kind in _IMAGE_MAGIC:
        if head.startswith(sig):
            return kind
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    return None
 
 
BIO_MAX_LENGTH = 500
 
 
@bp.route('/login', methods=['GET', 'POST'])
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
 
 
@bp.route('/signup', methods=['GET', 'POST'])
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
 
 
@bp.route('/login/email', methods=['GET', 'POST'])
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
 
 
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
 
 
@bp.route('/settings', methods=['GET'])
@login_required
def settings_page():
    return render_template('settings.html')
 
 
@bp.route('/settings/account', methods=['POST'])
@login_required
def settings_update_account():
    """Update username and email. Re-uses User uniqueness rules; same
    email-validator check as the signup form."""
    username = (request.form.get('username') or '').strip()
    raw_email = (request.form.get('email') or '').strip()
 
    if not username or len(username) > 80:
        flash('Username must be 1-80 characters.', 'error')
        return redirect(url_for('auth.settings_page'))
 
    # email-validator does the real work: rejects garbage like "aaaa@aaaa",
    # checks domain has a TLD, normalizes Unicode + uppercase. DNS check off
    # because it makes a real network call (slow + fails offline).
    try:
        valid = validate_email(raw_email, check_deliverability=False)
        email = valid.normalized.lower()
    except EmailNotValidError:
        flash('Invalid email address.', 'error')
        return redirect(url_for('auth.settings_page'))
    if len(email) > 120:
        flash('Email is too long (max 120 characters).', 'error')
        return redirect(url_for('auth.settings_page'))
 
    # uniqueness — only check if the value actually changed (otherwise we'd
    # always trip the constraint against the user's own row)
    if username != current_user.username:
        if User.query.filter_by(username=username).first():
            flash('That username is already taken.', 'error')
            return redirect(url_for('auth.settings_page'))
    if email != current_user.email:
        if User.query.filter_by(email=email).first():
            flash('That email is already in use.', 'error')
            return redirect(url_for('auth.settings_page'))
 
    current_user.username = username
    current_user.email = email
    db.session.commit()
    flash('Account details updated.', 'success')
    return redirect(url_for('auth.settings_page'))
 
 
@bp.route('/settings/password', methods=['POST'])
@login_required
def settings_update_password():
    """Change password — requires the current password and a matching confirmation."""
    current_pw = request.form.get('current_password') or ''
    new_pw = request.form.get('new_password') or ''
    confirm_pw = request.form.get('confirm_password') or ''
 
    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('auth.settings_page'))
    if len(new_pw) < 8:
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('auth.settings_page'))
    if new_pw != confirm_pw:
        flash("New password and confirmation don't match.", 'error')
        return redirect(url_for('auth.settings_page'))
 
    current_user.set_password(new_pw)
    db.session.commit()
    flash('Password updated.', 'success')
    return redirect(url_for('auth.settings_page'))
 
 
@bp.route('/api/settings/verify-password', methods=['POST'])
@login_required
def api_verify_password():
    """AJAX endpoint used by the Settings page to gate the 'change password'
    fields — JS calls this as the user types the current password and only
    unlocks the new-password inputs when the answer comes back ok=True."""
    payload = request.get_json(silent=True) or {}
    pw = payload.get('current_password') or ''
    return jsonify({'ok': bool(pw) and current_user.check_password(pw)})
 
 
@bp.route('/profile/edit', methods=['GET'])
@login_required
def profile_edit_page():
    """Profile-public details (avatar, bio). Account / security stuff
    (email, password, delete) lives on /settings instead."""
    return render_template('profile_edit.html', bio_max_length=BIO_MAX_LENGTH)
 
 
@bp.route('/profile/edit/bio', methods=['POST'])
@login_required
def profile_edit_bio():
    """Update the profile bio. Empty string clears it (falls back to the
    'add a bio' prompt on the user's own profile)."""
    bio = (request.form.get('bio') or '').strip() or None
    if bio and len(bio) > BIO_MAX_LENGTH:
        flash(f'Bio must be {BIO_MAX_LENGTH} characters or fewer.', 'error')
        return redirect(url_for('auth.profile_edit_page'))
    current_user.bio = bio
    db.session.commit()
    flash('Bio updated.', 'success')
    return redirect(url_for('auth.profile_edit_page'))
 
 
@bp.route('/settings/avatar', methods=['POST'])
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
        return redirect(url_for('auth.profile_edit_page'))
 
    # 2. extension whitelist
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_AVATAR_EXTS:
        flash(f'Unsupported file type. Use one of: {", ".join(sorted(ALLOWED_AVATAR_EXTS))}.', 'error')
        return redirect(url_for('auth.profile_edit_page'))
 
    # 3. size cap — measure by seeking to the end, then rewind for save()
    f.stream.seek(0, os.SEEK_END)
    size = f.stream.tell()
    f.stream.seek(0)
    if size > AVATAR_MAX_BYTES:
        flash(f'Image is too large (max {AVATAR_MAX_BYTES // (1024 * 1024)}MB).', 'error')
        return redirect(url_for('auth.profile_edit_page'))
 
    # 4. magic-byte sniff — confirms the file ACTUALLY is an image of an
    #    accepted format, not just something with a friendly extension
    sniffed = _sniff_image_type(f.stream)
    if sniffed is None:
        flash('That file does not look like a valid image.', 'error')
        return redirect(url_for('auth.profile_edit_page'))
 
    # 5. save with a fresh UUID name + canonical extension from the sniff
    stored_name = f'{uuid.uuid4().hex}.{sniffed}'
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
    f.save(save_path)
 
    # remove the previous avatar from disk before swapping the DB pointer
    old = current_user.avatar_filename
    current_user.avatar_filename = stored_name
    db.session.commit()
    if old:
        try:
            os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], old))
        except OSError:
            pass
 
    flash('Profile picture updated.', 'success')
    return redirect(url_for('auth.profile_edit_page'))
 
 
@bp.route('/settings/avatar/remove', methods=['POST'])
@login_required
def settings_remove_avatar():
    """Drop the current avatar. Falls back to the initial-letter avatar everywhere."""
    old = current_user.avatar_filename
    if not old:
        return redirect(url_for('auth.profile_edit_page'))
    current_user.avatar_filename = None
    db.session.commit()
    try:
        os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], old))
    except OSError:
        pass
    flash('Profile picture removed.', 'success')
    return redirect(url_for('auth.profile_edit_page'))
 
 
@bp.route('/settings/delete', methods=['POST'])
@login_required
def settings_delete_account():
    """Permanent account deletion. Requires the user's password as a final
    safety check. Reports and comments authored by the user are KEPT so other
    users' threads stay coherent — their author column is set to NULL and the
    UI renders the byline as "deleted_user". The user-specific stuff (votes,
    follows, conversations) still gets wiped."""
    if not current_user.check_password(request.form.get('password') or ''):
        flash('Incorrect password — account not deleted.', 'error')
        return redirect(url_for('auth.settings_page'))
 
    user = current_user._get_current_object()
    upload_dir = current_app.config['UPLOAD_FOLDER']
 
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
 