from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9а-яё]+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s


def _name_tokens(s: str) -> set[str]:
    stop = {"the", "a", "an", "and", "of", "movie", "film", "script", "transcript"}
    return {x for x in _norm(s).split() if x and x not in stop}


def _candidate_parsed_dirs(root: Path) -> list[Path]:
    return [root / "scripts" / "parsed" / "dialogue", root / "parsed" / "dialogue"]


def _candidate_unprocessed_dirs(root: Path) -> list[Path]:
    return [root / "scripts" / "unprocessed" / "imsdb", root / "unprocessed" / "imsdb"]


def _is_parsed_dialogue_file(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return "parsed" in parts and "dialogue" in parts


def _filename_similarity(a: str, b: str) -> int:
    ta = _name_tokens(a)
    tb = _name_tokens(b)
    if not ta or not tb:
        return 0
    overlap = len(ta.intersection(tb)) * 30
    ratio = int(SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() * 100)
    return overlap + ratio


def _best_dialogue_file_from_meta(root: Path, film_title: str) -> Optional[Path]:
    candidates = [
        root / "scripts" / "metadata" / "meta.json",
        root / "metadata" / "meta.json",
    ]
    target = _norm(film_title)
    for meta_path in candidates:
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            logger.debug("Failed to read script metadata %s: %s", meta_path, e)
            continue
        if not isinstance(data, dict):
            continue
        for _, item in data.items():
            if not isinstance(item, dict):
                continue
            tmdb_title = ((item.get("tmdb") or {}).get("title") or "") if isinstance(item.get("tmdb"), dict) else ""
            imdb_title = ((item.get("imdb") or {}).get("title") or "") if isinstance(item.get("imdb"), dict) else ""
            parsed = item.get("parsed") if isinstance(item.get("parsed"), dict) else {}
            dialog_name = parsed.get("dialogue") if isinstance(parsed, dict) else None
            if not dialog_name:
                continue
            names = {_norm(tmdb_title), _norm(imdb_title), _norm(str(item.get("name", "")))}
            names = {n for n in names if n}
            if target in names:
                p1 = root / "scripts" / "parsed" / "dialogue" / dialog_name
                p2 = root / "parsed" / "dialogue" / dialog_name
                if p1.exists():
                    return p1
                if p2.exists():
                    return p2
    return None


def _best_dialogue_file_by_name(root: Path, film_title: str) -> Optional[Path]:
    title_tokens = _name_tokens(film_title)
    if not title_tokens:
        return None

    best: tuple[int, Optional[Path]] = (0, None)
    for d in _candidate_parsed_dirs(root) + _candidate_unprocessed_dirs(root):
        if not d.exists():
            continue
        for p in d.glob("*.txt"):
            score = _filename_similarity(film_title, p.stem)
            if _is_parsed_dialogue_file(p):
                score += 25
            if score > best[0]:
                best = (score, p)
    return best[1]


def _extract_dialogue_lines(text: str, max_lines: int) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if "=>" in s:
            parts = s.split("=>", 1)
            char = parts[0].strip()
            dialog = parts[1].strip()
            if dialog:
                lines.append(f"{char}: {dialog}" if char else dialog)
        elif len(s) > 20:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines


def _looks_like_speaker_line(s: str) -> bool:
    if len(s) < 2 or len(s) > 35:
        return False
    if re.search(r"[^A-Z0-9\-\.'\(\)\s]", s):
        return False
    if re.match(r"^(INT\.|EXT\.|CUT TO|FADE|DISSOLVE|TITLE)", s):
        return False
    letters = re.sub(r"[^A-Z]", "", s)
    return len(letters) >= 2 and s == s.upper()


def _extract_screenplay_lines(text: str, max_lines: int) -> list[str]:
    lines: list[str] = []
    speaker: Optional[str] = None
    for raw in text.splitlines():
        s = re.sub(r"\s+", " ", raw.strip())
        if not s:
            continue

        if _looks_like_speaker_line(s):
            speaker = s.title()
            continue
        if re.match(r"^(INT\.|EXT\.|CUT TO|FADE IN|FADE OUT|DISSOLVE TO)", s, flags=re.IGNORECASE):
            speaker = None
            continue
        if len(s) < 18 or len(s) > 180:
            continue
        if not re.search(r"[A-Za-z]", s):
            continue
        if s.isupper() and len(s.split()) <= 8:
            continue

        if speaker:
            lines.append(f"{speaker}: {s}")
            speaker = None
        else:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines


def load_dialogues_for_film(film_title: str, script_db_root: str, max_lines: int = 120) -> list[str]:
    if not script_db_root:
        return []
    root = Path(script_db_root)
    if not root.exists() or not root.is_dir():
        return []

    f = _best_dialogue_file_from_meta(root, film_title)
    if not f:
        f = _best_dialogue_file_by_name(root, film_title)
    if not f or not f.exists():
        return []

    try:
        txt = f.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.debug("Failed to read script file %s: %s", f, e)
        return []

    if _is_parsed_dialogue_file(f):
        return _extract_dialogue_lines(txt, max_lines=max_lines)
    return _extract_screenplay_lines(txt, max_lines=max_lines)


def detect_script_db_ready(script_db_root: str) -> tuple[bool, str]:
    if not script_db_root:
        return False, "SCRIPT_DB_ROOT не задан"
    root = Path(script_db_root)
    if not root.exists() or not root.is_dir():
        return False, "SCRIPT_DB_ROOT не существует"
    if any(d.exists() for d in _candidate_parsed_dirs(root)):
        return True, "ok (parsed/dialogue)"
    if any(d.exists() for d in _candidate_unprocessed_dirs(root)):
        return True, "ok (unprocessed/imsdb)"
    return False, "не найдены scripts/parsed/dialogue и scripts/unprocessed/imsdb"
