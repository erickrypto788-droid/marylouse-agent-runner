from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import ROOT
from .models import Product


DEFAULT_HISTORY_FILE = "data/telegram_post_history.json"


STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "com", "sem", "e", "ou",
    "a", "o", "as", "os", "em", "no", "na", "nos", "nas", "por",
    "oferta", "promocao", "promoção", "original", "novo", "nova",
    "kit", "unidade", "unidades", "loja", "produto"
}


HIGH_INTENT_TERMS = [
    "fralda", "pampers", "huggies", "mamypoko", "lenço umedecido", "lenco umedecido",
    "papel higienico", "papel higiênico", "sabao em po", "sabão em pó", "detergente",
    "amaciante", "air fryer", "panela", "liquidificador", "cafeteira", "aspirador",
    "smartphone", "celular", "iphone", "xiaomi", "samsung", "notebook", "ssd",
    "monitor gamer", "processador", "ryzen", "rtx", "perfume", "barbeador",
    "secador", "chapinha", "escova secadora", "racao", "ração", "areia higienica",
    "areia higiênica", "monitor de pressao", "monitor de pressão", "termometro",
    "termômetro", "inalador", "nebulizador", "furadeira", "parafusadeira"
]


WEAK_TERMS = [
    "capa", "capinha", "pelicula", "película", "suporte", "adaptador", "cabo",
    "conector", "adesivo", "skin", "refil", "peca", "peça", "reposição", "reposicao",
    "controle remoto", "tampa", "parafuso", "manual", "apostila"
]


def now_ts() -> int:
    return int(time.time())


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokens(value: str) -> set[str]:
    text = normalize_text(value)
    return {
        token
        for token in text.split()
        if len(token) > 2 and token not in STOPWORDS
    }


def similar_titles(a: str, b: str) -> bool:
    ta = tokens(a)
    tb = tokens(b)

    if not ta or not tb:
        return False

    common = ta & tb
    union = ta | tb
    smaller = min(len(ta), len(tb))

    if len(common) >= 6:
        return True

    if smaller >= 4 and len(common) / smaller >= 0.78:
        return True

    if union and len(common) / len(union) >= 0.68:
        return True

    return False


def contains_any(text: str, terms: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(term) in normalized for term in terms)


def history_path(cfg: Dict[str, Any]) -> Path:
    raw = (
        cfg.get("agent", {}).get("telegram_history_file")
        or DEFAULT_HISTORY_FILE
    )

    path = Path(str(raw))

    if not path.is_absolute():
        path = ROOT / path

    return path


