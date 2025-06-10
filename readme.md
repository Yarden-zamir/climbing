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

3. **Run the server**
    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8001 --reload
    ```

4. **Browse**
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
│   ├── albums.html        # Albums page
│   ├── albums.txt         # List of Google Photos album links (one per line)
│   ├── css/
│   │   └── styles.css
│   └── js/
│       └── albums.js
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
  - Loads album links from `albums.txt`
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
  - Edit `static/albums.txt` (one Google Photos album link per line)
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
