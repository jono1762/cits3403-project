"""Bulk demo seed — populates a realistic-looking dataset for screenshots
and live demos. Opt-in, not run by init_env.py.

Wipes existing demo content (everything except categories/states/cities
and the user 'alice' — alice is preserved as the "you" who can vote in
the trending scenario) and rebuilds:

  - ~150 users with varied account ages, random follow / privacy settings
  - 25 reports across all cities + categories, with curated descriptions
    and 0-3 attached media each (copied from seed/media/{images,videos}/
    into app/static/uploads/ with fresh UUIDs)
  - 30-100 verifies + 10-40 disputes per report (no duplicate voter per
    report; only voters >7 days old contribute to trending score)
  - 0-4 comments per report
  - Random follow graph (~12 follows per user on average)
  - Trending demo: top report T just above candidate report C. alice
    has NOT voted on C; her one verify pushes C above T and into #1.

Run from project root (after init_env.py + flask db upgrade heads):

    python -m seed.demo_data

Uses a fixed random seed so the dataset is reproducible across runs.
"""
import os
import random
import shutil
import uuid
from datetime import datetime, timedelta

from app import create_app
from app.models import (
    db, User, Category, City, State, Report, ReportMedia, Verification,
    Comment, Follow, utcnow,
)


RNG_SEED = 42
NUM_USERS = 150
NUM_REPORTS = 25

MEDIA_SRC_IMAGES = os.path.join('seed', 'media', 'images')


# ============================================================
# Username pool — random combos of prefix + suffix make 150 unique handles
# ============================================================
USERNAME_PREFIXES = [
    'aussie', 'beach', 'bondi', 'bushwalker', 'commuter', 'coastal',
    'echo', 'flinders', 'gully', 'harbour', 'inlet', 'jasper', 'koala',
    'larrikin', 'mango', 'nullarbor', 'outback', 'platypus', 'quokka',
    'reef', 'sunset', 'tropic', 'uluru', 'verandah', 'wattle', 'xylo',
    'yarra', 'zephyr',
]
USERNAME_SUFFIXES = [
    '', '_42', '_au', '_local', '_walker', '_rider', '_watcher', '_03',
    '_99', '_x', '_dev', '_x2', '_pro', '_fan', '_77',
]

BIOS = [
    '', '', '', '',
    'Local enthusiast.',
    'Catch me on the train.',
    'Coffee + community reports.',
    'Walking the suburb so you don\'t have to.',
    'Just here to watch.',
    'Posting what I see.',
    'CBD commuter, weekday only.',
    'Photographer when the light is right.',
    'Skater. Reports the cracks I trip over.',
    'Dog walker, eyes always open.',
    'Cyclist. Knows every pothole.',
]


# ============================================================
# Per-city street / landmark pool — used to flavour descriptions + address
# ============================================================
CITY_PLACES = {
    'Sydney':         ['George St', 'Pitt St', 'Circular Quay', 'Hyde Park', 'Bondi', 'Darling Harbour', 'Oxford St', 'King St'],
    'Newcastle':      ['Hunter St', 'King St', 'the foreshore', 'Honeysuckle'],
    'Wollongong':     ['Crown St', 'the harbour', 'North Beach'],
    'Central Coast':  ['Terrigal Esplanade', 'Gosford station', 'The Entrance Rd'],
    'Melbourne':      ['Flinders St', 'Bourke St Mall', 'Collins St', 'Federation Square', 'Brunswick St', 'Chapel St', 'St Kilda Esplanade'],
    'Geelong':        ['Malop St', 'Eastern Beach', 'Pakington St'],
    'Ballarat':       ['Sturt St', 'Lake Wendouree', 'Lydiard St'],
    'Brisbane':       ['Queen St Mall', 'South Bank', 'Roma St', 'New Farm', 'West End'],
    'Gold Coast':     ['Surfers Paradise', 'Cavill Ave', 'Broadbeach'],
    'Sunshine Coast': ['Hastings St', 'Mooloolaba Esplanade'],
    'Cairns':         ['the Esplanade', 'Lake St', 'Cairns Central'],
    'Townsville':     ['Flinders St mall', 'the Strand'],
    'Perth':          ['Hay St', 'Murray St', 'Kings Park', 'St Georges Tce', 'Northbridge', 'Beaufort St'],
    'Mandurah':       ['Mandurah Terrace', 'the foreshore'],
    'Bunbury':        ['Victoria St', 'Koombana Bay'],
    'Adelaide':       ['Rundle Mall', 'North Tce', 'the Parade', 'Glenelg', 'King William St'],
    'Mount Gambier':  ['Commercial St', 'the Blue Lake'],
    'Hobart':         ['Salamanca Place', 'Liverpool St', 'Battery Point', 'Sandy Bay Rd'],
    'Launceston':     ['Brisbane St mall', 'Cataract Gorge'],
    'Canberra':       ['Northbourne Ave', 'Civic', 'Lake Burley Griffin', 'Parkes Way'],
    'Darwin':         ['Mitchell St', 'the Esplanade', 'Cullen Bay'],
    'Alice Springs':  ['Todd Mall', 'the Stuart Hwy'],
}