def load_history(cfg: Dict[str, Any]) -> Dict[str, Any]:
    path = history_path(cfg)

    if not path.exists():
        return {"posts": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            return {"posts": []}

        if not isinstance(data.get("posts"), list):
            data["posts"] = []

        return data

    except Exception:
        return {"posts": []}


def save_history(cfg: Dict[str, Any], history: Dict[str, Any]) -> None:
    path = history_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def clean_history(cfg: Dict[str, Any], history: Dict[str, Any]) -> Dict[str, Any]:
    keep_days = int(cfg.get("agent", {}).get("telegram_history_keep_days", 30))
    cutoff = now_ts() - keep_days * 86400

    history["posts"] = [
        item for item in history.get("posts", [])
        if int(item.get("posted_ts") or 0) >= cutoff
    ]

    return history


def product_identity(product: Product) -> Dict[str, str]:
    return {
        "key": str(product.key or ""),
        "marketplace": str(product.marketplace or ""),
        "id": str(product.id or ""),
        "title": str(product.title or ""),
        "title_norm": normalize_text(product.title),
        "url": str(product.url or ""),
        "affiliate_url": str(product.affiliate_url or ""),
        "category": str(product.category or ""),
        "bucket": product_bucket(product),
    }


def product_bucket(product: Product) -> str:
    text = normalize_text(" ".join([
        str(product.title or ""),
        str(product.category or ""),
        str(product.marketplace or ""),
    ]))

    buckets = [
        ("fraldas", ["fralda", "pampers", "huggies", "mamypoko", "lenco umedecido"]),
        ("celulares", ["smartphone", "celular", "iphone", "xiaomi", "galaxy", "motorola", "redmi", "poco"]),
        ("informatica", ["notebook", "ssd", "monitor gamer", "ryzen", "rtx", "gtx", "teclado", "mouse"]),
        ("casa_cozinha", ["air fryer", "panela", "liquidificador", "cafeteira", "aspirador"]),
        ("beleza", ["perfume", "barbeador", "secador", "chapinha", "escova secadora", "maquiagem"]),
        ("pet", ["racao", "ração", "cachorro", "gato", "areia higienica", "pet"]),
        ("saude", ["monitor de pressao", "pressão arterial", "termometro", "inalador", "oximetro"]),
        ("moda_feminina", ["vestido", "blusa feminina", "short feminino", "legging", "cropped", "regata feminina"]),
        ("calcados", ["tenis", "tênis", "sapato", "sandalia", "sandália", "chinelo", "bota"]),
        ("bolsas", ["mochila", "bolsa", "mala", "necessaire"]),
        ("supermercado", ["papel higienico", "detergente", "amaciante", "sabonete", "azeite"]),
    ]

    for bucket, terms in buckets:
        if any(normalize_text(term) in text for term in terms):
            return bucket

    category = normalize_text(product.category)

    if category:
        return category.replace(" ", "_")

    return "outros"


def is_recent_duplicate(product: Product, cfg: Dict[str, Any], history: Dict[str, Any]) -> Tuple[bool, str]:
    cooldown_hours = int(cfg.get("agent", {}).get("telegram_duplicate_cooldown_hours", 168))
    cutoff = now_ts() - cooldown_hours * 3600

    current = product_identity(product)

    for item in history.get("posts", []):
        posted_ts = int(item.get("posted_ts") or 0)

        if posted_ts < cutoff:
            continue

        if current["key"] and current["key"] == str(item.get("key") or ""):
            return True, f"mesma key em {cooldown_hours}h"

        if current["url"] and current["url"] == str(item.get("url") or ""):
            return True, f"mesma URL em {cooldown_hours}h"

        if current["affiliate_url"] and current["affiliate_url"] == str(item.get("affiliate_url") or ""):
            return True, f"mesmo link afiliado em {cooldown_hours}h"

        if current["marketplace"] == str(item.get("marketplace") or ""):
            old_title = str(item.get("title") or "")

            if old_title and similar_titles(current["title"], old_title):
                return True, f"título parecido em {cooldown_hours}h"

    return False, ""


def attractiveness_score(product: Product) -> float:
    text = normalize_text(" ".join([
        str(product.title or ""),
        str(product.category or ""),
        str(product.shipping_text or ""),
    ]))

    score = 0.0

    if contains_any(text, HIGH_INTENT_TERMS):
        score += 25

    discount = float(product.discount_percent or 0)

    if discount >= 60:
        score += 25
    elif discount >= 40:
        score += 18
    elif discount >= 20:
        score += 10

    price = float(product.price or 0)

    if 20 <= price <= 300:
        score += 12
    elif 300 < price <= 1500:
        score += 10
    elif 1500 < price <= 6000:
        score += 7

    if contains_any(text, WEAK_TERMS):
        score -= 25

    if product.rating and float(product.rating or 0) >= 4.6:
        score += 6

    if product.shipping_text and contains_any(product.shipping_text, ["gratis", "grátis", "free"]):
        score += 5

    return score


def filter_telegram_candidates(candidates: List[Product], cfg: Dict[str, Any]) -> List[Product]:
    history = clean_history(cfg, load_history(cfg))

    max_per_bucket = int(cfg.get("agent", {}).get("telegram_max_candidates_per_bucket", 2))
    min_quality = float(cfg.get("agent", {}).get("telegram_min_quality_score", -10))

    scored: list[Product] = []

    for product in candidates:
        duplicated, reason = is_recent_duplicate(product, cfg, history)

        if duplicated:
            print(f"[telegram-quality] Reprovado repetido: {product.key} - {reason}")
            continue

        qscore = attractiveness_score(product)

        if qscore < min_quality:
            print(f"[telegram-quality] Reprovado baixa atratividade: {product.key} | qscore={qscore:.1f}")
            continue

        product.score = round(float(product.score or 0) + qscore, 2)
        scored.append(product)

    scored.sort(key=lambda p: float(p.score or 0), reverse=True)

    bucket_counts: dict[tuple[str, str], int] = {}
    final: list[Product] = []

    for product in scored:
        bucket = product_bucket(product)
        key = (str(product.marketplace), bucket)

        if bucket_counts.get(key, 0) >= max_per_bucket:
            print(f"[telegram-quality] Ignorado por variedade: {product.key} | bucket={bucket}")
            continue

        bucket_counts[key] = bucket_counts.get(key, 0) + 1
        final.append(product)

    print(f"[telegram-quality] candidatos após curadoria: {len(final)}")

    return final


def mark_telegram_posted(product: Product, cfg: Dict[str, Any]) -> None:
    history = clean_history(cfg, load_history(cfg))

    ident = product_identity(product)
    ident["posted_ts"] = now_ts()
    ident["posted_at"] = datetime.now(timezone.utc).isoformat()
    ident["score"] = product.score

    history.setdefault("posts", []).insert(0, ident)
    history["posts"] = history["posts"][:1000]
    history["updated_at"] = datetime.now(timezone.utc).isoformat()

    save_history(cfg, history)

    print(f"[telegram-quality] histórico atualizado: {product.key}")
