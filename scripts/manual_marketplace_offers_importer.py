from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


CSV_PATH = Path(os.getenv("MANUAL_MARKETPLACE_OFFERS_CSV", "data/manual_marketplace_offers.csv"))
STATE_PATH = Path(os.getenv("MANUAL_MARKETPLACE_OFFERS_STATE", "data/manual_marketplace_offers_state.json"))

POST_COUNT = int(os.getenv("POST_COUNT", "3"))
POST_TELEGRAM = os.getenv("POST_TELEGRAM", "true").lower() == "true"
PUBLISH_SITE = os.getenv("PUBLISH_SITE", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

DEFAULT_VALID_HOURS = int(os.getenv("MANUAL_MARKETPLACE_VALID_HOURS", "24"))
REPOST_HOURS = int(os.getenv("MANUAL_MARKETPLACE_REPOST_HOURS", str(DEFAULT_VALID_HOURS)))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SITE_REPO = os.getenv("SITE_REPO", "erickrypto788-droid/marylouse-ofertas")
SITE_BRANCH = os.getenv("SITE_BRANCH", "main")
SITE_FILE_PATH = os.getenv("SITE_FILE_PATH", "data/offers.json")
SITE_REPO_TOKEN = os.getenv("SITE_REPO_TOKEN", "")

DEFAULT_IMAGE_URL = os.getenv(
    "MANUAL_MARKETPLACE_DEFAULT_IMAGE_URL",
    "https://marylouse-ofertas.vercel.app/assets/logo.png"
)

AFFILIATE_DISCLOSURE = os.getenv(
    "AFFILIATE_DISCLOSURE",
    "Aviso: como afiliados, podemos receber comissão por compras feitas pelos links."
)


def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def parse_iso(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def normalize_text(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def make_offer_id(row):
    base = "|".join([
        normalize_text(row.get("marketplace")),
        normalize_text(row.get("affiliate_url")),
        normalize_text(row.get("title")),
    ])
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    marketplace = normalize_text(row.get("marketplace")).replace(" ", "-") or "marketplace"
    return f"manual-{marketplace}-{digest}"


def load_json(path, default):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def state_records(state, key):
    records = state.get(f"{key}_records") or {}
    return records if isinstance(records, dict) else {}


def last_state_dt(state, key, offer_id):
    value = state_records(state, key).get(offer_id)
    return parse_iso(value)


def is_due_for_repost(state, key, offer_id):
    last = last_state_dt(state, key, offer_id)

    if not last:
        # Estado antigo sem timestamp: libera para não bloquear para sempre.
        return True

    return utc_now() >= last + timedelta(hours=REPOST_HOURS)


def mark_state(state, key, offer_id):
    ids = set(state.get(key) or [])
    ids.add(offer_id)
    state[key] = sorted(ids)

    records_key = f"{key}_records"
    records = state.get(records_key)

    if not isinstance(records, dict):
        records = {}

    records[offer_id] = iso_now()
    state[records_key] = records


def read_text_with_fallback(path):
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    raw = path.read_bytes()
    last_error = None

    for enc in encodings:
        try:
            text = raw.decode(enc)
            print(f"[manual-marketplace] CSV lido com encoding: {enc}")
            return text
        except UnicodeDecodeError as exc:
            last_error = exc

    raise RuntimeError(f"Não foi possível ler CSV: {last_error}")


def detect_delimiter(text):
    sample = text[:4096]
    first_line = text.splitlines()[0] if text.splitlines() else ""

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        return dialect.delimiter
    except Exception:
        if ";" in first_line:
            return ";"
        if "\t" in first_line:
            return "\t"
        return ","


def parse_price(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace("R$", "").replace("r$", "").replace(" ", "")

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    text = re.sub(r"[^0-9.]", "", text)

    if text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return round(float(text), 2)
    except Exception:
        return None


def format_brl(value):
    if value is None:
        return ""

    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def as_int(value, default):
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value).strip().replace(",", ".")))
    except Exception:
        return default


def marketplace_label(value):
    raw = str(value or "").strip()
    key = normalize_text(raw).replace(" ", "").replace("_", "").replace("-", "")

    labels = {
        "mercadolivre": "Mercado Livre",
        "ml": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "aliexpress": "AliExpress",
    }

    return labels.get(key, raw or "Marketplace")


def add_ml_params_if_needed(url, marketplace):
    if marketplace_label(marketplace) != "Mercado Livre":
        return url

    if not url:
        return url

    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))

    query.setdefault("matt_word", os.getenv("MERCADOLIVRE_MATT_WORD", "marylouse") or "marylouse")
    query.setdefault("matt_tool", os.getenv("MERCADOLIVRE_MATT_TOOL", "50459180") or "50459180")
    query.setdefault("forceInApp", "true")

    new_query = urllib.parse.urlencode(query)

    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def auto_category(title, category):
    if category:
        return category

    text = normalize_text(title)

    rules = [
        ("Mãe e Bebê", ["fralda", "pampers", "huggies", "mamypoko", "mamy poko", "lenço umedecido", "lenco umedecido", "bebê", "bebe", "baby"]),
        ("Celulares", ["smartphone", "celular", "iphone", "galaxy", "xiaomi", "redmi", "poco", "motorola", "android", "5g"]),
        ("Informática", ["notebook", "laptop", "ssd", "monitor gamer", "ryzen", "rtx", "gtx", "teclado", "mouse", "impressora"]),
        ("Casa e Cozinha", ["air fryer", "panela", "liquidificador", "cafeteira", "cozinha", "frigideira", "aspirador"]),
        ("Beleza", ["perfume", "barbeador", "secador", "chapinha", "escova secadora", "maquiagem", "shampoo"]),
        ("Pet", ["ração", "racao", "cachorro", "gato", "pet", "areia higiênica", "areia higienica"]),
        ("Saúde", ["monitor de pressão", "monitor de pressao", "termômetro", "termometro", "inalador", "oxímetro", "oximetro"]),
        ("Calçados", ["tênis", "tenis", "sapato", "sandália", "sandalia", "chinelo", "bota"]),
        ("Bolsas", ["mochila", "bolsa", "mala", "necessaire"]),
        ("Moda Feminina", ["vestido", "blusa feminina", "short feminino", "shorts feminino", "legging", "cropped", "regata feminina", "feminina"]),
        ("Moda Masculina", ["camiseta masculina", "camisa masculina", "bermuda masculina", "cueca", "masculino"]),
        ("Supermercados", ["papel higiênico", "papel higienico", "detergente", "amaciante", "sabão em pó", "sabao em po", "azeite"]),
        ("Games", ["playstation", "ps5", "xbox", "nintendo", "console", "controle gamer"]),
        ("Papelaria", ["caneta", "caderno", "papelaria", "estojo", "material escolar"]),
        ("Ferramentas", ["furadeira", "parafusadeira", "ferramenta", "martelo", "trena"]),
    ]

    for cat, words in rules:
        if any(word in text for word in words):
            return cat

    return "Outros"


