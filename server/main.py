import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup

# Initialize FastAPI app
app = FastAPI()

# Configure CORS to allow requests from the frontend client
origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",  # <-- ADD THIS for the new client port
    "http://127.0.0.1:8001",  # <-- And this one for completeness
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def fetch_html(client: httpx.AsyncClient, url: str):
    """Asynchronously fetches HTML content from a URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        response = await client.get(
            url, headers=headers, follow_redirects=True
        )
        response.raise_for_status()
        return response.text
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400, detail=f"Error fetching URL: {exc}"
        )


def parse_meta_tags(html: str, url: str):
    """Parses OG meta tags from HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")

    def get_meta_tag(prop):
        tag = soup.find("meta", property=prop)
        return tag["content"] if tag else None

    title = (
        get_meta_tag("og:title")
        or (soup.title.string if soup.title else "Untitled")
    )
    description = (
        get_meta_tag("og:description") or "No description available."
    )
    image_url = get_meta_tag("og:image") or ""
    image_url = image_url if image_url.startswith("http") else f"https://{image_url}"
    image_url = image_url.removesuffix(image_url.split("=")[-1]).removesuffix("=")
    image_url = image_url+"=s0"
    return {
        "title": title,
        "description": description,
        "imageUrl": image_url,
        "url": url,
    }


@app.get("/get-meta")
async def get_meta(url: str = Query(...)):
    """API endpoint to fetch and parse metadata from a URL."""
    async with httpx.AsyncClient() as client:
        html_content = await fetch_html(client, url)
        meta_data = parse_meta_tags(html_content, url)
        return meta_data