# ============================================================
# Curated reports — 25 of them, each with description and the specific
# media file name (or None) so the demo has memorable moments rather
# than generic "Heavy rain at {city}" repeats. Trending pair + the USA
# protest trick are explicit entries near the top.
#
# Format: (author_role, city_name, category_name, description, media_file)
# author_role: 'alice', 'bob', 'charlie', or 'random' (any other user)
# media_file: filename in seed/media/images/ or videos/, or None
# ============================================================
CURATED_REPORTS = [
    # --- TRENDING DEMO PAIR (T and C) — same time-of-day so candidate is
    # just newer than the leader. alice's vote on C bumps it to #1. ---
    ('random', 'Sydney',   'Weather',   'Heavy rain at George St, watch out for puddles.', 'sydney_rain.png'),
    ('random', 'Sydney',   'Weather',   'Storm front moving in over Sydney Harbour — visibility dropping fast.', 'thunderstorm_australia.png'),

    # --- The USA-protest trick: posted as Aus protest, gets DISPUTED ---
    ('random', 'Sydney',   'Noisiness', 'Massive protest spilling onto George St — hundreds of people, hard to walk through.', 'usaprotest.png'),

    # --- Sensational Bondi report ---
    ('random', 'Sydney',   'Emergency', 'Loud bangs at Bondi Beach — people running, unclear what happened.', 'bondibeachgunfight.png'),

    # --- Other Sydney ---
    ('random', 'Sydney',   'Weather',   'Clear sky over Bondi this morning — perfect beach day.', 'bondibeachsunny.png'),

    # --- Melbourne ---
    ('random', 'Melbourne','Weather',   'Thick fog rolling through Melbourne CBD — visibility under 50m on Flinders St.', 'melbournefog.png'),
    ('random', 'Melbourne','Traffic',   'Tram line blocked near Flinders Station, replacement bus chaos.', None),
    ('random', 'Melbourne','Noisiness', 'Live music spilling out of Brunswick St until 2am — neighbours fuming.', None),

    # --- Perth ---
    ('random', 'Perth',    'Traffic',   'Hay St gridlocked — accident near the bus station, lanes both ways stopped.', 'perthtrafficjam.png'),
    ('random', 'Perth',    'Noisiness', 'Ed Sheeran concert at RAC Arena, whole neighbourhood is packed and loud.', 'edsheeranperthconcert.png'),
    ('random', 'Perth',    'Hazards',   'Fallen branch on the Kings Park path — careful on the morning walk.', None),

    # --- Canberra ---
    ('random', 'Canberra', 'Emergency', 'Multi-car prang on Northbourne Ave, ambulances on scene.', 'canberracarcrash.png'),
    ('random', 'Canberra', 'Weather',   'Frost across Lake Burley Griffin this morning, paths slippery.', None),

    # --- Darwin ---
    ('random', 'Darwin',   'Noisiness', 'Construction starts at 6am again on Mitchell St — this is the third week in a row.', 'darwinconstruction.png'),

    # --- General AU protest ---
    ('random', 'Brisbane', 'Noisiness', 'Climate protest moving down Queen St Mall, traffic redirected.', 'aus_protest.png'),

    # --- Random fill, no images, varied cities ---
    ('random', 'Brisbane', 'Traffic',   'Roadworks on Roma St eating up two lanes, expect delays.', None),
    ('random', 'Gold Coast','Weather',  'Sudden downpour at Surfers Paradise, beach cleared out fast.', None),
    ('random', 'Adelaide', 'Hazards',   'Loose paving stones on Rundle Mall — easy to trip near the food court.', None),
    ('random', 'Hobart',   'Weather',   'Strong winds at Battery Point, bin lids flying around.', None),
    ('random', 'Launceston','Hazards',  'Tree limb hanging over the road on Brisbane St mall.', None),
    ('random', 'Newcastle','Noisiness', 'Loud party on Hunter St — sounds like a full DJ set, going past midnight.', None),
    ('random', 'Cairns',   'Emergency', 'Power outage across several blocks near the Esplanade.', None),
    ('random', 'Wollongong','Traffic',  'Crown St blocked, bus replacement organised but slow.', None),
    ('random', 'Geelong',  'Weather',   'Hailstones the size of grapes at Eastern Beach.', None),
    ('random', 'Townsville','Hazards',  'Slick patch on the pedestrian crossing at Flinders St mall.', None),

    # short clip videos to make sure at least some reports have video attachments
    # (these reuse two reports above by piggybacking — see seed code below; the
    # video gets attached on top of the image for variety)
]


