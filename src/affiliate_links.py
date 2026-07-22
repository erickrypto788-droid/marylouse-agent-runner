from __future__ import annotations

import hashlib
from typing import Any, Dict
from urllib.parse import quote_plus, urlencode, urlparse, parse_qsl, urlunparse

from .models import Product


def make_subid(product: Product, cfg: Dict[str, Any]) -> str:
    tracking = cfg.get("tracking", {})
    prefix = tracking.get("sub_id_prefix", "tg")
    raw = f"{product.marketplace}:{product.id}:{product.title}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:10]
    return f"{prefix}_{product.marketplace}_{digest}"


def append_query(url: str, params: Dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v is not None and v != ""})
    return urlunparse(parsed._replace(query=urlencode(query)))


def build_affiliate_link(product: Product, cfg: Dict[str, Any]) -> str:
    tracking = cfg.get("tracking", {})
    templates = tracking.get("affiliate_templates", {}) or {}
    template = templates.get(product.marketplace)
    subid = make_subid(product, cfg)

    if template:
        return template.format(
            url=product.url,
            encoded_url=quote_plus(product.url),
            product_id=product.id,
            marketplace=product.marketplace,
            subid=subid,
            title=product.title,
            encoded_title=quote_plus(product.title),
        )

    # Fallback conservador: preserva o link original.
    return product.url
