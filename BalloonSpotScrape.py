import os
import sqlite3
import logging
import requests
import base64
from dotenv import load_dotenv

# Construct paths dynamically based on the current file's directory
current_directory = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(current_directory, 'Balloon_spotify_scraping.log')
database_path = os.path.join(current_directory, 'TMASTL.db')

# Setup logging
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s',
    force=True
)


# Function to get Spotify access token
def get_spotify_access_token(client_id, client_secret):
    token_url = 'https://accounts.spotify.com/api/token'
    client_creds = f"{client_id}:{client_secret}"
    client_creds_b64 = base64.b64encode(client_creds.encode()).decode()

    headers = {
        "Authorization": f"Basic {client_creds_b64}"
    }
    payload = {
        "grant_type": "client_credentials"
    }

    response = requests.post(token_url, headers=headers, data=payload)
    if response.status_code in range(200, 299):
        token_data = response.json()
        logging.info("Successfully obtained access token.")
        return token_data['access_token']
    else:
        logging.error(f"Failed to obtain access token: Status code {response.status_code}")
        return None

# Function to fetch podcast episodes
def fetch_podcast_episodes(access_token, show_id, max_episodes=8, limit=50, market='US'):
    episodes_url = f'https://api.spotify.com/v1/shows/{show_id}/episodes'
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"market": market, "limit": limit, "offset": 0}

    all_episodes = []
    while len(all_episodes) < max_episodes:
        response = requests.get(episodes_url, headers=headers, params=params)
        if response.status_code != 200:
            logging.error(f"Error fetching episodes: Status code {response.status_code}")
            break

        episodes_data = response.json()
        episodes = episodes_data.get('items', [])
        all_episodes.extend(episodes[:max_episodes - len(all_episodes)])  # Add only the needed episodes

        if 'next' in episodes_data and episodes_data['next'] is not None:
            params['offset'] += limit
        else:
            break

    return all_episodes

# Function to check if an episode already exists
def episode_exists(url, table_name, db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT 1 FROM {table_name} WHERE URL = ?", (url,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

# Function to insert episodes
def insert_episode(spotify_id, title, date, url, description, table_name, db_path):
    logging.info(f"Attempting to insert episode: {title}")
    if not episode_exists(url, table_name, db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(f'''
                INSERT INTO {table_name} (ID, Title, Date, URL, Description)
                VALUES (?, ?, ?, ?, ?)
            ''', (spotify_id, title, date, url, description))
            conn.commit()
            logging.info(f"Successfully inserted: {title}")
        except sqlite3.IntegrityError as e:
            logging.error(f"Error inserting episode: {e}")
        finally:
            conn.close()
    else:
        logging.info(f"Episode already exists: {title}")

# Function to set up the database
def setup_database():
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS BalloonSpot (
                ID TEXT PRIMARY KEY,
                Title TEXT NOT NULL,
                Date TEXT NOT NULL,
                URL TEXT NOT NULL UNIQUE,
                Description TEXT NOT NULL
            );
        ''')
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Database setup error: {e}")
    finally:
        conn.close()

# Main script logic
def main():
    logging.info("Script started")

    load_dotenv(os.path.join(current_directory, 'spot.env'))
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

    access_token = get_spotify_access_token(client_id, client_secret)
    if not access_token:
        logging.error("Failed to get access token. Check your Spotify credentials.")
        return

    setup_database()

    show_id = '1ksryirpx66HWJnZFtMEo0'
    episodes = fetch_podcast_episodes(access_token, show_id)

    for episode in episodes:
        spotify_id = episode.get('id')  # Extracting the Spotify ID
        insert_episode(
            spotify_id=spotify_id,  # Adding the Spotify ID as an argument
            title=episode.get('name'),
            date=episode.get('release_date'),
            url=episode.get('external_urls', {}).get('spotify'),
            description=episode.get('description'),
            table_name='BalloonSpot',
            db_path=database_path
        )

    logging.info("Podcast episodes have been successfully updated.")

if __name__ == "__main__":
    main()
