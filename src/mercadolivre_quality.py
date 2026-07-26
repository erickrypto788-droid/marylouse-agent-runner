from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import ROOT
from .models import Product


DEFAULT_STATE_FILE = "data/mercadolivre_quality_state.json"


STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "com", "sem", "e", "ou",
    "a", "o", "as", "os", "em", "no", "na", "nos", "nas", "por",
    "oferta", "promocao", "promoção", "original", "novo", "nova",
    "kit", "unidade", "unidades", "ml", "g", "kg", "litro", "litros"
}


BUYER_INTENT_GROUPS = {
    "bebe_recorrente": [
        "fralda", "pampers", "huggies", "mamypoko", "mamy poko", "lenço umedecido",
        "lenco umedecido", "pomada assadura", "mamadeira", "chupeta"
    ],
    "supermercado_recorrente": [
        "papel higiênico", "papel higienico", "sabão em pó", "sabao em po",
        "detergente", "amaciante", "lava roupas", "sabonete", "creme dental",
        "papel toalha", "saco de lixo", "azeite", "arroz", "feijão", "feijao"
    ],
    "casa_cozinha": [
        "air fryer", "panela", "jogo de panelas", "frigideira", "cafeteira",
        "liquidificador", "batedeira", "mixer", "aspirador", "microondas",
        "micro-ondas", "purificador de água", "purificador de agua"
    ],
    "tech": [
        "smartphone", "celular", "iphone", "samsung", "galaxy", "xiaomi", "redmi",
        "motorola", "notebook", "ssd", "monitor", "impressora", "roteador",
        "tablet", "memória ram", "memoria ram", "processador", "ryzen"
    ],
    "beleza": [
        "perfume", "barbeador", "aparador", "secador", "chapinha", "escova secadora",
        "protetor solar", "shampoo", "condicionador", "hidratante"
    ],
    "pet": [
        "ração", "racao", "areia higiênica", "areia higienica", "petisco cachorro",
        "petisco gato", "comedouro", "bebedouro pet"
    ],
    "saude": [
        "monitor de pressão", "monitor de pressao", "pressão arterial",
        "pressao arterial", "termômetro", "termometro", "oxímetro", "oximetro",
        "inalador", "nebulizador", "medidor de glicose", "bioimpedância",
        "bioimpedancia"
    ],
    "esportes_fitness": [
        "halter", "halteres", "academia", "fitness", "bike spinning",
        "bicicleta ergometrica", "bicicleta ergométrica", "esteira",
        "bola futebol", "bola de futebol", "bola volei", "bola vôlei",
        "yoga", "colchonete", "tapete yoga", "luva academia",
        "caneleira", "anilha", "barra macica", "barra maciça",
        "whey", "creatina", "coqueteleira", "elastico treino",
        "elástico treino", "faixa elastica", "faixa elástica",
        "tenis corrida", "tênis corrida", "short academia",
        "camiseta termica", "camiseta térmica"
    ],
    "ferramentas": [
        "furadeira", "parafusadeira", "chave de fenda", "martelo", "trena",
        "alicate", "serra", "kit ferramentas"
    ],
    "casa_moveis": [
        "rack para tv", "painel para tv", "cadeira escritório", "cadeira escritorio",
        "cadeira gamer", "mesa computador", "escrivaninha", "colchão", "colchao"
    ],
}


BRANDS = [
    "pampers", "huggies", "mamypoko", "mamy poko", "johnson", "granado",
    "tramontina", "mondial", "philco", "oster", "electrolux", "brastemp",
    "consul", "samsung", "xiaomi", "motorola", "apple", "iphone", "lenovo",
    "asus", "acer", "dell", "hp", "lg", "philips", "taiff", "gama", "nivea",
    "eudora", "boticario", "o boticário", "pedigree", "whiskas", "golden",
    "premier", "stanley", "bosch", "dewalt", "makita",
    "kikos", "acte", "vollo", "gonew", "olympikus", "penalty", "wilson", "speedo", "mormaii", "adidas", "nike"
]


WEAK_TERMS = [
    "suporte", "capa", "case", "película", "pelicula", "adesivo", "skin",
    "refil", "filtro bebedouro", "peça", "peca", "reposição", "reposicao",
    "cabo", "adaptador", "conector", "plug", "controle remoto", "moldura",
    "tampa", "parafuso", "dobradiça", "dobradica", "manual", "apostila"
]


BLOCK_TERMS = [
    "usado", "seminovo", "recondicionado", "compatível com tesla", "tesla model",
    "para peças", "para pecas", "defeito"
]


def _now_ts() -> int:
    return int(time.time())


