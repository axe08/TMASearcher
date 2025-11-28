# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TMASearcher is a podcast episode search and playback system for three podcast shows hosted on tmastl.com:
- The Morning After (TMA) - Primary focus with full feature support
- Balloon Party with Tim McKernan
- The Tim McKernan Show

The system combines web scraping, MP3 direct playback, Spotify integration, and a Flask-based web application with advanced search, favorites management, and a persistent play queue.

## Database Architecture

Central SQLite database: `TMASTL.db`

**Episode Tables:**
- `TMA`, `Balloon`, `TMShow` - Store episode metadata (title, date, URL, show notes)
- `TMA` table includes `mp3url` field for direct MP3 playback (main playback method)
- Social engagement columns: `comments_count`, `favorites_count`, `likes_count`, `streams_count`
- Legacy fields: `transcribed_date`, `transcript` (AI transcription - not currently used)
- `processed_date` tracks when episodes have been tagged

**Spotify Tables:**
- `TMASpot`, `BalloonSpot`, `TMShowSpot` - Store Spotify URLs for fallback playback

**Tag Tables:**
- `{Podcast}_Note_Tags` and `{Podcast}_Title_Tags` - Word frequency counts for search filtering

**User Authentication Tables:**
- `users` - User accounts (username, email, password_hash, is_admin, is_active)
- `user_favorites` - User-to-episode favorites (user_id, podcast_name, episode_id)
- `comments` - Episode comments with optional timestamp references
- `comment_likes` - Comment like tracking
- `episode_likes` - Episode like tracking
- `password_reset_tokens` - Password reset functionality

Database triggers automatically update `*_count` columns when social engagement tables change.

## Core Scripts

### Data Collection Pipeline

Execute via `scrape_all.py` which runs scripts in sequence:

1. **Web Scraping** (`daily_scrape.py`, `BalloonScrape.py`, `TMShowScrape.py`)
   - Scrapes tmastl.com podcast pages using BeautifulSoup
   - Inserts new episodes into respective database tables
   - Converts dates from "Month Day, Year" to YYYY-MM-DD format
   - Uses 3-second delays between page requests

2. **Spotify Integration** (`TMASpotScrape.py`, `BalloonSpotScrape.py`, `TMShowSpotScrape.py`)
   - Fetches Spotify episode URLs via Spotify API
   - Requires `spot.env` with `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
   - Matches episodes to enable playback in web interface

3. **Tagging** (`tagger.py`)
   - Extracts keywords from episode titles and show notes
   - Populates tag tables with word frequency counts
   - Filters out common stop words
   - Enables tag-based search in Flask app

### Transcription Pipeline

**Script:** `tmatranscriber.py`

- Queries `TMA` table for episodes where `transcribed_date IS NULL`
- Downloads MP3 files from episode pages
- Uses faster-whisper with Whisper large-v3 model for transcription
- GPU acceleration via CUDA (if available), falls back to CPU
- Sentence splitting via spaCy (`en_core_web_sm` model)
- Outputs:
  - `generated_transcript_combined_texts/{episode}.txt` - Full transcript
  - `generated_transcript_metadata_tables/{episode}.csv/.json` - Segment metadata
  - Updates database with transcript text and `transcribed_date`
- Runs continuously, checking for new episodes hourly

**Settings to modify in tmatranscriber.py:**
- `use_spacy_for_sentence_splitting = 1`
- `disable_cuda_override = 1` (set to 0 to enable GPU)
- `max_simultaneous_youtube_downloads = 4`

### Web Application

**Script:** `app.py`

Flask application with user authentication, social features, and advanced playback.

**Key Pages:**
- `/` - Main search interface (index.html)
- `/favorites` - User's favorited episodes (favorites.html)
- `/tma_archive` - Browse all TMA episodes (tma_archive.html)
- `/episode/<id>` - Individual episode view with related episodes (episode.html)
- `/popular` - Popular episodes sorted by engagement (popular.html)
- `/auth/login`, `/auth/signup`, `/auth/profile` - User authentication pages

**Search & Browse API:**
- `/search` - Episode search with title/date/notes filters and match types
- `/search_archive` - Archive search with pagination
- `/fetch_archive_episodes` - Paginated archive data
- `/search_spotify` - Fuzzy match episode to Spotify URL (fallback playback)
- `/recent_episodes` - Last 90 days of episodes
- `/get_podcast_data` - All episodes for a podcast
- `/random_episode` - Get a random TMA episode
- `/related_episodes/<id>` - Episodes from ±1 week of target episode
- `/api/popular_episodes` - Episodes sorted by engagement metrics
- `/notes.json` - Episode notes export

**User & Social API (require authentication):**
- `/api/favorites` GET/POST - Get or add favorites
- `/api/favorites/<id>` DELETE - Remove favorite
- `/api/favorites/check/<id>` GET - Check if episode is favorited
- `/api/comments/<episode_id>` GET - Get comments (public)
- `/api/comments` POST - Add comment (rate-limited: 10/min)
- `/api/comments/<id>` PUT/DELETE - Edit/delete own comments
- `/api/likes/<episode_id>` POST/DELETE - Toggle episode like (rate-limited: 30/min)
- `/api/likes/<episode_id>/status` GET - Check like status
- `/api/stream/<episode_id>` POST - Track playback (rate-limited: 60/min)
- `/api/auth/status` GET - Check authentication status

**Frontend Architecture:**
- `static/js/play_queue.js` - Persistent play queue using localStorage
- `static/js/player_ui.js` - Audio player UI controls (exports `PlayerUI` global)
- `static/css/player.css` - Player styling
- `static/css/auth.css` - Authentication pages styling
- `static/css/main.css` - Global styles

**PlayerUI Module Pattern:**
Templates must include these files and call `PlayerUI.init()` on page load:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/player.css') }}?v=2">
<script defer src="{{ url_for('static', filename='js/play_queue.js') }}?v=2"></script>
<script defer src="{{ url_for('static', filename='js/player_ui.js') }}?v=2"></script>
```
Key methods: `PlayerUI.startPlayback(episode)`, `toggleAudioPlayPause()`, `seekAudio(seconds)`, `reopenPlayer()`

