import base64
import csv
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone


CSV_PATH = os.getenv("MANUAL_OFFERS_CSV", "data/manual_offers.csv")
STATE_PATH = os.getenv("MANUAL_OFFERS_STATE", "data/manual_offers_state.json")

POST_COUNT = int(os.getenv("POST_COUNT", "3"))
POST_TELEGRAM = os.getenv("POST_TELEGRAM", "true").lower() == "true"
PUBLISH_SITE = os.getenv("PUBLISH_SITE", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

VALID_HOURS = int(os.getenv("MANUAL_VALID_HOURS", "24"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SITE_REPO = os.getenv("SITE_REPO", "erickrypto788-droid/marylouse-ofertas")
SITE_BRANCH = os.getenv("SITE_BRANCH", "main")
SITE_FILE_PATH = os.getenv("SITE_FILE_PATH", "data/offers.json")
SITE_REPO_TOKEN = os.getenv("SITE_REPO_TOKEN", "")

MARKETPLACE = "Amazon"

AFFILIATE_DISCLOSURE = os.getenv(
    "AFFILIATE_DISCLOSURE",
    "Aviso: como afiliados, podemos receber comissão por compras feitas pelos links."
)

BR_TZ = timezone(timedelta(hours=-3))


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
        return dt
    except Exception:
        return None


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_price(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("R$", "").replace("r$", "").strip()
    text = text.replace(" ", "")

    if "," in text and "." in text:
        # Exemplo: 1.299,90
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        # Exemplo: 199,90
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

    text = f"{value:,.2f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def normalize_text(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def make_offer_id(row):
    base = normalize_text(row.get("affiliate_url") or row.get("title"))
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"manual-amazon-{digest}"


def auto_category(title):
    text = normalize_text(title)

    rules = [
        ("Celulares", [
            "celular", "smartphone", "iphone", "galaxy", "xiaomi", "motorola",
            "carregador celular", "capinha", "pelicula", "película"
        ]),
        ("Informática", [
            "notebook", "mouse", "teclado", "monitor", "ssd", "hd externo",
            "roteador", "impressora", "webcam", "headset gamer", "cadeira gamer"
        ]),
        ("Eletrônicos", [
            "echo", "alexa", "fire tv", "kindle", "fone", "bluetooth", "caixa de som",
            "speaker", "smartwatch", "tablet", "tv stick", "controle remoto"
        ]),
        ("Casa e Cozinha", [
            "air fryer", "panela", "frigideira", "cafeteira", "liquidificador",
            "batedeira", "mixer", "aspirador", "organizador", "garrafa", "copo",
            "jogo de cama", "toalha", "tapete", "luminária", "lampada", "lâmpada"
        ]),
        ("Eletrodomésticos", [
            "micro-ondas", "microondas", "geladeira", "fogão", "cooktop",
            "lavadora", "máquina de lavar", "ar condicionado", "ventilador"
        ]),
        ("Beleza", [
            "perfume", "hidratante", "shampoo", "condicionador", "secador",
            "chapinha", "barbeador", "maquiagem", "creme", "protetor solar"
        ]),
        ("Mãe e Bebê", [
            "fralda", "bebê", "bebe", "mamadeira", "chupeta", "lenço umedecido",
            "lenco umedecido", "carrinho de bebê", "cadeirinha"
        ]),
        ("Pet", [
            "ração", "racao", "pet", "cachorro", "gato", "areia higiênica",
            "areia higienica", "brinquedo pet"
        ]),
        ("Games", [
            "playstation", "ps5", "xbox", "nintendo", "controle gamer",
            "jogo", "games", "console"
        ]),
        ("Ferramentas", [
            "furadeira", "parafusadeira", "chave de fenda", "kit ferramentas",
            "serra", "trena", "martelo"
        ]),
        ("Papelaria", [
            "caneta", "caderno", "mochila escolar", "estojo", "agenda",
            "marca texto", "papel sulfite"
        ]),
        ("Esportes", [
            "halter", "bicicleta", "esteira", "academia", "bola", "tenis corrida",
            "tênis corrida", "garrafa térmica"
        ]),
        ("Moda Feminina", [
            "vestido", "blusa feminina", "calça feminina", "bolsa feminina"
        ]),
        ("Moda Masculina", [
            "camiseta masculina", "calça masculina", "bermuda masculina"
        ]),
        ("Calçados", [
            "tênis", "tenis", "sandália", "sandalia", "sapato", "chinelo", "bota"
        ]),
    ]

    for category, keywords in rules:
        for keyword in keywords:
            if keyword in text:
                return category

    return "Outros"


def read_csv_rows():
    if not os.path.exists(CSV_PATH):
        print(f"[manual] CSV não encontrado: {CSV_PATH}")
        return []

    rows = []

    with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required_columns = {"title", "price", "image_url", "affiliate_url"}
        current_columns = set(reader.fieldnames or [])

        missing = required_columns - current_columns
        if missing:
            raise RuntimeError(f"CSV sem colunas obrigatórias: {', '.join(sorted(missing))}")

        for line_number, row in enumerate(reader, start=2):
            row = {
                str(k).strip(): (v.strip() if isinstance(v, str) else v)
                for k, v in row.items()
            }

            title = row.get("title") or ""
            price = parse_price(row.get("price"))
            image_url = row.get("image_url") or ""
            affiliate_url = row.get("affiliate_url") or ""

            if not title and not affiliate_url:
                continue

            errors = []

            if not title:
                errors.append("title vazio")
            if price is None:
                errors.append("price inválido")
            if not image_url:
                errors.append("image_url vazio")
            if not affiliate_url:
                errors.append("affiliate_url vazio")

            if errors:
                print(f"[manual] linha {line_number} ignorada: {', '.join(errors)}")
                continue

            row["price_number"] = price
            row["price_text"] = format_brl(price)
            row["category"] = auto_category(title)
            row["offer_id"] = make_offer_id(row)

            rows.append(row)

    return rows


def telegram_api(method, payload):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ausente")

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

        except Exception as e:
            last_error = e
            print(f"[telegram] tentativa {attempt}/3 falhou: {e}")
            time.sleep(3 * attempt)

    raise last_error


def build_caption(row):
    title = row["title"]
    price_text = row["price_text"]
    category = row["category"]

    expires_at = utc_now() + timedelta(hours=VALID_HOURS)
    expires_local = expires_at.astimezone(BR_TZ).strftime("%d/%m às %H:%M")

    lines = [
        f"🔥 {title}",
        "",
        f"💰 Por: {price_text}",
        "",
        "🛒 Loja: Amazon",
        f"📌 Categoria: {category}",
        "",
        f"⏰ Oferta válida no site por até {VALID_HOURS}h.",
        f"⚠️ Preço conferido no momento da publicação e pode mudar a qualquer momento.",
        AFFILIATE_DISCLOSURE,
    ]

    caption = "\n".join(lines).strip()

    if len(caption) > 1000:
        caption = caption[:997] + "..."

    return caption


def post_to_telegram(row):
    if DRY_RUN:
        print(f"[dry-run] Telegram publicaria: {row['offer_id']} | {row['title']}")
        return

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID ausente")

    affiliate_url = row["affiliate_url"]
    image_url = row["image_url"]
    caption = build_caption(row)

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "Comprar na Amazon",
                    "url": affiliate_url
                }
            ]
        ]
    }

    photo_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": caption,
        "reply_markup": keyboard,
    }

    try:
        telegram_api("sendPhoto", photo_payload)
        print(f"[telegram] publicado com imagem: {row['offer_id']} | {row['title']}")
        return
    except Exception as e:
        print(f"[telegram] falha ao enviar imagem, tentando texto: {e}")

    text_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"{caption}\n\n{affiliate_url}",
        "reply_markup": keyboard,
        "disable_web_page_preview": False,
    }

    telegram_api("sendMessage", text_payload)
    print(f"[telegram] publicado como texto: {row['offer_id']} | {row['title']}")


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

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub HTTP {e.code}: {body}") from e