def read_rows():
    if not CSV_PATH.exists():
        print(f"[manual-marketplace] CSV não encontrado: {CSV_PATH}")
        return []

    text = read_text_with_fallback(CSV_PATH)
    delimiter = detect_delimiter(text)

    print(f"[manual-marketplace] CSV delimitador detectado: {repr(delimiter)}")

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    required = {"marketplace", "title", "price", "affiliate_url"}
    columns = set(reader.fieldnames or [])
    missing = required - columns

    if missing:
        raise RuntimeError(f"CSV sem colunas obrigatórias: {', '.join(sorted(missing))}")

    rows = []

    for line_number, row in enumerate(reader, start=2):
        row = {
            str(k).strip(): (v.strip() if isinstance(v, str) else v)
            for k, v in row.items()
            if k is not None
        }

        marketplace = marketplace_label(row.get("marketplace"))
        title = row.get("title") or ""
        price_number = parse_price(row.get("price"))
        old_price = parse_price(row.get("de") or row.get("old_price") or row.get("original_price"))
        affiliate_url = add_ml_params_if_needed(row.get("affiliate_url") or "", marketplace)
        image_url = row.get("image_url") or DEFAULT_IMAGE_URL
        category = auto_category(title, row.get("category") or "")
        description = row.get("description") or "Produto selecionado manualmente pela MaryLouse Ofertas."
        valid_hours = as_int(row.get("valid_hours"), DEFAULT_VALID_HOURS)

        errors = []

        if not marketplace:
            errors.append("marketplace vazio")
        if not title:
            errors.append("title vazio")
        if price_number is None:
            errors.append("price inválido")
        if not affiliate_url:
            errors.append("affiliate_url vazio")

        if errors:
            print(f"[manual-marketplace] linha {line_number} ignorada: {', '.join(errors)}")
            continue

        row["marketplace"] = marketplace
        row["title"] = title
        row["price_number"] = price_number
        row["price_text"] = format_brl(price_number)
        row["old_price_number"] = old_price if old_price and old_price > price_number else None
        row["old_price_text"] = format_brl(old_price) if old_price and old_price > price_number else ""
        row["discount_percent"] = round(((old_price - price_number) / old_price) * 100) if old_price and old_price > price_number else None
        row["affiliate_url"] = affiliate_url
        row["image_url"] = image_url
        row["category"] = category
        row["description"] = description
        row["valid_hours"] = valid_hours
        row["offer_id"] = make_offer_id(row)

        rows.append(row)

    print(f"[manual-marketplace] produtos válidos no CSV: {len(rows)}")

    for row in rows:
        print(
            f"[manual-marketplace] CSV: {row['offer_id']} | "
            f"{row['marketplace']} | {row['title']} | {row['price_text']} | {row['category']}"
        )

    return rows


