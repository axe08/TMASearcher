from flask import Flask, request, jsonify, render_template
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from urllib.parse import quote
from dotenv import load_dotenv
from fuzzywuzzy import process
import re
from flask_login import LoginManager, current_user, login_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables
load_dotenv('.env')  # Flask config (SECRET_KEY, etc.)
load_dotenv('spot.env')  # Spotify credentials


app = Flask(__name__)

# Security: Require SECRET_KEY in production
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable must be set in .env")
db_path = os.environ.get('DATABASE_URL', 'TMASTL.db')  # 'TMASTL.db' is the default value if the environment variable is not set

# Rate limiting for security
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please sign in to access this page.'
login_manager.login_message_category = 'info'

# Import and register auth blueprint
from auth import auth_bp, User, get_user_by_id

app.register_blueprint(auth_bp, url_prefix='/auth')

# Apply rate limits to auth routes (protect against brute force)
limiter.limit("5 per minute")(app.view_functions['auth.login'])
limiter.limit("5 per minute")(app.view_functions['auth.signup'])


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login."""
    user_row = get_user_by_id(int(user_id))
    if user_row:
        return User(user_row)
    return None

def parse_date_input(date_input):
    """
    Parse flexible date input and return SQL pattern for matching.
    Supports:
    - Year: 2023 -> '2023%'
    - Month/Year: 05/2022, 2022-05 -> '2022-05%' 
    - Full date: 2023-11-06 -> '2023-11-06%'
    """
    if not date_input or not date_input.strip():
        return None
        
    date_input = date_input.strip()
    
    # Pattern 1: Year only (4 digits)
    if re.match(r'^\d{4}$', date_input):
        return f'{date_input}%'
    
    # Pattern 2: MM/YYYY format
    mm_yyyy_match = re.match(r'^(\d{1,2})/(\d{4})$', date_input)
    if mm_yyyy_match:
        month, year = mm_yyyy_match.groups()
        month = month.zfill(2)  # Pad with zero if needed
        return f'{year}-{month}%'
    
    # Pattern 3: YYYY-MM format 
    yyyy_mm_match = re.match(r'^(\d{4})-(\d{1,2})$', date_input)
    if yyyy_mm_match:
        year, month = yyyy_mm_match.groups()
        month = month.zfill(2)  # Pad with zero if needed
        return f'{year}-{month}%'
    
    # Pattern 4: Full date formats (YYYY-MM-DD, MM/DD/YYYY, etc.)
    # Try to parse as full date and convert to YYYY-MM-DD format
    try:
        # Try YYYY-MM-DD first (our storage format)
        if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_input):
            parts = date_input.split('-')
            year, month, day = parts[0], parts[1].zfill(2), parts[2].zfill(2)
            return f'{year}-{month}-{day}%'
        
        # Try MM/DD/YYYY format
        mm_dd_yyyy_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_input)
        if mm_dd_yyyy_match:
            month, day, year = mm_dd_yyyy_match.groups()
            month, day = month.zfill(2), day.zfill(2)
            return f'{year}-{month}-{day}%'
            
    except (ValueError, IndexError):
        pass
    
    # Fallback: use original input with wildcard (existing behavior)
    return f'%{date_input}%'

def get_spotify_access_token():
    """Retrieve Spotify access token."""
    client_id = os.environ.get('SPOTIFY_CLIENT_ID')
    client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')

    response = requests.post(
        'https://accounts.spotify.com/api/token',
        data={'grant_type': 'client_credentials'},
        auth=(client_id, client_secret)
    )
    if response.status_code != 200:
        raise Exception('Failed to retrieve Spotify access token')
    return response.json()['access_token']

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favorites')
def favorites():
    return render_template('favorites.html')

@app.route('/search_spotify', methods=['GET'])
def search_spotify():
    title = request.args.get('title')
    current_podcast = request.args.get('currentPodcast')

    podcast_table_map = {
        'TMA': 'TMASpot',
        'Balloon Party': 'BalloonSpot',
        'The Tim McKernan Show': 'TMShowSpot'
    }

    table_name = podcast_table_map.get(current_podcast)
    if not table_name:
        return jsonify({'error': 'Invalid podcast name'}), 400

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT Title, URL FROM {table_name}")
        episodes = cursor.fetchall()

        # Use fuzzy matching to find the best match
        match = process.extractOne(title, [ep[0] for ep in episodes], score_cutoff=80)
        if match:
            matched_title = match[0]  # Only retrieve the matched title
            # Find the URL of the matched title
            url = next((ep[1] for ep in episodes if ep[0] == matched_title), None)
            if url:
                return jsonify({'spotifyUrl': url})
            else:
                return jsonify({'error': 'URL not found for matched episode'}), 404
        else:
            return jsonify({'error': 'Episode not found'}), 404
    except sqlite3.Error as e:
        return jsonify({'error': f'Database error: {e}'}), 500
    finally:
        conn.close()

@app.route('/recent_episodes', methods=['GET'])
def recent_episodes():
    podcast_name = request.args.get('podcast', default='TMA')  # Default to TMA if no podcast is specified
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Episodes per page
    
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}

    table_name = valid_podcasts.get(podcast_name)
    if not table_name:
        return jsonify({'error': 'Invalid podcast name'}), 400

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    thirty_days_ago = datetime.now() - timedelta(days=90)
    
    # Get total count for pagination
    count_query = f"SELECT COUNT(*) FROM {table_name} WHERE DATE >= ?"
    cursor.execute(count_query, (thirty_days_ago.strftime('%Y-%m-%d'),))
    total_count = cursor.fetchone()[0]
    
    # Get paginated results
    offset = (page - 1) * per_page
    query = f"SELECT ID, TITLE, DATE, URL, SHOW_NOTES, mp3url, comments_count, favorites_count, likes_count FROM {table_name} WHERE DATE >= ? ORDER BY DATE DESC LIMIT ? OFFSET ?"
    cursor.execute(query, (thirty_days_ago.strftime('%Y-%m-%d'), per_page, offset))
    episodes = cursor.fetchall()
    conn.close()

    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_next = page < total_pages
    has_prev = page > 1

    # include the mp3url, comments_count, favorites_count, and likes_count
    episodes_json = [{'id': e[0], 'title': e[1], 'date': e[2], 'url': e[3], 'show_notes': e[4], 'mp3url': e[5], 'comments_count': e[6] or 0, 'favorites_count': e[7] or 0, 'likes_count': e[8] or 0} for e in episodes]
    
    return jsonify({
        'episodes': episodes_json,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_next': has_next,
            'has_prev': has_prev,
            'next_num': page + 1 if has_next else None,
            'prev_num': page - 1 if has_prev else None
        }
    })

@app.route('/episode/<int:episode_id>')
def episode(episode_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT title, date, url, show_notes, mp3url, comments_count, favorites_count, likes_count FROM TMA WHERE id = ?", (episode_id,))
    episode = cursor.fetchone()
    conn.close()

    if episode:
        episode_data = {
            'id': episode_id,
            'title': episode[0],
            'date': episode[1],
            'url': episode[2],
            'show_notes': episode[3],
            'mp3url': episode[4],
            'comments_count': episode[5] or 0,
            'favorites_count': episode[6] or 0,
            'likes_count': episode[7] or 0
        }
        return render_template('episode.html', episode=episode_data)
    else:
        return "Episode not found", 404

@app.route('/get_podcast_data', methods=['GET'])
def get_podcast_data():
    podcast_name = request.args.get('podcast')
    # Validate the podcast_name against a predefined list of valid names
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}

    table_name = valid_podcasts.get(podcast_name)
    if table_name is not None:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        query = f"SELECT * FROM {table_name} ORDER BY DATE DESC"
        cursor.execute(query)
        episodes = cursor.fetchall()
        conn.close()

        episodes_json = [{'title': e[1], 'date': e[2], 'url': e[3], 'show_notes': e[4], 'mp3url': e[5]} for e in episodes]
        return jsonify(episodes_json)
    else:
        return jsonify({'error': 'Invalid podcast name'}), 400



def build_search_filters(title, date, notes, match_type):
    """Return an SQL WHERE clause and parameters for podcast searches."""

    def standardize_apostrophes(text):
        return text.replace("'", "’") if text else text

    std_title = standardize_apostrophes(title or '')
    std_notes = standardize_apostrophes(notes or '')

    text_conditions = []
    text_params = []

    if match_type == 'exact':
        if std_title:
            text_conditions.append("REPLACE(TITLE, '''', '’') LIKE ?")
            text_params.append(f'%{std_title}%')
        if std_notes:
            text_conditions.append("REPLACE(SHOW_NOTES, '''', '’') LIKE ?")
            text_params.append(f'%{std_notes}%')
    else:
        for word in std_title.split():
            text_conditions.append("REPLACE(TITLE, '''', '’') LIKE ?")
            text_params.append(f'%{word}%')
        for word in std_notes.split():
            text_conditions.append("REPLACE(SHOW_NOTES, '''', '’') LIKE ?")
            text_params.append(f'%{word}%')

    date_condition = None
    date_param = None
    if date:
        date_pattern = parse_date_input(date)
        if date_pattern:
            date_condition = "DATE LIKE ?"
            date_param = date_pattern

    clauses = []
    params = []

    if match_type == 'any':
        if text_conditions:
            clauses.append("(" + " OR ".join(text_conditions) + ")")
            params.extend(text_params)
        else:
            clauses.append("1 = 1")
    else:
        if text_conditions:
            clauses.extend(text_conditions)
            params.extend(text_params)

    if date_condition:
        clauses.append(date_condition)
        params.append(date_param)

    if not clauses:
        clauses.append("1 = 1")

    where_clause = " AND ".join(clauses)
    return where_clause, params


@app.route('/search', methods=['GET'])
def search():
    title = request.args.get('title', '')
    date = request.args.get('date', '')
    notes = request.args.get('notes', '')
    current_podcast = request.args.get('currentPodcast', 'TMA')  # Default to TMA if not provided
    match_type = request.args.get('matchType', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Results per page

    # Validate the podcast_name against a predefined list of valid names
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}
    table_name = valid_podcasts.get(current_podcast)  # return None if the podcast_name is not valid

    if table_name is not None:
        where_clause, base_params = build_search_filters(title, date, notes, match_type)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            count_query = f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}"
            cursor.execute(count_query, base_params)
            total_count = cursor.fetchone()[0]

            total_pages = (total_count + per_page - 1) // per_page
            has_next = page < total_pages
            has_prev = page > 1

            start = (page - 1) * per_page
            data_query = (
                f"SELECT ID, TITLE, DATE, URL, SHOW_NOTES, mp3url, comments_count, favorites_count, likes_count FROM {table_name} "
                f"WHERE {where_clause} ORDER BY DATE DESC LIMIT ? OFFSET ?"
            )
            data_params = base_params + [per_page, start]

            cursor.execute(data_query, data_params)
            paginated_results = cursor.fetchall()

        podcasts = [
            {'id': row[0], 'title': row[1], 'date': row[2], 'url': row[3], 'show_notes': row[4], 'mp3url': row[5], 'comments_count': row[6] or 0, 'favorites_count': row[7] or 0, 'likes_count': row[8] or 0}
            for row in paginated_results
        ]

        results = {
            'count': total_count,  # Total count of all results
            'podcasts': podcasts,  # Current page results
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'total_pages': total_pages,
                'has_next': has_next,
                'has_prev': has_prev,
                'next_num': page + 1 if has_next else None,
                'prev_num': page - 1 if has_prev else None
            }
        }
        return jsonify(results)
    else:
        return jsonify({'error': 'Invalid podcast name'}), 400

@app.route('/tma_archive')
def tma_archive():
    return render_template('tma_archive.html')


@app.route('/popular')
def popular_episodes_page():
    """Popular episodes page - shows most engaged-with episodes."""
    return render_template('popular.html')


@app.route('/api/popular_episodes', methods=['GET'])
def popular_episodes_api():
    """Get popular episodes sorted by engagement metrics."""
    sort_by = request.args.get('sort', 'likes')  # likes, favorites, comments, streams
    page = request.args.get('page', 1, type=int)
    per_page = 30

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Determine sort column
    if sort_by == 'favorites':
        sort_col = 'favorites_count'
    elif sort_by == 'comments':
        sort_col = 'comments_count'
    elif sort_by == 'streams':
        sort_col = 'streams_count'
    else:
        sort_col = 'likes_count'

    # Get total count of episodes with at least 1 engagement
    cursor.execute(f'''
        SELECT COUNT(*) FROM TMA
        WHERE {sort_col} > 0
    ''')
    total_count = cursor.fetchone()[0]

    # Get paginated results
    offset = (page - 1) * per_page
    cursor.execute(f'''
        SELECT id, title, date, url, show_notes, mp3url,
               favorites_count, comments_count, likes_count, streams_count
        FROM TMA
        WHERE {sort_col} > 0
        ORDER BY {sort_col} DESC, date DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset))

    episodes = cursor.fetchall()
    conn.close()

    # Calculate pagination
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    has_next = page < total_pages
    has_prev = page > 1

    episodes_json = [{
        'id': e[0],
        'title': e[1],
        'date': e[2],
        'url': e[3],
        'show_notes': e[4],
        'mp3url': e[5],
        'favorites_count': e[6] or 0,
        'comments_count': e[7] or 0,
        'likes_count': e[8] or 0,
        'streams_count': e[9] or 0
    } for e in episodes]

    return jsonify({
        'episodes': episodes_json,
        'sort_by': sort_by,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_next': has_next,
            'has_prev': has_prev,
            'next_num': page + 1 if has_next else None,
            'prev_num': page - 1 if has_prev else None
        }
    })


@app.route('/fetch_archive_episodes', methods=['GET'])
def fetch_archive_episodes():
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Episodes per page
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get total count for pagination
    count_query = "SELECT COUNT(*) FROM TMA_Archive"
    cursor.execute(count_query)
    total_count = cursor.fetchone()[0]
    
    # Get paginated results
    offset = (page - 1) * per_page
    query = "SELECT filename, date, mp3url FROM TMA_Archive ORDER BY date DESC LIMIT ? OFFSET ?"
    cursor.execute(query, (per_page, offset))
    episodes = cursor.fetchall()
    conn.close()
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_next = page < total_pages
    has_prev = page > 1
    
    episodes_json = [{'filename': e[0], 'date': e[1], 'mp3url': e[2]} for e in episodes]

    return jsonify({
        'episodes': episodes_json,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_next': has_next,
            'has_prev': has_prev,
            'next_num': page + 1 if has_next else None,
            'prev_num': page - 1 if has_prev else None
        }
    })
@app.route('/search_archive', methods=['GET'])
def search_archive():
    match_type = request.args.get('matchType')
    filename = request.args.get('filename', '').strip()
    date = request.args.get('date', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Results per page

    query = "SELECT filename, date, mp3url FROM TMA_Archive WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM TMA_Archive WHERE 1=1"
    params = []

    # Search by filename
    if filename:
        if match_type == 'all':
            conditions = " AND " + " AND ".join([f"filename LIKE ?" for keyword in filename.split()])
            query += conditions
            count_query += conditions
            params.extend([f'%{keyword}%' for keyword in filename.split()])
        elif match_type == 'any':
            conditions = " AND (" + " OR ".join([f"filename LIKE ?" for keyword in filename.split()]) + ")"
            query += conditions
            count_query += conditions
            params.extend([f'%{keyword}%' for keyword in filename.split()])
        elif match_type == 'exact':
            conditions = " AND filename LIKE ?"
            query += conditions
            count_query += conditions
            params.append(f'%{filename}%')

    # Search by date
    if date:
        date_pattern = parse_date_input(date)
        if date_pattern:
            conditions = " AND date LIKE ?"
            query += conditions
            count_query += conditions
            params.append(date_pattern)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get total count for pagination
    cursor.execute(count_query, params)
    total_count = cursor.fetchone()[0]
    
    # Add pagination to main query
    query += " ORDER BY date DESC LIMIT ? OFFSET ?"
    offset = (page - 1) * per_page
    cursor.execute(query, params + [per_page, offset])
    episodes = cursor.fetchall()
    conn.close()
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_next = page < total_pages
    has_prev = page > 1

    episodes_json = [{'filename': e[0], 'date': e[1], 'mp3url': e[2]} for e in episodes]
    
    return jsonify({
        'episodes': episodes_json,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_next': has_next,
            'has_prev': has_prev,
            'next_num': page + 1 if has_next else None,
            'prev_num': page - 1 if has_prev else None
        }
    })

@app.route('/related_episodes/<int:episode_id>')
def related_episodes(episode_id):
    """Get related episodes from the same time period (±1 week)"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get the current episode's date
    cursor.execute("SELECT date FROM TMA WHERE id = ?", (episode_id,))
    episode_result = cursor.fetchone()
    
    if not episode_result:
        return jsonify({'error': 'Episode not found'}), 404
    
    episode_date = episode_result[0]
    
    # Query for episodes within ±1 week, excluding the current episode
    # Added randomization while still prioritizing proximity to date
    query = """
    SELECT id, title, date, url, show_notes, mp3url 
    FROM TMA 
    WHERE id != ? 
    AND date BETWEEN date(?, '-7 days') AND date(?, '+7 days')
    ORDER BY RANDOM()
    LIMIT 6
    """
    
    cursor.execute(query, (episode_id, episode_date, episode_date))
    all_candidates = cursor.fetchall()
    
    # If we have candidates, randomly select 4 from the 6 retrieved
    if len(all_candidates) > 4:
        import random
        related = random.sample(all_candidates, 4)
    else:
        related = all_candidates
    conn.close()
    
    related_episodes = []
    for episode in related:
        related_episodes.append({
            'id': episode[0],
            'title': episode[1],
            'date': episode[2],
            'url': episode[3],
            'show_notes': episode[4],
            'mp3url': episode[5]
        })
    
    return jsonify({'related_episodes': related_episodes})

