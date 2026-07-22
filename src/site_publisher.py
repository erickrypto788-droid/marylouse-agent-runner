from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_FILE = ROOT / "site" / "data" / "offers.json"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(key, default)

    return getattr(obj, key, default)


def _first_value(obj: Any, keys: List[str], default: Any = None) -> Any:
    for key in keys:
        value = _get(obj, key, None)

        if value not in (None, "", [], {}):
            return value

    return default


def _clean_text(value: Any, max_len: int = 260) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\\n", "\n")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."

    return text


def _format_price(value: Any) -> str:
    if value in (None, ""):
        return ""

    if isinstance(value, str):
        text = value.strip()

        if not text:
            return ""

        if text.startswith("R$"):
            return text

        cleaned = (
            text.replace("R$", "")
            .replace("BRL", "")
            .replace("US$", "")
            .replace("$", "")
            .strip()
        )

        cleaned = re.sub(r"[^\d,.\-]", "", cleaned)

        if not cleaned:
            return text

        try:
            if "," in cleaned and "." in cleaned:
                # Ex: 1.234,56
                if cleaned.rfind(",") > cleaned.rfind("."):
                    number = float(cleaned.replace(".", "").replace(",", "."))
                # Ex: 1,234.56
                else:
                    number = float(cleaned.replace(",", ""))
            elif "," in cleaned:
                number = float(cleaned.replace(",", "."))
            else:
                number = float(cleaned)
        except Exception:
            return text
    else:
        try:
            number = float(value)
        except Exception:
            return str(value)

    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _first_url(value: Any) -> str:
    if not value:
        return ""

    if isinstance(value, dict):
        for key in [
            "promotion_link",
            "promotionUrl",
            "promotion_url",
            "source_value",
            "sourceValue",
            "url",
            "product_detail_url",
            "product_url",
            "affiliate_url",
            "affiliate_link",
            "image",
            "image_url",
            "thumbnail",
            "thumbnail_url",
            "picture",
            "picture_url",
        ]:
            found = _first_url(value.get(key))

            if found:
                return found

        return ""

    if isinstance(value, (list, tuple)):
        for item in value:
            found = _first_url(item)

            if found:
                return found

        return ""

    text = str(value).strip()
    match = re.search(r"https?://\S+", text)

    if not match:
        return ""

    link = match.group(0).strip()
    link = link.strip("'\"[]{}(),")
    return link


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _marketplace_label(value: Any) -> str:
    raw = str(value or "Oferta").strip()
    key = raw.lower().replace(" ", "").replace("-", "").replace("_", "")

    labels = {
        "aliexpress": "AliExpress",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "mercadolivre": "Mercado Livre",
        "ml": "Mercado Livre",
    }

    return labels.get(key, raw.capitalize())


