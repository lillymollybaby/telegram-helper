from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Optional

import httpx


def _safe_child_text(item: ET.Element, tag: str) -> Optional[str]:
    node = item.find(tag)
    if node is not None and node.text:
        return node.text.strip()
    return None


def normalize_film_title(entry_title: str) -> str:
    title = unescape(entry_title or "").strip()
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    title = re.sub(r"\s+\(\d{4}\)\s*$", "", title).strip()
    title = re.sub(r",\s*\d{4}\s*$", "", title).strip()
    return title or "Фильм"


def parse_letterboxd_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    for item in root.findall(".//item"):
        title = _safe_child_text(item, "title") or ""
        link = _safe_child_text(item, "link")
        guid = _safe_child_text(item, "guid") or link or title
        items.append(
            {
                "guid": guid,
                "entry_title": title,
                "film_title": normalize_film_title(title),
                "link": link,
                "published": _safe_child_text(item, "pubDate"),
                "summary": _safe_child_text(item, "description"),
            }
        )
    return items


def parse_watchlist_html(html_text: str) -> list[dict]:
    pattern = re.compile(r'data-item-name="([^"]+)"[^>]*data-item-link="([^"]+)"', re.IGNORECASE)
    out: list[dict] = []
    seen: set[str] = set()
    for m in pattern.finditer(html_text):
        name = unescape(m.group(1).strip())
        link = unescape(m.group(2).strip())
        if link.startswith("/"):
            link = f"https://letterboxd.com{link}"
        if link in seen:
            continue
        seen.add(link)
        out.append(
            {
                "guid": link,
                "entry_title": name,
                "film_title": normalize_film_title(name),
                "link": link,
                "published": None,
                "summary": None,
            }
        )
    return out


def looks_like_letterboxd_rss(url: str) -> bool:
    u = (url or "").strip().lower()
    return (u.startswith("http://") or u.startswith("https://")) and "letterboxd.com/" in u and "/rss" in u


def derive_watchlist_rss_url(rss_url: str) -> Optional[str]:
    u = (rss_url or "").strip()
    low = u.lower()
    if "letterboxd.com/" not in low:
        return None
    if "/watchlist/rss" in low:
        return u
    if "/rss" in low:
        return re.sub(r"/rss/?$", "/watchlist/rss/", u, flags=re.IGNORECASE)
    return None


async def fetch_letterboxd_items(url: str) -> tuple[list[dict], Optional[str]]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code >= 400:
                return [], f"RSS вернул {r.status_code}"
            items = parse_letterboxd_rss(r.text)
            if not items:
                return [], "в RSS нет записей"
            return items, None
    except Exception as e:
        return [], f"ошибка RSS: {e}"


async def fetch_watchlist_items(url: str) -> tuple[list[dict], Optional[str]]:
    items, err = await fetch_letterboxd_items(url)
    if items:
        return items, None
    if not err or "403" not in err:
        return items, err
    html_url = re.sub(r"/rss/?$", "/", url, flags=re.IGNORECASE)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(html_url)
            if r.status_code >= 400:
                return [], f"wishlist страница вернула {r.status_code}"
            parsed = parse_watchlist_html(r.text)
            if not parsed:
                return [], "не удалось распознать wishlist"
            return parsed, None
    except Exception as e:
        return [], f"ошибка wishlist: {e}"
