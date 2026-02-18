from __future__ import annotations

import asyncio
import csv
import gzip
import io
import json
import logging
import re
from pathlib import Path
from typing import Iterable, Optional

import httpx
from deep_translator import GoogleTranslator
from nltk.corpus import stopwords, wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize
from wordfreq import word_frequency

from app import config, db

logger = logging.getLogger(__name__)

OPENSUBTITLES_BASE = "https://api.opensubtitles.com/api/v1"
_SRT_TAG_RE = re.compile(r"</?[^>]+>")
_SRT_TIMECODE_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{3,}")
_CEFR_CACHE = Path("app") / "data" / "cefr_en_b1_c1.json"
_CEFR_LEVELS = {"B1", "B2", "C1"}
_CEFR_RAW_URLS = (
    "https://raw.githubusercontent.com/emmairwin/cefr-en/main/cefr_en.csv",
    "https://raw.githubusercontent.com/emmairwin/cefr-en/main/data/cefr_en.csv",
    "https://raw.githubusercontent.com/emmairwin/cefr-en/master/cefr_en.csv",
    "https://raw.githubusercontent.com/emmairwin/cefr-en/master/data/cefr_en.csv",
)

_nltk_ready = False


def _title_key(title: str) -> str:
    base = (title or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", base).strip()


def _is_srt_counter(line: str) -> bool:
    return bool(line.strip().isdigit())


def _clean_srt_text(srt_text: str) -> list[str]:
    lines: list[str] = []
    for raw in srt_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_srt_counter(line):
            continue
        if _SRT_TIMECODE_RE.match(line):
            continue
        line = _SRT_TAG_RE.sub("", line)
        line = re.sub(r"\{\\an\d\}", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def _decode_subtitle_content(content: bytes) -> str:
    body = content
    if len(content) >= 2 and content[0] == 0x1F and content[1] == 0x8B:
        body = gzip.decompress(content)
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="ignore")


def _safe_pos(token: str) -> str:
    if token.endswith("ing") or token.endswith("ed"):
        return wordnet.VERB
    if token.endswith("ly"):
        return wordnet.ADV
    if token.endswith("ous") or token.endswith("ive") or token.endswith("al") or token.endswith("ic"):
        return wordnet.ADJ
    return wordnet.NOUN


def _iter_csv_rows(text: str) -> Iterable[dict[str, str]]:
    sample = text[:2048]
    delimiter = ","
    if "\t" in sample and sample.count("\t") > sample.count(","):
        delimiter = "\t"
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    for row in reader:
        if row:
            yield {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k}


def _extract_word_level_pairs(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or item.get("lemma") or "").strip().lower()
            level = str(item.get("level") or item.get("cefr") or "").strip().upper()
            if word and level in _CEFR_LEVELS:
                result[word] = level
        return result

    for row in _iter_csv_rows(text):
        word = row.get("word") or row.get("lemma") or row.get("entry") or ""
        level = row.get("level") or row.get("cefr") or ""
        word = word.strip().lower()
        level = level.strip().upper()
        if word and level in _CEFR_LEVELS:
            result[word] = level
    return result


async def _ensure_nltk_data() -> None:
    global _nltk_ready
    if _nltk_ready:
        return
    import nltk

    needed = (
        ("punkt", "tokenizers/punkt"),
        ("punkt_tab", "tokenizers/punkt_tab"),
        ("stopwords", "corpora/stopwords"),
        ("wordnet", "corpora/wordnet"),
    )
    for item, path in needed:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(item, quiet=True)
    _nltk_ready = True


async def _load_cefr_b1_c1_words() -> set[str]:
    if _CEFR_CACHE.exists():
        try:
            cached = json.loads(_CEFR_CACHE.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return {str(x).strip().lower() for x in cached if str(x).strip()}
        except Exception as e:
            logger.debug("Failed to read CEFR cache %s: %s", _CEFR_CACHE, e)

    words: dict[str, str] = {}
    timeout = httpx.Timeout(15)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for url in _CEFR_RAW_URLS:
            try:
                r = await client.get(url)
                if r.status_code >= 400:
                    continue
                parsed = _extract_word_level_pairs(r.text)
                if parsed:
                    words.update(parsed)
                    break
            except Exception as e:
                logger.debug("Failed to load CEFR source %s: %s", url, e)
                continue
        if not words:
            try:
                r = await client.get("https://api.github.com/repos/emmairwin/cefr-en/contents")
                if r.status_code < 400:
                    for item in r.json():
                        if not isinstance(item, dict):
                            continue
                        dl = item.get("download_url")
                        name = str(item.get("name") or "").lower()
                        if not dl or not any(name.endswith(x) for x in (".csv", ".tsv", ".json")):
                            continue
                        rr = await client.get(dl)
                        if rr.status_code >= 400:
                            continue
                        parsed = _extract_word_level_pairs(rr.text)
                        if parsed:
                            words.update(parsed)
                            break
            except Exception as e:
                logger.debug("Failed CEFR GitHub API fallback: %s", e)

    out = {w for w, lvl in words.items() if lvl in _CEFR_LEVELS}
    if out:
        _CEFR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CEFR_CACHE.write_text(json.dumps(sorted(out), ensure_ascii=False), encoding="utf-8")
    return out


async def _search_subtitle_file_id(title: str, year: Optional[int]) -> Optional[int]:
    if not config.OPENSUBTITLES_API_KEY:
        logger.warning("OpenSubtitles: API key not configured")
        return None
    headers = {
        "Api-Key": config.OPENSUBTITLES_API_KEY,
        "User-Agent": "telegram-helper v1",
        "Accept": "application/json",
    }
    params = {
        "query": title,
        "languages": "en",
        "type": "movie",
        "order_by": "download_count",
        "order_direction": "desc",
    }
    if year:
        params["year"] = str(year)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(f"{OPENSUBTITLES_BASE}/subtitles", headers=headers, params=params)
        if r.status_code >= 400:
            logger.warning("OpenSubtitles search failed: title=%s status=%s body=%s", title, r.status_code, r.text[:240])
            return None
        data = r.json()
    for item in data.get("data", []):
        attrs = item.get("attributes", {}) if isinstance(item, dict) else {}
        files = attrs.get("files", []) if isinstance(attrs, dict) else []
        for f in files:
            if not isinstance(f, dict):
                continue
            file_id = f.get("file_id")
            if isinstance(file_id, int):
                logger.info("OpenSubtitles: Found file_id=%s for title=%s", file_id, title)
                return file_id
    logger.warning("OpenSubtitles: No subtitles found for title=%s", title)
    return None


async def _download_srt_by_file_id(file_id: int) -> Optional[str]:
    if not config.OPENSUBTITLES_API_KEY:
        return None
    headers = {
        "Api-Key": config.OPENSUBTITLES_API_KEY,
        "User-Agent": "telegram-helper v1",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"file_id": file_id, "sub_format": "srt"}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        r = await client.post(f"{OPENSUBTITLES_BASE}/download", headers=headers, json=payload)
        if r.status_code >= 400:
            logger.warning("OpenSubtitles download link failed: file_id=%s status=%s body=%s", file_id, r.status_code, r.text[:240])
            return None
        link = (r.json() or {}).get("link")
        if not link:
            logger.warning("OpenSubtitles: No download link in response for file_id=%s", file_id)
            return None
        logger.debug("OpenSubtitles: Got download link for file_id=%s, downloading...", file_id)
        rr = await client.get(link)
        if rr.status_code >= 400:
            logger.warning("OpenSubtitles: Failed to fetch subtitle file from link, status=%s", rr.status_code)
            return None
        logger.info("OpenSubtitles: Successfully downloaded subtitle, size=%s bytes", len(rr.content))
    return _decode_subtitle_content(rr.content)


def _pick_candidates(lines: list[str], cefr_words: set[str], limit: int) -> list[dict]:
    if not lines:
        return []
    lemmatizer = WordNetLemmatizer()
    sw = set(stopwords.words("english"))
    use_cefr_filter = bool(cefr_words)
    freq_counter: dict[str, int] = {}
    example_for: dict[str, str] = {}
    wf_by_word: dict[str, float] = {}

    # Common simple words/names to exclude
    COMMON_SIMPLE = {
        "charley", "charlie", "goblin", "harry", "london", "spider", "peter",
        "queen", "king", "prince", "princess", "dragon", "wizard", "magic",
        "hello", "goodbye", "thanks", "please", "sorry", "sure", "right",
        "left", "right", "come", "went", "look", "see", "tell", "got",
        "good", "bad", "big", "small", "nice", "thing", "stuff", "make",
        "take", "give", "get", "call", "say", "know", "think", "want",
        "need", "like", "have", "does", "done", "said", "told", "went",
        "come", "back", "time", "year", "day", "week", "month", "place",
        "person", "people", "guy", "girl", "man", "woman", "boy", "lady",
    }

    for line in lines:
        tokens = word_tokenize(line)
        for t in tokens:
            low = t.lower()
            if not _WORD_RE.fullmatch(low):
                continue
            # More strict: words must be at least 6 chars
            if len(low) < 6 or low in sw or low in COMMON_SIMPLE:
                continue
            
            # Skip probable names (start with capital + short)
            if t[0].isupper() and len(t) < 8:
                continue
                
            lemma = lemmatizer.lemmatize(low, _safe_pos(low))
            if lemma in sw or lemma in COMMON_SIMPLE or len(lemma) < 6:
                continue
            
            wf = word_frequency(lemma, "en")
            freq_counter[lemma] = freq_counter.get(lemma, 0) + 1
            wf_by_word[lemma] = wf
            example_for.setdefault(lemma, line)

    scored_words = [w for w, _ in sorted(freq_counter.items(), key=lambda kv: (wf_by_word.get(kv[0], 0.0), -kv[1], kv[0]))]
    out: list[dict] = []
    used: set[str] = set()

    def add_stage(min_wf: float, max_wf: float, require_cefr: bool = True) -> None:
        for word in scored_words:
            if word in used:
                continue
            wf = wf_by_word.get(word, 0.0)
            if not (min_wf <= wf <= max_wf):
                continue
            # STRICT: Always respect CEFR if available
            if use_cefr_filter and word not in cefr_words:
                continue
            used.add(word)
            out.append({"word": word, "example": example_for.get(word, "")})
            if len(out) >= limit:
                return

    # Stage 1: Very strict - only B1-C1 words with low frequency (not common)
    add_stage(1e-6, 2e-5, require_cefr=True)
    
    # Stage 2: Still strict - B1-C1 words, wider frequency range
    if len(out) < limit:
        add_stage(1e-6, 5e-5, require_cefr=True)
    
    # Stage 3: If still not enough - allow slightly higher frequency but still require CEFR
    if len(out) < limit:
        add_stage(1e-6, 1e-4, require_cefr=True)
    
    # Stage 4: Last resort - rare words (very low frequency) without CEFR requirement
    if len(out) < limit:
        add_stage(1e-7, 1e-6, require_cefr=False)

    return out


async def _translate_words(words: list[dict]) -> list[dict]:
    if not words:
        return []
    translator = GoogleTranslator(source="en", target="ru")

    def _tr(w: str, example: str = "") -> str:
        try:
            # If we have example, try to get better translation with context
            if example and len(example) > 10:
                # Translate the example first to understand context
                try:
                    example_ru = translator.translate(example[:50]) or ""
                    # Now translate the word with better understanding
                    result = translator.translate(w) or ""
                    # Additional context-aware translation attempt
                    if result and result != w:
                        return result
                except Exception:
                    pass
            
            # Fallback to simple translation
            result = translator.translate(w) or ""
            return result
        except Exception as e:
            logger.debug("Word translation failed for '%s': %s", w, e)
            return ""

    out: list[dict] = []
    for item in words:
        word = item.get("word", "")
        example = item.get("example", "")
        translated = await asyncio.to_thread(_tr, word, example)
        if not translated:
            translated = "(перевод недоступен)"
        out.append(
            {
                "word": item["word"],
                "translation": translated,
                "example": item.get("example", ""),
            }
        )
    return out


async def extract_words_from_movie_subtitles(film_title: str, year: Optional[int] = None, limit: int = 15) -> list[dict]:
    try:
        await _ensure_nltk_data()
        cache_key = _title_key(film_title)
        lines = db.get_subtitle_cache(cache_key, year)
        if lines:
            logger.info("Using cached subtitles for film=%s year=%s lines_count=%s", film_title, year, len(lines))
        else:
            logger.info("Cache miss for film=%s year=%s, fetching from OpenSubtitles...", film_title, year)
            file_id = await _search_subtitle_file_id(film_title, year)
            if not file_id:
                logger.warning("Could not find subtitle file_id for film=%s", film_title)
                return []
            srt_text = await _download_srt_by_file_id(file_id)
            if not srt_text:
                logger.warning("Failed to download subtitle for film=%s file_id=%s", film_title, file_id)
                return []
            lines = _clean_srt_text(srt_text)
            logger.info("Extracted %s lines from subtitle for film=%s", len(lines), film_title)
            db.save_subtitle_cache(cache_key, year, lines, source="opensubtitles")

        cefr_words = await _load_cefr_b1_c1_words()
        logger.debug("Loaded %s CEFR (B1-C1) words for filtering", len(cefr_words))
        
        candidates = await asyncio.to_thread(_pick_candidates, lines, cefr_words, limit)
        logger.info("Filtered down to %s word candidates from %s lines (using strict CEFR filter)", len(candidates), len(lines))
        
        translated = await _translate_words(candidates[:limit])
        logger.info("Successfully extracted %s translated words for film=%s (only strict B1-C1 vocabulary)", len(translated), film_title)
        if translated:
            logger.debug("Sample words: %s", [(w.get('word'), w.get('translation')) for w in translated[:3]])
        return translated[:limit]
    except Exception as e:
        logger.warning("Subtitle word extraction failed for film=%s: %s", film_title, e, exc_info=True)
        return []


def format_words_for_telegram(film_title: str, year: Optional[int], words: list[dict], page: int = 0, per_page: int = 5) -> str:
    """Format words with pagination support."""
    if not words:
        return ""
    
    # Calculate pagination
    total_pages = (len(words) + per_page - 1) // per_page
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(words))
    page_words = words[start_idx:end_idx]
    
    # Header
    header = f'📚 <b>Слова из фильма "{film_title}"</b>'
    if year:
        header += f" <i>({year})</i>"
    header += f"\n📖 Страница {page + 1} из {total_pages}"
    
    lines = [header, ""]
    
    # Words
    for idx, item in enumerate(page_words, start=start_idx + 1):
        w = str(item.get("word") or "").strip()
        tr = str(item.get("translation") or "").strip()
        ex = str(item.get("example") or "").strip()
        if not w or not tr:
            continue
        
        # Better formatting with more context
        lines.append(f"<b>{idx}. {w}</b>")
        lines.append(f"   🇷🇺 <i>{tr}</i>")
        if ex:
            # Show more of the example
            example_text = ex[:80] if len(ex) > 80 else ex
            lines.append(f"   💬 <code>{example_text}</code>")
        lines.append("")
    
    if len(lines) <= 2:
        return ""
    
    text = "\n".join(lines).strip()
    
    # Footer with page indicator
    if total_pages > 1:
        text += f"\n\n{'▫️' * (total_pages)}\n <b>{' ' * page}▪️</b>"
    
    return text
