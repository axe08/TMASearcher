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

print("Script started")
logging.info("Script started")

LOG_FILE_PATH = '/home/axe08admin/Web_App/tma_scraping.log'

# Setup logging with timestamp
logging.basicConfig(
    filename='tma_scraping.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s',
    force=True
)

# Full path to the database
DATABASE_PATH = '/home/axe08admin/Web_App/TMASTL.db'

# Database setup function
def setup_database():
    conn = sqlite3.connect(DATABASE_PATH)
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

# Function to insert episode data into the database
def insert_episode(title, date, url, show_notes):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO TMA (TITLE, DATE, URL, SHOW_NOTES)
            VALUES (?, ?, ?, ?)
        ''', (title, date, url, show_notes))
        conn.commit()
    except sqlite3.IntegrityError as e:
        logging.error(f"Error inserting episode into database: {e}")
    finally:
        conn.close()

def convert_date_format(date_str):
    # Convert from "MONTH DAY, YEAR" to "YYYY-MM-DD"
    date_obj = datetime.strptime(date_str, '%B %d, %Y')
    return date_obj.strftime('%Y-%m-%d')

# Modified function to scrape the specified number of pages
def scrape_latest_podcasts(pages_to_scrape):
    setup_database()
    base_url = 'https://www.tmastl.com/podcasts/the-morning-after/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:94.0) Gecko/20100101 Firefox/94.0'
    }
    delay = 3  # Be ethical with your scraping delay

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
                    # Convert the date format here before inserting into the database
                    episode_date_formatted = convert_date_format(episode_date)
                    episode_notes = episode.select_one('.the_content').get_text(separator="\n").strip()
                    episode_notes_cleaned = episode_notes.replace("Learn more about your ad choices. Visit megaphone.fm/adchoices", "").strip()
                    # Use the formatted date for insertion
                    insert_episode(episode_title, episode_date_formatted, episode_url, episode_notes_cleaned)
                    logging.info(f"Scraped: {episode_title}")

            else:
                logging.error(f"Failed to retrieve web page, status code: {response.status_code}")
                break  # Break out of the loop if the page doesn't exist

            time.sleep(delay)
        except Exception as e:
            logging.error(f"An error occurred on page {page_num}: {e}")
            break  # Break out of the loop if an exception occurs

    logging.info("Finished scraping the requested pages.")

# Run the scrape function
scrape_latest_podcasts(1)
