# User Authentication & Social Features - Implementation Plan

**Status:** Planning Phase
**Branch:** `feature/user-auth`
**Estimated Effort:** 3-5 weeks (single developer)
**Complexity:** Medium to High

## Overview

This document outlines the architectural plan for adding user authentication and social engagement features to TMASearcher. The goal is to transform the app from a localStorage-based single-user system to a multi-user platform with server-side state management.

## Features to Implement

1. **User Authentication System**
   - Email/password registration and login
   - Session management with "Remember Me"
   - Password reset functionality

2. **User-Based Favorites**
   - Migrate from localStorage to database-backed favorites
   - Sync favorites across devices
   - Migration tool for existing localStorage data

3. **Comments System**
   - Episode-level comments
   - Comment editing/deletion (own comments only)
   - Sorting: newest, oldest, most liked

4. **Like System**
   - Like comments
   - Track like counts

5. **Trending/Discovery Page**
   - Sort episodes by most favorites
   - Sort episodes by most comments
   - Sort episodes by recency

## Database Architecture

### New Tables Required

#### 1. Users Table
```sql
CREATE TABLE users (
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

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
```

#### 2. User Favorites Table
```sql
CREATE TABLE user_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    podcast_name TEXT NOT NULL,  -- 'TMA', 'Balloon', 'TMShow'
    episode_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, podcast_name, episode_id)
);

CREATE INDEX idx_user_favorites_user ON user_favorites(user_id);
CREATE INDEX idx_user_favorites_episode ON user_favorites(podcast_name, episode_id);
```

#### 3. Comments Table
```sql
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    podcast_name TEXT NOT NULL,
    episode_id INTEGER NOT NULL,
    comment_text TEXT NOT NULL,
    timestamp_ref INTEGER,  -- Optional: timestamp in seconds for timestamp-linked comments
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    is_edited BOOLEAN DEFAULT 0,
    likes_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_comments_episode ON comments(podcast_name, episode_id, created_at DESC);
CREATE INDEX idx_comments_user ON comments(user_id);
```

#### 4. Comment Likes Table
```sql
CREATE TABLE comment_likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    comment_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (comment_id) REFERENCES comments(id) ON DELETE CASCADE,
    UNIQUE(user_id, comment_id)
);

CREATE INDEX idx_comment_likes_comment ON comment_likes(comment_id);
CREATE INDEX idx_comment_likes_user ON comment_likes(user_id);
```

#### 5. Password Reset Tokens Table
```sql
CREATE TABLE password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_reset_tokens_token ON password_reset_tokens(token);
```

### Modify Existing Episode Tables

Add engagement count columns to `TMA`, `Balloon`, and `TMShow` tables:

```sql
-- Add columns
ALTER TABLE TMA ADD COLUMN favorites_count INTEGER DEFAULT 0;
ALTER TABLE TMA ADD COLUMN comments_count INTEGER DEFAULT 0;

ALTER TABLE Balloon ADD COLUMN favorites_count INTEGER DEFAULT 0;
ALTER TABLE Balloon ADD COLUMN comments_count INTEGER DEFAULT 0;

ALTER TABLE TMShow ADD COLUMN favorites_count INTEGER DEFAULT 0;
ALTER TABLE TMShow ADD COLUMN comments_count INTEGER DEFAULT 0;

-- Add indexes for sorting by engagement
CREATE INDEX idx_tma_favorites ON TMA(favorites_count DESC);
CREATE INDEX idx_tma_comments ON TMA(comments_count DESC);
CREATE INDEX idx_balloon_favorites ON Balloon(favorites_count DESC);
CREATE INDEX idx_balloon_comments ON Balloon(comments_count DESC);
CREATE INDEX idx_tmshow_favorites ON TMShow(favorites_count DESC);
CREATE INDEX idx_tmshow_comments ON TMShow(comments_count DESC);
```

### Database Triggers for Auto-Updating Counts