@app.route('/random_episode')
def random_episode():
    """Get a random episode from the database"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get a random episode
    cursor.execute("""
        SELECT id, title, date, url, show_notes, mp3url 
        FROM TMA 
        ORDER BY RANDOM() 
        LIMIT 1
    """)
    
    episode = cursor.fetchone()
    conn.close()
    
    if episode:
        return jsonify({
            'episode': {
                'id': episode[0],
                'title': episode[1],
                'date': episode[2],
                'url': episode[3],
                'show_notes': episode[4],
                'mp3url': episode[5]
            }
        })
    else:
        return jsonify({'error': 'No episodes found'}), 404

@app.route('/notes.json')
def notes():
    from flask import send_file
    return send_file('notes.json', mimetype='application/json')


# ==========================================
# User Favorites API
# ==========================================

@app.route('/api/favorites', methods=['GET'])
@login_required
def get_favorites():
    """Get all favorites for the logged-in user."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT uf.episode_id, uf.podcast_name, uf.created_at,
               t.title, t.date, t.url, t.show_notes, t.mp3url
        FROM user_favorites uf
        JOIN TMA t ON uf.episode_id = t.id AND uf.podcast_name = 'TMA'
        WHERE uf.user_id = ?
        ORDER BY uf.created_at DESC
    ''', (current_user.id,))

    favorites = []
    for row in cursor.fetchall():
        favorites.append({
            'id': row['episode_id'],
            'title': row['title'],
            'date': row['date'],
            'url': row['url'],
            'show_notes': row['show_notes'],
            'mp3url': row['mp3url'],
            'addedAt': row['created_at']
        })

    conn.close()
    return jsonify({'favorites': favorites})


@app.route('/api/favorites', methods=['POST'])
@login_required
def add_favorite():
    """Add an episode to user's favorites."""
    data = request.get_json()
    episode_id = data.get('episode_id')
    podcast_name = data.get('podcast_name', 'TMA')

    if not episode_id:
        return jsonify({'error': 'Episode ID required'}), 400

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT OR IGNORE INTO user_favorites (user_id, podcast_name, episode_id)
            VALUES (?, ?, ?)
        ''', (current_user.id, podcast_name, episode_id))
        conn.commit()

        return jsonify({'success': True, 'message': 'Added to favorites'})
    except sqlite3.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/favorites/<int:episode_id>', methods=['DELETE'])
