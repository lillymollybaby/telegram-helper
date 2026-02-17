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
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{OPENSUBTITLES_BASE}/subtitles", headers=headers, params=params)
        if r.status_code >= 400:
            logger.warning("OpenSubtitles search failed: status=%s body=%s", r.status_code, r.text[:240])
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
                return file_id
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
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(f"{OPENSUBTITLES_BASE}/download", headers=headers, json=payload)
        if r.status_code >= 400:
            logger.warning("OpenSubtitles download link failed: status=%s body=%s", r.status_code, r.text[:240])
            return None
        link = (r.json() or {}).get("link")
        if not link:
            return None
        rr = await client.get(link)
        if rr.status_code >= 400:
            return None
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

    for line in lines:
        tokens = word_tokenize(line)
        for t in tokens:
            low = t.lower()
            if not _WORD_RE.fullmatch(low):
                continue
            if len(low) < 5 or low in sw:
                continue
            lemma = lemmatizer.lemmatize(low, _safe_pos(low))
            if lemma in sw or len(lemma) < 5:
                continue
            wf = word_frequency(lemma, "en")
            freq_counter[lemma] = freq_counter.get(lemma, 0) + 1
            wf_by_word[lemma] = wf
            example_for.setdefault(lemma, line)

    scored_words = [w for w, _ in sorted(freq_counter.items(), key=lambda kv: (wf_by_word.get(kv[0], 0.0), -kv[1], kv[0]))]
    out: list[dict] = []
    used: set[str] = set()

    def add_stage(min_wf: float, max_wf: float, require_cefr: bool) -> None:
        for word in scored_words:
            if word in used:
                continue
            wf = wf_by_word.get(word, 0.0)
            if not (min_wf <= wf <= max_wf):
                continue
            if require_cefr and word not in cefr_words:
                continue
            used.add(word)
            out.append({"word": word, "example": example_for.get(word, "")})
            if len(out) >= limit:
                return

    # Stage 1: strict B1-C1.
    add_stage(1e-6, 3e-5, require_cefr=use_cefr_filter)
    # Stage 2: wider upper bound to avoid too-short lists.
    if len(out) < limit:
        add_stage(1e-6, 1e-4, require_cefr=use_cefr_filter)
    # Stage 3: no CEFR (when subtitle vocabulary is narrow or CEFR set is too strict).
    if len(out) < limit:
        add_stage(1e-6, 1e-4, require_cefr=False)
    # Stage 4: final fill with medium-frequency words.
    if len(out) < limit:
        add_stage(1e-7, 3e-4, require_cefr=False)

    return out


async def _translate_words(words: list[dict]) -> list[dict]:
    if not words:
        return []
    translator = GoogleTranslator(source="en", target="ru")

    def _tr(w: str) -> str:
        try:
            return translator.translate(w) or ""
        except Exception as e:
            logger.debug("Word translation failed for '%s': %s", w, e)
            return ""

    out: list[dict] = []
    for item in words:
        translated = await asyncio.to_thread(_tr, item["word"])
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
        if not lines:
            file_id = await _search_subtitle_file_id(film_title, year)
            if not file_id:
                return []
            srt_text = await _download_srt_by_file_id(file_id)
            if not srt_text:
                return []
            lines = _clean_srt_text(srt_text)
            db.save_subtitle_cache(cache_key, year, lines, source="opensubtitles")

        cefr_words = await _load_cefr_b1_c1_words()
        candidates = await asyncio.to_thread(_pick_candidates, lines, cefr_words, limit)
        translated = await _translate_words(candidates[:limit])
        return translated[:limit]
    except Exception as e:
        logger.warning("Subtitle word extraction failed for %s: %s", film_title, e)
        return []


def format_words_for_telegram(film_title: str, year: Optional[int], words: list[dict]) -> str:
    header = f'Слова из фильма "{film_title}"'
    if year:
        header += f" ({year})"
    lines = [header, ""]
    for idx, item in enumerate(words[:15], start=1):
        w = str(item.get("word") or "").strip()
        tr = str(item.get("translation") or "").strip()
        ex = str(item.get("example") or "").strip()
        if not w or not tr:
            continue
        lines.append(f"{idx}. {w} — {tr}")
        if ex:
            lines.append(f'Реплика: "{ex}"')
        lines.append("")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines).strip()
