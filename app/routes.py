# app/routes.py
from flask import current_app as app
from flask import render_template, request, jsonify
from .models import db, User, Category, Report

@app.route('/')
def index():
    # Once we have base.html and index.html, we will change this to:
    # return render_template('index.html')
    return "Database connected and Flask is running! Ready to build the map."

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Logic for checking passwords will go here
        pass
    
    # return render_template('login.html')
    return "This will be the login page."