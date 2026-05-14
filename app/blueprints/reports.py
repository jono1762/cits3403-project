"""Report-related routes — listing, view, create, edit, delete, vote, plus
the Trending page and From-Following feed. Owns the report-token Jinja
filter and the expiry-banner context processor as well."""
import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeSerializer, BadSignature
from markupsafe import Markup
from datetime import datetime, timedelta
 
from ..models import (
    db, User, Category, Report, State, City, ReportMedia, Verification,
    Comment, CommentVote, Follow, FavouriteReport,
)
 
bp = Blueprint('reports', __name__)
 
 
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
 
 
# Magic-byte signatures for each accepted format. Used by _sniff_media_type so
# renaming a binary (evil.exe → evil.png) can't fool the upload endpoints —
# we inspect the actual file content, not the user-supplied extension.
_IMAGE_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'\xff\xd8\xff',      'jpg'),
    (b'GIF87a',            'gif'),
    (b'GIF89a',            'gif'),
)


def _sniff_media_type(stream):
    """Return (media_type, ext) — e.g. ('image', 'png') or ('video', 'mp4') —
    if the stream's first bytes match a whitelisted format, else None. Stream
    position is restored so the caller can still save the file afterwards."""
    pos = stream.tell()
    head = stream.read(16)
    stream.seek(pos)

    for sig, kind in _IMAGE_MAGIC:
        if head.startswith(sig):
            return ('image', kind)
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return ('image', 'webp')

    # MP4 / MOV / M4V — ISO Base Media File Format. Box layout: 4-byte size,
    # 4-byte type 'ftyp', 4-byte major brand. QuickTime brand 'qt  ' = .mov,
    # everything else (isom, mp42, iso5, ...) maps to .mp4 for our purposes.
    if len(head) >= 12 and head[4:8] == b'ftyp':
        brand = head[8:12]
        return ('video', 'mov' if brand == b'qt  ' else 'mp4')

    # WebM / Matroska — EBML header
    if head[:4] == b'\x1A\x45\xDF\xA3':
        return ('video', 'webm')

    return None


def _validate_uploads(files):
    """Sniff each uploaded file via _sniff_media_type. Returns a 2-tuple:
        (sniffs, None) on success — sniffs is a list of (media_type, ext)
        (None, error)  on first failure — error is a user-facing string
    Lets each caller pick its own error-reporting style (JSON return vs
    errors-dict)."""
    sniffs = []
    for f in files:
        s = _sniff_media_type(f.stream)
        if not s:
            return None, f'"{f.filename}" is not a valid image or video.'
        sniffs.append(s)
    return sniffs, None


