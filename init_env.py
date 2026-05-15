"""Generate a .env file with a fresh random SECRET_KEY.

Run once after cloning the repo:

    python init_env.py

Idempotent: if .env already exists, the script exits without overwriting.
Edit the file by hand (or delete it and re-run) if you want a new key.
"""
import os
import secrets

ENV_PATH = '.env'


def main():
    if os.path.exists(ENV_PATH):
        print(f'.env already exists at {os.path.abspath(ENV_PATH)} — nothing to do.')
        print('Delete it and re-run if you want a fresh SECRET_KEY.')
        return

    key = secrets.token_hex(32)   # 64-char hex string = 256 bits of entropy
    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.write(f'SECRET_KEY={key}\n')
    print(f'Created {os.path.abspath(ENV_PATH)} with a fresh random SECRET_KEY.')


if __name__ == '__main__':
    main()
