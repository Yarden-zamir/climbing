readme is 100% ai generated gpt-4.1

# Climbing UI

A modern, animated web app for browsing Google Photos climbing albums, featuring beautiful transitions, skeleton loading, image blur/fade-in, and typewriter text effects.  
**The main page includes an [Excalidraw flowchart](https://link.excalidraw.com/readonly/AtAowLIPvMThzN3XHsEf) that explains everything about climbing.**

---

## Features

- **Excalidraw flowchart** on the main page, visually explaining climbing concepts
- **Animated skeleton loading** for both images and text
- **Blur + fade-in** for images (works with cached/lazy images)
- **Typewriter effect** for album titles/descriptions
- **Responsive, modern design** with Poppins font and gradient heading
- **RTL support** for Hebrew and other right-to-left languages
- **Animated page transitions** (content fades, navbar stays)
- **Google Photos album preview** with OpenGraph scraping and image proxying
- **Production-ready FastAPI backend** (serves both API and static UI)
- **Nginx/Uvicorn deployment ready**

---

## Quickstart (Development)

1. **Clone the repo**

   ```bash
   git clone github.com/yarden-zamir/climbing
   cd <your-repo>
   ```

2. **Install Python dependencies**

   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e .
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
   - The main page displays the Excalidraw climbing flowchart.
   - The Albums page shows animated Google Photos album previews.

---

## Project Structure

```
.
├── main.py                # FastAPI backend (serves API + static UI)
├── pyproject.toml         # Python dependencies
├── static/
│   ├── index.html         # Main page with Excalidraw flowchart
│   ├── albums.html        # Albums page with filtering and crew faces
│   ├── albums.json        # Album metadata with crew information and URLs
│   ├── crew.html          # Crew directory page
│   ├── css/
│   │   └── styles.css
│   ├── js/
│   │   └── albums.js
│   ├── memes.html         # Memes page
│   └── photos/            # Static photos
```

---

## Deployment (Production)

- **Recommended:** Uvicorn + Nginx + systemd
- See deployment instructions above or ask for a full guide.

---

## How it Works

- **Main Page:**
  - Displays an embedded Excalidraw flowchart explaining climbing.
- **Albums Page:**

  - Loads album links from `albums.json`
  - Shows animated skeletons for images/text
  - Fetches album metadata and preview image via backend API
  - Fades in images with blur, types in text, and shows album date
  - Page transitions are animated (main content only, navbar stays)

- **Backend:**
  - `/get-meta?url=...` — Scrapes OpenGraph data from Google Photos album
  - `/get-image?url=...` — Proxies images to avoid CORS/CORB
  - Serves all static files from `/static`

---

## Customization

- **Add albums:**
  - Edit `static/albums.json` (add new album metadata)
- **Change styles:**
  - Edit `static/css/styles.css`
- **Change text effects:**
  - Edit `static/js/albums.js` (`typewriter` function)

---

## Accessibility & Performance

- Respects `prefers-reduced-motion` for faster transitions on accessibility devices
- Fast, responsive, and works on all modern browsers

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

# Climbing Album Management

A web application for managing climbing albums and crew progress.

## Features

- **Albums**: Browse climbing albums with filtering by crew members
- **Crew**: View crew member progress, skills, and level statistics
- **Memes**: Browse climbing photos and memes
- **Add Albums**: Submit new Google Photos albums with automatic PR creation

## Setup

### Prerequisites

- Python 3.13+
- uv package manager

### Installation

```bash
uv pip install -e .
```

### Environment Variables

For the album submission feature to work, you need to set up these environment variables:

```bash
# GitHub Personal Access Token with repo permissions
export GITHUB_TOKEN="your_github_token_here"

# GitHub repository URL (optional, defaults to yarden-zamir/climbing)
export GITHUB_REPO_URL="https://github.com/your-username/your-repo.git"
```

#### Creating a GitHub Token

1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Select the following scopes:
   - `repo` (Full control of private repositories)
   - `pull_request` (Access to pull requests)
4. Copy the generated token and set it as the `GITHUB_TOKEN` environment variable

### Running the Application

```bash
uv run uvicorn main:app --reload
```

The application will be available at `http://localhost:8000`

## Adding Albums

The new album submission feature allows users to:

1. **Add Album Button**: Click the orange "+" button on the albums page
2. **Google Photos URL**: Paste a Google Photos album link (e.g., `https://photos.app.goo.gl/...`)
3. **URL Validation**: The system automatically validates the URL and fetches album metadata
4. **Crew Selection**: Select existing crew members who participated in the climb
5. **Add New People**: Optionally add new people to the crew database
6. **Automatic PR**: The system creates a GitHub branch and pull request automatically

### How It Works

When you submit an album:

1. The URL is validated to ensure it's a valid Google Photos album
2. Album metadata (title, description, cover image) is fetched and displayed
3. A new Git branch is created with timestamp (e.g., `add-album-20241215-143022`)
4. The following files are updated:
   - `static/albums.json` - Album metadata is added
   - `climbers/*/details.json` - New climber profiles are created (if any)
5. A pull request is automatically created for review
6. You receive a link to the PR for review and merging

### File Structure

- `static/albums.json` - List of album metadata
- `climbers/` - Individual climber profiles and photos
- `static/photos/` - Meme photos
- `main.py` - FastAPI backend application
- `static/` - Frontend assets (HTML, CSS, JS)

## Development

The application uses:

- **Backend**: FastAPI with Python
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **GitHub API**: PyGithub for repository operations
- **Image Processing**: Pillow for photo metadata
- **HTTP Requests**: httpx for external API calls
