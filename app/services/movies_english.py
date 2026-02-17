from __future__ import annotations

import json
import re
from collections import Counter
from typing import Optional


FALLBACK_WORD_BANK: list[dict] = [
    {"word": "ominous", "translation": "зловещий", "example": "The soundtrack feels ominous."},
    {"word": "intricate", "translation": "замысловатый", "example": "The plot is intricate."},
    {"word": "redemption", "translation": "искупление", "example": "The story explores redemption."},
    {"word": "ambiguity", "translation": "неоднозначность", "example": "The ending leaves ambiguity."},
    {"word": "haunting", "translation": "преследующий, навязчивый", "example": "It has a haunting atmosphere."},
    {"word": "resilient", "translation": "стойкий, выносливый", "example": "She remains resilient under pressure."},
    {"word": "vulnerable", "translation": "уязвимый", "example": "He feels vulnerable in that moment."},
    {"word": "relentless", "translation": "неумолимый", "example": "The pace is relentless from start to finish."},
    {"word": "uncertain", "translation": "неопределенный", "example": "Their future is uncertain."},
    {"word": "deception", "translation": "обман", "example": "The conflict is built on deception."},
    {"word": "sacrifice", "translation": "жертва, жертвовать", "example": "The hero makes a sacrifice."},
    {"word": "confrontation", "translation": "конфронтация, столкновение", "example": "A confrontation changes everything."},
]

FALLBACK_TRANSLATIONS: dict[str, str] = {x["word"]: x["translation"] for x in FALLBACK_WORD_BANK}
FALLBACK_TRANSLATIONS.update(
    {
        "ominously": "зловеще",
        "intricacy": "сложность, запутанность",
        "redeem": "искупать",
        "redemptive": "искупительный",
        "ambiguous": "неоднозначный",
        "vulnerability": "уязвимость",
        "relentlessly": "неумолимо",
        "uncertainty": "неопределенность",
        "deceptive": "обманчивый",
        "sacrificed": "пожертвовал",
        "confront": "сталкиваться, противостоять",
        "confronted": "столкнулся",
        "consequence": "последствие",
        "consequences": "последствия",
        "collapse": "крах, обрушение",
        "catastrophe": "катастрофа",
        "catastrophic": "катастрофический",
        "desperation": "отчаяние",
        "desperate": "отчаянный",
        "obsession": "одержимость",
        "obsessed": "одержимый",
        "betrayal": "предательство",
        "betrayed": "предал",
        "forgiveness": "прощение",
        "haunted": "преследуемый (мыслями)",
        "isolation": "изоляция",
        "isolated": "изолированный",
        "conscience": "совесть",
        "fragments": "фрагменты",
        "fragmented": "раздробленный",
        "fate": "судьба",
        "destiny": "предназначение",
        "survival": "выживание",
        "survivor": "выживший",
        "trauma": "травма",
        "traumatic": "травматичный",
        "mysterious": "таинственный",
        "mystery": "тайна",
        "inevitable": "неизбежный",
        "intensity": "интенсивность",
        "identity": "личность",
        "illusion": "иллюзия",
        "legacy": "наследие",
        "moral": "моральный, нравственный",
        "ethical": "этический",
        "tension": "напряжение",
        "turbulent": "бурный, неспокойный",
        "hostile": "враждебный",
        "conspiracy": "заговор",
        "anxiety": "тревога",
        "disturbing": "тревожный, disturbing",
        "devastating": "разрушительный",
        "wilderness": "дикая местность",
        "hostility": "враждебность",
        "integrity": "честность, целостность",
        "compassion": "сострадание",
        "conflicted": "внутренне противоречивый",
        "reckless": "безрассудный",
        "ruthless": "безжалостный",
        "brutality": "жестокость",
        "enigma": "загадка",
    }
)