def telegram_api(method, payload):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ausente.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")

    last_error = None

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)

            if not result.get("ok"):
                raise RuntimeError(f"Telegram retornou erro: {result}")

            return result

        except Exception as exc:
            last_error = exc
            print(f"[telegram-marketplace] tentativa {attempt}/3 falhou: {exc}")
            time.sleep(3 * attempt)

    raise last_error


def telegram_image_candidates(image_url):
    url = str(image_url or "").strip()

    if not url:
        return []

    candidates = []

    # Telegram costuma aceitar melhor JPG/PNG do que WEBP.
    if url.lower().endswith(".webp"):
        candidates.append(url[:-5] + ".jpg")
        candidates.append(url[:-5] + ".png")

    candidates.append(url)

    # Remove duplicados mantendo ordem.
    clean = []
    seen = set()

    for item in candidates:
        if item and item not in seen:
            clean.append(item)
            seen.add(item)

    return clean


def build_caption(row):
    marketplace = row["marketplace"]
    title = row["title"]
    url = row["affiliate_url"]
    price_text = row["price_text"]
    old_price_text = row.get("old_price_text") or ""
    discount_percent = row.get("discount_percent")
    description = row.get("description") or ""
    valid_hours = row.get("valid_hours") or DEFAULT_VALID_HOURS

    lines = []

    if old_price_text and discount_percent:
        lines.extend([
            f"🔥 {discount_percent}% OFF — Oferta {marketplace}!",
            "",
            f"📌 {title}",
            "",
            f"💸 De: {old_price_text}",
            "",
            f"🔥 Por: {price_text}",
        ])
    else:
        lines.extend([
            f"🔥 Oferta {marketplace}!",
            "",
            f"📌 {title}",
            "",
            f"🔥 Por: {price_text}",
        ])

    if description:
        lines.extend(["", description])

    lines.extend([
        "",
        f"🛒 Loja: {marketplace}",
        f"⏰ Oferta válida no site por até {valid_hours}h.",
        "",
        f"🛒 Comprar agora: {url}",
        "",
        AFFILIATE_DISCLOSURE,
    ])

    caption = "\n".join(lines).strip()

    if len(caption) > 1024:
        suffix = f"\n\n🛒 Comprar agora: {url}\n\n{AFFILIATE_DISCLOSURE}"
        allowed = 1024 - len(suffix) - 3
        caption = caption[:allowed].rstrip() + "..." + suffix

    return caption


def post_to_telegram(row):
    if DRY_RUN:
        print(f"[dry-run] Telegram publicaria: {row['offer_id']} | {row['title']}")
        print(build_caption(row))
        return

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID ausente.")

    caption = build_caption(row)
    image_url = row.get("image_url") or ""

    if image_url:
        for candidate in telegram_image_candidates(image_url):
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "photo": candidate,
                "caption": caption,
            }

            try:
                telegram_api("sendPhoto", payload)
                print(f"[telegram-marketplace] publicado com imagem: {row['offer_id']} | {row['title']} | {candidate}")
                return
            except Exception as exc:
                print(f"[telegram-marketplace] falha imagem {candidate}, tentando próxima/texto: {exc}")

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": caption,
        "disable_web_page_preview": False,
    }

    telegram_api("sendMessage", payload)
    print(f"[telegram-marketplace] publicado como texto: {row['offer_id']} | {row['title']}")


