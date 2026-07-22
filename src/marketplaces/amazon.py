from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
from typing import Any, Dict, List

import requests

from .base import Marketplace
from ..models import Product
from ..utils import to_float


class AmazonMarketplace(Marketplace):
    name = "amazon"

    def _sign(self, method: str, host: str, region: str, target: str, payload: str) -> Dict[str, str]:
        access_key = os.getenv("AMAZON_ACCESS_KEY", "")
        secret_key = os.getenv("AMAZON_SECRET_KEY", "")
        if not access_key or not secret_key:
            raise RuntimeError("AMAZON_ACCESS_KEY e AMAZON_SECRET_KEY não configurados")

        service = "ProductAdvertisingAPI"
        now = dt.datetime.utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        canonical_uri = "/paapi5/searchitems"
        canonical_querystring = ""
        headers = {
            "content-encoding": "amz-1.0",
            "content-type": "application/json; charset=utf-8",
            "host": host,
            "x-amz-date": amz_date,
            "x-amz-target": target,
        }
        signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
        canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in signed_headers.split(";"))
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = "\n".join(
            [method, canonical_uri, canonical_querystring, canonical_headers, signed_headers, payload_hash]
        )

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = "\n".join(
            [algorithm, amz_date, credential_scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()]
        )

        def sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
        k_region = sign(k_date, region)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"{algorithm} Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers["Authorization"] = authorization
        return headers

    def fetch(self) -> List[Product]:
        mcfg = self.cfg.get("marketplaces", {}).get(self.name, {})
        if not mcfg.get("enabled", False):
            return []
        if not os.getenv("AMAZON_ACCESS_KEY") or not os.getenv("AMAZON_SECRET_KEY") or not os.getenv("AMAZON_PARTNER_TAG"):
            print("[amazon] Desabilitado: configure AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY e AMAZON_PARTNER_TAG.")
            return []

        host = os.getenv("AMAZON_HOST", "webservices.amazon.com.br")
        region = os.getenv("AMAZON_REGION", "us-east-1")
        marketplace = os.getenv("AMAZON_MARKETPLACE", "www.amazon.com.br")
        partner_tag = os.getenv("AMAZON_PARTNER_TAG", "")
        item_count = int(mcfg.get("item_count", 10))
        search_index = mcfg.get("search_index", "All")
        target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
        products: List[Product] = []
        seen: set[str] = set()

        for keyword in mcfg.get("keywords", []) or []:
            body = {
                "Keywords": keyword,
                "SearchIndex": search_index,
                "ItemCount": item_count,
                "PartnerTag": partner_tag,
                "PartnerType": "Associates",
                "Marketplace": marketplace,
                "Resources": [
                    "Images.Primary.Large",
                    "ItemInfo.Title",
                    "Offers.Listings.Price",
                    "Offers.Listings.SavingBasis",
                    "Offers.Listings.Availability.Message",
                    "Offers.Listings.DeliveryInfo.IsFreeShippingEligible",
                    "CustomerReviews.Count",
                    "CustomerReviews.StarRating",
                ],
            }
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            try:
                headers = self._sign("POST", host, region, target, payload)
                resp = requests.post(f"https://{host}/paapi5/searchitems", data=payload.encode("utf-8"), headers=headers, timeout=45)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"[amazon] Erro buscando '{keyword}': {exc}")
                continue

            items = ((data.get("SearchResult") or {}).get("Items") or [])
            for item in items:
                asin = str(item.get("ASIN") or "")
                if not asin or asin in seen:
                    continue
                seen.add(asin)
                title = (((item.get("ItemInfo") or {}).get("Title") or {}).get("DisplayValue") or "").strip()
                image = ((((item.get("Images") or {}).get("Primary") or {}).get("Large") or {}).get("URL"))
                listings = ((item.get("Offers") or {}).get("Listings") or [])
                listing = listings[0] if listings else {}
                price_obj = listing.get("Price") or {}
                saving_basis = listing.get("SavingBasis") or {}
                price = to_float(price_obj.get("Amount"))
                old_price = to_float(saving_basis.get("Amount"))
                availability = ((listing.get("Availability") or {}).get("Message"))
                delivery = listing.get("DeliveryInfo") or {}
                shipping_text = availability
                if delivery.get("IsFreeShippingEligible"):
                    shipping_text = "Frete grátis"
                reviews = item.get("CustomerReviews") or {}
                rating = to_float(reviews.get("StarRating"))
                products.append(
                    Product(
                        marketplace=self.name,
                        id=asin,
                        title=title,
                        price=price,
                        old_price=old_price,
                        currency=str(price_obj.get("Currency") or "BRL"),
                        url=str(item.get("DetailPageURL") or ""),
                        image_url=image,
                        rating=rating,
                        sales_count=None,
                        commission_rate=None,
                        shipping_text=shipping_text,
                        category=search_index,
                        raw=item,
                    )
                )
        return products
