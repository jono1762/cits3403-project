from flask import current_app as app
from flask import render_template
from .models import db, User, Category, Report

@app.route('/')
def index():
    return "Flask is running."

@app.route('/login', methods=['GET', 'POST'])
def login():
    return "Login page."