**Template Consistency:**
All main templates share:
- Same player CSS/JS includes with `?v=2` cache busting
- Navigation with `.nav-btn` and `.nav-text` span classes
- Mobile icons-only navigation at `max-width: 479px` (hides `.nav-text`)
- Dark mode toggle support

**Client-side State Management:**
- Play queue persisted to localStorage (`tma_play_queue`)
- Current track state (`tma_current_track`)
- Favorites stored in localStorage
- Episode progress tracking

**Authentication Architecture:**
- Flask-Login manages user sessions (`auth.py`)
- bcrypt for password hashing
- WTForms for form validation (`forms.py`)
- Flask-Limiter for rate limiting (auth: 5/min, comments: 10/min, likes: 30/min)
- Auth blueprint registered at `/auth` prefix

**Environment:**
- Reads `.env` for SECRET_KEY (required for sessions)
- Reads `spot.env` for Spotify credentials
- `DATABASE_URL` env var overrides default `TMASTL.db` path
- Runs on `0.0.0.0:5000` (accessible from network)

## Common Commands

**Run Flask web app:**
```bash
source venv/bin/activate
python app.py
# Runs on http://0.0.0.0:5000 (accessible from network at http://192.168.1.153:5000)
# Debug mode enabled with auto-reload
```

**Execute full data collection pipeline:**
```bash
python scrape_all.py
# Runs: daily_scrape → BalloonScrape → TMShowScrape → TMASpotScrape → BalloonSpotScrape → TMShowSpotScrape → tagger
```

**Run individual scrapers:**
```bash
python daily_scrape.py        # TMA episodes (scrapes 1 page)
python BalloonScrape.py       # Balloon Party episodes
python TMShowScrape.py        # Tim McKernan Show episodes
```

**Run transcription pipeline:**
```bash
python tmatranscriber.py
# Continuously processes untranscribed TMA episodes
# Requires faster-whisper, spaCy, and large-v3 Whisper model
```

**Update Spotify URLs:**
```bash
python TMASpotScrape.py       # TMA Spotify links
python BalloonSpotScrape.py   # Balloon Spotify links
python TMShowSpotScrape.py    # TMShow Spotify links
```

**Generate tags:**
```bash
python tagger.py
# Processes episodes where processed_date IS NULL
```

**Run user auth database migration:**
```bash
python migrate_user_auth.py
# Creates users, user_favorites, comments, episode_likes tables
# Also creates triggers for automatic count updates
python migrate_user_auth.py --dry-run  # Preview SQL without executing
```

