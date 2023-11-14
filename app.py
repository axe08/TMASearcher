from flask import Flask, request, jsonify
import sqlite3
from flask import render_template
from datetime import datetime, timedelta
import os
import requests
from urllib.parse import quote
from dotenv import load_dotenv
from fuzzywuzzy import fuzz

load_dotenv('spot.env')


app = Flask(__name__)
db_path = os.environ.get('DATABASE_URL', 'TMASTL.db')  # 'TMASTL.db' is the default value if the environment variable is not set

def get_spotify_access_token():
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

@app.route('/search_spotify', methods=['GET'])
def search_spotify():
    title = request.args.get('title')
    showId = request.args.get('showId')
    access_token = get_spotify_access_token()

    # URL-encode the title for the query
    encoded_title = quote(title)

    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(f'https://api.spotify.com/v1/shows/{showId}/episodes?query={encoded_title}&type=episode', headers=headers)

    if response.status_code == 200:
        episodes = response.json().get('items', [])
        for episode in episodes:
            # Using fuzzy matching for a more flexible comparison
            if fuzz.partial_ratio(episode['name'].lower(), title.lower()) > 80:  # Adjust this threshold as needed
                return jsonify({'spotifyUrl': episode['external_urls']['spotify']})
        
        return jsonify({'error': 'Episode not found on Spotify'}), 404
    else:
        return jsonify({'error': 'Failed to fetch data from Spotify'}), response.status_code


@app.route('/')
def index():
    return render_template('index.html')

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


def search_database(table_name, title, date, notes):
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            query = f"""
            SELECT TITLE, DATE, URL, SHOW_NOTES
            FROM {table_name}
            WHERE TITLE LIKE ?
              AND DATE LIKE ?
              AND SHOW_NOTES LIKE ?;
            """
            cursor.execute(query, ('%' + title + '%', '%' + date + '%', '%' + notes + '%'))
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

    # Validate the podcast_name against a predefined list of valid names
    valid_podcasts = {'TMA': 'TMA', 'The Tim McKernan Show': 'TMShow', 'Balloon Party': 'Balloon'}
    table_name = valid_podcasts.get(current_podcast)  # return None if the podcast_name is not valid

    if table_name is not None:
        search_results = search_database(table_name, title, date, notes)  # Pass the correct table name
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