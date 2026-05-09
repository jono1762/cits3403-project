from flask import current_app as app
from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
from .models import db, Category, Report, City, Verification, FavouriteLocation, FavouriteReport
# Report-related helpers live in the reports blueprint now. The favourites
# and map pages here still call a couple, so we re-import them.
from .blueprints.reports import _active_reports_q, _encode_report_id, TRENDING_LIMIT
 
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
# profile / search / follow / block routes moved to app/blueprints/users.py
 
 
@app.route('/messages')
@login_required
def messages_page():
    # ?user=<id> → JS auto-opens that conversation on page load
    return render_template('messages.html')
 
 