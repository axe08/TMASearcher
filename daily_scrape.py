from bs4 import BeautifulSoup
import requests
import logging
import sqlite3
from datetime import datetime
import os
import time
import re


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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.tmastl.com/',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
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

                    if episode_title_element and episode_date_element:
                        episode_title = episode_title_element.text.strip()
                        episode_url = episode['href']
                        episode_date = episode_date_element.text.strip()
                        episode_date_formatted = convert_date_format(episode_date)

                        # Go to the full episode page to get the full notes
                        episode_response = requests.get(episode_url, headers=headers)
                        if episode_response.status_code == 200:
                            episode_soup = BeautifulSoup(episode_response.text, 'lxml')
                            notes_container = episode_soup.find('div', class_='the_content')
                            if notes_container:
                                episode_notes = notes_container.get_text(separator="\n").strip()
                                episode_notes_cleaned = re.sub(
                                    r'Learn more about your ad choices\.?\s*Visit\s*podcastchoices\.com/adchoices\.?',
                                    '',
                                    episode_notes,
                                    flags=re.IGNORECASE
                                ).strip()
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
scrape_latest_podcasts(15)