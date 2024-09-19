from bs4 import BeautifulSoup
import requests
import logging
import sqlite3
from datetime import datetime
import os
import time


# Construct paths dynamically based on the current file's directory
current_directory = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(current_directory, 'tma_scraping.log')
database_path = os.path.join(current_directory, 'TMASTL.db')

# Setup logging
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s',
    force=True
)

# Database setup
def setup_database():
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS TMA (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TITLE TEXT NOT NULL,
            DATE TEXT NOT NULL,
            URL TEXT NOT NULL UNIQUE,
            SHOW_NOTES TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

# Check if an episode already exists in the database
def episode_exists(url, table_name):
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT 1 FROM {table_name} WHERE URL = ?", (url,))
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
    finally:
        conn.close()

# Insert episode data into the database
def insert_episode(title, date, url, show_notes, table_name):
    if not episode_exists(url, table_name):
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        try:
            cursor.execute(f'''
                INSERT INTO {table_name} (TITLE, DATE, URL, SHOW_NOTES)
                VALUES (?, ?, ?, ?)
            ''', (title, date, url, show_notes))
            conn.commit()
            logging.info(f"Successfully inserted: {title}")
        except sqlite3.IntegrityError as e:
            logging.error(f"Error inserting episode into database: {e}")
        finally:
            conn.close()
    else:
        logging.info(f"Episode already exists: {title}")

# Convert date format
def convert_date_format(date_str):
    date_obj = datetime.strptime(date_str, '%B %d, %Y')
    return date_obj.strftime('%Y-%m-%d')

# Scrape the webpage
def scrape_latest_podcasts(pages_to_scrape):
    setup_database()
    base_url = 'https://www.tmastl.com/podcasts/the-morning-after/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0'
    }
    delay = 3  # Delay between page requests

    for page_num in range(1, pages_to_scrape + 1):
        try:
            url = f"{base_url}?episode_page={page_num}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                episodes = soup.find_all('a', class_='episode-link')

                for episode in episodes:
                    episode_title_element = episode.find('h6', class_='post-title')
                    episode_date_element = episode.find('time')
                    episode_notes_element = episode.find('div', class_='the_content')

                    if episode_title_element and episode_date_element and episode_notes_element:
                        episode_title = episode_title_element.text.strip()
                        episode_url = episode['href']
                        episode_date = episode_date_element.text.strip()
                        episode_date_formatted = convert_date_format(episode_date)
                        episode_notes = episode_notes_element.get_text(separator="\n").strip()

                        # Clean episode notes
                        episode_notes_cleaned = episode_notes.replace("Learn more about your ad choices. Visit megaphone.fm/adchoices", "").strip()

                        # Insert into the database
                        insert_episode(episode_title, episode_date_formatted, episode_url, episode_notes_cleaned, 'TMA')
                        logging.info(f"Scraped: {episode_title}")
            else:
                logging.error(f"Failed to retrieve web page, status code: {response.status_code}")
                break  # Stop if we encounter a failed request

            time.sleep(delay)
        except Exception as e:
            logging.error(f"An error occurred on page {page_num}: {e}")
            break  # Break on exceptions

    logging.info("Finished scraping the requested pages.")

# Run the scrape function for a specific number of pages
scrape_latest_podcasts(20)
