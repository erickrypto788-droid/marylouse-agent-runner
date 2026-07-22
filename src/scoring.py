from __future__ import annotations

from typing import Any, Dict

from .models import Product


def _norm(value: float | None, max_value: float) -> float:
    if value is None or value <= 0:
        return 0.0

    if max_value <= 0:
        return 0.0

    return min(float(value) / float(max_value), 1.0)


def _marketplace_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _active_niche_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    active = cfg.get("active_niche") or {}

    if not isinstance(active, dict):
        return {}

    key = active.get("key")

    if not key:
        return {}

    niches_cfg = cfg.get("niches", {}) or {}
    lists = niches_cfg.get("lists", {}) or {}

    if not isinstance(lists, dict):
        return {}

    niche = lists.get(str(key), {})

    return niche if isinstance(niche, dict) else {}


def _niche_applies_to_product(product: Product, niche: Dict[str, Any]) -> bool:
    if not niche:
        return False

    product_marketplace = _marketplace_key(product.marketplace)

    only_marketplaces = niche.get("only_marketplaces") or niche.get("marketplaces_enabled") or []
    only_marketplaces = {
        _marketplace_key(x)
        for x in only_marketplaces
        if str(x).strip()
    }

    if only_marketplaces and product_marketplace not in only_marketplaces:
        return False

    niche_marketplaces = niche.get("marketplaces") or {}

    if isinstance(niche_marketplaces, dict) and niche_marketplaces:
        allowed_by_keywords = {
            _marketplace_key(name)
            for name, keywords in niche_marketplaces.items()
            if keywords
        }

        if allowed_by_keywords and product_marketplace not in allowed_by_keywords:
            return False

    elif not niche.get("keywords"):
        return False

    return True


def _effective_filters(product: Product, cfg: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    filters = dict(cfg.get("filters", {}) or {})

    marketplace_filters = filters.get("marketplace_filters", {}) or {}

    if isinstance(marketplace_filters, dict):
        mfilters = marketplace_filters.get(product.marketplace, {}) or {}

        if isinstance(mfilters, dict):
            filters.update(mfilters)

    niche = _active_niche_cfg(cfg)

    if niche and _niche_applies_to_product(product, niche):
        for key in [
            "min_price",
            "max_price",
            "min_discount_percent",
            "min_rating",
            "require_image",
        ]:
            if key in niche:
                filters[key] = niche[key]

        return filters, niche

    return filters, {}


def _contains_any(text: str, terms: list[str]) -> bool:
    normalized = text.lower()

    return any(str(term).strip().lower() in normalized for term in terms if str(term).strip())


def score_product(product: Product, cfg: Dict[str, Any]) -> float:
    weights = cfg.get("scoring", {}) or {}
    filters, niche = _effective_filters(product, cfg)

    discount_component = _norm(product.discount_percent, 60)
    commission_component = _norm((product.commission_rate or 0) * 100, 20)
    sales_component = _norm(product.sales_count, 3000)
    rating_component = _norm(product.rating, 5)

    shipping_text = (product.shipping_text or "").lower()

    shipping_component = 1.0 if any(
        x in shipping_text
        for x in ["grátis", "gratis", "free", "rápida", "rapida"]
    ) else 0.0

    novelty_component = 1.0

    score = (
        discount_component * float(weights.get("discount_weight", 0.35))
        + commission_component * float(weights.get("commission_weight", 0.25))
        + sales_component * float(weights.get("sales_weight", 0.18))
        + rating_component * float(weights.get("rating_weight", 0.12))
        + shipping_component * float(weights.get("shipping_weight", 0.07))
        + novelty_component * float(weights.get("novelty_weight", 0.03))
    )

    # Boost opcional para nichos onde queremos produtos de ticket maior:
    # smartphones, consoles, monitores, notebooks etc.
    if niche and niche.get("prefer_high_ticket", False):
        price = product.price or 0

        try:
            min_price = float(filters.get("min_price", 0))
        except Exception:
            min_price = 0.0

        try:
            reference_price = float(
                niche.get("ticket_score_reference")
                or filters.get("max_price")
                or 5000
            )
        except Exception:
            reference_price = 5000.0

        price_component = _norm(
            max(float(price) - min_price, 0.0),
            max(reference_price - min_price, 1.0),
        )

        score += price_component * float(weights.get("high_ticket_weight", 0.12))

        premium_terms = niche.get("premium_terms") or []

        if isinstance(premium_terms, list) and _contains_any(product.title or "", premium_terms):
            score += float(weights.get("premium_keyword_boost", 0.08))

    return round(score * 100, 2)


def passes_filters(product: Product, cfg: Dict[str, Any]) -> tuple[bool, str]:
    filters, niche = _effective_filters(product, cfg)

    allowed = set(filters.get("allowed_marketplaces", []))

    if allowed and product.marketplace not in allowed:
        return False, f"marketplace {product.marketplace} não permitido"

    title_text = (product.title or "").lower()

    title_blacklist = []

    global_blacklist = filters.get("title_blacklist", []) or []
    if isinstance(global_blacklist, list):
        title_blacklist.extend(global_blacklist)

    marketplace_blacklists = filters.get("marketplace_title_blacklist", {}) or {}
    if isinstance(marketplace_blacklists, dict):
        marketplace_terms = marketplace_blacklists.get(product.marketplace, []) or []
        if isinstance(marketplace_terms, list):
            title_blacklist.extend(marketplace_terms)

    for term in title_blacklist:
        term_text = str(term or "").strip().lower()
        if term_text and term_text in title_text:
            return False, f"termo bloqueado no título ({term_text})"

    if filters.get("require_image", True) and not product.image_url:
        return False, "sem imagem"

    if product.price is None:
        return False, "sem preço"

    min_price = float(filters.get("min_price", 0))
    max_price = float(filters.get("max_price", 10**9))

    if product.price < min_price:
        reason = f"preço abaixo do mínimo ({product.price})"

        if niche.get("name"):
            reason += f" para nicho {niche.get('name')}"

        return False, reason

    if product.price > max_price:
        reason = f"preço acima do máximo ({product.price})"

        if niche.get("name"):
            reason += f" para nicho {niche.get('name')}"

        return False, reason

    min_discount = float(filters.get("min_discount_percent", 0))

    # Se não houver preço antigo, não reprova automaticamente;
    # apenas não ganha score de desconto.
    if product.old_price is not None and (product.discount_percent or 0) < min_discount:
        return False, f"desconto abaixo do mínimo ({product.discount_percent}%)"

    min_rating = filters.get("min_rating")

    if min_rating is not None and product.rating is not None:
        if float(product.rating) < float(min_rating):
            return False, f"avaliação abaixo do mínimo ({product.rating})"

    if not product.url:
        return False, "sem URL"

    return True, "ok"
