#!/home/axe08admin/.virtualenvs/tmaenv/bin/python
import requests
from bs4 import BeautifulSoup
import logging
import sqlite3
import time
from datetime import datetime
import os

# Change the working directory
#os.chdir('/home/axe08admin/Web_App')

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

# Print Script Start
print("Script started")
logging.info("Script started")

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
# Check if an episode already exists in the database to cut down on url unique constraint error
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

# Insert episode data into the database if it does not exist yet based on url
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


def convert_date_format(date_str):
    # Convert from "MONTH DAY, YEAR" to "YYYY-MM-DD"
    date_obj = datetime.strptime(date_str, '%B %d, %Y')
    return date_obj.strftime('%Y-%m-%d')

# Scrape the specified number of pages
def scrape_latest_podcasts(pages_to_scrape):
    setup_database()
    base_url = 'https://www.tmastl.com/podcasts/the-morning-after/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0'
    }
    delay = 3  #Delay timer when searching multiple pages

    for page_num in range(1, pages_to_scrape + 1):
        try:
            url = f"{base_url}?episode_page={page_num}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                episodes = soup.find_all('div', class_='col-10 px-3 align-self-center')

                for episode in episodes:
                    episode_title = episode.select_one('.post-title a').text
                    episode_url = episode.select_one('.post-title a')['href']
                    episode_date = episode.select_one('.byline time').text.strip()
                    # Convert date format before inserting into the database
                    episode_date_formatted = convert_date_format(episode_date)
                    episode_notes = episode.select_one('.the_content').get_text(separator="\n").strip()
                    episode_notes_cleaned = episode_notes.replace("Learn more about your ad choices. Visit megaphone.fm/adchoices", "").strip()
                    # Use formatted date for insertion O.o
                    insert_episode(episode_title, episode_date_formatted, episode_url, episode_notes_cleaned, 'TMA')
                    logging.info(f"Scraped: {episode_title}")

            else:
                logging.error(f"Failed to retrieve web page, status code: {response.status_code}")
                break  # Break out of the loop if the page doesn't exist

            time.sleep(delay)
        except Exception as e:
            logging.error(f"An error occurred on page {page_num}: {e}")
            break  # Break out of the loop if an exception occurs

    logging.info("Finished scraping the requested pages.")

# Run the scrape function for a specific number of pages
scrape_latest_podcasts(1)