def get_site_offers():
    if not SITE_REPO_TOKEN:
        raise RuntimeError("SITE_REPO_TOKEN ausente")

    url = f"https://api.github.com/repos/{SITE_REPO}/contents/{SITE_FILE_PATH}?ref={SITE_BRANCH}"
    data = github_request("GET", url, SITE_REPO_TOKEN)

    content_b64 = data.get("content", "")
    sha = data.get("sha")

    raw = base64.b64decode(content_b64).decode("utf-8")
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


def is_manual_offer(offer):
    source = str(offer.get("source") or "").lower()
    source_type = str(offer.get("source_type") or "").lower()
    manual_id = str(offer.get("manual_id") or "")

    return (
        "manual" in source
        or "manual" in source_type
        or manual_id.startswith("manual-amazon-")
    )


def is_expired_manual_offer(offer):
    if not is_manual_offer(offer):
        return False

    expires_at = parse_iso(offer.get("expires_at"))
    if not expires_at:
        return False

    return utc_now() > expires_at


def build_site_offer(row):
    published_at = utc_now()
    expires_at = published_at + timedelta(hours=VALID_HOURS)

    image_url = row["image_url"]
    affiliate_url = row["affiliate_url"]
    price = row["price_number"]

    offer = {
        "id": row["offer_id"],
        "manual_id": row["offer_id"],
        "source": "manual_csv",
        "source_type": "manual_csv",

        "marketplace": MARKETPLACE,
        "store": MARKETPLACE,

        "title": row["title"],
        "description": f"Oferta Amazon selecionada manualmente. Preço conferido no momento da publicação.",
        "category": row["category"],

        "price": price,
        "current_price": price,
        "sale_price": price,
        "price_text": row["price_text"],

        "image_url": image_url,
        "image": image_url,

        "url": affiliate_url,
        "affiliate_url": affiliate_url,
        "product_url": affiliate_url,
        "link": affiliate_url,

        "coupon": "",
        "score": 100,
        "currency": "BRL",

        "created_at": published_at.isoformat(),
        "published_at": published_at.isoformat(),
        "posted_at": published_at.isoformat(),
        "collected_at": published_at.isoformat(),
        "expires_at": expires_at.isoformat(),

        "valid_hours": VALID_HOURS,
        "disclaimer": "Preço conferido no momento da publicação e pode mudar a qualquer momento.",
    }

    return offer


