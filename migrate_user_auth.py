#!/usr/bin/env python3
"""
Database Migration Script for User Authentication & Social Features
Run this script to add the required tables and triggers for user auth.

Usage:
    python migrate_user_auth.py [--dry-run]

Options:
    --dry-run    Print SQL statements without executing them
"""

import sqlite3
import sys
import os
from datetime import datetime

# Database path
DATABASE_PATH = os.environ.get('DATABASE_URL', 'TMASTL.db')

# SQL statements for new tables
CREATE_TABLES_SQL = """
-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    is_admin BOOLEAN DEFAULT 0,
    UNIQUE(username COLLATE NOCASE),
    UNIQUE(email COLLATE NOCASE)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- User Favorites Table
CREATE TABLE IF NOT EXISTS user_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    podcast_name TEXT NOT NULL,
    episode_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, podcast_name, episode_id)
);

CREATE INDEX IF NOT EXISTS idx_user_favorites_user ON user_favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_user_favorites_episode ON user_favorites(podcast_name, episode_id);

-- Comments Table
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    podcast_name TEXT NOT NULL,
    episode_id INTEGER NOT NULL,
    comment_text TEXT NOT NULL,
    timestamp_ref INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    is_edited BOOLEAN DEFAULT 0,
    likes_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comments_episode ON comments(podcast_name, episode_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_user ON comments(user_id);

-- Comment Likes Table
CREATE TABLE IF NOT EXISTS comment_likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    comment_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (comment_id) REFERENCES comments(id) ON DELETE CASCADE,
    UNIQUE(user_id, comment_id)
);

CREATE INDEX IF NOT EXISTS idx_comment_likes_comment ON comment_likes(comment_id);
CREATE INDEX IF NOT EXISTS idx_comment_likes_user ON comment_likes(user_id);

-- Password Reset Tokens Table
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reset_tokens_token ON password_reset_tokens(token);

-- Episode Likes Table
CREATE TABLE IF NOT EXISTS episode_likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    podcast_name TEXT NOT NULL,
    episode_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, podcast_name, episode_id)
);

CREATE INDEX IF NOT EXISTS idx_episode_likes_user ON episode_likes(user_id);
CREATE INDEX IF NOT EXISTS idx_episode_likes_episode ON episode_likes(podcast_name, episode_id);
"""

# SQL for adding count columns to episode tables
ALTER_EPISODE_TABLES_SQL = {
    'TMA': [
        "ALTER TABLE TMA ADD COLUMN favorites_count INTEGER DEFAULT 0;",
        "ALTER TABLE TMA ADD COLUMN comments_count INTEGER DEFAULT 0;",
        "ALTER TABLE TMA ADD COLUMN likes_count INTEGER DEFAULT 0;",
        "ALTER TABLE TMA ADD COLUMN streams_count INTEGER DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_tma_favorites ON TMA(favorites_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tma_comments ON TMA(comments_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tma_likes ON TMA(likes_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tma_streams ON TMA(streams_count DESC);",
    ],
    'Balloon': [
        "ALTER TABLE Balloon ADD COLUMN favorites_count INTEGER DEFAULT 0;",
        "ALTER TABLE Balloon ADD COLUMN comments_count INTEGER DEFAULT 0;",
        "ALTER TABLE Balloon ADD COLUMN likes_count INTEGER DEFAULT 0;",
        "ALTER TABLE Balloon ADD COLUMN streams_count INTEGER DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_balloon_favorites ON Balloon(favorites_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_balloon_comments ON Balloon(comments_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_balloon_likes ON Balloon(likes_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_balloon_streams ON Balloon(streams_count DESC);",
    ],
    'TMShow': [
        "ALTER TABLE TMShow ADD COLUMN favorites_count INTEGER DEFAULT 0;",
        "ALTER TABLE TMShow ADD COLUMN comments_count INTEGER DEFAULT 0;",
        "ALTER TABLE TMShow ADD COLUMN likes_count INTEGER DEFAULT 0;",
        "ALTER TABLE TMShow ADD COLUMN streams_count INTEGER DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_tmshow_favorites ON TMShow(favorites_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tmshow_comments ON TMShow(comments_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tmshow_likes ON TMShow(likes_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_tmshow_streams ON TMShow(streams_count DESC);",
    ],
}