```sql
-- Favorites count triggers
CREATE TRIGGER increment_favorites_count AFTER INSERT ON user_favorites
BEGIN
    UPDATE TMA SET favorites_count = favorites_count + 1
    WHERE ID = NEW.episode_id AND NEW.podcast_name = 'TMA';

    UPDATE Balloon SET favorites_count = favorites_count + 1
    WHERE ID = NEW.episode_id AND NEW.podcast_name = 'Balloon';

    UPDATE TMShow SET favorites_count = favorites_count + 1
    WHERE ID = NEW.episode_id AND NEW.podcast_name = 'TMShow';
END;

CREATE TRIGGER decrement_favorites_count AFTER DELETE ON user_favorites
BEGIN
    UPDATE TMA SET favorites_count = favorites_count - 1
    WHERE ID = OLD.episode_id AND OLD.podcast_name = 'TMA';

    UPDATE Balloon SET favorites_count = favorites_count - 1
    WHERE ID = OLD.episode_id AND OLD.podcast_name = 'Balloon';

    UPDATE TMShow SET favorites_count = favorites_count - 1
    WHERE ID = OLD.episode_id AND OLD.podcast_name = 'TMShow';
END;

-- Comments count triggers
CREATE TRIGGER increment_comments_count AFTER INSERT ON comments
BEGIN
    UPDATE TMA SET comments_count = comments_count + 1
    WHERE ID = NEW.episode_id AND NEW.podcast_name = 'TMA';

    UPDATE Balloon SET comments_count = comments_count + 1
    WHERE ID = NEW.episode_id AND NEW.podcast_name = 'Balloon';

    UPDATE TMShow SET comments_count = comments_count + 1
    WHERE ID = NEW.episode_id AND NEW.podcast_name = 'TMShow';
END;

CREATE TRIGGER decrement_comments_count AFTER DELETE ON comments
BEGIN
    UPDATE TMA SET comments_count = comments_count - 1
    WHERE ID = OLD.episode_id AND OLD.podcast_name = 'TMA';

    UPDATE Balloon SET comments_count = comments_count - 1
    WHERE ID = OLD.episode_id AND OLD.podcast_name = 'Balloon';

    UPDATE TMShow SET comments_count = comments_count - 1
    WHERE ID = OLD.episode_id AND OLD.podcast_name = 'TMShow';
END;

-- Comment likes count triggers
CREATE TRIGGER increment_comment_likes AFTER INSERT ON comment_likes
BEGIN
    UPDATE comments SET likes_count = likes_count + 1 WHERE id = NEW.comment_id;
END;

CREATE TRIGGER decrement_comment_likes AFTER DELETE ON comment_likes
BEGIN
    UPDATE comments SET likes_count = likes_count - 1 WHERE id = OLD.comment_id;
END;
```

## Backend Implementation

### Required Python Packages

Add to `requirements.txt`:
```
Flask-Login==0.6.3
Flask-Bcrypt==1.0.1
Flask-WTF==1.2.1
Flask-Limiter==3.5.0
email-validator==2.1.0
itsdangerous==2.1.2
```

### Flask Application Setup

```python
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
import secrets

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Initialize extensions
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
bcrypt = Bcrypt(app)
limiter = Limiter(app, key_func=lambda: current_user.id if current_user.is_authenticated else request.remote_addr)

# User model
class User(UserMixin):
    def __init__(self, id, username, email, is_admin=False):
        self.id = id
        self.username = username
        self.email = email
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, is_admin FROM users WHERE id = ? AND is_active = 1", (user_id,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data:
        return User(id=user_data[0], username=user_data[1], email=user_data[2], is_admin=user_data[3])
    return None
```

### New API Endpoints Required

**Authentication (5 endpoints):**
- `POST /register` - User registration
- `POST /login` - User login
- `GET /logout` - User logout
- `GET /api/current_user` - Get current user info
- `POST /api/reset_password` - Password reset (future)

**Favorites (4 endpoints):**
- `GET /api/favorites` - Get user's favorites
- `POST /api/favorites` - Add to favorites
- `DELETE /api/favorites/<podcast>/<id>` - Remove from favorites
- `POST /api/favorites/check` - Check if episode is favorited

**Comments (6 endpoints):**
- `GET /api/comments/<podcast>/<id>` - Get all comments for episode
- `POST /api/comments` - Add comment (rate limited: 10/min)
- `PUT /api/comments/<id>` - Edit own comment
- `DELETE /api/comments/<id>` - Delete own comment
- `POST /api/comments/<id>/like` - Like a comment
- `DELETE /api/comments/<id>/unlike` - Unlike a comment

**Trending/Discovery (2 endpoints):**
- `GET /trending` - Trending page view
- `GET /api/trending` - Get trending episodes (with sort params)

### Security Measures

1. **Password Security:**
   - Bcrypt hashing (minimum 8 characters, recommend 12+)
   - Never store plaintext passwords

2. **CSRF Protection:**
   - Flask-WTF provides CSRF tokens for forms
   - Include CSRF token in AJAX headers

3. **Rate Limiting:**
   - Comment posting: 10/minute per user
   - Favorites: 100/hour per user
   - Login attempts: 5/minute per IP

