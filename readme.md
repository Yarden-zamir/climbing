# Climbing App

A modern, animated web app for browsing climbing albums, managing crew, and sharing memes. Features beautiful transitions, real-time push notifications, PWA installation, and a modular FastAPI backend with Redis.

---

## Highlights

- **Visual Flowchart:** [Excalidraw diagram](https://link.excalidraw.com/readonly/AtAowLIPvMThzN3XHsEf) on the main page
- **Albums:** Browse, filter, and auto-refresh climbing albums with animated particle effects
- **Crew:** Track crew member progress, skills, achievements, and levels
- **Memes:** Upload and browse memes in a dedicated gallery
- **Push Notifications:** Real-time notifications for new albums, crew additions, and memes with device management
- **PWA Ready:** Installable app with offline support, service worker caching, and app shortcuts
- **Admin Panel:** Manage users, stats, notification broadcasts, and trigger metadata refresh (admin only)
- **Hybrid Auth:** Supports both Google OAuth (session) and JWT Bearer tokens for API/mobile
- **Animated UI:** Skeleton loading, blur/fade-in, typewriter text, and particle animations for real-time feedback
- **Responsive Design:** Modern, RTL-ready, accessible, and mobile-friendly
- **Production-ready:** Modular FastAPI backend, Redis data layer, and robust permission system

---

## Quickstart

1. **Clone & Install**
    ```bash
    git clone github.com/yarden-zamir/climbing
    cd climbing
    uv sync
    ```
2. **Set Secret Key**
    ```bash
    echo "SECRET_KEY=$(openssl rand -hex 32)" > .env
    ```
3. **Run the Server**
    ```bash
    uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload
    ```
4. **Browse**
    - Open [http://localhost:8001](http://localhost:8001)

---

## Project Structure

```
climbing/
├── main.py                # FastAPI app entrypoint
├── routes/                # Modular API endpoints (albums, crew, memes, notifications, admin, etc.)
├── middleware/            # Custom middleware (case-insensitive, cache-busting, pretty JSON)
├── models/                # Pydantic models for API
├── utils/                 # Logging, metadata parsing, background tasks, export
├── scripts/               # CLI scripts (migrate, admin, export, VAPID key generation)
├── redis_store.py         # Redis data layer (crew, albums, memes, push subscriptions)
├── sw.js                  # Service worker for PWA and push notifications
├── static/                # HTML, CSS, JS, images, PWA manifest
│   ├── manifest.json      # PWA manifest for installable app
│   ├── js/
│   │   ├── notifications.js    # Push notification management
│   │   ├── pwa-manager.js      # PWA installation prompts
│   │   └── notification-health-manager.js  # Notification debugging
│   └── ...
├── redis-schema.yml       # Redis schema docs
├── pyproject.toml         # Python dependencies
```

---

## Key Features

- **Albums:**
  - Add albums via Google Photos URL
  - Crew selection and instant DB update
  - Animated auto-refresh with change detection (particles for add/delete/update)
  - Album metadata scraping and image proxying

- **Crew:**
  - Add/edit/delete crew members with skills, achievements, and images
  - Real-time updates and particle animations for changes
  - Team stats exclude "Is Etherial" members
  - "NEW" badge for recent crew, with tooltip for first climb date

- **Memes:**
  - Upload, browse, and delete memes in a responsive gallery
  - Masonry layout, image preview, and context menu for deletion

- **Push Notifications:**
  - Real-time notifications for new albums, crew additions, and memes
  - Device-based subscriptions with customizable preferences
  - Admin broadcast notifications and reliability monitoring
  - Automatic cleanup of expired/invalid subscriptions

- **PWA Features:**
  - Installable as native app on mobile and desktop
  - Offline-first architecture with service worker caching
  - App shortcuts for quick access to albums, crew, and adding content
  - Background sync and push notification support

- **Admin:**
  - View system stats, manage users, refresh album metadata
  - Notification management: broadcast messages, device statistics, reliability metrics
  - Permission system with roles (user, admin, pending)

- **Authentication:**
  - Google OAuth for web
  - JWT Bearer tokens for API/mobile (see `JWT_API_AUTH.md`)
  - Hybrid endpoints support both session and JWT

- **Backend:**
  - Modular FastAPI app (routes, middleware, models, utils)
  - Redis for all data (crew, albums, memes, sessions)
  - Proper Redis data types (sets, hashes, etc.)
  - Scripts for migration, admin, and export

---

## API & Scripts

- **API:**
  - `/api/crew` — Crew management (CRUD, skills, achievements)
  - `/api/albums` — Album management (submit, edit crew, enriched listing)
  - `/api/memes` — Meme gallery (list, upload, delete)
  - `/api/notifications` — Push notification subscriptions, device management, preferences
  - `/api/admin` — Admin stats, metadata refresh, notification broadcasts
  - `/api/auth` — Auth endpoints (login, user info, JWT)
  - `/api/utilities` — Health check, image endpoints
  - See `JWT_API_AUTH.md` for JWT usage and hybrid auth

- **Scripts:**
  - `scripts/redis_data_migration.py` — Migrate old JSON arrays to Redis sets
  - `scripts/make_admin.py` — Promote user to admin
  - `scripts/list_users.py` — List all users
  - `scripts/export_utils.py` — Export Redis DB
  - `scripts/generate_vapid_keys.py` — Generate VAPID keys for push notifications

---

## Push Notifications Setup

To enable push notifications, you'll need to generate VAPID keys:

```bash
# Generate VAPID keys for push notifications
uv run python scripts/generate_vapid_keys.py

# Keys will be saved to private_key.pem and public_key.pem
# The app will automatically detect and use them
```

Push notifications work automatically once VAPID keys are configured. Users can:
- Subscribe to notifications from the browser
- Manage device subscriptions and preferences
- Receive real-time updates for new albums, crew members, and memes

Admins can:
- View notification statistics and device breakdowns
- Send broadcast notifications to all users
- Monitor notification delivery reliability

---

## Customization

- **Styles:** Edit `static/css/styles.css`
- **Text Effects:** Edit `static/js/albums.js` (typewriter, particles)
- **Add Data:** Use web UI or scripts for crew/albums/memes

---

## Accessibility & Performance

- Respects `prefers-reduced-motion` for accessibility
- Fast, responsive, and works on all modern browsers
- Efficient Redis operations and batch updates

---

## License

MIT

---

## Credits

- [FastAPI](https://fastapi.tiangolo.com/)
- [Uvicorn](https://www.uvicorn.org/)
- [Redis](https://redis.io/)
- [Excalidraw](https://excalidraw.com/)
- [Google Photos](https://photos.google.com/)
- [Poppins font](https://fonts.google.com/specimen/Poppins)
