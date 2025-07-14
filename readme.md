readme is 100% ai generated gpt-4.1

# Climbing UI

A modern, animated web app for browsing Google Photos climbing albums, featuring beautiful transitions, skeleton loading, image blur/fade-in, and typewriter text effects.  
**The main page includes an [Excalidraw flowchart](https://link.excalidraw.com/readonly/AtAowLIPvMThzN3XHsEf) that explains everything about climbing.**

---

## Features

- **Excalidraw flowchart** on the main page, visually explaining climbing concepts
- **Albums**: Browse climbing albums with filtering by crew members
- **Crew**: View crew member progress, skills, and level statistics  
- **Memes**: Browse climbing photos and memes
- **Add Albums**: Submit new Google Photos albums with instant database updates
- **Animated skeleton loading** for both images and text
- **Blur + fade-in** for images (works with cached/lazy images)
- **Typewriter effect** for album titles/descriptions
- **Responsive, modern design** with Poppins font and gradient heading
- **RTL support** for Hebrew and other right-to-left languages
- **Animated page transitions** (content fades, navbar stays)
- **Google Photos album preview** with OpenGraph scraping and image proxying
- **Production-ready FastAPI backend** (serves both API and static UI)

---

## Quickstart (Development)

1. **Clone the repo**
    ```bash
    git clone github.com/yarden-zamir/climbing
    cd climbing
    ```

2. **Install dependencies**
    ```bash
    uv sync
    ```

3. **Set the SECRET_KEY environment variable**

   > The backend requires a secret key for session management and security. Generate and set it with:

   ```bash
   echo "SECRET_KEY=$(openssl rand -hex 32)" > .env
   ```

4. **Run the server**
    ```bash
    uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload
    ```

5. **Browse**
    - Open [http://localhost:8001](http://localhost:8001)

---

## Project Structure

```
.
├── main.py                # FastAPI backend (serves API + static UI)
├── pyproject.toml         # Python dependencies
├── redis_store.py         # Redis data layer [[memory:2866449]]
├── redis-schema.yml       # Redis schema documentation
├── static/
│   ├── index.html         # Main page with Excalidraw flowchart
│   ├── albums.html        # Albums page with filtering and crew faces
│   ├── crew.html          # Crew directory page
│   ├── memes.html         # Memes page
│   ├── css/
│   │   └── styles.css
│   ├── js/
│   │   └── albums.js
│   └── photos/            # Static photos
├── climbers/              # Legacy climber profile files (now in Redis)
└── scripts/               # Utility scripts
```

---

## Adding Albums

The album submission feature allows users to:

1. **Add Album Button**: Click the orange "+" button on the albums page
2. **Google Photos URL**: Paste a Google Photos album link (e.g., `https://photos.app.goo.gl/...`)
3. **URL Validation**: The system automatically validates the URL and fetches album metadata
4. **Crew Selection**: Select existing crew members who participated in the climb
5. **Add New People**: Optionally add new people to the crew database
6. **Instant Addition**: Albums are immediately added to the database

### How Album Submission Works

When you submit an album:

1. The URL is validated to ensure it's a valid Google Photos album
2. Album metadata (title, description, cover image) is fetched and displayed
3. Album data is directly stored in Redis [[memory:2866449]] with proper data types
4. New climber profiles are created in Redis if any new people were added
5. The album appears immediately on the albums page with animated effects
6. Crew member climb counts and levels are automatically updated

---

## How it Works

- **Main Page:**  
  - Displays an embedded Excalidraw flowchart explaining climbing
  
- **Albums Page:**  
  - Loads album data from Redis [[memory:2866449]] using proper data types
  - Shows animated skeletons for images/text
  - Fetches album metadata and preview image via backend API
  - Fades in images with blur, types in text, and shows album date
  - Page transitions are animated (main content only, navbar stays)
  - Real-time updates with particle animations for new/updated albums

- **Backend:**  
  - `/get-meta?url=...` — Scrapes OpenGraph data from Google Photos album
  - `/get-image?url=...` — Proxies images to avoid CORS/CORB
  - Uses Redis for data storage with proper data types for better performance [[memory:2866449]]
  - Serves all static files from `/static`

---

## Deployment (Production)

**Recommended setup:** Uvicorn + Nginx + systemd

```bash
# Install dependencies
uv sync

# Run with uvicorn
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

For production deployment, consider using a reverse proxy like Nginx and a process manager like systemd.

---

## Development

The application uses:
- **Backend**: FastAPI with Python
- **Data Layer**: Redis with proper data types (sets, hashes, etc.) [[memory:2866449]]
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Image Processing**: Pillow for photo metadata
- **HTTP Requests**: httpx for external API calls

### Development Commands

```bash
# Install dependencies
uv sync

# Add new dependency
uv add package-name

# Run development server
uv run uvicorn main:app --reload

# Run scripts
uv run python scripts/script_name.py
```

---

## Customization

- **Add albums:** Use the web interface or directly update Redis data [[memory:2866449]]
- **Change styles:** Edit `static/css/styles.css`
- **Change text effects:** Edit `static/js/albums.js` (`typewriter` function)

---

## Accessibility & Performance

- Respects `prefers-reduced-motion` for faster transitions on accessibility devices
- Fast, responsive, and works on all modern browsers
- Uses Redis for efficient data operations [[memory:2866449]]

---

## License

MIT

---

## Credits

- [FastAPI](https://fastapi.tiangolo.com/)
- [Uvicorn](https://www.uvicorn.org/)
- [Poppins font](https://fonts.google.com/specimen/Poppins)
- [Google Photos](https://photos.google.com/)
- [Excalidraw](https://excalidraw.com/)
- [Redis](https://redis.io/)
