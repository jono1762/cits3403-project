# CITS3403 Project

## Description

This application is a Flask web app for community-based local condition reporting across Australian cities. Its purpose is to help users share, browse, and assess short-lived reports about weather, noise, hazards, traffic, and emergencies in their area.

The application is designed around location-based reports. Users can browse public reports, view reports on a map, filter reports by state, city, category, and feed type, and open individual report pages for more detail. Registered users can create reports, attach image or video evidence, comment on reports, verify or dispute reports, favourite reports and locations, and follow other users. Reports automatically expire after seven days so the information shown by the app remains current.

The app also includes user profiles, credibility-style statistics based on report verification, private messaging between users, message requests, chat blocking, saved locations, saved reports, and a live weather page backed by the Open-Meteo API. The backend uses Flask blueprints to separate authentication, report management, user/profile features, public pages, and JSON API endpoints. Data is stored with SQLAlchemy and SQLite, with schema changes managed through Flask-Migrate.

## Group Members

| UWA ID | Name | GitHub Username |
| --- | --- | --- |
| 24314826 | Jonathan Abraham | jono1762 |
| 24116757 | Zi Hao Chan | Ziihaooo |
| 23446652 | Tyler Yeoh | Nylernothere |

## Launching the Application

These instructions assume Python is installed and that commands are run from the project root.

**Step 1: Create and activate a virtual environment**

```powershell
python -m venv venv
.\venv\Scripts\activate
```

**Step 2: Install dependencies**

```powershell
pip install -r requirements.txt
```

**Step 3: Configure the Flask app and apply database migrations**

```powershell
$env:FLASK_APP = "run.py"
flask db upgrade
```

**Step 4: Start the application**

```powershell
python run.py
```

**Step 5: Open the app in a browser**

```text
http://127.0.0.1:5000
```

On first launch after the database tables exist, the app seeds default categories, Australian states and cities, and a small set of test users and sample reports.

## Running Tests

Run all tests with:

```powershell
pytest
```

Run only the unit tests with:

```powershell
pytest tests/unit
```

Run only the Selenium browser tests with:

```powershell
pytest tests/selenium
```

The Selenium tests require Google Chrome to be installed. The test suite creates isolated test databases and upload folders, so it does not use the normal development database.