def _parse_ts(value: Any) -> int:
    if value is None:
        return 0

    if isinstance(value, (int, float)):
        if value > 1000000000000:
            return int(value / 1000)
        return int(value)

    text = str(value).strip()

    if not text:
        return 0

    if text.isdigit():
        return _parse_ts(int(text))

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def contains_any(text: str, terms: List[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(term) in normalized for term in terms if str(term).strip())


def title_tokens(value: str) -> set[str]:
    text = normalize_text(value)
    return {
        token
        for token in text.split()
        if len(token) > 2 and token not in STOPWORDS
    }


def similar_titles(a: str, b: str) -> bool:
    ta = title_tokens(a)
    tb = title_tokens(b)

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


def ml_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return (cfg.get("marketplaces", {}) or {}).get("mercadolivre", {}) or {}


def state_path(cfg: Dict[str, Any]) -> Path:
    mcfg = ml_cfg(cfg)
    raw = str(mcfg.get("quality_state_file") or DEFAULT_STATE_FILE)

    path = Path(raw)

    if not path.is_absolute():
        path = ROOT / path

    return path


def load_state(cfg: Dict[str, Any]) -> Dict[str, Any]:
    path = state_path(cfg)

    if not path.exists():
        return {"posted": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            return {"posted": []}

        if not isinstance(data.get("posted"), list):
            data["posted"] = []

        return data

    except Exception:
        return {"posted": []}


def save_state(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    path = state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def product_ids(product: Product) -> Dict[str, str]:
    raw = product.raw or {}

    catalog_id = str(
        raw.get("catalog_product_id")
        or (raw.get("catalog_detail") or {}).get("id")
        or ""
    ).strip()

    item_id = str(
        raw.get("item_id")
        or product.id
        or ""
    ).strip()

    url = str(product.url or product.affiliate_url or "").strip()
    affiliate_url = str(product.affiliate_url or "").strip()

    return {
        "key": str(product.key or "").strip(),
        "product_id": str(product.id or "").strip(),
        "catalog_product_id": catalog_id,
        "item_id": item_id,
        "url": url,
        "affiliate_url": affiliate_url,
        "title_norm": normalize_text(product.title),
    }


def clean_state(cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    cooldown_hours = int(ml_cfg(cfg).get("quality_cooldown_hours", 48))
    cutoff = _now_ts() - cooldown_hours * 3600

    posted = []

    for record in state.get("posted", []) or []:
        ts = _parse_ts(record.get("posted_ts") or record.get("posted_at"))

        if ts >= cutoff:
            posted.append(record)

    state["posted"] = posted
    return state


def is_recent_duplicate(product: Product, cfg: Dict[str, Any], state: Dict[str, Any]) -> Tuple[bool, str]:
    cooldown_hours = int(ml_cfg(cfg).get("quality_cooldown_hours", 48))
    cutoff = _now_ts() - cooldown_hours * 3600

    ids = product_ids(product)

    for record in state.get("posted", []) or []:
        ts = _parse_ts(record.get("posted_ts") or record.get("posted_at"))

        if ts < cutoff:
            continue

        for field in ["key", "product_id", "catalog_product_id", "item_id", "url", "affiliate_url"]:
            current = ids.get(field)

            if current and current == str(record.get(field) or "").strip():
                return True, f"{field} repetido em {cooldown_hours}h"

        old_title = str(record.get("title") or "")

        if old_title and similar_titles(product.title, old_title):
            return True, f"título parecido em {cooldown_hours}h"

    return False, ""


def detect_intent_group(title: str) -> str:
    for group, terms in BUYER_INTENT_GROUPS.items():
        if contains_any(title, terms):
            return group

    return "outros"


def classify_category(title: str) -> str:
    group = detect_intent_group(title)

    mapping = {
        "bebe_recorrente": "Mãe e Bebê",
        "supermercado_recorrente": "Supermercados",
        "casa_cozinha": "Casa e Cozinha",
        "tech": "Informática",
        "beleza": "Beleza",
        "pet": "Pet",
        "saude": "Saúde",
        "esportes_fitness": "Esportes",
        "ferramentas": "Ferramentas",
        "casa_moveis": "Casa e Cozinha",
    }

    return mapping.get(group, "Outros")


def commercial_score(product: Product, cfg: Dict[str, Any]) -> Tuple[bool, float, str, str, str]:
    title = str(product.title or "")
    text = normalize_text(title)
    mcfg = ml_cfg(cfg)

    min_quality_score = float(mcfg.get("quality_min_score", 55))

    if contains_any(text, BLOCK_TERMS):
        return False, -100.0, "bloqueado por termo ruim", "Outros", "bloqueado"

    group = detect_intent_group(title)
    category = classify_category(title)

    score = 0.0

    # 1) Intenção real de compra.
    if group != "outros":
        score += 38
    else:
        score += 5

    # 2) Marca conhecida.
    if contains_any(text, BRANDS):
        score += 16

    # 3) Desconto.
    discount = float(product.discount_percent or 0)

    if discount >= 15:
        score += min(discount, 70) * 0.45
    elif discount > 0:
        score += discount * 0.15

    # 4) Faixa de preço.
    price = float(product.price or 0)

    if group in {"supermercado_recorrente", "bebe_recorrente"}:
        if 20 <= price <= 250:
            score += 16
        elif price < 20:
            score -= 15
    elif group in {"tech", "casa_moveis"}:
        if 150 <= price <= 8000:
            score += 15
    elif group in {"casa_cozinha", "beleza", "pet", "saude", "ferramentas", "esportes_fitness"}:
        if 35 <= price <= 2500:
            score += 15
    else:
        if 50 <= price <= 3000:
            score += 8

    # 5) Frete.
    shipping = normalize_text(product.shipping_text or "")

    if "gratis" in shipping or "free" in shipping:
        score += 8

    # 6) Preço antigo ajuda.
    if product.old_price and product.old_price > product.price:
        score += 6

    # 7) Penalizações.
    weak = contains_any(text, WEAK_TERMS)

    if weak and group == "outros":
        return False, score - 50, "produto fraco/genérico sem intenção clara", category, group

    if weak:
        score -= 18

    # 8) Muito genérico sem marca e sem grupo.
    if group == "outros" and not contains_any(text, BRANDS):
        score -= 25

    if score < min_quality_score:
        return False, score, f"score comercial baixo ({score:.1f})", category, group

    return True, score, "aprovado", category, group


def select_quality_mercadolivre_products(
    candidates: List[Product],
    cfg: Dict[str, Any],
    limit: int
) -> List[Product]:
    if limit <= 0:
        return []

    mcfg = ml_cfg(cfg)

    max_per_category = int(mcfg.get("quality_max_per_category", 2))
    max_per_group = int(mcfg.get("quality_max_per_group", 1))

    state = clean_state(cfg, load_state(cfg))

    approved = []

    for product in candidates:
        duplicated, reason = is_recent_duplicate(product, cfg, state)

        if duplicated:
            print(f"[ml-quality] Reprovado 48h: {product.key} - {reason} | {str(product.title or '')[:90]}")
            continue

        ok, qscore, reason, category, group = commercial_score(product, cfg)

        if not ok:
            print(f"[ml-quality] Reprovado: {product.key} - {reason} | {str(product.title or '')[:90]}")
            continue

        # Ajusta categoria para melhorar site/Telegram.
        if category and category != "Outros":
            product.category = category

        base_score = float(product.score or 0)
        final_score = base_score + qscore

        approved.append((final_score, qscore, category, group, product))

    approved.sort(key=lambda item: item[0], reverse=True)

    selected: List[Product] = []
    category_counts: Dict[str, int] = {}
    group_counts: Dict[str, int] = {}
    selected_titles: List[str] = []

    for final_score, qscore, category, group, product in approved:
        if len(selected) >= limit:
            break

        if category_counts.get(category, 0) >= max_per_category:
            print(f"[ml-quality] Ignorado por diversidade de categoria: {product.key} | {category}")
            continue

        if group_counts.get(group, 0) >= max_per_group:
            print(f"[ml-quality] Ignorado por diversidade de grupo: {product.key} | {group}")
            continue

        if any(similar_titles(product.title, old) for old in selected_titles):
            print(f"[ml-quality] Ignorado por similaridade na seleção: {product.key}")
            continue

        product.score = round(final_score, 2)
        selected.append(product)
        selected_titles.append(product.title)
        category_counts[category] = category_counts.get(category, 0) + 1
        group_counts[group] = group_counts.get(group, 0) + 1

        print(
            f"[ml-quality] Selecionado: {product.key} | "
            f"score_final={product.score} | qualidade={qscore:.1f} | "
            f"categoria={category} | grupo={group}"
        )

    if not selected:
        print("[ml-quality] Nenhum produto Mercado Livre passou na curadoria de qualidade.")

    return selected


def mark_mercadolivre_posted(product: Product, cfg: Dict[str, Any]) -> None:
    state = clean_state(cfg, load_state(cfg))

    ids = product_ids(product)
    record = {
        **ids,
        "title": product.title,
        "category": product.category,
        "price": product.price,
        "score": product.score,
        "posted_ts": _now_ts(),
        "posted_at": datetime.now(timezone.utc).isoformat(),
    }

    state.setdefault("posted", []).insert(0, record)

    # Mantém arquivo pequeno.
    state["posted"] = state.get("posted", [])[:800]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    save_state(cfg, state)
    print(f"[ml-quality] Estado 48h atualizado: {ids.get('key')}")
