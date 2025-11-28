"""
Admin Panel for TMASearcher
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
import sqlite3
import os

admin_bp = Blueprint('admin', __name__)

DATABASE_PATH = os.environ.get('DATABASE_URL', 'TMASTL.db')


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def admin_required(f):
    """Decorator to require admin access."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# ==========================================
# Dashboard
# ==========================================

@admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard with stats."""
    conn = get_db()
    cursor = conn.cursor()

    # Get counts
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM comments')
    comment_count = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM user_favorites')
    favorite_count = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM episode_likes')
    like_count = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM TMA')
    episode_count = cursor.fetchone()[0]

    # Recent users
    cursor.execute('''
        SELECT id, username, email, created_at, last_login, is_active, is_admin
        FROM users ORDER BY created_at DESC LIMIT 5
    ''')
    recent_users = cursor.fetchall()

    # Recent comments
    cursor.execute('''
        SELECT c.id, c.comment_text, c.created_at, u.username, t.title
        FROM comments c
        JOIN users u ON c.user_id = u.id
        LEFT JOIN TMA t ON c.episode_id = t.id
        ORDER BY c.created_at DESC LIMIT 5
    ''')
    recent_comments = cursor.fetchall()

    conn.close()

    return render_template('admin/dashboard.html',
                           user_count=user_count,
                           comment_count=comment_count,
                           favorite_count=favorite_count,
                           like_count=like_count,
                           episode_count=episode_count,
                           recent_users=recent_users,
                           recent_comments=recent_comments)


# ==========================================
# Users Management
# ==========================================

@admin_bp.route('/users')
@admin_required
def users():
    """List all users."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.id, u.username, u.email, u.created_at, u.last_login,
               u.is_active, u.is_admin,
               (SELECT COUNT(*) FROM user_favorites WHERE user_id = u.id) as favorites,
               (SELECT COUNT(*) FROM episode_likes WHERE user_id = u.id) as likes,
               (SELECT COUNT(*) FROM comments WHERE user_id = u.id) as comments
        FROM users u
        ORDER BY u.created_at DESC
    ''')
    users = cursor.fetchall()
    conn.close()

    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_user_active(user_id):
    """Toggle user active status."""
    if user_id == current_user.id:
        flash('Cannot deactivate yourself.', 'danger')
        return redirect(url_for('admin.users'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_active = NOT is_active WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

    flash('User status updated.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_user_admin(user_id):
    """Toggle user admin status."""
    if user_id == current_user.id:
        flash('Cannot remove your own admin status.', 'danger')
        return redirect(url_for('admin.users'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_admin = NOT is_admin WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

    flash('User admin status updated.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Delete a user and all their data."""
    if user_id == current_user.id:
        flash('Cannot delete yourself.', 'danger')
        return redirect(url_for('admin.users'))

    conn = get_db()
    cursor = conn.cursor()

    # Get username for flash message
    cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    if user:
        # Delete user (cascades to favorites, comments, likes via FK)
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        flash(f'User "{user["username"]}" deleted.', 'success')
    else:
        flash('User not found.', 'danger')

    conn.close()
    return redirect(url_for('admin.users'))


# ==========================================
# Comments Management
# ==========================================

@admin_bp.route('/comments')
@admin_required
def comments():
    """List all comments."""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    conn = get_db()
    cursor = conn.cursor()

    # Get total count
    cursor.execute('SELECT COUNT(*) FROM comments')
    total = cursor.fetchone()[0]

    # Get paginated comments
    offset = (page - 1) * per_page
    cursor.execute('''
        SELECT c.id, c.comment_text, c.created_at, c.is_edited,
               c.podcast_name, c.episode_id, c.timestamp_ref,
               u.id as user_id, u.username,
               t.title as episode_title
        FROM comments c
        JOIN users u ON c.user_id = u.id
        LEFT JOIN TMA t ON c.episode_id = t.id AND c.podcast_name = 'TMA'
        ORDER BY c.created_at DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset))
    comments = cursor.fetchall()
    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('admin/comments.html',
                           comments=comments,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@admin_bp.route('/comments/<int:comment_id>/delete', methods=['POST'])
@admin_required
def delete_comment(comment_id):
    """Delete a comment."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    conn.commit()
    conn.close()

    flash('Comment deleted.', 'success')
    return redirect(url_for('admin.comments'))


# ==========================================
# Episodes Management
# ==========================================

@admin_bp.route('/episodes')
@admin_required
def episodes():
    """List/search episodes."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    podcast = request.args.get('podcast', 'TMA')
    per_page = 30

    valid_podcasts = {'TMA': 'TMA', 'Balloon': 'Balloon', 'TMShow': 'TMShow'}
    table_name = valid_podcasts.get(podcast, 'TMA')

    conn = get_db()
    cursor = conn.cursor()

    # Build query
    if search:
        count_query = f"SELECT COUNT(*) FROM {table_name} WHERE title LIKE ? OR date LIKE ?"
        data_query = f"""
            SELECT id, title, date, url, show_notes, mp3url,
                   comments_count, favorites_count, likes_count
            FROM {table_name}
            WHERE title LIKE ? OR date LIKE ?
            ORDER BY date DESC
            LIMIT ? OFFSET ?
        """
        search_param = f'%{search}%'
        cursor.execute(count_query, (search_param, search_param))
        total = cursor.fetchone()[0]

        offset = (page - 1) * per_page
        cursor.execute(data_query, (search_param, search_param, per_page, offset))
    else:
        cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
        total = cursor.fetchone()[0]

        offset = (page - 1) * per_page
        cursor.execute(f'''
            SELECT id, title, date, url, show_notes, mp3url,
                   comments_count, favorites_count, likes_count
            FROM {table_name}
            ORDER BY date DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset))

    episodes = cursor.fetchall()
    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('admin/episodes.html',
                           episodes=episodes,
                           page=page,
                           total_pages=total_pages,
                           total=total,
                           search=search,
                           podcast=podcast)


@admin_bp.route('/episodes/<int:episode_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_episode(episode_id):
    """Edit an episode."""
    podcast = request.args.get('podcast', 'TMA')
    valid_podcasts = {'TMA': 'TMA', 'Balloon': 'Balloon', 'TMShow': 'TMShow'}
    table_name = valid_podcasts.get(podcast, 'TMA')

    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        date = request.form.get('date', '').strip()
        url = request.form.get('url', '').strip()
        show_notes = request.form.get('show_notes', '').strip()
        mp3url = request.form.get('mp3url', '').strip()

        cursor.execute(f'''
            UPDATE {table_name}
            SET title = ?, date = ?, url = ?, show_notes = ?, mp3url = ?
            WHERE id = ?
        ''', (title, date, url, show_notes, mp3url, episode_id))
        conn.commit()
        conn.close()

        flash('Episode updated.', 'success')
        return redirect(url_for('admin.episodes', podcast=podcast))

    # GET - show edit form
    cursor.execute(f'''
        SELECT id, title, date, url, show_notes, mp3url
        FROM {table_name}
        WHERE id = ?
    ''', (episode_id,))
    episode = cursor.fetchone()
    conn.close()

    if not episode:
        flash('Episode not found.', 'danger')
        return redirect(url_for('admin.episodes'))

    return render_template('admin/edit_episode.html', episode=episode, podcast=podcast)


@admin_bp.route('/episodes/<int:episode_id>/delete', methods=['POST'])
@admin_required
def delete_episode(episode_id):
    """Delete an episode."""
    podcast = request.form.get('podcast', 'TMA')
    valid_podcasts = {'TMA': 'TMA', 'Balloon': 'Balloon', 'TMShow': 'TMShow'}
    table_name = valid_podcasts.get(podcast, 'TMA')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM {table_name} WHERE id = ?', (episode_id,))
    conn.commit()
    conn.close()

    flash('Episode deleted.', 'success')
    return redirect(url_for('admin.episodes', podcast=podcast))