def merge_site_offers(existing_offers, new_rows):
    new_offers = [build_site_offer(row) for row in new_rows]

    new_ids = {offer.get("id") for offer in new_offers}
    new_urls = {
        offer.get("affiliate_url")
        for offer in new_offers
        if offer.get("affiliate_url")
    }
    new_titles = {
        normalize_text(offer.get("title"))
        for offer in new_offers
        if offer.get("title")
    }

    cleaned = []
    removed_expired = 0
    removed_duplicates = 0

    for offer in existing_offers:
        if is_expired_manual_offer(offer):
            removed_expired += 1
            continue

        offer_id = offer.get("id") or offer.get("manual_id")
        offer_url = offer.get("affiliate_url") or offer.get("url") or offer.get("link") or ""
        offer_title = normalize_text(offer.get("title"))

        if offer_id in new_ids:
            removed_duplicates += 1
            continue

        if offer_url and offer_url in new_urls:
            removed_duplicates += 1
            continue

        if offer_title and offer_title in new_titles:
            removed_duplicates += 1
            continue

        cleaned.append(offer)

    updated = new_offers + cleaned

    max_offers = int(os.getenv("SITE_MAX_OFFERS", "400"))
    updated = updated[:max_offers]

    return updated, len(new_offers), removed_expired, removed_duplicates


def publish_to_site(rows):
    if DRY_RUN:
        print(f"[dry-run] Site publicaria {len(rows)} oferta(s).")
        for row in rows:
            print(f"[dry-run] Site: {row['offer_id']} | {row['title']} | {row['price_text']}")
        return

    if not PUBLISH_SITE:
        return

    for attempt in range(1, 4):
        try:
            existing_offers, sha = get_site_offers()
            updated, added, removed_expired, removed_duplicates = merge_site_offers(existing_offers, rows)

            old_json = json.dumps(existing_offers, ensure_ascii=False, sort_keys=True)
            new_json = json.dumps(updated, ensure_ascii=False, sort_keys=True)

            if old_json == new_json:
                print("[site] nada para atualizar.")
                return

            message = (
                f"Publica {added} oferta(s) manuais Amazon via CSV "
                f"e remove {removed_expired} expirada(s)"
            )

            put_site_offers(updated, sha, message)

            print(
                f"[site] atualizado. novas={added}, "
                f"expiradas_removidas={removed_expired}, "
                f"duplicadas_removidas={removed_duplicates}"
            )
            return

        except Exception as e:
            print(f"[site] tentativa {attempt}/3 falhou: {e}")
            if attempt >= 3:
                raise
            time.sleep(5 * attempt)


def main():
    state = load_json(STATE_PATH, {"posted_ids": [], "site_ids": []})

    posted_ids = set(state.get("posted_ids") or [])
    site_ids = set(state.get("site_ids") or [])

    rows = read_csv_rows()

    print(f"[manual] ofertas válidas no CSV: {len(rows)}")

    if not rows:
        print("[manual] nenhuma oferta válida encontrada.")
        return 0

    for row in rows:
        print(
            f"[manual] CSV: {row['offer_id']} | "
            f"{row['title']} | {row['price_text']} | {row['category']}"
        )

    selected_for_telegram = [
        row for row in rows
        if row["offer_id"] not in posted_ids
    ][:POST_COUNT]

    selected_for_site = [
        row for row in rows
        if row["offer_id"] not in site_ids
    ][:POST_COUNT]

    print(f"[manual] pendentes Telegram: {len(selected_for_telegram)}")
    print(f"[manual] pendentes Site: {len(selected_for_site)}")

    if POST_TELEGRAM:
        for row in selected_for_telegram:
            post_to_telegram(row)
            if not DRY_RUN:
                posted_ids.add(row["offer_id"])
    else:
        print("[manual] POST_TELEGRAM=false, não vai postar no Telegram.")

    if PUBLISH_SITE:
        publish_to_site(selected_for_site)
        if not DRY_RUN:
            for row in selected_for_site:
                site_ids.add(row["offer_id"])
    else:
        print("[manual] PUBLISH_SITE=false, não vai publicar no site.")

    if not DRY_RUN:
        state["posted_ids"] = sorted(posted_ids)
        state["site_ids"] = sorted(site_ids)
        state["updated_at"] = iso_now()
        save_json(STATE_PATH, state)
        print(f"[manual] estado salvo em {STATE_PATH}")
    else:
        print("[dry-run] estado não foi alterado.")

    print("[manual] concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
