"""
Authentication Forms for TMASearcher
"""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Regexp
import sqlite3
import os

DATABASE_PATH = os.environ.get('DATABASE_URL', 'TMASTL.db')


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class LoginForm(FlaskForm):
    """Login form."""
    email = StringField('Email', validators=[
        DataRequired(message='Email is required'),
        Email(message='Please enter a valid email address')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message='Password is required')
    ])
    remember = BooleanField('Remember me')
    submit = SubmitField('Sign In')


class SignupForm(FlaskForm):
    """Registration form."""
    username = StringField('Username', validators=[
        DataRequired(message='Username is required'),
        Length(min=3, max=20, message='Username must be 3-20 characters'),
        Regexp('^[a-zA-Z0-9_]+$', message='Username can only contain letters, numbers, and underscores')
    ])
    email = StringField('Email', validators=[
        DataRequired(message='Email is required'),
        Email(message='Please enter a valid email address')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message='Password is required'),
        Length(min=8, message='Password must be at least 8 characters')
    ])
    password_confirm = PasswordField('Confirm Password', validators=[
        DataRequired(message='Please confirm your password'),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Create Account')

    def validate_username(self, field):
        """Check if username is already taken."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE LOWER(username) = LOWER(?)', (field.data,))
        user = cursor.fetchone()
        conn.close()
        if user:
            raise ValidationError('Username is already taken')

    def validate_email(self, field):
        """Check if email is already registered."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE LOWER(email) = LOWER(?)', (field.data,))
        user = cursor.fetchone()
        conn.close()
        if user:
            raise ValidationError('Email is already registered')


class ForgotPasswordForm(FlaskForm):
    """Forgot password form."""
    email = StringField('Email', validators=[
        DataRequired(message='Email is required'),
        Email(message='Please enter a valid email address')
    ])
    submit = SubmitField('Send Reset Link')


class ResetPasswordForm(FlaskForm):
    """Reset password form."""
    password = PasswordField('New Password', validators=[
        DataRequired(message='Password is required'),
        Length(min=8, message='Password must be at least 8 characters')
    ])
    password_confirm = PasswordField('Confirm New Password', validators=[
        DataRequired(message='Please confirm your password'),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Reset Password')


class ChangePasswordForm(FlaskForm):
    """Change password form (when logged in)."""
    current_password = PasswordField('Current Password', validators=[
        DataRequired(message='Current password is required')
    ])
    new_password = PasswordField('New Password', validators=[
        DataRequired(message='New password is required'),
        Length(min=8, message='Password must be at least 8 characters')
    ])
    new_password_confirm = PasswordField('Confirm New Password', validators=[
        DataRequired(message='Please confirm your new password'),
        EqualTo('new_password', message='Passwords must match')
    ])
    submit = SubmitField('Change Password')
