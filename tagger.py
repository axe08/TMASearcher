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

def create_table(table_name):
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag TEXT PRIMARY KEY,
            count INTEGER NOT NULL
        )
        """)
        logging.info(f"Ensured {table_name} table exists.")

def process_and_insert_tags(table_name, notes, title):
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
        "05", "06", "06", "07", "08", "09", "10","00","45","2023","2022","2024","us"
    ])

    # Process and insert note tags
    note_words = re.sub(r'\W+', ' ', notes.lower()).split()
    note_tags = [word for word in note_words if word not in stop_words]
    note_word_counts = Counter(note_tags)
    for tag, count in note_word_counts.items():
        c.execute(f"INSERT INTO {table_name}_Note_Tags (tag, count) VALUES (?, ?) ON CONFLICT(tag) DO UPDATE SET count = count + EXCLUDED.count", (tag, count))

    # Process and insert title tags
    title_words = re.sub(r'\W+', ' ', title.lower()).split()
    title_tags = [word for word in title_words if word not in stop_words]
    title_word_counts = Counter(title_tags)
    for tag, count in title_word_counts.items():
        c.execute(f"INSERT INTO {table_name}_Title_Tags (tag, count) VALUES (?, ?) ON CONFLICT(tag) DO UPDATE SET count = count + EXCLUDED.count", (tag, count))

def process_episodes(table_name):
    # Fetch all unprocessed episodes (both show notes and titles)
    c.execute(f"SELECT ID, SHOW_NOTES, TITLE FROM {table_name} WHERE processed_date IS NULL")
    episodes = c.fetchall()

    for episode_id, notes, title in episodes:
        process_and_insert_tags(table_name, notes, title)
        
        # Update processed date for the episode
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute(f"UPDATE {table_name} SET processed_date = ? WHERE ID = ?", (current_time, episode_id))

# Ensure the tables exist and process episodes
create_table("TMA")
create_table("Balloon")
create_table("TMShow")

process_episodes("TMA")
process_episodes("Balloon")
process_episodes("TMShow")

# Commit and close
conn.commit()
conn.close()
