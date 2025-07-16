# Climbing App

A modern, animated web app for browsing climbing albums, managing crew, and sharing memes. Features beautiful transitions, real-time updates, and a modular FastAPI backend with Redis.

---

## Highlights

- **Visual Flowchart:** [Excalidraw diagram](https://link.excalidraw.com/readonly/AtAowLIPvMThzN3XHsEf) on the main page
- **Albums:** Browse, filter, and auto-refresh climbing albums with animated particle effects
- **Crew:** Track crew member progress, skills, achievements, and levels
- **Memes:** Upload and browse memes in a dedicated gallery
- **Admin Panel:** Manage users, stats, and trigger metadata refresh (admin only)
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
├── routes/                # Modular API endpoints (albums, crew, memes, admin, etc.)
├── middleware/            # Custom middleware (case-insensitive, cache-busting, pretty JSON)
├── models/                # Pydantic models for API
├── utils/                 # Logging, metadata parsing, background tasks, export
├── scripts/               # CLI scripts (migrate, admin, export, etc.)
├── redis_store.py         # Redis data layer (crew, albums, memes)
├── static/                # HTML, CSS, JS, images
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

- **Admin:**
  - View system stats, manage users, refresh album metadata
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
  - `/api/admin` — Admin stats, metadata refresh
  - `/api/auth` — Auth endpoints (login, user info, JWT)
  - `/api/utilities` — Health check, image endpoints
  - See `JWT_API_AUTH.md` for JWT usage and hybrid auth

- **Scripts:**
  - `scripts/redis_data_migration.py` — Migrate old JSON arrays to Redis sets
  - `scripts/make_admin.py` — Promote user to admin
  - `scripts/list_users.py` — List all users
  - `scripts/export_utils.py` — Export Redis DB

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