COMMON_ENGLISH_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "almost",
    "always",
    "another",
    "around",
    "because",
    "before",
    "being",
    "between",
    "could",
    "didnt",
    "doesnt",
    "dont",
    "every",
    "first",
    "found",
    "going",
    "great",
    "heard",
    "himself",
    "inside",
    "into",
    "itself",
    "maybe",
    "might",
    "never",
    "nothing",
    "other",
    "out",
    "really",
    "right",
    "should",
    "something",
    "still",
    "their",
    "there",
    "these",
    "thing",
    "think",
    "those",
    "through",
    "together",
    "under",
    "until",
    "where",
    "which",
    "would",
    "youre",
    "your",
    "just",
    "have",
    "has",
    "had",
    "with",
    "what",
    "when",
    "they",
    "them",
    "then",
    "this",
    "that",
    "from",
    "were",
    "been",
    "will",
    "cant",
    "wont",
}

ADVANCED_SUFFIXES = (
    "tion",
    "sion",
    "ment",
    "ness",
    "ance",
    "ence",
    "ity",
    "ism",
    "ship",
    "ous",
    "ive",
    "able",
    "ible",
    "ial",
    "ary",
    "ory",
    "istic",
    "ical",
    "ward",
)


def normalize_word_token(word: str) -> str:
    return re.sub(r"[^a-z]", "", (word or "").lower())


def word_lookup_variants(word: str) -> list[str]:
    w = normalize_word_token(word)
    if not w:
        return []
    variants = [w]
    for suffix in ("ies", "es", "s", "ed", "ing", "ly"):
        if w.endswith(suffix) and len(w) > len(suffix) + 3:
            if suffix == "ies":
                variants.append(w[:-3] + "y")
            else:
                variants.append(w[: -len(suffix)])
    dedup: list[str] = []
    for v in variants:
        if v and v not in dedup:
            dedup.append(v)
    return dedup


def fallback_translation(word: str) -> Optional[str]:
    for v in word_lookup_variants(word):
        t = FALLBACK_TRANSLATIONS.get(v)
        if t:
            return t
    return None


def extract_fallback_words_from_dialogues(film_title: str, dialogues: list[str], need: int = 12) -> list[dict]:
    scored: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for line in dialogues:
        line_clean = re.sub(r"\s+", " ", (line or "").strip())
        if not line_clean:
            continue
        tokens = re.findall(r"[A-Za-z][A-Za-z'-]{4,}", line_clean)
        for token in tokens:
            word = normalize_word_token(token)
            if len(word) < 5 or word in COMMON_ENGLISH_STOPWORDS:
                continue
            score = 1
            if len(word) >= 8:
                score += 2
            if len(word) >= 10:
                score += 2
            if any(word.endswith(suf) for suf in ADVANCED_SUFFIXES):
                score += 2
            scored[word] += score
            if word not in examples:
                examples[word] = line_clean[:180]

    ranked = sorted(scored.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    out: list[dict] = []
    used: set[str] = set()
    for word, _ in ranked:
        if word in used:
            continue
        tr = fallback_translation(word)
        if not tr:
            continue
        out.append(
            {
                "word": word,
                "translation": tr,
                "example": examples.get(word) or f"In the film {film_title}, this word appears in dialogue.",
            }
        )
        used.add(word)
        if len(out) >= need:
            return out

    for item in FALLBACK_WORD_BANK:
        w = item["word"]
        if w in used:
            continue
        out.append(item)
        used.add(w)
        if len(out) >= need:
            break
    return out


def parse_json_array_maybe(text: str) -> list[dict]:
    raw = (text or "").strip()
    if not raw:
        return []
    raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        arr = json.loads(raw)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out: list[dict] = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        w = str(it.get("word", "")).strip().lower()
        t = str(it.get("translation", "")).strip()
        ex = str(it.get("example", "")).strip()
        if w and t:
            out.append({"word": w, "translation": t, "example": ex})
    return out


def normalize_translation_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-zа-я0-9\\s-]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\\s+", " ", s)
    return s
