import sqlite3
import re
from collections import Counter
from flask import Flask
import os
import logging
from datetime import datetime

#app = Flask(__name__)
db_path = os.environ.get('DATABASE_URL', 'TMASTL.db')  # 'TMASTL.db' is the default value if the environment variable is not set

# Connect to your database
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Ensure the TMA_Tags table exists
c.execute("""
CREATE TABLE IF NOT EXISTS TMA_Note_Tags (
    tag TEXT PRIMARY KEY,
    count INTEGER NOT NULL
)
""")
logging.info("Ensured TMA_Tags table exists.")

c.execute("""
CREATE TABLE IF NOT EXISTS TMA_Title_Tags (
    tag TEXT PRIMARY KEY,
    count INTEGER NOT NULL
)
""")
logging.info("Ensured TMA_Title_Tags table exists.")

# Configure logging
logging.basicConfig(filename='podcast_processing.log',  # Log to a file; use 'filename'
                    filemode='a',  # Append mode, so logs are added to the file
                    format='%(asctime)s - %(levelname)s - %(message)s',  # Include timestamp, log level, and message
                    datefmt='%Y-%m-%d %H:%M:%S',  # Format for timestamps
                    level=logging.INFO)  # Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)


#stop words to not be included in tags
stop_words = set([
    "the", "and", "a", "to", "of", "in", "you", "it", "for", "on", "with", "as", "is", "that", "this",
    "at", "by", "not", "are", "be", "from", "but", "they", "or", "an", "so", "if", "out", "up", "about",
    "what", "which", "their", "there", "been", "one", "every", "do", "how", "has", "more", "her", "like",
    "when", "can", "who", "will", "just", "any", "him", "your", "his", "into", "some", "could", "than",
    "then", "now", "its", "only", "over", "after", "below", "other", "our", "out", "new", "used", "me",
    "we", "these", "those", "she", "himself", "herself", "itself", "myself", "yourself", "themselves",
    "ourselves", "no", "nor", "not", "don't", "should", "would", "could", "does", "doing", "because",
    "until", "during", "under", "against", "further", "once", "here", "there", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now", "segment", "1", "2",
    "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "01", "02", "03", "04", 
    "05", "06", "06", "07", "08", "09", "10",
])

# Fetch all unprocessed episodes (both show notes and titles)
c.execute("SELECT ID, SHOW_NOTES, TITLE FROM TMA WHERE processed_date IS NULL")
episodes = c.fetchall()

for episode_id, notes, title in episodes:
    # Process and insert note tags (as before)
    note_words = re.sub(r'\W+', ' ', notes.lower()).split()
    note_tags = [word for word in note_words if word not in stop_words]
    note_word_counts = Counter(note_tags)
    for tag, count in note_word_counts.items():
        c.execute("INSERT INTO TMA_Note_Tags (tag, count) VALUES (?, ?) ON CONFLICT(tag) DO UPDATE SET count = count + EXCLUDED.count", (tag, count))

    # New section: Process and insert title tags
    title_words = re.sub(r'\W+', ' ', title.lower()).split()
    title_tags = [word for word in title_words if word not in stop_words]
    title_word_counts = Counter(title_tags)
    for tag, count in title_word_counts.items():
        c.execute("INSERT INTO TMA_Title_Tags (tag, count) VALUES (?, ?) ON CONFLICT(tag) DO UPDATE SET count = count + EXCLUDED.count", (tag, count))
    
    # Update processed date for the episode
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE TMA SET processed_date = ? WHERE ID = ?", (current_time, episode_id))

# Commit and close
conn.commit()
conn.close()
logging.info("Finished processing unprocessed episodes and titles.")