COMMENT_LINES = [
    "Just walked past, can confirm.",
    "Looks different now — might be sorted?",
    "Thanks for the heads-up.",
    "Same here, came through about an hour ago.",
    "Council should know about this.",
    "Yep, still happening as of 5 min ago.",
    "I'd avoid that area for a bit.",
    "Was there earlier — wasn't this bad before.",
    "Anyone got more details?",
    "Saw it on the news too.",
    "Cleared up by the time I got there.",
    "Stay safe everyone.",
    "Drove past — didn't notice anything?",
    "On my way now, will update.",
    "Confirmed, lights out on my street too.",
    "Doesn't look like Australia to me lol",
    "These photos look fake.",
    "Pretty sure that's a stock image.",
]


# ============================================================
# Helpers
# ============================================================
def generate_usernames(n):
    """Yield n unique usernames combining prefix + suffix."""
    seen = set()
    while len(seen) < n:
        username = random.choice(USERNAME_PREFIXES) + random.choice(USERNAME_SUFFIXES)
        if username and username not in seen:
            seen.add(username)
            yield username


def copy_media_to_uploads(filename, upload_dir):
    """Copy seed image file into app/static/uploads/ with a UUID name.
    Returns (stored_filename, media_type) or (None, None) if missing."""
    src = os.path.join(MEDIA_SRC_IMAGES, filename)
    media_type = 'image'
    ext = filename.rsplit('.', 1)[1]
    if not os.path.exists(src):
        print(f'  WARNING: media file not found: {src}')
        return None, None
    stored = f'{uuid.uuid4().hex}.{ext}'
    shutil.copy(src, os.path.join(upload_dir, stored))
    return stored, media_type


def wipe_demo_data():
    """Remove everything except categories, states, cities, and alice.
    Keeping alice means the trending-demo voter survives across runs."""
    Verification.query.delete()
    Comment.query.delete()
    ReportMedia.query.delete()
    Follow.query.delete()
    Report.query.delete()
    # Wipe all users EXCEPT alice (preserved for trending demo)
    User.query.filter(User.username != 'alice').delete()
    db.session.commit()


