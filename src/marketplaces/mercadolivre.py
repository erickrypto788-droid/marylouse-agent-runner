from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .base import Marketplace
from ..models import Product
from ..utils import to_float, to_int


ROOT = Path(__file__).resolve().parents[2]
ML_API_BASE = "https://api.mercadolibre.com"


class MercadoLivreMarketplace(Marketplace):
    name = "mercadolivre"

    def fetch(self) -> List[Product]:
        mcfg = self.cfg.get("marketplaces", {}).get(self.name, {}) or {}

        if not mcfg.get("enabled", False):
            return []

        mcfg = self._apply_keyword_group(mcfg)

        source_mode = str(mcfg.get("source_mode", "catalog")).strip().lower()

        if source_mode != "catalog":
            print(f"[mercadolivre] source_mode '{source_mode}' não suportado neste momento. Use 'catalog'.")
            return []

        token = self._get_access_token(mcfg)

        if not token:
            print("[mercadolivre] Desabilitado: configure MERCADOLIVRE_REFRESH_TOKEN + CLIENT_ID/SECRET ou gere token local.")
            return []

        site_id = str(mcfg.get("site_id") or os.getenv("ML_SITE_ID") or "MLB").strip()
        keywords = mcfg.get("keywords", []) or []
        limit = int(mcfg.get("limit_per_keyword", 10))
        max_products_per_keyword = int(mcfg.get("max_products_per_keyword", limit))

        allowed_domains = set(mcfg.get("allowed_domain_ids", []) or [])
        blocked_domains = set(mcfg.get("blocked_domain_ids", []) or [])

        products: List[Product] = []
        seen: set[str] = set()

        for keyword in keywords:
            catalog_products = self._search_catalog_products(
                token=token,
                site_id=site_id,
                keyword=str(keyword),
                limit=limit,
            )

            for catalog in catalog_products[:max_products_per_keyword]:
                product_id = str(catalog.get("id") or "").strip()
                domain_id = str(catalog.get("domain_id") or "").strip()

                if not product_id:
                    continue

                if allowed_domains and domain_id not in allowed_domains:
                    continue

                if blocked_domains and domain_id in blocked_domains:
                    continue

                if product_id in seen:
                    continue

                # Alguns detalhes de catálogo podem falhar com 503/timeout.
                # Se falhar, usamos o próprio resultado do products/search como fallback.
                detail = self._get_catalog_detail(token, product_id) or catalog

                title = str(detail.get("name") or catalog.get("name") or "").strip()

                if not title:
                    continue

                items = self._get_catalog_items(token, product_id)

                if not items:
                    # Alguns produtos de catálogo não têm buy box/winners disponíveis.
                    continue

                selected_item = self._choose_item(items)

                if not selected_item:
                    continue

                item_id = str(selected_item.get("item_id") or selected_item.get("id") or "").strip()

                if not item_id:
                    continue

                unique_key = f"{product_id}:{item_id}"

                if unique_key in seen:
                    continue

                seen.add(unique_key)

                price = to_float(selected_item.get("price"))
                old_price = to_float(selected_item.get("original_price"))

                if price is None:
                    continue

                image_url = self._first_picture(detail) or self._first_picture(catalog)

                original_url = self._catalog_url(product_id)
                affiliate_url = self._add_matt_params(original_url, mcfg)

                shipping = selected_item.get("shipping") or {}
                shipping_text = "Frete grátis" if shipping.get("free_shipping") else None

                category_label = self._category_label(domain_id, mcfg)

                products.append(
                    Product(
                        marketplace=self.name,
                        id=item_id,
                        title=title,
                        price=price,
                        old_price=old_price,
                        currency=str(selected_item.get("currency_id") or "BRL"),
                        url=affiliate_url,
                        affiliate_url=affiliate_url,
                        image_url=image_url,
                        rating=None,
                        sales_count=to_int(selected_item.get("sold_quantity")),
                        commission_rate=None,
                        shipping_text=shipping_text,
                        category=category_label,
                        raw={
                            "source_mode": "catalog",
                            "catalog_product_id": product_id,
                            "item_id": item_id,
                            "domain_id": domain_id,
                            "original_url": original_url,
                            "affiliate_mode": "matt_params",
                            "selected_item": selected_item,
                            "catalog_detail": {
                                "id": detail.get("id"),
                                "name": detail.get("name"),
                                "domain_id": detail.get("domain_id"),
                            },
                        },
                    )
                )

        return products



    def _resolve_path(self, value: str) -> Path:
        path = Path(str(value))

        if not path.is_absolute():
            path = ROOT / path

        path.parent.mkdir(parents=True, exist_ok=True)

        return path

    def _apply_keyword_group(self, mcfg: Dict[str, Any]) -> Dict[str, Any]:
        groups = mcfg.get("keyword_groups") or {}

        if not isinstance(groups, dict) or not groups:
            return mcfg

        enabled_groups = []

        for key, group in groups.items():
            if not isinstance(group, dict):
                continue

            if group.get("enabled", True):
                enabled_groups.append((str(key), group))

        if not enabled_groups:
            return mcfg

        groups_per_run = int(mcfg.get("niche_groups_per_run", 4))

        if groups_per_run <= 0:
            groups_per_run = 1

        mode = str(mcfg.get("niche_mode", "sequential")).strip().lower()

        if mode in {"random", "aleatorio", "aleatório"}:
            selected_groups = random.sample(enabled_groups, min(groups_per_run, len(enabled_groups)))
            selected_index = 0
        else:
            state_path = self._resolve_path(mcfg.get("niche_state_file") or "data/mercadolivre_niche_state.json")

            try:
                if state_path.exists():
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(state, dict):
                        state = {}
                else:
                    state = {}
            except Exception:
                state = {}

            selected_index = int(state.get("next_index", 0))

            selected_groups = []

            for offset in range(min(groups_per_run, len(enabled_groups))):
                selected_groups.append(enabled_groups[(selected_index + offset) % len(enabled_groups)])

            state["next_index"] = (selected_index + len(selected_groups)) % len(enabled_groups)
            state["last_keys"] = [key for key, _ in selected_groups]
            state["last_names"] = [group.get("name") or key for key, group in selected_groups]
            state["updated_at"] = int(time.time())

            try:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                print(f"[mercadolivre] Não foi possível salvar estado de nicho: {exc}")

        new_cfg = dict(mcfg)

        combined_keywords = []
        selected_names = []

        # Começa com configuração global.
        allowed_domains = set(mcfg.get("allowed_domain_ids", []) or [])
        blocked_domains = set(mcfg.get("blocked_domain_ids", []) or [])

        for selected_key, selected_group in selected_groups:
            selected_names.append(selected_group.get("name") or selected_key)

            keywords = selected_group.get("keywords") or []
            combined_keywords.extend([str(x) for x in keywords if str(x).strip()])

            for domain in selected_group.get("allowed_domain_ids", []) or []:
                allowed_domains.add(str(domain))

            for domain in selected_group.get("blocked_domain_ids", []) or []:
                blocked_domains.add(str(domain))

        # Remove duplicadas mantendo ordem.
        seen_keywords = set()
        unique_keywords = []

        for keyword in combined_keywords:
            key = keyword.strip().lower()

            if not key or key in seen_keywords:
                continue

            seen_keywords.add(key)
            unique_keywords.append(keyword)

        if unique_keywords:
            new_cfg["keywords"] = unique_keywords

        # Categoria genérica quando há múltiplos nichos.
        new_cfg["category_label"] = "Mercado Livre"

        new_cfg["allowed_domain_ids"] = list(allowed_domains)
        new_cfg["blocked_domain_ids"] = list(blocked_domains)

        print(
            f"[mercadolivre] Nichos ativos: {', '.join(selected_names)} "
            f"| {len(unique_keywords)} keywords | grupos={len(selected_groups)}"
        )

        return new_cfg

    def _token_file(self) -> Path:
        return ROOT / "data" / "mercadolivre_oauth_token.json"

    def _get_access_token(self, mcfg: Dict[str, Any]) -> str:
        env_token = (
            os.getenv("MERCADOLIVRE_ACCESS_TOKEN", "").strip()
            or os.getenv("ML_ACCESS_TOKEN", "").strip()
        )

        if env_token:
            return env_token

        token_data: Dict[str, Any] = {}

        token_file = self._token_file()

        if token_file.exists():
            try:
                token_data = json.loads(token_file.read_text(encoding="utf-8"))
            except Exception:
                token_data = {}

        refresh_token = (
            os.getenv("MERCADOLIVRE_REFRESH_TOKEN", "").strip()
            or str(token_data.get("refresh_token") or "").strip()
        )

        client_id = (
            os.getenv("MERCADOLIVRE_CLIENT_ID", "").strip()
            or os.getenv("ML_APP_ID", "").strip()
            or str(mcfg.get("client_id") or "").strip()
        )

        client_secret = (
            os.getenv("MERCADOLIVRE_CLIENT_SECRET", "").strip()
            or os.getenv("ML_CLIENT_SECRET", "").strip()
            or str(mcfg.get("client_secret") or "").strip()
        )

        if refresh_token and client_id and client_secret:
            refreshed = self._refresh_access_token(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )

            if refreshed.get("access_token"):
                try:
                    token_file.parent.mkdir(parents=True, exist_ok=True)
                    token_file.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass

                return str(refreshed.get("access_token") or "").strip()

        file_token = str(token_data.get("access_token") or "").strip()

        if file_token:
            return file_token

        return ""

    def _refresh_access_token(self, client_id: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
        url = f"{ML_API_BASE}/oauth/token"

        payload = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

        try:
            response = requests.post(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                timeout=30,
            )

            if response.status_code != 200:
                print(f"[mercadolivre] Falha renovando token: {response.status_code} {response.text[:300]}")
                return {}

            return response.json()

        except Exception as exc:
            print(f"[mercadolivre] Erro renovando token: {exc}")
            return {}

    def _get_json(self, token: str, url: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "telegram-affiliate-agent/1.0",
                        "Accept": "application/json",
                    },
                    timeout=20,
                )

                if response.status_code == 404:
                    return {}

                # Erros temporários do Mercado Livre: tenta novamente.
                if response.status_code in {429, 500, 502, 503, 504}:
                    print(
                        f"[mercadolivre] HTTP {response.status_code} temporário em {url}. "
                        f"Tentativa {attempt}/{max_attempts}"
                    )

                    if attempt < max_attempts:
                        time.sleep(1.5 * attempt)
                        continue

                    print(f"[mercadolivre] Falha final HTTP {response.status_code}: {response.text[:250]}")
                    return {}

                if response.status_code != 200:
                    print(f"[mercadolivre] HTTP {response.status_code}: {url} | {response.text[:250]}")
                    return {}

                data = response.json()

                return data if isinstance(data, dict) else {}

            except requests.exceptions.Timeout:
                print(f"[mercadolivre] Timeout em {url}. Tentativa {attempt}/{max_attempts}")

                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)
                    continue

                return {}

            except Exception as exc:
                print(f"[mercadolivre] Erro GET {url}: {exc}")

                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)
                    continue

                return {}

        return {}

    def _search_catalog_products(self, token: str, site_id: str, keyword: str, limit: int) -> List[Dict[str, Any]]:
        url = f"{ML_API_BASE}/products/search"

        params = {
            "status": "active",
            "site_id": site_id,
            "q": keyword,
            "limit": limit,
        }

        data = self._get_json(token, url, params=params)

        results = data.get("results", [])

        if not isinstance(results, list):
            return []

        return [item for item in results if isinstance(item, dict)]

    def _get_catalog_detail(self, token: str, product_id: str) -> Dict[str, Any]:
        url = f"{ML_API_BASE}/products/{product_id}"

        return self._get_json(token, url)

    def _get_catalog_items(self, token: str, product_id: str) -> List[Dict[str, Any]]:
        url = f"{ML_API_BASE}/products/{product_id}/items"

        data = self._get_json(token, url)

        results = data.get("results", [])

        if not isinstance(results, list):
            return []

        return [item for item in results if isinstance(item, dict)]

    def _choose_item(self, items: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        valid = []

        for item in items:
            price = to_float(item.get("price"))

            if price is None:
                continue

            if str(item.get("condition") or "").lower() not in {"", "new"}:
                continue

            valid.append(item)

        if not valid:
            return None

        def sort_key(item: Dict[str, Any]) -> tuple:
            shipping = item.get("shipping") or {}
            free_shipping = 1 if shipping.get("free_shipping") else 0
            price = to_float(item.get("price")) or 10**12

            # Preferimos frete grátis e menor preço.
            return (-free_shipping, price)

        valid.sort(key=sort_key)

        return valid[0]

    def _catalog_url(self, product_id: str) -> str:
        return f"https://www.mercadolivre.com.br/p/{product_id}"

    def _add_matt_params(self, url: str, mcfg: Dict[str, Any]) -> str:
        matt_word = str(
            mcfg.get("matt_word")
            or os.getenv("MERCADOLIVRE_MATT_WORD", "")
            or "marylouse"
        ).strip()

        matt_tool = str(
            mcfg.get("matt_tool")
            or os.getenv("MERCADOLIVRE_MATT_TOOL", "")
            or "50459180"
        ).strip()

        force_in_app = bool(mcfg.get("force_in_app", True))

        if not matt_word or not matt_tool:
            return url

        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))

        query["matt_word"] = matt_word
        query["matt_tool"] = matt_tool

        if force_in_app:
            query["forceInApp"] = "true"

        new_query = urlencode(query)

        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

    def _first_picture(self, obj: Dict[str, Any]) -> str:
        pictures = obj.get("pictures") or []

        if not isinstance(pictures, list):
            return ""

        for pic in pictures:
            if not isinstance(pic, dict):
                continue

            url = str(pic.get("url") or "").strip()

            if url:
                if url.startswith("http://"):
                    url = url.replace("http://", "https://", 1)

                return url

        return ""

    def _category_label(self, domain_id: str, mcfg: Dict[str, Any]) -> str:
        labels = mcfg.get("domain_category_labels", {}) or {}

        if isinstance(labels, dict) and domain_id in labels:
            return str(labels[domain_id])

        if domain_id:
            return domain_id.replace("MLB-", "").replace("_", " ").title()

        return str(mcfg.get("category_label") or "Mercado Livre")

