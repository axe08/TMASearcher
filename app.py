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
    thirty_days_ago = datetime.now() - timedelta(days=30)
    query = f"SELECT * FROM {table_name} WHERE DATE >= ? ORDER BY DATE DESC"
    cursor.execute(query, (thirty_days_ago.strftime('%Y-%m-%d'),))
    episodes = cursor.fetchall()
    conn.close()
    # Convert the episodes into a JSON-friendly format
    episodes_json = [{'title': e[1], 'date': e[2], 'url': e[3], 'show_notes': e[4]} for e in episodes]
    return jsonify(episodes_json)


@app.route('/get_podcast_data', methods=['GET'])
def get_podcast_data():
    podcast_name = request.args.get('podcast')
    # Validate the podcast_name against a predefined list of valid names
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}

    table_name = valid_podcasts.get(podcast_name)  # Return None if the podcast_name is not valid

    if table_name is not None:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        query = f"SELECT * FROM {table_name} ORDER BY DATE DESC"
        cursor.execute(query)
        episodes = cursor.fetchall()
        conn.close()

        episodes_json = [{'title': e[1], 'date': e[2], 'url': e[3], 'show_notes': e[4]} for e in episodes]
        return jsonify(episodes_json)
    else:
        return jsonify({'error': 'Invalid podcast name'}), 400


def search_database(table_name, title, date, notes, match_type):
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Split title and notes into separate keywords
            title_keywords = title.split()
            notes_keywords = notes.split()

            # Start building the query
            query = f"SELECT TITLE, DATE, URL, SHOW_NOTES FROM {table_name} WHERE "

            # Add conditions for title keywords and notes
            title_conditions = ["TITLE LIKE ?" for _ in title_keywords]
            notes_conditions = ["SHOW_NOTES LIKE ?" for _ in notes_keywords]

            # Combine all conditions based on match type
            operator = " AND " if match_type == "all" else " OR "
            all_conditions = title_conditions + notes_conditions

            # Include date condition only if date is provided
            if date:
                all_conditions.append("DATE LIKE ?")
                params = ['%' + kw + '%' for kw in title_keywords + notes_keywords] + ['%' + date + '%']
            else:
                params = ['%' + kw + '%' for kw in title_keywords + notes_keywords]

            query += operator.join(all_conditions) + ";"

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
            {'title': row[0], 'date': row[1], 'url': row[2], 'show_notes': row[3]}
            for row in search_results
        ]

        results = {
            'count': len(search_results),  # Get the total count of results
            'podcasts': podcasts
        }
        return jsonify(results)
    else:
        return jsonify({'error': 'Invalid podcast name'}), 400


if __name__ == '__main__':
    app.run(debug=True)