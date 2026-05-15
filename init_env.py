"""One-shot bootstrap script. Run once after cloning + installing deps.

What it does:
  1. Creates `.env` with a fresh random SECRET_KEY (if `.env` doesn't exist).
  2. Seeds the two tables the app NEEDS to function — categories and
     locations. Without these, the Report form 500s and the map is empty.

Run from the project root:

    python init_env.py

Prerequisite: `flask db upgrade heads` must have been run already so the
schema exists. If it hasn't, this script will print a helpful error.

For optional test data (sample users, reports, comments), use
`python -m seed.initial_data --users --comments --all` separately.
"""
import os
import secrets

ENV_PATH = '.env'


def ensure_env():
    """Generate .env with a random SECRET_KEY if it doesn't exist yet."""
    if os.path.exists(ENV_PATH):
        print(f'.env already exists at {os.path.abspath(ENV_PATH)} — keeping it.')
        return
    key = secrets.token_hex(32)   # 64-char hex = 256 bits of entropy
    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.write(f'SECRET_KEY={key}\n')
    print(f'Created {os.path.abspath(ENV_PATH)} with a fresh random SECRET_KEY.')


def seed_required_data():
    """Seed categories + locations — the two tables the app can't run without."""
    # Late imports: env must be loaded first so Config doesn't raise.
    from dotenv import load_dotenv
    load_dotenv()

    from app import create_app
    from seed.initial_data import seed_categories, seed_locations

    app = create_app()
    with app.app_context():
        try:
            seed_categories()
            seed_locations()
        except Exception as e:
            print('Could not seed required data — does the DB schema exist yet?')
            print('Run `flask db upgrade heads` first, then re-run this script.')
            print(f'(underlying error: {e})')
            return
    print('Seeded categories + locations.')


def main():
    ensure_env()
    seed_required_data()


if __name__ == '__main__':
    main()
