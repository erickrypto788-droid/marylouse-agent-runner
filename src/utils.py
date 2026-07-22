from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable, Optional
from urllib.parse import quote_plus


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value) if isinstance(value, float) else False:
            return None
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Normaliza valores como R$ 1.234,56 ou 1,234.56
    s = re.sub(r"[^0-9,.-]", "", s)
    if "," in s and "." in s:
        # Assume formato brasileiro se a última vírgula vier após o último ponto.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def to_int(value: Any) -> Optional[int]:
    f = to_float(value)
    return int(f) if f is not None else None


def clamp(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def first_present(*values: Any) -> Any:
    for v in values:
        if v is not None and v != "":
            return v
    return None


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def safe_quote(value: str) -> str:
    return quote_plus(value or "")


def normalize_rate(value: Any) -> Optional[float]:
    """Converte taxas: 0.08, '8%', '0.0800', '8.0' -> 0.08 quando fizer sentido."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and "%" in value:
        f = to_float(value)
        return f / 100 if f is not None else None
    f = to_float(value)
    if f is None:
        return None
    if f > 1:
        return f / 100
    return f


def find_first_key_recursive(obj: Any, candidate_keys: Iterable[str]) -> Any:
    keys = set(candidate_keys)
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                return v
        for v in obj.values():
            found = find_first_key_recursive(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_key_recursive(item, keys)
            if found is not None:
                return found
    return None
