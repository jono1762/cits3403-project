# Seed data

Self-contained directory for everything used to populate the dev database
with realistic demo content. Run by `python seed/seed_db.py` from the
project root.

## Layout

```
seed/
├── README.md            this file
├── seed_db.py           main entry point — clears + repopulates the DB
├── data/                text data the script reads from
│   ├── users.json       demo users (username, email, bio, password)
│   ├── reports.json     demo reports (author, city, category, body, media)
│   └── comments.json    demo comments (author, report ref, body)
└── media/
    ├── images/          drop .jpg / .png / .webp here
    │                    file names are referenced from reports.json
    └── videos/          drop .mp4 / .webm here
```

## How the media files are used

`seed_db.py` copies any file referenced by `reports.json` from
`seed/media/images/` (or `videos/`) into `app/static/uploads/` with a
fresh UUID name, then attaches a `ReportMedia` row pointing at the new
upload filename. That keeps production uploads (`app/static/uploads/`)
isolated from the source files we ship in this folder.

## Quick rules

- Initial reference data (categories, states, cities, default test users)
  is still seeded by `create_app()` on first boot — no change.
- This folder adds the *demo* layer on top: extra users, reports with
  real attachments, comment threads.
- Drop new media into `seed/media/images/` or `seed/media/videos/`,
  add a matching entry to `seed/data/reports.json`, re-run the script.
