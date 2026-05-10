"""Report-related routes — listing, view, create, edit, delete, vote, plus
the Trending page and From-Following feed. Owns the report-token Jinja
filter and the expiry-banner context processor as well."""
import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeSerializer, BadSignature
from datetime import datetime, timedelta
 
from ..models import (
    db, User, Category, Report, State, City, ReportMedia, Verification,
    Comment, CommentVote, Follow, FavouriteReport,
)
 
bp = Blueprint('reports', __name__)
 
 
# ============================================================
# Constants
# ============================================================
 
# whitelist of file types the upload endpoint accepts
ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
ALLOWED_VIDEO_EXTS = {'mp4', 'webm', 'mov'}
MAX_MEDIA_FILES = 5
 
TRENDING_LIMIT = 10
# Anti-gaming — only verifies / disputes from accounts at least this many
# days old count toward the trending score. The displayed verify_count /
# dispute_count on each card stays unchanged (still totals every vote);
# this only affects which reports rank in the top N.
TRENDING_VOTER_MIN_AGE_DAYS = 7
 
# Body cap for new comments — kept here because view_report passes it to
# the template; the comment endpoints themselves live in blueprints/api.py.
COMMENT_MAX_LENGTH = 2000
 
# Track when the lazy cleanup last ran so we don't hammer the DB on every
# listing render. Module-level (per-process) state — fine for single-worker
# dev / a single gunicorn process. For multi-worker prod we'd promote this
# into the DB or a cron job.
_LAST_REPORT_CLEANUP = None
_REPORT_CLEANUP_INTERVAL_MIN = 5
 
 
# ============================================================
# Helpers — query, expiry cleanup, trending score, token encoding
# ============================================================
 
def _active_reports_q():
    """Base query for reports still within their expiry window. Use this
    everywhere reports are rendered to a guest or non-author audience so
    expired stuff doesn't leak."""
    return Report.query.filter(Report.expires_at > datetime.utcnow())
 
 
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
 
    upload_dir = current_app.config['UPLOAD_FOLDER']
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
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='report-id')
 
 
@bp.app_template_filter('report_token')
def _encode_report_id(report_id):
    """Jinja filter: turn a Report.id into the opaque URL token."""
    return _report_serializer().dumps(report_id)
 
 
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
 
 
# ============================================================
# Context processor — site-wide expiry banner
# ============================================================
 
@bp.app_context_processor
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
 
 
# ============================================================
# Routes — view, vote, edit
# ============================================================
 
@bp.route('/reports/<string:token>')
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
@bp.route('/api/reports/<int:report_id>/vote', methods=['POST'])
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
@bp.route('/reports/<int:report_id>/edit', methods=['GET', 'POST'])
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
                disk_path = os.path.join(current_app.config['UPLOAD_FOLDER'], m.filename)
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
                    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
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
 
 
# ============================================================
# Listing page + From-Following feed (shared handler)
# ============================================================
 
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
        return redirect(url_for('auth.login'))
 
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
 
 
@bp.route('/listing')
def listing_page():
    return _build_listing_response(Report.query)
 
 
@bp.route('/listing/following')
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
 
 
# ============================================================
# Create + delete report
# ============================================================
 
# /reports — page where a logged-in user fills out and submits a report
@bp.route('/reports')
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
@bp.route('/api/reports', methods=['POST'])
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
            save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
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
        'view_url': url_for('reports.view_report', token=_encode_report_id(report.id)),
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
 
 
@bp.route('/api/reports/<int:report_id>', methods=['DELETE'])
@login_required
def api_delete_report(report_id):
    """Author-only — wipes the report, its media (DB rows + disk files), and any votes."""
    report = Report.query.get_or_404(report_id)
    if report.user_id != current_user.id:
        return jsonify({'error': "You can't delete someone else's report."}), 403
 
    # remove media files from disk first; the DB rows go via cascade on the relationship
    for m in report.media:
        disk_path = os.path.join(current_app.config['UPLOAD_FOLDER'], m.filename)
        try:
            os.remove(disk_path)
        except OSError:
            pass  # file already gone — fine
 
    # also remove on-disk media attached to each comment, and clear comment votes
    # (comments themselves cascade-delete with the report; CommentMedia rows cascade
    # with the comment; but the disk files and CommentVote rows need manual cleanup)
    for c in report.comments:
        for m in c.media:
            disk_path = os.path.join(current_app.config['UPLOAD_FOLDER'], m.filename)
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
 
 