def _parse_created_ts(offer: Dict[str, Any]) -> int | None:
    created_ts = offer.get("created_ts")

    if isinstance(created_ts, (int, float)):
        return int(created_ts)

    if isinstance(created_ts, str) and created_ts.strip().isdigit():
        return int(created_ts.strip())

    created_at_iso = offer.get("created_at_iso")

    if created_at_iso:
        try:
            return int(datetime.fromisoformat(str(created_at_iso)).timestamp())
        except Exception:
            pass

    created_at = offer.get("created_at")

    if created_at:
        text = str(created_at).strip()

        for fmt in [
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                return int(datetime.strptime(text, fmt).timestamp())
            except Exception:
                continue

    return None


def _normalize_existing_offer(offer: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(offer, dict):
        return {}

    normalized = dict(offer)

    ts = _parse_created_ts(normalized)

    if ts is not None:
        normalized["created_ts"] = ts

        if not normalized.get("created_at_iso"):
            try:
                normalized["created_at_iso"] = datetime.fromtimestamp(ts).isoformat(timespec="seconds")
            except Exception:
                pass

    if normalized.get("marketplace"):
        normalized["marketplace"] = _marketplace_label(normalized.get("marketplace"))

    return normalized


def _filter_recent_offers(offers: List[Dict[str, Any]], keep_hours: float) -> List[Dict[str, Any]]:
    if keep_hours <= 0:
        return offers

    cutoff = int(time.time() - (keep_hours * 3600))
    recent: List[Dict[str, Any]] = []

    for offer in offers:
        ts = _parse_created_ts(offer)

        # Se não conseguir identificar a data, mantém para não apagar oferta por engano.
        if ts is None or ts >= cutoff:
            recent.append(offer)

    return recent


def _sort_offers(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        offers,
        key=lambda offer: _parse_created_ts(offer) or 0,
        reverse=True,
    )


def _load_offers() -> List[Dict[str, Any]]:
    SITE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not SITE_DATA_FILE.exists():
        return []

    try:
        with SITE_DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return []

        offers = []

        for item in data:
            if isinstance(item, dict):
                normalized = _normalize_existing_offer(item)

                if normalized:
                    offers.append(normalized)

        return offers
    except Exception:
        return []


def _save_offers(offers: List[Dict[str, Any]]) -> None:
    SITE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    tmp_file = SITE_DATA_FILE.with_suffix(".json.tmp")

    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(offers, f, ensure_ascii=False, indent=2)

    tmp_file.replace(SITE_DATA_FILE)


def _make_offer_id(product: Any, affiliate_url: str, raw_title: str, marketplace: str) -> str:
    product_id = _first_value(
        product,
        ["id", "product_id", "item_id", "itemId", "productId"],
        "",
    )

    raw = f"{marketplace}|{product_id}|{affiliate_url}|{raw_title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]


def _copy_value(offer_copy: Any, keys: List[str], default: Any = None) -> Any:
    for key in keys:
        value = _get(offer_copy, key, None)

        if value not in (None, "", [], {}):
            return value

    return default


def _is_noise_line(line: str) -> bool:
    text = line.strip()
    lowered = text.lower()

    if not text:
        return True

    if lowered.startswith("http"):
        return True

    if "comprar agora" in lowered:
        return True

    if "comprar com desconto" in lowered:
        return True

    if "pegar oferta" in lowered:
        return True

    if lowered.startswith("#"):
        return True

    if lowered.startswith("💸"):
        return True

    if lowered.startswith("⭐"):
        return True

    if lowered.startswith("🛒"):
        return True

    if lowered.startswith("de:"):
        return True

    if lowered.startswith("por:"):
        return True

    if lowered.startswith("🔥 por"):
        return True

    return False


def _clean_card_text(value: Any, max_len: int) -> str:
    text = _clean_text(value, max_len * 2)

    # Remove hashtags no final ou no meio da frase.
    text = re.sub(r"#[\wÀ-ÿ_]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."

    return text


def _site_title(product: Any, offer_copy: Any = None) -> str:
    # 1) Melhor opção: título curto criado pela IA.
    copy_title = _copy_value(
        offer_copy,
        ["title_short", "short_title", "title", "headline"],
        "",
    )

    if copy_title:
        title = _clean_card_text(copy_title, 78)

        # Evita títulos genéricos demais.
        lowered = title.lower()
        generic_titles = {
            "oferta encontrada",
            "produto selecionado",
            "oferta especial",
            "promoção encontrada",
        }

        if title and lowered not in generic_titles:
            return title

    # 2) Fallback: título original do produto, só que mais curto.
    raw_title = _get(product, "title", "Oferta encontrada")
    return _clean_card_text(raw_title, 82)


def _site_description(product: Any, offer_copy: Any = None, title: str = "") -> str:
    # 1) Tenta aproveitar a legenda gerada para o Telegram.
    caption = _copy_value(offer_copy, ["caption", "description", "text"], "")

    if caption:
        caption = str(caption).replace("\\n", "\n")
        parts = []

        for line in caption.splitlines():
            line = line.strip()

            if _is_noise_line(line):
                continue

            # Evita repetir exatamente o título.
            if title and _clean_text(line, 200).lower() == _clean_text(title, 200).lower():
                continue

            parts.append(line)

        if parts:
            description = " ".join(parts[:3])
            description = _clean_card_text(description, 155)

            if description:
                return description

    # 2) Tenta usar hook da IA.
    hook = _copy_value(offer_copy, ["hook", "subtitle"], "")

    if hook:
        description = _clean_card_text(hook, 155)

        if description:
            return description

    # 3) Fallback seguro.
    raw_title = _get(product, "title", "produto selecionado")
    return _clean_card_text(f"Oferta selecionada automaticamente: {raw_title}", 155)


def product_to_site_offer(product: Any, offer_copy: Any = None) -> Dict[str, Any]:
    raw_title = _clean_card_text(_get(product, "title", "Oferta encontrada"), 160)

    title = _site_title(product, offer_copy)

    marketplace = _marketplace_label(
        _first_value(product, ["marketplace", "source"], "Oferta")
    )

    category = _clean_card_text(
        _first_value(product, ["category", "niche", "category_name"], "Oferta"),
        60,
    )

    price_value = _first_value(
        product,
        ["price", "sale_price", "current_price", "price_current"],
        "",
    )

    old_price_value = _first_value(
        product,
        ["old_price", "original_price", "price_before_discount", "list_price", "regular_price"],
        "",
    )

    discount_value = _first_value(
        product,
        ["discount_percent", "discount", "discount_percentage"],
        None,
    )

    try:
        discount_percent = round(float(discount_value), 0) if discount_value is not None else None
    except Exception:
        discount_percent = None

    rating_value = _first_value(
        product,
        ["rating", "review_rating", "evaluate_rate", "score_rating"],
        None,
    )

    try:
        rating = round(float(rating_value), 1) if rating_value is not None else None
    except Exception:
        rating = None

    image = _first_url(
        _first_value(
            product,
            [
                "image",
                "image_url",
                "thumbnail",
                "thumbnail_url",
                "picture",
                "picture_url",
                "images",
                "image_urls",
            ],
            "",
        )
    )

    affiliate_url = _first_url(
        _first_value(
            product,
            ["affiliate_url", "affiliate_link", "url", "product_url", "link"],
            "",
        )
    )

    description = _site_description(product, offer_copy, title)

    offer_id = _make_offer_id(product, affiliate_url, raw_title, marketplace)

    now = datetime.now()
    now_ts = int(time.time())

    return {
        "id": offer_id,
        "title": title,
        "raw_title": raw_title,
        "description": description,
        "marketplace": marketplace,
        "category": category,
        "old_price": _format_price(old_price_value),
        "price": _format_price(price_value),
        "discount_percent": discount_percent,
        "rating": rating,
        "image": image,
        "affiliate_url": affiliate_url,
        "created_at": now.strftime("%d/%m/%Y %H:%M"),
        "created_at_iso": now.isoformat(timespec="seconds"),
        "created_ts": now_ts,
    }




def _normalize_marketplace_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _apply_active_niche_category(offer: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(offer, dict):
        return offer

    if not isinstance(cfg, dict):
        return offer

    site_cfg = cfg.get("site", {}) or {}

    # Por padrão, usa o nicho ativo como categoria do site,
    # mas somente quando o nicho realmente se aplica ao marketplace do produto.
    if site_cfg.get("prefer_active_niche_as_category", True) is False:
        return offer

    active_niche = cfg.get("active_niche") or {}

    if not isinstance(active_niche, dict):
        return offer

    niche_key = active_niche.get("key")
    niche_name = active_niche.get("name") or niche_key

    if not niche_key or not niche_name:
        return offer

    niches_cfg = cfg.get("niches", {}) or {}
    lists = niches_cfg.get("lists", {}) or {}
    niche_cfg = lists.get(str(niche_key), {}) if isinstance(lists, dict) else {}

    if not isinstance(niche_cfg, dict):
        return offer

    product_marketplace = _normalize_marketplace_key(offer.get("marketplace"))

    only_marketplaces = niche_cfg.get("only_marketplaces") or niche_cfg.get("marketplaces_enabled") or []
    only_marketplaces = {
        _normalize_marketplace_key(x)
        for x in only_marketplaces
        if str(x).strip()
    }

    if only_marketplaces and product_marketplace not in only_marketplaces:
        return offer

    niche_marketplaces = niche_cfg.get("marketplaces") or {}

    if isinstance(niche_marketplaces, dict) and niche_marketplaces:
        allowed_by_keywords = {
            _normalize_marketplace_key(name)
            for name, keywords in niche_marketplaces.items()
            if keywords
        }

        if allowed_by_keywords and product_marketplace not in allowed_by_keywords:
            return offer

    elif not niche_cfg.get("keywords"):
        # Se o nicho não tem keywords gerais nem keywords por marketplace,
        # não aplica categoria automaticamente.
        return offer

    try:
        offer["category"] = _clean_card_text(niche_name, 60)
    except Exception:
        offer["category"] = str(niche_name).strip()[:60]

    offer["niche"] = {
        "key": active_niche.get("key"),
        "name": active_niche.get("name") or active_niche.get("key"),
    }

    return offer



def _dedupe_title_key(offer: Dict[str, Any]) -> str:
    marketplace = str(offer.get("marketplace") or "").strip().lower()
    title = str(offer.get("title") or offer.get("raw_title") or "").strip().lower()

    try:
        import unicodedata

        title = unicodedata.normalize("NFD", title)
        title = "".join(ch for ch in title if unicodedata.category(ch) != "Mn")
    except Exception:
        pass

    title = re.sub(r"[^a-z0-9À-ÿ]+", " ", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()

    # 120 caracteres já é suficiente para identificar duplicados visuais
    # sem ficar sensível demais a pequenas variações.
    return f"{marketplace}|{title[:120]}"

def _dedupe_offers(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_ids = set()
    seen_urls = set()
    seen_titles = set()
    clean: List[Dict[str, Any]] = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        offer_id = str(offer.get("id") or "").strip()
        url = str(offer.get("affiliate_url") or "").strip()
        title_key = _dedupe_title_key(offer)

        if offer_id and offer_id in seen_ids:
            continue

        if url and url in seen_urls:
            continue

        if title_key and title_key in seen_titles:
            continue

        if offer_id:
            seen_ids.add(offer_id)

        if url:
            seen_urls.add(url)

        if title_key:
            seen_titles.add(title_key)

        clean.append(offer)

    return clean


def publish_offer_to_site(
    product: Any,
    offer_copy: Any = None,
    cfg: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    cfg = cfg or {}

    site_cfg = cfg.get("site", {}) if isinstance(cfg, dict) else {}

    if site_cfg.get("enabled") is False:
        return {"published": False, "reason": "site disabled"}

    max_offers = _safe_int(site_cfg.get("max_offers", 200), 200)
    keep_hours = _safe_float(site_cfg.get("keep_hours", 12), 12)

    offer = product_to_site_offer(product, offer_copy)
    offer = _apply_active_niche_category(offer, cfg)

    if not offer.get("affiliate_url"):
        return {
            "published": False,
            "reason": "missing affiliate_url",
            "offer": offer,
        }

    offers = _load_offers()

    # Remove duplicados pelo id ou pelo link de afiliado.
    offers = [
        existing
        for existing in offers
        if existing.get("id") != offer.get("id")
        and existing.get("affiliate_url") != offer.get("affiliate_url")
    ]

    # Oferta mais nova no topo.
    offers.insert(0, offer)

    # Mantém somente ofertas recentes, ex: últimas 12 horas.
    offers = _filter_recent_offers(offers, keep_hours)

    # Ordena por data mais recente.
    offers = _sort_offers(offers)

    # Remove duplicados por id, link e marketplace+título normalizado.
    offers = _dedupe_offers(offers)

    # Limite máximo de segurança.
    offers = offers[:max_offers]

    _save_offers(offers)

    return {
        "published": True,
        "file": str(SITE_DATA_FILE),
        "offer": offer,
        "total": len(offers),
        "keep_hours": keep_hours,
        "max_offers": max_offers,
    }


publish_offer = publish_offer_to_site
