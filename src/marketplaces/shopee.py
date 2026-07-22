from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List

import requests

from .base import Marketplace
from ..models import Product
from ..utils import normalize_rate, to_float, to_int


class ShopeeMarketplace(Marketplace):
    name = "shopee"

    def _headers(self, payload: str) -> Dict[str, str]:
        app_id = os.getenv("SHOPEE_APP_ID", "")
        secret = os.getenv("SHOPEE_SECRET", "")
        if not app_id or not secret:
            raise RuntimeError("SHOPEE_APP_ID e SHOPEE_SECRET não configurados")
        timestamp = str(int(time.time()))
        signature = hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")).hexdigest()
        return {
            "Content-Type": "application/json",
            "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}",
        }

    def _post_graphql(self, body: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = os.getenv("SHOPEE_ENDPOINT", "https://open-api.affiliate.shopee.com.br/graphql")
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        resp = requests.post(endpoint, data=payload.encode("utf-8"), headers=self._headers(payload), timeout=45)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"Shopee GraphQL errors: {data['errors']}")
        return data

    def fetch(self) -> List[Product]:
        mcfg = self.cfg.get("marketplaces", {}).get(self.name, {})
        if not mcfg.get("enabled", False):
            return []
        if not os.getenv("SHOPEE_APP_ID") or not os.getenv("SHOPEE_SECRET"):
            print("[shopee] Desabilitado: configure SHOPEE_APP_ID e SHOPEE_SECRET para usar a API.")
            return []

        keywords = mcfg.get("keywords", []) or []
        limit = int(mcfg.get("limit_per_keyword", 20))
        list_type = int(mcfg.get("list_type", 2))
        sort_type = int(mcfg.get("sort_type", 2))
        products: List[Product] = []
        seen: set[str] = set()

        query = """
        query ProductOffer($keyword: String, $listType: Int, $sortType: Int, $page: Int, $limit: Int) {
          productOfferV2(keyword: $keyword, listType: $listType, sortType: $sortType, page: $page, limit: $limit) {
            nodes {
              itemId
              productName
              productLink
              offerLink
              imageUrl
              priceMin
              priceMax
              priceDiscountRate
              sales
              ratingStar
              commissionRate
              sellerCommissionRate
              shopeeCommissionRate
              commission
              shopId
              shopName
              shopType
              periodStartTime
              periodEndTime
            }
            pageInfo { page limit hasNextPage }
          }
        }
        """

        for keyword in keywords:
            body = {
                "query": query,
                "operationName": "ProductOffer",
                "variables": {
                    "keyword": keyword,
                    "listType": list_type,
                    "sortType": sort_type,
                    "page": 1,
                    "limit": limit,
                },
            }
            try:
                data = self._post_graphql(body)
            except Exception as exc:
                print(f"[shopee] Erro buscando '{keyword}': {exc}")
                continue
            nodes = (((data.get("data") or {}).get("productOfferV2") or {}).get("nodes") or [])
            for item in nodes:
                item_id = str(item.get("itemId") or "")
                if not item_id or item_id in seen:
                    continue
                seen.add(item_id)
                price = to_float(item.get("priceMin"))
                discount_rate = to_float(item.get("priceDiscountRate"))
                old_price = None
                if price is not None and discount_rate and discount_rate > 0 and discount_rate < 100:
                    old_price = round(price / (1 - discount_rate / 100), 2)
                products.append(
                    Product(
                        marketplace=self.name,
                        id=item_id,
                        title=str(item.get("productName") or "").strip(),
                        price=price,
                        old_price=old_price,
                        currency="BRL",
                        url=str(item.get("productLink") or item.get("offerLink") or ""),
                        affiliate_url=str(item.get("offerLink") or "") or None,
                        image_url=str(item.get("imageUrl") or "") or None,
                        rating=to_float(item.get("ratingStar")),
                        sales_count=to_int(item.get("sales")),
                        commission_rate=normalize_rate(item.get("commissionRate")),
                        commission_value=to_float(item.get("commission")),
                        shipping_text=None,
                        category=str(item.get("shopName") or "") or None,
                        raw=item,
                    )
                )
        return products
