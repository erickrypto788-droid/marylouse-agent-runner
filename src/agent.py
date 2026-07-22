from __future__ import annotations

import copy
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .affiliate_links import build_affiliate_link
from .config import ROOT
from .copywriter import create_copy
from .marketplaces import ALL_MARKETPLACES
from .models import Product
from .scoring import passes_filters, score_product
from .storage import Storage
from .telegram import TelegramClient
from .site_publisher import publish_offer_to_site


def _resolve_db_path(cfg: Dict[str, Any]) -> str:
    path = os.getenv("SQLITE_PATH") or "data/agent.sqlite3"
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return str(p)


def _resolve_state_path(cfg: Dict[str, Any]) -> Path:
    path = cfg.get("niches", {}).get("state_file") or "data/niche_state.json"
    p = Path(str(path))
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_niche_state(cfg: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve_state_path(cfg)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_niche_state(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    path = _resolve_state_path(cfg)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _enabled_niche_items(cfg: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    niches_cfg = cfg.get("niches", {}) or {}
    lists = niches_cfg.get("lists", {}) or {}
    items: List[Tuple[str, Dict[str, Any]]] = []

    if isinstance(lists, dict):
        for key, value in lists.items():
            if not isinstance(value, dict):
                continue
            if value.get("enabled", True):
                items.append((str(key), value))

    return items


def choose_active_niche(cfg: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    niches_cfg = cfg.get("niches", {}) or {}
    if not niches_cfg.get("enabled", False):
        return None

    items = _enabled_niche_items(cfg)
    if not items:
        print("[nichos] Ativado, mas nenhuma lista de nicho habilitada foi encontrada.")
        return None

    mode = str(niches_cfg.get("mode", "sequential")).strip().lower()

    if mode in {"random", "aleatorio", "aleatório"}:
        return random.choice(items)

    # Padrão: rotação sequencial persistente em data/niche_state.json
    state = _load_niche_state(cfg)
    index = int(state.get("next_index", 0))
    selected = items[index % len(items)]
    state["next_index"] = (index + 1) % len(items)
    state["last_key"] = selected[0]
    state["last_name"] = selected[1].get("name") or selected[0]
    state["updated_at"] = int(time.time())
    _save_niche_state(cfg, state)
    return selected


def _keywords_for_marketplace(niche: Dict[str, Any], marketplace_name: str) -> List[str]:
    # Permite keywords específicas por marketplace:
    # marketplaces:
    #   shopee: ["produto viral", "achadinhos"]
    #   amazon: ["gadgets"]
    marketplace_keywords = (niche.get("marketplaces") or {}).get(marketplace_name)
    if marketplace_keywords:
        return [str(x) for x in marketplace_keywords if str(x).strip()]

    # Fallback: keywords gerais do nicho aplicadas a todos os marketplaces habilitados.
    general_keywords = niche.get("keywords") or []
    return [str(x) for x in general_keywords if str(x).strip()]


def apply_niche_rotation(cfg: Dict[str, Any]) -> Dict[str, Any]:
    selected = choose_active_niche(cfg)
    if not selected:
        return cfg

    niche_key, niche = selected
    niche_name = niche.get("name") or niche_key

    new_cfg = copy.deepcopy(cfg)
    new_cfg["active_niche"] = {
        "key": niche_key,
        "name": niche_name,
    }

    marketplaces_cfg = new_cfg.setdefault("marketplaces", {})
    only_marketplaces = niche.get("only_marketplaces") or niche.get("marketplaces_enabled") or []
    only_marketplaces = {str(x) for x in only_marketplaces if str(x).strip()}

    applied = []

    for marketplace_name, mcfg in marketplaces_cfg.items():
        if not isinstance(mcfg, dict):
            continue
        if not mcfg.get("enabled", False):
            continue
        if only_marketplaces and marketplace_name not in only_marketplaces:
            continue

        keywords = _keywords_for_marketplace(niche, marketplace_name)
        if not keywords:
            continue

        mcfg["keywords"] = keywords
        applied.append(f"{marketplace_name}={len(keywords)} keywords")

    if applied:
        print(f"[nichos] Nicho ativo: {niche_name} ({niche_key}) | " + ", ".join(applied))
    else:
        print(f"[nichos] Nicho ativo: {niche_name} ({niche_key}), mas nenhuma keyword foi aplicada.")

    return new_cfg




def _normalize_title_for_duplicate(value: Any) -> str:
    import re
    import unicodedata

    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9À-ÿ]+", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:140]


def _site_duplicate_keys(cfg: Dict[str, Any]) -> set[str]:
    path = ROOT / "site" / "data" / "offers.json"

    if not path.exists():
        return set()

    try:
        with path.open("r", encoding="utf-8") as f:
            offers = json.load(f)

        if not isinstance(offers, list):
            return set()

        keys: set[str] = set()

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            marketplace = str(offer.get("marketplace") or "").strip().lower()

            # Importante: usar title E raw_title.
            # O title do site pode ser encurtado pela IA, enquanto o produto bruto
            # vem com outro título. Precisamos bloquear pelos dois.
            for title in [
                offer.get("title"),
                offer.get("raw_title"),
                offer.get("product_title"),
            ]:
                if marketplace and title:
                    keys.add(f"{marketplace}|{_normalize_title_for_duplicate(title)}")

        return keys

    except Exception as exc:
        print(f"[site-duplicado] Não foi possível ler offers.json: {exc}")
        return set()

def fetch_all_products(cfg: Dict[str, Any]) -> List[Product]:
    products: List[Product] = []
    for MarketplaceCls in ALL_MARKETPLACES:
        marketplace = MarketplaceCls(cfg)
        try:
            fetched = marketplace.fetch()
            print(f"[{marketplace.name}] {len(fetched)} produtos coletados")
            products.extend(fetched)
        except Exception as exc:
            print(f"[{marketplace.name}] Falha geral: {exc}")
    return products


def prepare_candidates(products: List[Product], cfg: Dict[str, Any], storage: Storage) -> List[Product]:
    recent_days = int(cfg.get("agent", {}).get("recent_duplicate_days", 10))
    max_candidates = int(cfg.get("agent", {}).get("max_candidates_per_run", 80))

    agent_cfg = cfg.get("agent", {}) or {}
    post_one_per_marketplace = bool(agent_cfg.get("post_one_per_marketplace", True))

    site_keys = _site_duplicate_keys(cfg)
    seen_run_titles: set[str] = set()

    candidates: List[Product] = []

    for product in products:
        if product.affiliate_url:
            product.url = product.url or product.affiliate_url

        product.affiliate_url = product.affiliate_url or build_affiliate_link(product, cfg)

        ok, reason = passes_filters(product, cfg)

        if not ok:
            print(f"[filtro] Reprovado: {product.key} - {reason}")
            continue

        title_key = f"{product.marketplace}|{_normalize_title_for_duplicate(product.title)}"

        if title_key in site_keys:
            print(f"[duplicado-site] Ignorado por título já existente no site: {product.key}")
            continue

        if title_key in seen_run_titles:
            print(f"[duplicado-rodada] Ignorado por título repetido na rodada: {product.key}")
            continue

        if storage.was_recently_posted(product, recent_days):
            print(f"[duplicado] Ignorado: {product.key}")
            continue

        product.score = score_product(product, cfg)

        candidates.append(product)
        seen_run_titles.add(title_key)

    candidates.sort(key=lambda p: p.score, reverse=True)

    # Se vamos selecionar por marketplace, não cortamos aqui.
    # Senão, marketplaces como Mercado Livre podem ficar fora dos top N antes da seleção.
    if post_one_per_marketplace:
        return candidates

    return candidates[:max_candidates]

def select_products_to_post(candidates: List[Product], cfg: Dict[str, Any]) -> List[Product]:
    agent_cfg = cfg.get("agent", {}) or {}

    post_one_per_marketplace = bool(agent_cfg.get("post_one_per_marketplace", True))

    if not post_one_per_marketplace:
        post_limit = int(agent_cfg.get("post_limit_per_run", 3))
        return candidates[:post_limit]

    default_posts_per_marketplace = int(agent_cfg.get("posts_per_marketplace", 1))
    per_marketplace_limits = agent_cfg.get("posts_per_marketplace_by_marketplace", {}) or {}

    marketplaces_cfg = cfg.get("marketplaces", {}) or {}

    active_marketplaces: List[str] = []

    for name, mcfg in marketplaces_cfg.items():
        if isinstance(mcfg, dict) and mcfg.get("enabled", False):
            active_marketplaces.append(str(name))

    if not active_marketplaces:
        for product in candidates:
            if product.marketplace not in active_marketplaces:
                active_marketplaces.append(product.marketplace)

    selected: List[Product] = []
    selected_keys = set()
    selected_title_keys = set()

    for marketplace_name in active_marketplaces:
        mcfg = marketplaces_cfg.get(marketplace_name, {}) or {}

        limit = default_posts_per_marketplace

        if isinstance(per_marketplace_limits, dict) and marketplace_name in per_marketplace_limits:
            limit = int(per_marketplace_limits.get(marketplace_name) or limit)

        if isinstance(mcfg, dict) and mcfg.get("posts_per_run") is not None:
            limit = int(mcfg.get("posts_per_run") or limit)

        picked = 0

        for product in candidates:
            if product.marketplace != marketplace_name:
                continue

            title_key = f"{product.marketplace}|{_normalize_title_for_duplicate(product.title)}"

            if product.key in selected_keys:
                continue

            if title_key in selected_title_keys:
                continue

            selected.append(product)
            selected_keys.add(product.key)
            selected_title_keys.add(title_key)

            picked += 1

            if picked >= limit:
                break

        if picked == 0:
            print(f"[seleção] Nenhum candidato aprovado para marketplace ativo: {marketplace_name}")

    if selected:
        resumo = ", ".join(f"{p.marketplace}:{p.id}" for p in selected)
        print(f"[seleção] {len(selected)} produto(s) selecionado(s) por marketplace: {resumo}")
    else:
        print("[seleção] Nenhum produto selecionado para postagem.")

    return selected

def run_once(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = apply_niche_rotation(cfg)

    dry_run = bool(cfg.get("agent", {}).get("dry_run", True))
    post_limit = int(cfg.get("agent", {}).get("post_limit_per_run", 3))
    min_seconds_between_posts = int(cfg.get("agent", {}).get("min_seconds_between_posts", 60))

    storage = Storage(_resolve_db_path(cfg))
    telegram = TelegramClient(cfg)

    try:
        products = fetch_all_products(cfg)
        candidates = prepare_candidates(products, cfg, storage)
        print(f"[agent] {len(candidates)} candidatos após filtros e score")

        posted = []
        for product in select_products_to_post(candidates, cfg):
            offer_copy = create_copy(product, cfg)
            if not offer_copy.approved:
                print(f"[copy] IA reprovou {product.key}: {offer_copy.reason}")
                continue

            print("\n" + "=" * 80)
            print(f"[selecionado] {product.marketplace} | score={product.score} | {product.title}")
            print(offer_copy.caption)
            print("=" * 80 + "\n")

            message_id = None
            if dry_run:
                print("[dry-run] Não postado no Telegram. Ajuste DRY_RUN=false para publicar.")
            else:
                if not telegram.enabled:
                    raise RuntimeError("Telegram não configurado. Preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")
                message_id = telegram.send_offer(product, offer_copy)
                print(f"[telegram] Postado com message_id={message_id}")
                try:
                    site_result = publish_offer_to_site(product, offer_copy, cfg)
                    if site_result.get("published"):
                        print(f"[site] Oferta salva no site: {site_result.get('file')} (total={site_result.get('total')})")
                    elif site_result.get("reason") != "site disabled":
                        print(f"[site] Oferta nao salva no site: {site_result.get('reason')}")
                except Exception as exc:
                    print(f"[site] Falha ao salvar oferta no site: {exc}")
                if min_seconds_between_posts > 0:
                    time.sleep(min_seconds_between_posts)

            storage.mark_posted(product, offer_copy, telegram_message_id=message_id, dry_run=dry_run)
            posted.append({"product": product.to_dict(), "copy": offer_copy.to_dict(), "message_id": message_id})

        return {"dry_run": dry_run, "active_niche": cfg.get("active_niche"), "total_products": len(products), "candidates": len(candidates), "posted": posted}
    finally:
        storage.close()
