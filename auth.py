"""
Authentication Routes for TMASearcher
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
import bcrypt
import sqlite3
import os
from datetime import datetime

from forms import LoginForm, SignupForm, ChangePasswordForm

auth_bp = Blueprint('auth', __name__)

DATABASE_PATH = os.environ.get('DATABASE_URL', 'TMASTL.db')


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_by_id(user_id):
    """Get user by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_user_by_email(email):
    """Get user by email (case-insensitive)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE LOWER(email) = LOWER(?)', (email,))
    user = cursor.fetchone()
    conn.close()
    return user


def create_user(username, email, password):
    """Create a new user with hashed password."""
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (username, email, password_hash, created_at, is_active)
        VALUES (?, ?, ?, ?, 1)
    ''', (username, email, password_hash, datetime.now().isoformat()))
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return user_id


def verify_password(stored_hash, password):
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))


def update_last_login(user_id):
    """Update user's last login timestamp."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_login = ? WHERE id = ?',
                   (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def get_user_stats(user_id):
    """Get user's favorites and listening stats."""
    conn = get_db()
    cursor = conn.cursor()

    # Count favorites
    cursor.execute('SELECT COUNT(*) as count FROM user_favorites WHERE user_id = ?', (user_id,))
    favorites_count = cursor.fetchone()['count']

    # Count comments
    cursor.execute('SELECT COUNT(*) as count FROM comments WHERE user_id = ?', (user_id,))
    comments_count = cursor.fetchone()['count']

    # Count likes given
    cursor.execute('SELECT COUNT(*) as count FROM episode_likes WHERE user_id = ?', (user_id,))
    likes_count = cursor.fetchone()['count']

    conn.close()

    return {
        'favorites': favorites_count,
        'comments': comments_count,
        'likes': likes_count
    }


# User class for Flask-Login
class User:
    """User class for Flask-Login."""
    def __init__(self, user_row):
        self.id = user_row['id']
        self.username = user_row['username']
        self.email = user_row['email']
        self.is_active = bool(user_row['is_active'])
        self.is_admin = bool(user_row['is_admin']) if user_row['is_admin'] else False
        self.created_at = user_row['created_at']
        self.last_login = user_row['last_login']

    def get_id(self):
        return str(self.id)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()

    if form.validate_on_submit():
        user_row = get_user_by_email(form.email.data)

        if user_row and verify_password(user_row['password_hash'], form.password.data):
            if not user_row['is_active']:
                flash('Your account has been deactivated. Please contact support.', 'danger')
                return render_template('login.html', form=form)

            user = User(user_row)
            login_user(user, remember=form.remember.data)
            update_last_login(user.id)

            # Redirect to next page if specified
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'danger')

    return render_template('login.html', form=form)


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """Signup page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = SignupForm()

    if form.validate_on_submit():
        user_id = create_user(
            username=form.username.data,
            email=form.email.data,
            password=form.password.data
        )

        # Log the user in immediately after signup
        user_row = get_user_by_id(user_id)
        user = User(user_row)
        login_user(user, remember=True)
        update_last_login(user.id)

        flash('Welcome to TMASearcher! Your account has been created.', 'success')
        return redirect(url_for('index'))

    return render_template('signup.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout user."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@auth_bp.route('/profile')
@login_required
def profile():
    """User profile page."""
    stats = get_user_stats(current_user.id)
    return render_template('profile.html', stats=stats)


@auth_bp.route('/profile/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password page."""
    form = ChangePasswordForm()

    if form.validate_on_submit():
        user_row = get_user_by_id(current_user.id)

        if verify_password(user_row['password_hash'], form.current_password.data):
            # Update password
            new_hash = bcrypt.hashpw(
                form.new_password.data.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                          (new_hash, current_user.id))
            conn.commit()
            conn.close()

            flash('Your password has been updated.', 'success')
            return redirect(url_for('auth.profile'))
        else:
            flash('Current password is incorrect.', 'danger')

    return render_template('change_password.html', form=form)
