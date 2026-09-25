from __future__ import annotations

import re
import unicodedata


TEXT_NORMALIZER_VERSION = "text-norm/v2"

# Letters that NFKD does not decompose into an ASCII base plus combining marks.
# Without this map they are silently dropped: "đuôi" became "uoi".
_TRANSLITERATE = str.maketrans(
    {
        "đ": "d",
        "ð": "d",
        "ł": "l",
        "ø": "o",
        "ħ": "h",
        "ı": "i",
        "ŧ": "t",
        "æ": "ae",
        "œ": "oe",
        "þ": "th",
    }
)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    """Retrieval normalizer (`text-norm/v2`).

    Case-folds, transliterates letters NFKD cannot decompose, strips
    combining marks and keeps ``[a-z0-9_]`` word runs.
    """

    folded = _fold(value.casefold().translate(_TRANSLITERATE))
    return " ".join(re.findall(r"[a-z0-9_]+", folded))


def normalize_identity_v1(value: str) -> str:
    """Frozen normalizer used by ``evidence-v2`` identity segments.

    Evidence identity must stay deterministic across releases, so it keeps
    the original behavior, including dropping undecomposable letters. Do not
    change this function; introduce a new evidence identity version instead.
    """

    return " ".join(re.findall(r"[a-z0-9_]+", _fold(value.casefold())))


def tokens(value: str) -> list[str]:
    return [part for part in normalize_text(value).split() if len(part) > 1]
