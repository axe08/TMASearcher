import feedparser
import sqlite3
from datetime import datetime

# Connect to your database
conn = sqlite3.connect('TMASTL.db')
cursor = conn.cursor()

# Function to fetch RSS feed
def fetch_rss_feed(url):
    return feedparser.parse(url)

# Helper function to parse and format the pubDate from RSS
def parse_pub_date(rss_date):
    # RSS date format: "Mon, 02 Apr 2018 12:07:52 -0000"
    rss_format = "%a, %d %b %Y %H:%M:%S %z"
    parsed_date = datetime.strptime(rss_date, rss_format)
    # Reformat to match your DB's date format (YYYY-MM-DD)
    return parsed_date.strftime("%Y-%m-%d")

# Helper function to normalize title (replaces apostrophes, ellipses, and dashes)
def normalize_title(title):
    # Replace all apostrophes (smart and straight) with a standard apostrophe
    title = title.replace("’", "'").replace("‘", "'")  # Normalize apostrophes
    # Replace all dashes (en dash, em dash) with a standard hyphen
    title = title.replace("–", "-").replace("—", "-")  # Normalize dashes
    # Replace ellipsis (…) with three dots (...)
    title = title.replace("…", "...")  # Normalize ellipses
    return title.strip().lower()

# Fetch RSS feed data
rss_feed_url = "https://feeds.megaphone.fm/tmastl"
rss_feed = fetch_rss_feed(rss_feed_url)

# Loop through RSS feed items
for entry in rss_feed.entries:
    rss_title = normalize_title(entry.title)  # Normalize RSS title in Python
    pub_date = parse_pub_date(entry.published)  # Parse and format the pub_date to match DB format
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

    # Execute the query (no REPLACE functions needed)
    cursor.execute(query, (rss_title, pub_date))
    
    result = cursor.fetchone()

    if result:
        db_id, db_title, db_date, db_mp3url = result
        print(f"Exact match found: RSS Title='{rss_title}', DB Title='{db_title}'")

        if not db_mp3url and mp3_url:
            # Update the mp3url in the database
            cursor.execute("UPDATE TMA SET mp3url = ? WHERE ID = ?", (mp3_url, db_id))
            print(f"Updated mp3url for Title: '{rss_title}'")
    else:
        # Debugging: Log failed match
        print(f"No match found for RSS Title: '{rss_title}' on Date: '{pub_date}'")

# Commit and close connection
conn.commit()
conn.close()