# SQL for triggers
CREATE_TRIGGERS_SQL = """
-- Favorites count triggers
CREATE TRIGGER IF NOT EXISTS increment_favorites_tma AFTER INSERT ON user_favorites
WHEN NEW.podcast_name = 'TMA'
BEGIN
    UPDATE TMA SET favorites_count = favorites_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_favorites_balloon AFTER INSERT ON user_favorites
WHEN NEW.podcast_name = 'Balloon'
BEGIN
    UPDATE Balloon SET favorites_count = favorites_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_favorites_tmshow AFTER INSERT ON user_favorites
WHEN NEW.podcast_name = 'TMShow'
BEGIN
    UPDATE TMShow SET favorites_count = favorites_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_favorites_tma AFTER DELETE ON user_favorites
WHEN OLD.podcast_name = 'TMA'
BEGIN
    UPDATE TMA SET favorites_count = favorites_count - 1 WHERE ID = OLD.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_favorites_balloon AFTER DELETE ON user_favorites
WHEN OLD.podcast_name = 'Balloon'
BEGIN
    UPDATE Balloon SET favorites_count = favorites_count - 1 WHERE ID = OLD.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_favorites_tmshow AFTER DELETE ON user_favorites
WHEN OLD.podcast_name = 'TMShow'
BEGIN
    UPDATE TMShow SET favorites_count = favorites_count - 1 WHERE ID = OLD.episode_id;
END;

-- Comments count triggers
CREATE TRIGGER IF NOT EXISTS increment_comments_tma AFTER INSERT ON comments
WHEN NEW.podcast_name = 'TMA'
BEGIN
    UPDATE TMA SET comments_count = comments_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_comments_balloon AFTER INSERT ON comments
WHEN NEW.podcast_name = 'Balloon'
BEGIN
    UPDATE Balloon SET comments_count = comments_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_comments_tmshow AFTER INSERT ON comments
WHEN NEW.podcast_name = 'TMShow'
BEGIN
    UPDATE TMShow SET comments_count = comments_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_comments_tma AFTER DELETE ON comments
WHEN OLD.podcast_name = 'TMA'
BEGIN
    UPDATE TMA SET comments_count = comments_count - 1 WHERE ID = OLD.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_comments_balloon AFTER DELETE ON comments
WHEN OLD.podcast_name = 'Balloon'
BEGIN
    UPDATE Balloon SET comments_count = comments_count - 1 WHERE ID = OLD.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_comments_tmshow AFTER DELETE ON comments
WHEN OLD.podcast_name = 'TMShow'
BEGIN
    UPDATE TMShow SET comments_count = comments_count - 1 WHERE ID = OLD.episode_id;
END;

-- Comment likes count trigger
CREATE TRIGGER IF NOT EXISTS increment_comment_likes AFTER INSERT ON comment_likes
BEGIN
    UPDATE comments SET likes_count = likes_count + 1 WHERE id = NEW.comment_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_comment_likes AFTER DELETE ON comment_likes
BEGIN
    UPDATE comments SET likes_count = likes_count - 1 WHERE id = OLD.comment_id;
END;

-- Episode likes count triggers
CREATE TRIGGER IF NOT EXISTS increment_episode_likes_tma AFTER INSERT ON episode_likes
WHEN NEW.podcast_name = 'TMA'
BEGIN
    UPDATE TMA SET likes_count = likes_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_episode_likes_balloon AFTER INSERT ON episode_likes
WHEN NEW.podcast_name = 'Balloon'
BEGIN
    UPDATE Balloon SET likes_count = likes_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_episode_likes_tmshow AFTER INSERT ON episode_likes
WHEN NEW.podcast_name = 'TMShow'
BEGIN
    UPDATE TMShow SET likes_count = likes_count + 1 WHERE ID = NEW.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_episode_likes_tma AFTER DELETE ON episode_likes
WHEN OLD.podcast_name = 'TMA'
BEGIN
    UPDATE TMA SET likes_count = likes_count - 1 WHERE ID = OLD.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_episode_likes_balloon AFTER DELETE ON episode_likes
WHEN OLD.podcast_name = 'Balloon'
BEGIN
    UPDATE Balloon SET likes_count = likes_count - 1 WHERE ID = OLD.episode_id;
END;

CREATE TRIGGER IF NOT EXISTS decrement_episode_likes_tmshow AFTER DELETE ON episode_likes
WHEN OLD.podcast_name = 'TMShow'
BEGIN
    UPDATE TMShow SET likes_count = likes_count - 1 WHERE ID = OLD.episode_id;
END;
"""


def column_exists(cursor, table, column):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def table_exists(cursor, table):
    """Check if a table exists."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def run_migration(dry_run=False):
    """Run the database migration."""
    print(f"Database Migration for User Auth & Social Features")
    print(f"=" * 50)
    print(f"Database: {DATABASE_PATH}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Time: {datetime.now().isoformat()}")
    print()

    if not os.path.exists(DATABASE_PATH):
        print(f"ERROR: Database file not found: {DATABASE_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    try:
        # Step 1: Create new tables
        print("Step 1: Creating new tables...")
        if dry_run:
            print(CREATE_TABLES_SQL)
        else:
            cursor.executescript(CREATE_TABLES_SQL)
            print("  - Created users table")
            print("  - Created user_favorites table")
            print("  - Created comments table")
            print("  - Created comment_likes table")
            print("  - Created episode_likes table")
            print("  - Created password_reset_tokens table")
        print()

        # Step 2: Add columns to episode tables
        print("Step 2: Adding count columns to episode tables...")
        for table, statements in ALTER_EPISODE_TABLES_SQL.items():
            if not table_exists(cursor, table):
                print(f"  - Skipping {table} (table does not exist)")
                continue

            for sql in statements:
                if 'ADD COLUMN' in sql:
                    col_name = sql.split('ADD COLUMN')[1].split()[0]
                    if column_exists(cursor, table, col_name):
                        print(f"  - Skipping {table}.{col_name} (already exists)")
                        continue

                if dry_run:
                    print(f"  SQL: {sql}")
                else:
                    try:
                        cursor.execute(sql)
                        print(f"  - Executed: {sql[:60]}...")
                    except sqlite3.OperationalError as e:
                        if 'duplicate column' in str(e).lower():
                            print(f"  - Skipping (already exists): {sql[:40]}...")
                        else:
                            raise
        print()

        # Step 3: Create triggers
        print("Step 3: Creating triggers...")
        if dry_run:
            print(CREATE_TRIGGERS_SQL)
        else:
            cursor.executescript(CREATE_TRIGGERS_SQL)
            print("  - Created favorites count triggers")
            print("  - Created comments count triggers")
            print("  - Created comment likes trigger")
            print("  - Created episode likes triggers")
        print()

        # Commit changes
        if not dry_run:
            conn.commit()
            print("Migration completed successfully!")
        else:
            print("Dry run completed. No changes made.")

        # Verify tables
        print()
        print("Verification:")
        for table in ['users', 'user_favorites', 'comments', 'comment_likes', 'episode_likes', 'password_reset_tokens']:
            exists = table_exists(cursor, table)
            print(f"  - {table}: {'EXISTS' if exists else 'MISSING'}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    run_migration(dry_run)
