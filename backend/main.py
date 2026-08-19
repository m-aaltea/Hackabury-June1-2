import asyncio
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import scrape_page
from gemini import analyse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    url: str


@app.post("/api/scrape")
async def scrape(req: ScrapeRequest):
    try:
        return await asyncio.wait_for(_scrape(req), timeout=25)
    except TimeoutError:
        return {"error": "The website analysis timed out. Please try again."}


async def _scrape(req: ScrapeRequest):
    t0 = time.time()
    try:
        scraped = await scrape_page(req.url)
        print(f"[scrape] {time.time()-t0:.2f}s")
    except Exception as exc:
        return {"error": f"Failed to fetch URL: {exc}"}

    t1 = time.time()
    result = await analyse(scraped)
    print(f"[gemini] {time.time()-t1:.2f}s  [total] {time.time()-t0:.2f}s")

    if scraped.get("blocked"):
        result["blocked"] = True
        result["block_reason"] = scraped.get("block_reason", "unknown")

    return result