## Environment Setup

**Required environment files:**

`.env` - Flask configuration:
```
SECRET_KEY=your_secure_random_key_here
```

`spot.env` - Spotify API credentials:
```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
DATABASE_URL=TMASTL.db  # Optional override
```

Generate a SECRET_KEY with: `python -c "import secrets; print(secrets.token_hex(32))"`

**Python dependencies:** See `requirements.txt`
- Flask, requests, BeautifulSoup (web scraping/serving)
- Flask-Login, Flask-WTF, Flask-Limiter, bcrypt (authentication)
- faster-whisper, spacy, pytube (transcription)
- fuzzywuzzy (Spotify episode matching)
- python-dotenv (config)

**spaCy model:**
```bash
python -m spacy download en_core_web_sm
```

## Architecture Notes

**Podcast table name mapping:**
```python
{
    'TMA': 'TMA',
    'Balloon Party': 'Balloon',
    'The Tim McKernan Show': 'TMShow'
}
```

**Authentication flow:**
- `auth.py` defines the `auth_bp` Blueprint with `/login`, `/signup`, `/logout`, `/profile`, `/change-password`
- `forms.py` contains WTForms classes with validation (LoginForm, SignupForm, ChangePasswordForm)
- Flask-Login's `@login_required` decorator protects routes; `current_user` provides user context
- Passwords hashed with bcrypt; rate limits prevent brute force attacks

**Search match types:**
- `exact` - Phrase match in title/notes
- `all` - AND logic (all terms must match)
- `any` - OR logic (any term matches)

**Apostrophe normalization:** Search queries standardize curly quotes (') to straight quotes (') for matching.

**Date filtering:** Partial date matching supported (e.g., "2024" matches all 2024 episodes).

**Transcription workflow (legacy, not currently in active use):**
1. Query for `transcribed_date IS NULL` ordered by `Date DESC`
2. Extract MP3 URL from episode page's JavaScript config
3. Download to `downloaded_audio/`
4. Transcribe with Whisper (GPU/CPU)
5. Save outputs to `generated_transcript_*` directories
6. Update database with transcript and timestamp
7. Delete audio file

**Play Queue Architecture:**
- Episodes added to queue stored in localStorage as JSON
- Queue state synchronized across tabs via storage events
- Supports reordering, removal, and play-next functionality
- Current playback position persisted

**Related Episodes Algorithm:**
- Queries episodes within ±1 week of target episode date
- Returns 4 random episodes from nearby time period
- Excludes current episode from results

**Social Engagement Counts:**
- Database triggers in `migrate_user_auth.py` auto-update `*_count` columns
- `favorites_count`, `comments_count`, `likes_count` on episode tables
- When a user favorites/comments/likes, trigger increments the count
- When removed, trigger decrements the count

**Script paths:** Some scripts have hardcoded shebangs (`#!/home/axe08admin/.virtualenvs/tmaenv/bin/python`) - adjust for local environment if needed.

## UI Features

**Search Functionality:**
- Multi-field search (title, date, show notes)
- Three match types: exact phrase, all words (AND), any word (OR)
- Search term highlighting in results
- Podcast selector (TMA, Balloon Party, Tim McKernan Show)

**Playback Features:**
- Direct MP3 streaming from episode pages
- Persistent play queue across sessions
- Episode progress tracking
- Random episode discovery
- Related episodes based on air date proximity

**Episode Management:**
- Favorites system (server-side for logged-in users, localStorage fallback)
- Play queue with drag-and-drop reordering
- Episode cards with quick actions (play, queue, favorite)
- Archive view with pagination
- Popular episodes page sorted by likes/favorites/comments

**Social Features:**
- User authentication (signup, login, profile, password change)
- Episode likes and favorites (per-user)
- Episode comments with timestamp references
- Engagement indicators (like/favorite/comment counts on episode cards)

**Responsive Design:**
- Mobile-first CSS approach
- Dark mode support
- Fixed audio player bar
- Touch-friendly controls (44px minimum touch targets)

## Git Workflow

- **Main branch:** `master`
- **Development branch:** `UI-Beta` (active UI improvements)
- Feature branches use `feature/` prefix (e.g., `feature/user-auth`)
