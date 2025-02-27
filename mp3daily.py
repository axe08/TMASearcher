import feedparser
import sqlite3
from datetime import datetime, timedelta
import os
import unicodedata

# Construct db paths dynamically
current_directory = os.path.dirname(os.path.abspath(__file__))
database_path = os.path.join(current_directory, 'TMASTL.db')

# Connect to your database
conn = sqlite3.connect('TMASTL.db')
cursor = conn.cursor()

# Function to fetch RSS feed
def fetch_rss_feed(url):
    return feedparser.parse(url)

# Helper function to parse and format the pubDate from RSS
def parse_pub_date(rss_date):
    rss_format = "%a, %d %b %Y %H:%M:%S %z"
    parsed_date = datetime.strptime(rss_date, rss_format)
    return parsed_date.strftime("%Y-%m-%d")

# Helper function to normalize title (replaces apostrophes, ellipses, and dashes)
def normalize_title(title):
    title = unicodedata.normalize('NFKC', title)  # Normalize Unicode
    title = title.replace("’", "'").replace("‘", "'")  # Normalize apostrophes
    title = title.replace("–", "-").replace("—", "-").replace("−", "-").replace("‒", "-")  # Normalize dashes
    title = title.replace("…", "...")  # Normalize ellipses
    return title.strip().lower()

# Get the date of N days ago to limit the RSS feed items
def get_n_days_ago(days):
    n_days_ago = datetime.now() - timedelta(days=days)
    return n_days_ago.strftime("%Y-%m-%d")

# Fetch RSS feed data
rss_feed_url = "https://feeds.megaphone.fm/tmastl"
rss_feed = fetch_rss_feed(rss_feed_url)

# Define the number of days to look back (e.g., only process episodes from the last 3 days)
days_to_look_back = 4
cutoff_date = get_n_days_ago(days_to_look_back)

# Loop through RSS feed items
for entry in rss_feed.entries:
    rss_title = normalize_title(entry.title)  # Normalize RSS title
    pub_date = parse_pub_date(entry.published)  # Parse and format the pub_date to match DB format

    # Skip episodes older than the cutoff date
    if pub_date < cutoff_date:
        continue

    mp3_url = entry.enclosures[0].href if entry.enclosures else None

    # Debugging: Log the title and date from RSS feed
    print(f"RSS Title: '{rss_title}', RSS Date: '{pub_date}', MP3 URL: {mp3_url}")

    # SQL query with no REPLACE functions, since normalization is done in Python
    query = """
        SELECT ID, TITLE, DATE, mp3url 
        FROM TMA 
        WHERE LOWER(TRIM(TITLE)) = ? AND DATE = ?
    """
    print(f"Executing SQL Query: {query} with parameters ({rss_title}, {pub_date})")

    # Execute the query to check if the entry exists in the database
    cursor.execute(query, (rss_title, pub_date))
    result = cursor.fetchone()

    if result:
        db_id, db_title, db_date, db_mp3url = result
        print(f"Exact match found: RSS Title='{rss_title}', DB Title='{db_title}'")

        # Update the mp3url if it’s missing and available
        if not db_mp3url and mp3_url:
            cursor.execute("UPDATE TMA SET mp3url = ? WHERE ID = ?", (mp3_url, db_id))
            print(f"Updated mp3url for Title: '{rss_title}'")
    else:
    # Debugging: Log failed match
        print(f"No match found for RSS Title: '{rss_title}' on Date: '{pub_date}'")

    # Case-insensitive check in Python
    cursor.execute("SELECT ID, TITLE, mp3url FROM TMA WHERE DATE = ?", (pub_date,))
    db_entries = cursor.fetchall()
    found_match = False
    for db_id, db_title, db_mp3url in db_entries:
        if normalize_title(db_title) == rss_title:
            print(f"Case-insensitive match found: RSS Title='{rss_title}', DB Title='{db_title}'")
            if not db_mp3url and mp3_url:
                cursor.execute("UPDATE TMA SET mp3url = ? WHERE ID = ?", (mp3_url, db_id))
                print(f"Updated mp3url for Title: '{rss_title}'")
            found_match = True
            break
    if not found_match:
        print (f"DB titles on date {pub_date}: {[(title, ) for title, in cursor.execute('SELECT TITLE FROM TMA WHERE DATE = ?',(pub_date,)).fetchall()]}")
# Commit and close connection
conn.commit()
conn.close()