4. **SQL Injection Prevention:**
   - Always use parameterized queries
   - Never concatenate user input into SQL

5. **XSS Prevention:**
   - Escape user-generated content (comments)
   - Use DOMPurify or similar on frontend
   - Store comments as plain text, escape on display

6. **Session Security:**
   ```python
   app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only in production
   app.config['SESSION_COOKIE_HTTPONLY'] = True
   app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
   ```

## Frontend Implementation

### New Templates Needed

1. `/templates/login.html` - Login form
2. `/templates/register.html` - Registration form
3. `/templates/trending.html` - Trending episodes page

### JavaScript Components to Build

1. **Auth Manager** (`static/js/auth.js`)
   - Handle login/register forms
   - Check authentication status on page load
   - Migrate localStorage favorites on first login

2. **Comments UI** (`static/js/comments.js`)
   - Load and render comments
   - Submit new comments
   - Edit/delete own comments
   - Like/unlike comments
   - Sort comments (newest, oldest, most liked)

3. **Favorites Manager** (modify existing)
   - Change from localStorage to API-based
   - Keep localStorage as fallback for anonymous users
   - Sync on login

### localStorage Migration Flow

```javascript
async function migrateFavoritesToServer() {
    const localFavorites = JSON.parse(localStorage.getItem('tma_favorites') || '[]');

    if (localFavorites.length === 0) return;

    const confirmed = confirm(`Migrate ${localFavorites.length} favorites to your account?`);
    if (!confirmed) return;

    for (const fav of localFavorites) {
        await fetch('/api/favorites', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                podcast_name: fav.podcast_name,
                episode_id: fav.episode_id
            })
        });
    }

    localStorage.removeItem('tma_favorites');
    alert('Favorites migrated successfully!');
}
```

### UI Updates Required

1. **Navigation Bar:**
   - Add "Login" / "Register" links (when not authenticated)
   - Add "My Account" dropdown with username and "Logout" (when authenticated)

2. **Episode Cards:**
   - Show engagement metrics (favorites count, comments count)
   - Update favorite button to use API
   - Add "Comments" button

3. **Episode Detail Page:**
   - Add comments section below episode details
   - Show comment form (authenticated users only)
   - Display existing comments with like buttons

4. **Trending Page:**
   - Episode cards sorted by engagement
   - Filter tabs: "Most Favorites", "Most Comments", "Recent"
   - Pagination support

## Implementation Phases

### Phase 1: Database Setup (Week 1)
- [ ] Create database migration script
- [ ] Add new tables (users, user_favorites, comments, comment_likes, password_reset_tokens)
- [ ] Add columns to episode tables (favorites_count, comments_count)
- [ ] Create database triggers
- [ ] Test on development database copy

### Phase 2: Authentication (Week 2)
- [ ] Install Flask-Login, Flask-Bcrypt
- [ ] Create User model
- [ ] Implement registration endpoint
- [ ] Implement login endpoint
- [ ] Implement logout endpoint
- [ ] Create login/register HTML templates
- [ ] Build auth.js frontend logic
- [ ] Test authentication flows

### Phase 3: User-Based Favorites (Week 2)
- [ ] Implement favorites API endpoints
- [ ] Update frontend to use API instead of localStorage
- [ ] Build localStorage migration tool
- [ ] Update favorites page to load from server
- [ ] Test cross-device sync

### Phase 4: Comments System (Week 3)
- [ ] Implement comments API endpoints
- [ ] Add rate limiting
- [ ] Build comments UI component
- [ ] Add comment sorting
- [ ] Implement like/unlike functionality
- [ ] Test comment CRUD operations

### Phase 5: Trending Page (Week 3-4)
- [ ] Create trending.html template
- [ ] Implement /api/trending endpoint
- [ ] Build frontend for sorting/filtering
- [ ] Add pagination
- [ ] Test with large datasets

### Phase 6: Security & Polish (Week 4-5)
- [ ] Security audit (CSRF, XSS, SQL injection)
- [ ] Add comprehensive rate limiting
- [ ] Mobile responsiveness testing
- [ ] Accessibility review (keyboard nav, ARIA labels)
- [ ] Load testing
- [ ] Bug fixes and polish

## Key Challenges & Solutions

### Challenge 1: Performance with Aggregated Queries
**Problem:** Counting favorites/comments for trending page could be slow.
**Solution:** Denormalized count columns + database triggers + proper indexing.

