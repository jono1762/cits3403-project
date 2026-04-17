from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from .models import db, User, Category, Report
from .forms import LoginForm, EmailLoginForm, SignupForm

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')

    return render_template('login.html', form=form)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = SignupForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('index'))

    return render_template('signup.html', form=form)

@app.route('/login/email', methods=['GET', 'POST'])
def login_email():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = EmailLoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid email or password.', 'error')

    return render_template('login_email.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# /reports/test — simple HTML page to manually test the report API in the browser
@app.route('/reports/test')
@login_required
def reports_test_page():
    categories = Category.query.order_by(Category.id).all()
    return render_template('reports_test.html', categories=categories)

# POST /api/reports — logged-in user submits a report via AJAX
@app.route('/api/reports', methods=['POST'])
@login_required
def api_create_report():
    # dont crash if client sends invalid JSON or no body at all
    data = request.get_json(silent=True) or {}

    category_id = data.get('category_id')
    # strip whitespace and default to empty string if description is missing or not a string
    description = (data.get('description') or '').strip()

    # server-side validation — description is optional, only category must be valid
    errors = {}
    if not isinstance(category_id, int) or not Category.query.get(category_id):
        errors['category_id'] = 'Invalid or missing category.'

    if errors:
        return jsonify({'errors': errors}), 400

    report = Report(
        user_id=current_user.id,
        category_id=category_id,
        description=description,
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({
        'id': report.id,
        'user_id': report.user_id,
        'category_id': report.category_id,
        'description': report.description,
        'created_at': report.created_at.isoformat(),
    }), 201