def github_request(method, url, token, payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub HTTP {exc.code}: {body}") from exc


def get_site_offers():
    if not SITE_REPO_TOKEN:
        raise RuntimeError("SITE_REPO_TOKEN ausente.")

    url = f"https://api.github.com/repos/{SITE_REPO}/contents/{SITE_FILE_PATH}?ref={SITE_BRANCH}"
    data = github_request("GET", url, SITE_REPO_TOKEN)

    raw = base64.b64decode(data.get("content", "")).decode("utf-8")
    sha = data.get("sha")
    offers = json.loads(raw)

    if not isinstance(offers, list):
        offers = []

    return offers, sha


def put_site_offers(offers, sha, message):
    content = json.dumps(offers, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    payload = {
        "message": message,
        "content": content_b64,
        "sha": sha,
        "branch": SITE_BRANCH,
    }

    url = f"https://api.github.com/repos/{SITE_REPO}/contents/{SITE_FILE_PATH}"
    return github_request("PUT", url, SITE_REPO_TOKEN, payload)


def build_site_offer(row):
    published_at = utc_now()
    expires_at = published_at + timedelta(hours=int(row.get("valid_hours") or DEFAULT_VALID_HOURS))

    offer = {
        "id": row["offer_id"],
        "manual_id": row["offer_id"],
        "source": "manual_marketplace_csv",
        "source_type": "manual_marketplace",
        "type": "product",

        "marketplace": row["marketplace"],
        "store": row["marketplace"],

        "title": row["title"],
        "description": row.get("description") or "",
        "category": row.get("category") or "Outros",

        "price": row["price_number"],
        "current_price": row["price_number"],
        "sale_price": row["price_number"],
        "price_text": row["price_text"],

        "old_price": row.get("old_price_number"),
        "original_price": row.get("old_price_number"),
        "old_price_text": row.get("old_price_text") or "",
        "discount_percent": row.get("discount_percent"),

        "image_url": row.get("image_url") or DEFAULT_IMAGE_URL,
        "image": row.get("image_url") or DEFAULT_IMAGE_URL,

        "url": row["affiliate_url"],
        "affiliate_url": row["affiliate_url"],
        "product_url": row["affiliate_url"],
        "link": row["affiliate_url"],

        "coupon": "",
        "score": 100,
        "currency": "BRL",

        "created_at": published_at.isoformat(),
        "created_at_iso": published_at.isoformat(),
        "created_ts": int(published_at.timestamp()),
        "published_at": published_at.isoformat(),
        "posted_at": published_at.isoformat(),
        "collected_at": published_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "valid_hours": int(row.get("valid_hours") or DEFAULT_VALID_HOURS),
    }

    return offer


def publish_to_site(rows):
    if DRY_RUN:
        print(f"[dry-run] Site publicaria {len(rows)} produto(s).")
        return

    if not rows:
        return

    existing, sha = get_site_offers()
    new_offers = [build_site_offer(row) for row in rows]

    new_ids = {o.get("id") for o in new_offers}
    new_urls = {o.get("affiliate_url") for o in new_offers if o.get("affiliate_url")}

    cleaned = []

    for offer in existing:
        oid = offer.get("id") or offer.get("manual_id")
        url = offer.get("affiliate_url") or offer.get("url") or offer.get("link") or ""

        if oid in new_ids:
            continue

        if url and url in new_urls:
            continue

        cleaned.append(offer)

    updated = new_offers + cleaned
    updated = updated[:500]

    put_site_offers(
        updated,
        sha,
        f"Publica {len(new_offers)} produto(s) manual(is) marketplace"
    )

    print(f"[site-marketplace] publicado(s) {len(new_offers)} produto(s) no site.")


def main():
    state = load_json(STATE_PATH, {"posted_ids": [], "site_ids": []})

    rows = read_rows()

    selected_for_telegram = [
        row for row in rows
        if is_due_for_repost(state, "posted_ids", row["offer_id"])
    ][:POST_COUNT]

    selected_for_site = [
        row for row in rows
        if is_due_for_repost(state, "site_ids", row["offer_id"])
    ][:POST_COUNT]

    print(f"[manual-marketplace] pendentes Telegram: {len(selected_for_telegram)}")
    print(f"[manual-marketplace] pendentes Site: {len(selected_for_site)}")

    if POST_TELEGRAM:
        for row in selected_for_telegram:
            post_to_telegram(row)

            if not DRY_RUN:
                mark_state(state, "posted_ids", row["offer_id"])
    else:
        print("[manual-marketplace] POST_TELEGRAM=false")

    if PUBLISH_SITE:
        publish_to_site(selected_for_site)

        if not DRY_RUN:
            for row in selected_for_site:
                mark_state(state, "site_ids", row["offer_id"])
    else:
        print("[manual-marketplace] PUBLISH_SITE=false")

    if not DRY_RUN:
        state["updated_at"] = iso_now()
        state["repost_hours"] = REPOST_HOURS
        save_json(STATE_PATH, state)

    print("[manual-marketplace] concluído.")


if __name__ == "__main__":
    main()
