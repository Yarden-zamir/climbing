import httpx
import re
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup

# Initialize FastAPI app
app = FastAPI()

# Configure CORS
origins = [
	"https://climbing.yarden-zamir.com"
	"https://yarden-zamir.com"
	"http://localhost",
	"http://localhost:8000",
	"http://127.0.0.1:8000",
	"http://localhost:8001",  
	"http://127.0.0.1:8001",  
	"http://localhost:8002",  
	"http://127.0.0.1:8002",
]
app.add_middleware(
	CORSMiddleware,
	allow_origins=origins,
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


async def fetch_url(client: httpx.AsyncClient, url: str):
	"""Generic helper to fetch a URL and handle errors."""
	try:
		headers = {
			"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
		}
		response = await client.get(
			url, headers=headers, follow_redirects=True
		)
		response.raise_for_status()
		return response
	except httpx.RequestError as exc:
		# This will be caught by the endpoint and returned as a proper HTTP error
		raise HTTPException(
			status_code=400, detail=f"Error fetching URL: {exc}"
		)


def parse_meta_tags(html: str, url: str):
	"""Parses OG meta tags and modifies the image URL for full size."""
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

	if image_url:
		image_url = re.sub(r"=w\d+.*$", "=s0", image_url)

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
		response = await fetch_url(client, url)
		meta_data = parse_meta_tags(response.text, url)
		return meta_data


@app.get("/get-image")
async def get_image(url: str = Query(...)):
	"""
	Acts as a proxy to fetch an image.
	This avoids client-side CORB errors.
	"""
	async with httpx.AsyncClient() as client:
		response = await fetch_url(client, url)
		# Get the original content type (e.g., 'image/jpeg')
		content_type = response.headers.get("content-type", "application/octet-stream")
		# Stream the image content back to the client
		return Response(content=response.content, media_type=content_type)