def _to_int(v):
    """Parse a form/JSON value to int, returning None for empty / invalid input."""
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
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
    means the same thing on every page: this report is currently on Trending.
    Active-only filter mirrors _active_reports_q so reports the listing would
    hide can never poison the trending top-N."""
    _, _, _, score_expr = _trending_score_components()
    rows = (
        db.session.query(Report.id)
        .filter(Report.expires_at > datetime.utcnow())
        .outerjoin(Verification, Verification.report_id == Report.id)
        .outerjoin(User, User.id == Verification.user_id)
        .group_by(Report.id)
        .order_by(score_expr.desc(), Report.created_at.desc())
        .limit(TRENDING_LIMIT)
        .all()
    )
    return {row[0] for row in rows}
 
 
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
        new_sniffs = []
        if remaining_after_delete + len(new_files) > MAX_MEDIA_FILES:
            errors['media'] = f'Too many attachments (max {MAX_MEDIA_FILES} total).'
        else:
            sniffs, err = _validate_uploads(new_files)
            if err:
                errors['media'] = err
            else:
                new_sniffs = sniffs
 
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
                for f, (media_type, ext) in zip(new_files, new_sniffs):
                    stored_name = f'{uuid.uuid4().hex}.{ext}'
                    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
                    f.save(save_path)
                    saved_paths.append(save_path)
                    db.session.add(ReportMedia(
                        report_id=report.id,
                        filename=stored_name,
                        original_name=secure_filename(f.filename) or stored_name,
                        media_type=media_type,
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
            return redirect(url_for('users.profile_page'))
 
        # validation failed — fall through and re-render the form showing errors
        for msg in errors.values():
            flash(msg, 'error')
 
    categories = Category.query.order_by(Category.id).all()
    states = State.query.order_by(State.name).all()
    # JS-side lookup: { state_id: [{id, name}, ...] } so the city dropdown
    # can repopulate when the user changes state without a server round-trip
    cities_by_state = {
        s.id: [{'id': c.id, 'name': c.name} for c in s.cities]
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
# Public — guests can browse without an account.
# Default sort = newest first. ?sort=top is the legacy Trending URL,
# kept working via the feed_trending toggle on this consolidated page.
def _apply_basic_filters(query, state_id, city_id, category_id):
    """state / city / category dropdown filters. State goes through City
    because Report only stores city_id."""
    if state_id:
        query = query.join(City, City.id == Report.city_id).filter(City.state_id == state_id)
    if city_id:
        query = query.filter(Report.city_id == city_id)
    if category_id:
        query = query.filter(Report.category_id == category_id)
    return query


def _apply_listing_sort(query, sort):
    """Apply ORDER BY for the chosen sort mode. The outer-joins keep
    reports with zero votes / comments visible (at the bottom) rather
    than dropping them."""
    if sort == 'verifies':
        from sqlalchemy import case
        verify_count = db.func.count(case((Verification.status == 'verify', 1)))
        return (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(verify_count.desc(), Report.created_at.desc())
        )
    if sort == 'disputes':
        from sqlalchemy import case
        dispute_count = db.func.count(case((Verification.status == 'dispute', 1)))
        return (
            query.outerjoin(Verification, Verification.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(dispute_count.desc(), Report.created_at.desc())
        )
    if sort == 'comments':
        comment_count = db.func.count(Comment.id)
        return (
            query.outerjoin(Comment, Comment.report_id == Report.id)
                 .group_by(Report.id)
                 .order_by(comment_count.desc(), Report.created_at.desc())
        )
    if sort == 'oldest':
        return query.order_by(Report.created_at.asc())
    return query.order_by(Report.created_at.desc())


def _build_listing_response(base_query, feed_mode=None):
    """Shared listing-page handler. base_query is the starting Report.query
    (already pre-filtered if /listing/following routes here). feed_mode is
    'following' for the From Following page, None for the regular listing —
    template uses it to render the right title.

    Also runs the throttled lazy cleanup of expired reports — this is the
    main public listing endpoint so it's a natural place to garbage-collect."""
    _cleanup_expired_reports()

    page = request.args.get('page', 1, type=int)
    state_id = request.args.get('state_id', type=int)
    city_id = request.args.get('city_id', type=int)
    category_id = request.args.get('category_id', type=int)
    sort = request.args.get('sort', 'recent')
    feed_trending = request.args.get('feed_trending') in {'1', 'true', 'on'}
    feed_following = request.args.get('feed_following') in {'1', 'true', 'on'}

    # Fetch filter options for the UI
    categories = Category.query.order_by(Category.id).all()
    states = State.query.order_by(State.name).all()
    cities_by_state = {
        s.id: [{'id': c.id, 'name': c.name} for c in s.cities]
        for s in states
    }
    fav_report_ids = {row.report_id for row in FavouriteReport.query.filter_by(user_id=current_user.id).all()} if current_user.is_authenticated else set()

    # Backward compatibility: old Trending URLs now behave like the Trending
    # feed filter on the shared listing page.
    if sort == 'top':
        feed_trending = True
        sort = 'recent'

    if feed_following and not current_user.is_authenticated:
        feed_following = False

    if city_id and not state_id:
        selected_city = City.query.get(city_id)
        if selected_city:
            state_id = selected_city.state_id

    # Active reports only — expired posts never show up regardless of feed.
    query = base_query.filter(Report.expires_at > datetime.utcnow())
    if feed_following:
        query = _following_reports_query().filter(Report.expires_at > datetime.utcnow())

    if feed_trending:
        trending_ids = _trending_report_ids()
        query = query.filter(Report.id.in_(trending_ids)) if trending_ids else query.filter(db.literal(False))

    query = _apply_basic_filters(query, state_id, city_id, category_id)
    query = _apply_listing_sort(query, sort)

    pagination = query.paginate(page=page, per_page=20, error_out=False)

    trending_ids = _trending_report_ids()
    feed_query_args = {}
    if feed_trending:
        feed_query_args['feed_trending'] = 1
    if feed_following:
        feed_query_args['feed_following'] = 1

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
        feed_trending_active=feed_trending,
        feed_following_active=feed_following,
        feed_query_args=feed_query_args,
    )
 
 
@bp.route('/listing')
def listing_page():
    return _build_listing_response(Report.query)
 
 
def _following_reports_query():
    followed_ids = [
        row.followed_id
        for row in Follow.query.filter_by(follower_id=current_user.id).all()
    ]
    if not followed_ids:
        return Report.query.filter(db.literal(False))
    return Report.query.filter(Report.user_id.in_(followed_ids))


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
        s.id: [{'id': sub.id, 'name': sub.name} for sub in s.cities]
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
    sniffs = []
    if len(files) > MAX_MEDIA_FILES:
        errors['media'] = f'Too many files (max {MAX_MEDIA_FILES}).'
    else:
        result, err = _validate_uploads(files)
        if err:
            errors['media'] = err
        else:
            sniffs = result
 
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
        for f, (media_type, ext) in zip(files, sniffs):
            stored_name = f'{uuid.uuid4().hex}.{ext}'
            save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
            f.save(save_path)
            saved_paths.append(save_path)
 
            db.session.add(ReportMedia(
                report_id=report.id,
                filename=stored_name,
                original_name=secure_filename(f.filename) or stored_name,
                media_type=media_type,
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
 
 