import os
import uuid
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from .models import db, User, Category, Report, State, Suburb, ReportMedia
from .forms import LoginForm, EmailLoginForm, SignupForm

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
@login_required
def index():
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

# /reports — page where a logged-in user fills out and submits a report
@app.route('/reports')
@login_required
def reports_page():
    categories = Category.query.order_by(Category.id).all()
    states = State.query.order_by(State.name).all()
    # build a plain dict the template can dump as JSON for the suburb cascade
    suburbs_by_state = {
        s.id: [{'id': sub.id, 'name': sub.name} for sub in s.suburbs]
        for s in states
    }
    return render_template(
        'reports.html',
        categories=categories,
        states=states,
        suburbs_by_state=suburbs_by_state,
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
    suburb_id = _to_int(data.get('suburb_id'))
    description = (data.get('description') or '').strip()
    address = (data.get('address') or '').strip() or None   # store None instead of empty string

    # server-side validation — description, address, media are optional; category and suburb are required
    errors = {}
    if not category_id or not Category.query.get(category_id):
        errors['category_id'] = 'Invalid or missing category.'
    if not suburb_id or not Suburb.query.get(suburb_id):
        errors['suburb_id'] = 'Invalid or missing location.'
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
        suburb_id=suburb_id,
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

    # response includes media URLs so the frontend can show thumbnails immediately
    return jsonify({
        'id': report.id,
        'user_id': report.user_id,
        'category_id': report.category_id,
        'suburb_id': report.suburb_id,
        'suburb_name': report.suburb.name,
        'state_code': report.suburb.state.code,
        'address': report.address,
        'description': report.description,
        'created_at': report.created_at.isoformat(),
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
