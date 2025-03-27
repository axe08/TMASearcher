from flask import Flask, request, jsonify, render_template
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from urllib.parse import quote
from dotenv import load_dotenv
from fuzzywuzzy import process

# Load environment variables
load_dotenv('spot.env')


app = Flask(__name__)
db_path = os.environ.get('DATABASE_URL', 'TMASTL.db')  # 'TMASTL.db' is the default value if the environment variable is not set

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
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}

    table_name = valid_podcasts.get(podcast_name)
    if not table_name:
        return jsonify({'error': 'Invalid podcast name'}), 400

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    thirty_days_ago = datetime.now() - timedelta(days=90)
    query = f"SELECT * FROM {table_name} WHERE DATE >= ? ORDER BY DATE DESC"
    cursor.execute(query, (thirty_days_ago.strftime('%Y-%m-%d'),))
    episodes = cursor.fetchall()
    conn.close()
    
    # include the mp3url
    episodes_json = [{'id': e[0], 'title': e[1], 'date': e[2], 'url': e[3], 'show_notes': e[4], 'mp3url': e[5]} for e in episodes]
    return jsonify(episodes_json)

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
                conditions.append("DATE LIKE ?")
                params.append(f'%{date}%')

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

    # Validate the podcast_name against a predefined list of valid names
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}
    table_name = valid_podcasts.get(current_podcast)  # return None if the podcast_name is not valid

    if table_name is not None:
        # Pass the correct table name and match type
        search_results = search_database(table_name, title, date, notes, match_type)  
        podcasts = [
            {'id': row[0], 'title': row[1], 'date': row[2], 'url': row[3], 'show_notes': row[4], 'mp3url': row[5]}
            for row in search_results
        ]


        results = {
            'count': len(search_results),  # Get the total count of results
            'podcasts': podcasts
        }
        return jsonify(results)
    else:
        return jsonify({'error': 'Invalid podcast name'}), 400

@app.route('/tma_archive')
def tma_archive():
    return render_template('tma_archive.html')


@app.route('/fetch_archive_episodes', methods=['GET'])
def fetch_archive_episodes():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = "SELECT filename, date, mp3url FROM TMA_Archive ORDER BY date DESC"
    cursor.execute(query)
    episodes = cursor.fetchall()
    conn.close()
    episodes_json = [{'filename': e[0], 'date': e[1], 'mp3url': e[2]} for e in episodes]

    return jsonify(episodes_json)
@app.route('/search_archive', methods=['GET'])

@app.route('/search_archive', methods=['GET'])
def search_archive():
    match_type = request.args.get('matchType')
    filename = request.args.get('filename', '').strip()
    date = request.args.get('date', '').strip()

    query = "SELECT filename, date, mp3url FROM TMA_Archive WHERE 1=1"
    params = []

    # Search by filename
    if filename:
        if match_type == 'all':
            query += " AND " + " AND ".join([f"filename LIKE ?" for keyword in filename.split()])
            params.extend([f'%{keyword}%' for keyword in filename.split()])
        elif match_type == 'any':
            query += " AND (" + " OR ".join([f"filename LIKE ?" for keyword in filename.split()]) + ")"
            params.extend([f'%{keyword}%' for keyword in filename.split()])
        elif match_type == 'exact':
            query += " AND filename LIKE ?"
            params.append(f'%{filename}%')

    # Search by date
    if date:
        query += " AND date LIKE ?"
        params.append(f'%{date}%')


    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(query, params)
    episodes = cursor.fetchall()
    conn.close()

    episodes_json = [{'filename': e[0], 'date': e[1], 'mp3url': e[2]} for e in episodes]
    return jsonify(episodes_json)

@app.route('/notes.json')
def notes():
    from flask import send_file
    return send_file('notes.json', mimetype='application/json')

if __name__ == '__main__':
    app.run(debug=True)