### Challenge 2: localStorage to Server Migration
**Problem:** Users have local favorites that need to be preserved.
**Solution:** On first login, detect localStorage data and offer one-time migration.

### Challenge 3: Anonymous vs Authenticated Flows
**Problem:** Should anonymous users be able to browse? Comment?
**Solution:**
- Allow browsing without login
- Store favorites in localStorage for anonymous users
- Require login for comments and likes
- Prompt to login when trying to favorite (with migration offer)

### Challenge 4: Security
**Problem:** User-generated content opens up attack vectors.
**Solution:**
- Parameterized queries for SQL injection
- Escape HTML in comments for XSS prevention
- Rate limiting for abuse prevention
- CSRF tokens on all forms
- Bcrypt for password hashing

## Testing Strategy

### Unit Tests
- Password hashing/verification
- Authentication flows (register, login, logout)
- Database triggers update counts correctly
- Favorites CRUD operations
- Comments CRUD operations

### Integration Tests
- Full user journey: register → login → favorite → comment → like
- localStorage migration flow
- Unauthorized access attempts (editing others' comments)
- CSRF token validation

### Performance Tests
- Query performance with 10,000+ comments
- Trending page load time
- Concurrent user stress testing
- Index effectiveness verification

### Security Tests
- SQL injection attempts
- XSS in comment fields
- CSRF bypass attempts
- Rate limiting effectiveness
- Session hijacking prevention

## Files to Create/Modify

### New Files:
- `/migrations/001_add_social_features.sql` - Database migration
- `/templates/login.html` - Login page
- `/templates/register.html` - Registration page
- `/templates/trending.html` - Trending page
- `/static/js/auth.js` - Authentication logic
- `/static/js/comments.js` - Comments UI
- `/static/css/auth.css` - Auth forms styling
- `/static/css/comments.css` - Comments styling

### Modified Files:
- `/home/alex/TMASearcher/app.py` - Add all new endpoints
- `/home/alex/TMASearcher/requirements.txt` - Add new packages
- `/home/alex/TMASearcher/templates/base.html` - Add auth navigation
- `/home/alex/TMASearcher/templates/index.html` - Show engagement metrics
- `/home/alex/TMASearcher/templates/episode.html` - Add comments section
- `/home/alex/TMASearcher/templates/favorites.html` - Load from API
- `/home/alex/TMASearcher/static/js/favorites.js` - API-based favorites

## Accessibility Considerations

- All interactive elements keyboard-navigable (Tab, Enter, Escape)
- ARIA labels on favorite/like buttons
- Focus management after form submissions
- Screen reader announcements for dynamic content updates
- Minimum 44x44px touch targets on mobile
- Color contrast ratios meet WCAG AA standards

## Mobile Considerations

- Responsive layouts for all new components
- Touch-friendly button sizes
- Optimistic UI updates (immediate feedback)
- Loading states for API calls
- Offline mode handling (show login prompt for interactions)
- Test in iOS Safari and in-app browsers

## Environment Variables

Add to `spot.env` or separate `.env` file:
```
SECRET_KEY=<generate-random-32-byte-hex>  # Required for sessions
DATABASE_URL=TMASTL.db  # Already exists
SPOTIFY_CLIENT_ID=<existing>
SPOTIFY_CLIENT_SECRET=<existing>
```

Generate SECRET_KEY:
```python
import secrets
print(secrets.token_hex(32))
```

## Next Steps

When ready to start implementation:

1. **Review this plan** - Make sure it aligns with your vision
2. **Set up development environment** - Install new packages
3. **Create database backup** - Before running migrations
4. **Start with Phase 1** - Database setup and authentication
5. **Iterate** - Build, test, refine each component

## Questions to Resolve Before Starting

- [ ] Do you want social login (Google, Facebook) or just email/password?
- [ ] Should comments support threading/replies, or flat structure only?
- [ ] Do you want email verification for new accounts?
- [ ] Should there be admin moderation tools for comments?
- [ ] Do you want real-time updates (WebSockets) or manual refresh?
- [ ] What's the abuse prevention strategy (spam detection, reporting)?

## Resources & References

- [Flask-Login Documentation](https://flask-login.readthedocs.io/)
- [Flask-Bcrypt Documentation](https://flask-bcrypt.readthedocs.io/)
- [OWASP Top 10 Security Risks](https://owasp.org/www-project-top-ten/)
- [Web Content Accessibility Guidelines (WCAG)](https://www.w3.org/WAI/WCAG21/quickref/)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-24
**Author:** Generated by audio-webapp-architect agent