@login_required
def remove_favorite(episode_id):
    """Remove an episode from user's favorites."""
    podcast_name = request.args.get('podcast_name', 'TMA')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            DELETE FROM user_favorites
            WHERE user_id = ? AND episode_id = ? AND podcast_name = ?
        ''', (current_user.id, episode_id, podcast_name))
        conn.commit()

        return jsonify({'success': True, 'message': 'Removed from favorites'})
    except sqlite3.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/favorites/check/<int:episode_id>', methods=['GET'])
@login_required
def check_favorite(episode_id):
    """Check if an episode is favorited by the user."""
    podcast_name = request.args.get('podcast_name', 'TMA')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT 1 FROM user_favorites
        WHERE user_id = ? AND episode_id = ? AND podcast_name = ?
    ''', (current_user.id, episode_id, podcast_name))

    is_favorited = cursor.fetchone() is not None
    conn.close()

    return jsonify({'is_favorited': is_favorited})


@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Check if user is logged in (for frontend)."""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': current_user.id,
                'username': current_user.username
            }
        })
    return jsonify({'authenticated': False})


# ==========================================
# Comments API
# ==========================================

@app.route('/api/comments/<int:episode_id>', methods=['GET'])
def get_comments(episode_id):
    """Get all comments for an episode (public endpoint)."""
    podcast_name = request.args.get('podcast_name', 'TMA')

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT c.id, c.user_id, c.comment_text, c.timestamp_ref,
               c.created_at, c.updated_at, c.is_edited, c.likes_count,
               u.username
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.podcast_name = ? AND c.episode_id = ?
        ORDER BY c.created_at DESC
    ''', (podcast_name, episode_id))

    comments = []
    for row in cursor.fetchall():
        comments.append({
            'id': row['id'],
            'user_id': row['user_id'],
            'username': row['username'],
            'comment_text': row['comment_text'],
            'timestamp_ref': row['timestamp_ref'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'is_edited': bool(row['is_edited']),
            'likes_count': row['likes_count']
        })

    conn.close()
    return jsonify({'comments': comments, 'count': len(comments)})


@app.route('/api/comments', methods=['POST'])
@limiter.limit("10 per minute")
@login_required
def add_comment():
    """Add a comment to an episode."""
    data = request.get_json()
    episode_id = data.get('episode_id')
    podcast_name = data.get('podcast_name', 'TMA')
    comment_text = data.get('comment_text', '').strip()
    timestamp_ref = data.get('timestamp_ref')  # Optional: timestamp in seconds

    if not episode_id:
        return jsonify({'error': 'Episode ID required'}), 400

    if not comment_text:
        return jsonify({'error': 'Comment text required'}), 400

    if len(comment_text) > 2000:
        return jsonify({'error': 'Comment too long (max 2000 characters)'}), 400

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO comments (user_id, podcast_name, episode_id, comment_text, timestamp_ref)
            VALUES (?, ?, ?, ?, ?)
        ''', (current_user.id, podcast_name, episode_id, comment_text, timestamp_ref))
        conn.commit()

        comment_id = cursor.lastrowid

        return jsonify({
            'success': True,
            'message': 'Comment added',
            'comment': {
                'id': comment_id,
                'user_id': current_user.id,
                'username': current_user.username,
                'comment_text': comment_text,
                'timestamp_ref': timestamp_ref,
                'created_at': datetime.now().isoformat(),
                'is_edited': False,
                'likes_count': 0
            }
        })
    except sqlite3.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/comments/<int:comment_id>', methods=['PUT'])
@login_required
def edit_comment(comment_id):
    """Edit a comment (owner only)."""
    data = request.get_json()
    comment_text = data.get('comment_text', '').strip()

    if not comment_text:
        return jsonify({'error': 'Comment text required'}), 400

    if len(comment_text) > 2000:
        return jsonify({'error': 'Comment too long (max 2000 characters)'}), 400

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check ownership
    cursor.execute('SELECT user_id FROM comments WHERE id = ?', (comment_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Comment not found'}), 404

    if row[0] != current_user.id:
        conn.close()
        return jsonify({'error': 'Not authorized to edit this comment'}), 403

    try:
        cursor.execute('''
            UPDATE comments
            SET comment_text = ?, updated_at = CURRENT_TIMESTAMP, is_edited = 1
            WHERE id = ?
        ''', (comment_text, comment_id))
        conn.commit()

        return jsonify({'success': True, 'message': 'Comment updated'})
    except sqlite3.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Delete a comment (owner only)."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check ownership
    cursor.execute('SELECT user_id FROM comments WHERE id = ?', (comment_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Comment not found'}), 404

    if row[0] != current_user.id:
        conn.close()
        return jsonify({'error': 'Not authorized to delete this comment'}), 403

    try:
        cursor.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
        conn.commit()

        return jsonify({'success': True, 'message': 'Comment deleted'})
    except sqlite3.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==========================================
# Stream Tracking API
# ==========================================

@app.route('/api/stream/<int:episode_id>', methods=['POST'])
@limiter.limit("60 per minute")
def track_stream(episode_id):
    """Track when an episode is streamed (played)."""
    podcast_name = request.args.get('podcast_name', 'TMA')

    # Validate podcast name
    valid_podcasts = {'TMA': 'TMA', 'Balloon Party': 'Balloon', 'The Tim McKernan Show': 'TMShow'}
    table_name = valid_podcasts.get(podcast_name, 'TMA')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Increment streams_count
        cursor.execute(f'''
            UPDATE {table_name}
            SET streams_count = COALESCE(streams_count, 0) + 1
            WHERE id = ?
        ''', (episode_id,))
        conn.commit()

        # Get updated count
        cursor.execute(f'SELECT streams_count FROM {table_name} WHERE id = ?', (episode_id,))
        result = cursor.fetchone()
        streams_count = result[0] if result else 0

        return jsonify({'success': True, 'streams_count': streams_count})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==========================================
# Episode Likes API
# ==========================================

@app.route('/api/likes/<int:episode_id>', methods=['POST', 'DELETE'])
@limiter.limit("30 per minute")
@login_required
def toggle_like(episode_id):
    """Toggle like on an episode."""
    podcast_name = request.args.get('podcast_name', 'TMA')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if already liked
    cursor.execute('''
        SELECT id FROM episode_likes
        WHERE user_id = ? AND episode_id = ? AND podcast_name = ?
    ''', (current_user.id, episode_id, podcast_name))
    existing = cursor.fetchone()

    try:
        if existing:
            # Unlike
            cursor.execute('''
                DELETE FROM episode_likes
                WHERE user_id = ? AND episode_id = ? AND podcast_name = ?
            ''', (current_user.id, episode_id, podcast_name))
            conn.commit()
            action = 'unliked'
        else:
            # Like
            cursor.execute('''
                INSERT INTO episode_likes (user_id, podcast_name, episode_id)
                VALUES (?, ?, ?)
            ''', (current_user.id, podcast_name, episode_id))
            conn.commit()
            action = 'liked'

        # Get updated count
        cursor.execute('''
            SELECT likes_count FROM TMA WHERE id = ?
        ''', (episode_id,))
        row = cursor.fetchone()
        likes_count = row[0] if row else 0

        return jsonify({
            'success': True,
            'action': action,
            'likes_count': likes_count
        })
    except sqlite3.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/likes/<int:episode_id>/status', methods=['GET'])
def get_like_status(episode_id):
    """Check if current user has liked an episode."""
    podcast_name = request.args.get('podcast_name', 'TMA')

    if not current_user.is_authenticated:
        return jsonify({'is_liked': False, 'likes_count': 0})

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if liked
    cursor.execute('''
        SELECT 1 FROM episode_likes
        WHERE user_id = ? AND episode_id = ? AND podcast_name = ?
    ''', (current_user.id, episode_id, podcast_name))
    is_liked = cursor.fetchone() is not None

    # Get count
    cursor.execute('SELECT likes_count FROM TMA WHERE id = ?', (episode_id,))
    row = cursor.fetchone()
    likes_count = row[0] if row else 0

    conn.close()
    return jsonify({'is_liked': is_liked, 'likes_count': likes_count})


@app.route('/api/likes', methods=['GET'])
@login_required
def get_user_likes():
    """Get all episodes liked by current user."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT el.episode_id, el.podcast_name, el.created_at,
               t.title, t.date, t.url, t.show_notes, t.mp3url
        FROM episode_likes el
        JOIN TMA t ON el.episode_id = t.id AND el.podcast_name = 'TMA'
        WHERE el.user_id = ?
        ORDER BY el.created_at DESC
    ''', (current_user.id,))

    likes = []
    for row in cursor.fetchall():
        likes.append({
            'episode_id': row['episode_id'],
            'podcast_name': row['podcast_name'],
            'created_at': row['created_at'],
            'title': row['title'],
            'date': row['date'],
            'url': row['url'],
            'show_notes': row['show_notes'],
            'mp3url': row['mp3url']
        })

    conn.close()
    return jsonify({'likes': likes, 'count': len(likes)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
