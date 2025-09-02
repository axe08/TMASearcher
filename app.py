from flask import Flask, request, jsonify, render_template
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from urllib.parse import quote
from dotenv import load_dotenv
from fuzzywuzzy import process
import re

# Load environment variables
load_dotenv('spot.env')


app = Flask(__name__)
db_path = os.environ.get('DATABASE_URL', 'TMASTL.db')  # 'TMASTL.db' is the default value if the environment variable is not set

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
    query = f"SELECT * FROM {table_name} WHERE DATE >= ? ORDER BY DATE DESC LIMIT ? OFFSET ?"
    cursor.execute(query, (thirty_days_ago.strftime('%Y-%m-%d'), per_page, offset))
    episodes = cursor.fetchall()
    conn.close()
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_next = page < total_pages
    has_prev = page > 1
    
    # include the mp3url
    episodes_json = [{'id': e[0], 'title': e[1], 'date': e[2], 'url': e[3], 'show_notes': e[4], 'mp3url': e[5]} for e in episodes]
    
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

    cursor.execute("SELECT title, date, url, show_notes, mp3url FROM TMA WHERE id = ?", (episode_id,))
    episode = cursor.fetchone()
    conn.close()

    if episode:
        episode_data = {
            'id': episode_id,
            'title': episode[0],
            'date': episode[1],
            'url': episode[2],
            'show_notes': episode[3],
            'mp3url': episode[4]
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



def search_database(table_name, title, date, notes, match_type):
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            query = f"SELECT ID, TITLE, DATE, URL, SHOW_NOTES, mp3url FROM {table_name} WHERE "
            conditions = []
            params = []

            # Function to standardize apostrophes
            def standardize_apostrophes(text):
                return text.replace("'", "’") if text else text

            # Adjust search terms
            std_title = standardize_apostrophes(title)
            std_notes = standardize_apostrophes(notes)

            # Prepare conditions for title and notes
            if match_type == 'exact':
                if std_title:
                    conditions.append("REPLACE(TITLE, '''', '’') LIKE ?")
                    params.append(f'%{std_title}%')
                if std_notes:
                    conditions.append("REPLACE(SHOW_NOTES, '''', '’') LIKE ?")
                    params.append(f'%{std_notes}%')
            else:
                for word in std_title.split():
                    conditions.append("REPLACE(TITLE, '''', '’') LIKE ?")
                    params.append(f'%{word}%')
                for word in std_notes.split():
                    conditions.append("REPLACE(SHOW_NOTES, '''', '’') LIKE ?")
                    params.append(f'%{word}%')

            # Date condition
            if date:
                date_pattern = parse_date_input(date)
                if date_pattern:
                    conditions.append("DATE LIKE ?")
                    params.append(date_pattern)

            # Constructing the query based on conditions
            if match_type == 'all':
                query += " AND ".join(conditions) if conditions else "1 = 1"
            elif match_type == 'any':
                query += "(" + " OR ".join(conditions) + ")" if conditions else "1 = 1"
            else:  # For 'exact' and other cases
                query += " AND ".join(conditions) if conditions else "1 = 1"

            # Finalize query
            query += ";"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return rows
    except sqlite3.Error as e:
        print(f"An error occurred during database operation: {e}")
        return []


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
        # Get all search results for counting
        search_results = search_database(table_name, title, date, notes, match_type)
        total_count = len(search_results)
        
        # Calculate pagination
        total_pages = (total_count + per_page - 1) // per_page
        has_next = page < total_pages
        has_prev = page > 1
        
        # Apply pagination to results
        start = (page - 1) * per_page
        end = start + per_page
        paginated_results = search_results[start:end]
        
        podcasts = [
            {'id': row[0], 'title': row[1], 'date': row[2], 'url': row[3], 'show_notes': row[4], 'mp3url': row[5]}
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
