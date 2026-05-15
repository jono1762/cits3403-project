"""Initial reference data + a small batch of test data.

Each chunk is its own function so you can run them independently from
the CLI. The app no longer auto-seeds on boot — you decide what to
populate.

Usage (from the project root):

    python -m seed.initial_data --categories
    python -m seed.initial_data --locations
    python -m seed.initial_data --users
    python -m seed.initial_data --comments
    python -m seed.initial_data --all

All chunks are idempotent — re-running any of them is safe.
"""
import argparse

from app import create_app
from app.models import db, User, Category, State, City, Report, Comment


# ============================================================
# Categories — the 5 report categories + marker colour for each
# ============================================================
DEFAULT_CATEGORIES = [
    ('Weather',   '#3498db'),
    ('Noisiness', '#9b59b6'),
    ('Hazards',   '#e67e22'),
    ('Traffic',   '#f1c40f'),
    ('Emergency', '#e74c3c'),
]


def seed_categories():
    """Fill the categories table so the Report form has valid FKs."""
    if Category.query.first() is not None:
        return  # already seeded, skip
    for name, color in DEFAULT_CATEGORIES:
        db.session.add(Category(name=name, marker_color=color))
    db.session.commit()


# ============================================================
# Locations — 8 AU states/territories + major cities per state
# ============================================================
DEFAULT_LOCATIONS = {
    ('NSW', 'New South Wales'):       ['Sydney', 'Newcastle', 'Wollongong', 'Central Coast'],
    ('VIC', 'Victoria'):              ['Melbourne', 'Geelong', 'Ballarat'],
    ('QLD', 'Queensland'):            ['Brisbane', 'Gold Coast', 'Sunshine Coast', 'Cairns', 'Townsville'],
    ('WA',  'Western Australia'):     ['Perth', 'Mandurah', 'Bunbury'],
    ('SA',  'South Australia'):       ['Adelaide', 'Mount Gambier'],
    ('TAS', 'Tasmania'):              ['Hobart', 'Launceston'],
    ('ACT', 'Australian Capital Territory'): ['Canberra'],
    ('NT',  'Northern Territory'):    ['Darwin', 'Alice Springs'],
}


def seed_locations():
    """Fill states + cities so the Location dropdowns have options."""
    if State.query.first() is not None:
        return  # already seeded, skip
    for (code, name), city_names in DEFAULT_LOCATIONS.items():
        state = State(code=code, name=name)
        db.session.add(state)
        db.session.flush()  # get state.id before adding cities
        for city_name in city_names:
            db.session.add(City(name=city_name, state_id=state.id))
    db.session.commit()


# ============================================================
# Test users + sample reports — for trying out search / profile pages
# without having to sign up multiple accounts yourself.
# Password for everyone here is 'Test@1234'.
# ============================================================
DEFAULT_TEST_USERS = [
    ('alice',   'alice@test.com'),
    ('bob',     'bob@test.com'),
    ('charlie', 'charlie@test.com'),
]

DEFAULT_TEST_REPORTS = [
    ('alice',   'Sydney',   'Weather', 'Heavy rain at George St, watch out for puddles.'),
    ('bob',     'Melbourne','Traffic', 'Tram line blocked near Flinders Station.'),
    ('charlie', 'Perth',    'Hazards', 'Fallen branch on the Kings Park path.'),
]


def seed_test_users_and_reports():
    """Add 3 test users and 1 sample report each. Skips anything already there."""
    for username, email in DEFAULT_TEST_USERS:
        if User.query.filter_by(username=username).first():
            continue
        u = User(username=username, email=email)
        u.set_password('Test@1234')
        db.session.add(u)
    db.session.commit()

    for username, city_name, category_name, description in DEFAULT_TEST_REPORTS:
        user = User.query.filter_by(username=username).first()
        if not user or user.reports:
            continue
        city = City.query.filter_by(name=city_name).first()
        category = Category.query.filter_by(name=category_name).first()
        if not (city and category):
            continue
        db.session.add(Report(
            user_id=user.id,
            city_id=city.id,
            category_id=category.id,
            description=description,
        ))
    db.session.commit()


# ============================================================
# Canned comments — drops a few onto any report that has none yet,
# so verify/dispute pills are reachable without juggling logins.
# ============================================================
DEFAULT_TEST_COMMENTS = [
    ('alice',   "Just walked past, can confirm — situation matches the report."),
    ('bob',     "Looks different from where I'm standing — might be outdated?"),
    ('charlie', "Thanks for the heads-up, useful info."),
]


def seed_test_comments():
    """Idempotent — reports that already have any comment are left alone."""
    for report in Report.query.all():
        if Comment.query.filter_by(report_id=report.id).first():
            continue
        for username, body in DEFAULT_TEST_COMMENTS:
            commenter = User.query.filter_by(username=username).first()
            if not commenter or commenter.id == report.user_id:
                continue
            db.session.add(Comment(
                report_id=report.id,
                user_id=commenter.id,
                body=body,
            ))
    db.session.commit()


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='Seed reference + test data into the database.',
    )
    parser.add_argument('--categories', action='store_true',
                        help='Seed the 5 report categories (Weather, Hazards, ...).')
    parser.add_argument('--locations', action='store_true',
                        help='Seed AU states + major cities.')
    parser.add_argument('--users', action='store_true',
                        help='Seed test users (alice / bob / charlie) + 1 sample report each.')
    parser.add_argument('--comments', action='store_true',
                        help='Seed canned comments on reports that have none.')
    parser.add_argument('--all', action='store_true',
                        help='Seed everything above in order.')
    args = parser.parse_args()

    if not any([args.categories, args.locations, args.users, args.comments, args.all]):
        parser.print_help()
        return

    app = create_app()
    with app.app_context():
        if args.all or args.categories:
            seed_categories()
            print('Categories seeded.')
        if args.all or args.locations:
            seed_locations()
            print('Locations seeded.')
        if args.all or args.users:
            seed_test_users_and_reports()
            print('Test users + sample reports seeded.')
        if args.all or args.comments:
            seed_test_comments()
            print('Test comments seeded.')


if __name__ == '__main__':
    main()
