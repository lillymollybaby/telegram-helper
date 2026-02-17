from __future__ import annotations

from html import escape
from typing import Optional

from app.services import tmdb


def build_movie_facts_text(film_title: str, details: Optional[dict]) -> str:
    if not details:
        return f"Не нашел детали по «{escape(film_title)}»."
    genres = ", ".join(g.get("name", "") for g in details.get("genres", []) if g.get("name")) or "—"
    lines = [
        f"🎞 <b>{escape(details.get('title') or film_title)}</b>",
        f"Год/дата: <b>{escape(details.get('release_date') or '—')}</b>",
        f"Длительность: <b>{escape(str(details.get('runtime') or '—'))} мин</b>",
        f"Жанры: <b>{escape(genres)}</b>",
    ]
    if isinstance(details.get("vote_average"), (int, float)):
        lines.append(f"Рейтинг TMDB: <b>{details['vote_average']:.1f}</b>")
    return "\n".join(lines)


def build_people_data(film_title: str, details: Optional[dict]) -> tuple[str, list[dict]]:
    if not details:
        return f"Не нашел актеров/режиссера по «{escape(film_title)}».", []
    credits = details.get("credits", {})
    crew = credits.get("crew", []) if isinstance(credits, dict) else []
    cast = credits.get("cast", []) if isinstance(credits, dict) else []
    director = next((p for p in crew if (p.get("job") or "").lower() == "director"), None)
    top_cast = cast[:6]
    lines = [f"🎭 <b>{escape(details.get('title') or film_title)}</b>"]
    lines.append(f"Режиссер: <b>{escape((director or {}).get('name', '—'))}</b>")
    people = []
    if director and director.get("profile_path"):
        people.append({"name": director["name"], "role": "Режиссер", "photo": tmdb.image_url(director["profile_path"])})
    for p in top_cast:
        if p.get("profile_path"):
            people.append({"name": p.get("name", "Actor"), "role": p.get("character") or "Актер", "photo": tmdb.image_url(p.get("profile_path"))})
    return "\n".join(lines), people
