import os
import uuid
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeSerializer, BadSignature
from .models import db, User, Category, Report, State, Suburb, ReportMedia, Verification
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
    # logged-out users see the landing page; logged-in users go to the map
    # (redirect rather than render so map_page() supplies the data context)
    if not current_user.is_authenticated:
        return render_template('landing.html')
    return redirect(url_for('map_page'))

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


# /favourites — saved suburbs + saved reports for the logged-in user.
# Backend doesn't actually persist favourites yet — page renders placeholder
# items so the UI exists. Wire to a real Favourite model later.
@app.route('/favourites')
@login_required
def favourites_page():
    fake_suburbs = [
        {'name': 'Bondi', 'state_code': 'NSW', 'reports_today': 8},
        {'name': 'Stirling', 'state_code': 'WA', 'reports_today': 3},
        {'name': 'Yarra Trail', 'state_code': 'VIC', 'reports_today': 5},
    ]
    fake_reports = [
        {'category': 'Weather',  'color': '#3498db', 'title': 'Storm warning issued',  'where': 'Bondi · NSW',     'when': '24 min ago'},
        {'category': 'Hazards',  'color': '#e67e22', 'title': 'Tree down at Yarra',    'where': 'Melbourne · VIC', 'when': '5 min ago'},
        {'category': 'Traffic',  'color': '#f1c40f', 'title': 'Mitchell Fwy backed up','where': 'Perth · WA',      'when': '8 min ago'},
    ]
    return render_template(
        'favourites.html',
        fake_suburbs=fake_suburbs,
        fake_reports=fake_reports,
    )


# /settings — UI-only stub. Renders the form, accepts POST, flashes a
# success message, but doesn't persist anything yet. Wire to real
# username/email/password update logic in a follow-up branch.
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    if request.method == 'POST':
        flash('Settings saved.', 'success')
        return redirect(url_for('settings_page'))
    return render_template('settings.html')


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
    # public map view — used by the "Start as guest" button on the landing page
    suburb_ids = {s.name: s.id for s in Suburb.query.all()}
    category_ids = {c.name: c.id for c in Category.query.all()}

    # real top-trending city = suburb with the most reports overall
    top_city_row = (
        db.session.query(Suburb.name, db.func.count(Report.id))
        .join(Report, Report.suburb_id == Suburb.id)
        .group_by(Suburb.id)
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

    return render_template(
        'index.html',
        suburb_ids_by_name=suburb_ids,
        category_ids_by_name=category_ids,
        city_to_state=CITY_TO_STATE,
        state_flag_url=STATE_FLAG_URL,
        top_city=top_city,
        top_category=top_category,
    )

# /landing — always renders the landing/intro page regardless of auth state.
# Lets logged-in users revisit the public-facing home if they want.
@app.route('/landing')
def home_landing():
    return render_template('landing.html')

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
    return render_template('report_view.html', report=report)


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

    return jsonify({
        'verify_count': Verification.query.filter_by(report_id=report.id, status='verify').count(),
        'dispute_count': Verification.query.filter_by(report_id=report.id, status='dispute').count(),
        'user_vote': user_vote,
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
        suburb_id = request.form.get('suburb_id', type=int)
        description = (request.form.get('description') or '').strip()
        address = (request.form.get('address') or '').strip() or None

        # media edits: user may delete some existing attachments and/or add new ones
        delete_ids = request.form.getlist('delete_media_ids', type=int)
        new_files = [f for f in request.files.getlist('media') if f and f.filename]

        # only allow deleting attachments that actually belong to THIS report
        media_to_delete = [m for m in report.media if m.id in delete_ids]

        # total files after delete + upload must stay under the limit
        remaining_after_delete = len(report.media) - len(media_to_delete)

        # same validation rules as create — category + suburb required, address optional
        errors = {}
        if not category_id or not Category.query.get(category_id):
            errors['category_id'] = 'Invalid or missing category.'
        if not suburb_id or not Suburb.query.get(suburb_id):
            errors['suburb_id'] = 'Invalid or missing location.'
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
            report.suburb_id = suburb_id
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
    suburbs_by_state = {
        s.id: [{'id': sub.id, 'name': sub.name} for sub in s.suburbs]
        for s in states
    }
    return render_template(
        'report_edit.html',
        report=report,
        categories=categories,
        states=states,
        suburbs_by_state=suburbs_by_state,
    )

# /listing — list all reports.
# Public — guests can browse without an account.
# Default sort = newest first; ?sort=top sorts by verification count (top reports).
@app.route('/listing')
def listing_page():
    page = request.args.get('page', 1, type=int)
    state_id = request.args.get('state_id', type=int)
    suburb_id = request.args.get('suburb_id', type=int)
    category_id = request.args.get('category_id', type=int)
    sort = request.args.get('sort', 'recent')   # 'recent' or 'top'

    query = Report.query
    # state filter has to go through Suburb because Report only stores suburb_id, not state_id
    if state_id:
        query = query.join(Suburb, Suburb.id == Report.suburb_id).filter(Suburb.state_id == state_id)
    if suburb_id:
        query = query.filter(Report.suburb_id == suburb_id)
    if category_id:
        query = query.filter(Report.category_id == category_id)

    if sort == 'top':
        # outer-join + group + count so reports with zero verifications still appear
        query = (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(db.func.count(Verification.id).desc(), Report.created_at.desc())
        )
    else:
        query = query.order_by(Report.created_at.desc())
    pagination = query.paginate(page=page, per_page=20, error_out=False)

    # dropdown data — same shape the create form uses, so the cascade JS is identical
    states = State.query.order_by(State.name).all()
    suburbs_by_state = {
        s.id: [{'id': sub.id, 'name': sub.name} for sub in s.suburbs]
        for s in states
    }
    categories = Category.query.order_by(Category.id).all()

    return render_template(
        'reports_listing.html',
        pagination=pagination,
        states=states,
        suburbs_by_state=suburbs_by_state,
        categories=categories,
        selected_state_id=state_id,
        selected_suburb_id=suburb_id,
        selected_category_id=category_id,
        sort=sort,
    )

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