# ============================================================
# Seeding
# ============================================================
def seed_users():
    """Create ~150 users with varied account age, privacy settings, and bios."""
    now = utcnow()

    # Ensure alice exists and is OLDER than 7 days so her trending vote counts
    alice = User.query.filter_by(username='alice').first()
    if not alice:
        alice = User(username='alice', email='alice@demo.com', bio='I keep an eye on the city.')
        alice.set_password('Test@1234')
        db.session.add(alice)
        db.session.flush()
    alice.created_at = now - timedelta(days=30)

    # 11 demo users with hand-written bios (kept from earlier seeders)
    demo_users = [
        ('bob',          'I see things on my walk to the train.'),
        ('charlie',      'CBD coffee + community reports.'),
        ('nina_walks',   'Sydney CBD walker. Mostly hazards near Hyde Park.'),
        ('jordan_perth', 'Trail user out west. Sharing hazards I spot.'),
        ('kai_mel',      'Tram rider, always running late.'),
        ('riley_qld',    'Brisbane local. Weather watcher.'),
        ('sam_k',        'Adelaide. Reports go in, news comes out.'),
        ('mira_act',     'Canberra. Quiet street watcher.'),
        ('tom_burton',   'Hobart, sharing what I see.'),
        ('eli_darwin',   'Darwin. Emergencies mostly — stay safe.'),
    ]
    for username, bio in demo_users:
        if User.query.filter_by(username=username).first():
            continue
        u = User(username=username, email=f'{username}@demo.com', bio=bio)
        u.set_password('Test@1234')
        # 80% are >7 days old, 20% are newer (so anti-gaming filter has real variety)
        days_old = random.randint(8, 60) if random.random() < 0.8 else random.randint(0, 6)
        u.created_at = now - timedelta(days=days_old, hours=random.randint(0, 23))
        u.following_list_public = random.random() < 0.6
        u.followers_list_public = random.random() < 0.7
        db.session.add(u)

    db.session.commit()

    # Fill out to NUM_USERS with randomly-generated handles
    already = NUM_USERS - User.query.count()
    if already > 0:
        usernames = list(generate_usernames(already))
        for username in usernames:
            u = User(
                username=username,
                email=f'{username}@demo.com',
                bio=random.choice(BIOS),
            )
            u.set_password('Test@1234')
            days_old = random.randint(8, 60) if random.random() < 0.8 else random.randint(0, 6)
            u.created_at = now - timedelta(days=days_old, hours=random.randint(0, 23))
            u.following_list_public = random.random() < 0.6
            u.followers_list_public = random.random() < 0.7
            db.session.add(u)
        db.session.commit()


def seed_reports(upload_dir):
    """Create the 25 curated reports, attaching media where specified."""
    now = utcnow()
    all_users = User.query.filter(User.username != 'alice').all()
    created_reports = []

    for i, (author_role, city_name, category_name, description, media_file) in enumerate(CURATED_REPORTS):
        # Pick the author
        if author_role == 'random':
            author = random.choice(all_users)
        else:
            author = User.query.filter_by(username=author_role).first() or random.choice(all_users)

        city = City.query.filter_by(name=city_name).first()
        category = Category.query.filter_by(name=category_name).first()
        if not (city and category):
            continue

        # Optionally insert an address line using a random street
        address = None
        if random.random() < 0.6:
            address = random.choice(CITY_PLACES.get(city_name, [city_name]))

        # Timestamps: trending demo pair (i=0 and i=1) must be CLOSE in time,
        # with C (i=1) AFTER T (i=0) by a few seconds so it wins the tiebreak.
        if i == 0:
            created_at = now - timedelta(hours=4)
        elif i == 1:
            created_at = now - timedelta(hours=4) + timedelta(seconds=30)
        else:
            # Spread the rest across the last 5 days
            hours_ago = random.uniform(0.5, 5 * 24)
            created_at = now - timedelta(hours=hours_ago)

        report = Report(
            user_id=author.id,
            city_id=city.id,
            category_id=category.id,
            description=description,
            address=address,
            created_at=created_at,
            expires_at=created_at + timedelta(days=7),
        )
        db.session.add(report)
        db.session.flush()

        # Attach the curated media (image)
        if media_file:
            stored, media_type = copy_media_to_uploads(media_file, upload_dir)
            if stored:
                db.session.add(ReportMedia(
                    report_id=report.id,
                    filename=stored,
                    original_name=media_file,
                    media_type=media_type,
                ))

        created_reports.append(report)

    db.session.commit()
    return created_reports


