from __future__ import annotations

from typing import Optional

import httpx

from app import config


async def search_movie(title: str) -> Optional[dict]:
    if not config.TMDB_API_KEY:
        return None
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": config.TMDB_API_KEY, "query": title, "include_adult": "false"}
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(url, params=params)
        if r.status_code >= 400:
            return None
        data = r.json()
    return data.get("results", [None])[0]


async def movie_details(movie_id: int) -> Optional[dict]:
    if not config.TMDB_API_KEY:
        return None
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": config.TMDB_API_KEY, "append_to_response": "credits"}
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(url, params=params)
        if r.status_code >= 400:
            return None
        return r.json()


def image_url(path: Optional[str]) -> Optional[str]:
    return f"https://image.tmdb.org/t/p/w500{path}" if path else None