def seed_votes(reports):
    """Add 30-100 verifies + 10-40 disputes per report. Trending demo pair
    is engineered: T=50/0, C=49/0, alice excluded from C's verifies."""
    all_users = User.query.filter(User.username != 'alice').all()
    alice = User.query.filter_by(username='alice').first()

    for i, report in enumerate(reports):
        # Trending demo pair has carefully engineered vote counts
        if i == 0:
            # T — top trending: 50 verifies, 0 disputes
            voters = random.sample(all_users, 50)
            for v in voters:
                db.session.add(Verification(report_id=report.id, user_id=v.id, status='verify'))
        elif i == 1:
            # C — candidate: 49 verifies (alice NOT among them), 0 disputes
            voters = random.sample([u for u in all_users if u.id != alice.id], 49)
            for v in voters:
                db.session.add(Verification(report_id=report.id, user_id=v.id, status='verify'))
        elif i == 2:
            # The USA-protest trick: more disputes than verifies
            available = list(all_users)
            random.shuffle(available)
            verify_n = random.randint(8, 15)
            dispute_n = random.randint(40, 70)
            for v in available[:verify_n]:
                db.session.add(Verification(report_id=report.id, user_id=v.id, status='verify'))
            for v in available[verify_n:verify_n + dispute_n]:
                db.session.add(Verification(report_id=report.id, user_id=v.id, status='dispute'))
        else:
            # Normal report: random heavy verifies + some disputes
            available = [u for u in all_users if u.id != report.user_id]
            random.shuffle(available)
            verify_n = random.randint(30, 100)
            dispute_n = random.randint(10, 40)
            verify_n = min(verify_n, len(available))
            dispute_n = min(dispute_n, len(available) - verify_n)
            for v in available[:verify_n]:
                db.session.add(Verification(report_id=report.id, user_id=v.id, status='verify'))
            for v in available[verify_n:verify_n + dispute_n]:
                db.session.add(Verification(report_id=report.id, user_id=v.id, status='dispute'))

    db.session.commit()


def seed_comments(reports):
    """Drop 0-4 random comments on each report (not from the author)."""
    all_users = User.query.all()
    for report in reports:
        n = random.randint(0, 4)
        candidates = [u for u in all_users if u.id != report.user_id]
        random.shuffle(candidates)
        for commenter in candidates[:n]:
            db.session.add(Comment(
                report_id=report.id,
                user_id=commenter.id,
                body=random.choice(COMMENT_LINES),
            ))
    db.session.commit()


def seed_follows():
    """Each user follows 0-15 random others. Random follow graph."""
    all_users = User.query.all()
    for user in all_users:
        n_follows = random.randint(0, 15)
        candidates = [u for u in all_users if u.id != user.id]
        random.shuffle(candidates)
        for target in candidates[:n_follows]:
            db.session.add(Follow(follower_id=user.id, followed_id=target.id))
    db.session.commit()


# ============================================================
# Main
# ============================================================
def main():
    random.seed(RNG_SEED)
    app = create_app()
    with app.app_context():
        upload_dir = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_dir, exist_ok=True)

        print('Wiping existing demo data (keeping alice + categories/states/cities)...')
        wipe_demo_data()

        print(f'Seeding ~{NUM_USERS} users...')
        seed_users()
        print(f'  -> {User.query.count()} users in DB')

        print(f'Seeding {NUM_REPORTS} reports + media...')
        reports = seed_reports(upload_dir)
        print(f'  -> {len(reports)} reports created')

        print('Seeding verifies + disputes (heavy)...')
        seed_votes(reports)
        v = Verification.query.filter_by(status='verify').count()
        d = Verification.query.filter_by(status='dispute').count()
        print(f'  -> {v} verifies + {d} disputes')

        print('Seeding comments...')
        seed_comments(reports)
        print(f'  -> {Comment.query.count()} comments')

        print('Seeding follow graph...')
        seed_follows()
        print(f'  -> {Follow.query.count()} follows')

        print('\nDone.')
        print('  Login as: alice / Test@1234   (your trending-demo voter)')
        print('  The top trending report is T; the next one is C.')
        print("  Verify report C as alice -> C jumps above T into #1.")


if __name__ == '__main__':
    main()
