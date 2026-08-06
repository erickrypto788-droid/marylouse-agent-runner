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
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


CSV_PATH = Path(os.getenv("MANUAL_COUPONS_CSV", "data/manual_coupons.csv"))
STATE_PATH = Path(os.getenv("MANUAL_COUPONS_STATE", "data/manual_coupons_state.json"))

POST_COUNT = int(os.getenv("POST_COUNT", "3"))
POST_TELEGRAM = os.getenv("POST_TELEGRAM", "true").lower() == "true"
PUBLISH_SITE = os.getenv("PUBLISH_SITE", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

DEFAULT_VALID_HOURS = int(os.getenv("MANUAL_COUPON_VALID_HOURS", "24"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SITE_REPO = os.getenv("SITE_REPO", "erickrypto788-droid/marylouse-ofertas")
SITE_BRANCH = os.getenv("SITE_BRANCH", "main")
SITE_FILE_PATH = os.getenv("SITE_FILE_PATH", "data/offers.json")
SITE_REPO_TOKEN = os.getenv("SITE_REPO_TOKEN", "")

DEFAULT_IMAGE_URL = os.getenv(
    "MANUAL_COUPON_DEFAULT_IMAGE_URL",
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


def normalize_text(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def make_coupon_id(row):
    base = "|".join([
        normalize_text(row.get("marketplace")),
        normalize_text(row.get("title")),
        normalize_text(row.get("coupon")),
        normalize_text(row.get("affiliate_url")),
    ])
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"manual-coupon-{digest}"


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


def read_text_with_fallback(path):
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error = None

    raw = path.read_bytes()

    for enc in encodings:
        try:
            text = raw.decode(enc)
            print(f"[manual-coupons] CSV lido com encoding: {enc}")
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


def as_int(value, default):
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value).strip().replace(",", ".")))
    except Exception:
        return default


def read_rows():
    if not CSV_PATH.exists():
        print(f"[manual-coupons] CSV não encontrado: {CSV_PATH}")
        return []

    text = read_text_with_fallback(CSV_PATH)
    delimiter = detect_delimiter(text)

    print(f"[manual-coupons] CSV delimitador detectado: {repr(delimiter)}")

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    required = {"marketplace", "title", "affiliate_url"}
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

        marketplace = row.get("marketplace") or ""
        title = row.get("title") or ""
        affiliate_url = row.get("affiliate_url") or ""

        errors = []

        if not marketplace:
            errors.append("marketplace vazio")
        if not title:
            errors.append("title vazio")
        if not affiliate_url:
            errors.append("affiliate_url vazio")

        if errors:
            print(f"[manual-coupons] linha {line_number} ignorada: {', '.join(errors)}")
            continue

        row["coupon_id"] = make_coupon_id(row)
        row["valid_hours"] = as_int(row.get("valid_hours"), DEFAULT_VALID_HOURS)
        row["category"] = row.get("category") or "Cupons e Promoções"
        row["description"] = row.get("description") or "Confira o cupom disponível antes de finalizar sua compra."
        row["image_url"] = row.get("image_url") or DEFAULT_IMAGE_URL
        row["coupon"] = row.get("coupon") or ""

        rows.append(row)

    print(f"[manual-coupons] cupons válidos no CSV: {len(rows)}")

    for row in rows:
        print(
            f"[manual-coupons] CSV: {row['coupon_id']} | "
            f"{row.get('marketplace')} | {row.get('title')}"
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
            print(f"[telegram-coupon] tentativa {attempt}/3 falhou: {exc}")
            time.sleep(3 * attempt)

    raise last_error


def build_caption(row):
    marketplace = row["marketplace"]
    title = row["title"]
    coupon = row.get("coupon") or ""
    description = row.get("description") or ""
    url = row["affiliate_url"]
    valid_hours = row.get("valid_hours") or DEFAULT_VALID_HOURS

    lines = [
        f"🎟️ Cupom {marketplace} disponível!",
        "",
        f"📌 {title}",
        "",
    ]

    if description:
        lines.extend([description, ""])

    if coupon:
        lines.extend([
            f"🏷️ Cupom: {coupon}",
            "",
        ])

    lines.extend([
        f"🛒 Loja: {marketplace}",
        f"⏰ Válido no site por até {valid_hours}h.",
        "",
        f"👉 Pegar cupom: {url}",
        "",
        AFFILIATE_DISCLOSURE,
    ])

    caption = "\n".join(lines).strip()

    if len(caption) > 1024:
        suffix = f"\n\n👉 Pegar cupom: {url}\n\n{AFFILIATE_DISCLOSURE}"
        allowed = 1024 - len(suffix) - 3
        caption = caption[:allowed].rstrip() + "..." + suffix

    return caption


def post_to_telegram(row):
    if DRY_RUN:
        print(f"[dry-run] Telegram publicaria cupom: {row['coupon_id']} | {row['title']}")
        print(build_caption(row))
        return

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID ausente.")

    caption = build_caption(row)
    image_url = row.get("image_url") or ""

    if image_url:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": image_url,
            "caption": caption,
        }

        try:
            telegram_api("sendPhoto", payload)
            print(f"[telegram-coupon] publicado com imagem: {row['coupon_id']} | {row['title']}")
            return
        except Exception as exc:
            print(f"[telegram-coupon] falha ao enviar imagem, tentando texto: {exc}")

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": caption,
        "disable_web_page_preview": False,
    }

    telegram_api("sendMessage", payload)
    print(f"[telegram-coupon] publicado como texto: {row['coupon_id']} | {row['title']}")


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

    url = row["affiliate_url"]

    return {
        "id": row["coupon_id"],
        "manual_id": row["coupon_id"],
        "source": "manual_coupon_csv",
        "source_type": "manual_coupon",
        "type": "coupon",

        "marketplace": row["marketplace"],
        "store": row["marketplace"],

        "title": row["title"],
        "description": row.get("description") or "",
        "category": row.get("category") or "Cupons e Promoções",

        "coupon": row.get("coupon") or "",
        "price": "",
        "price_text": "",
        "old_price": "",
        "discount_percent": None,

        "image_url": row.get("image_url") or DEFAULT_IMAGE_URL,
        "image": row.get("image_url") or DEFAULT_IMAGE_URL,

        "url": url,
        "affiliate_url": url,
        "product_url": url,
        "link": url,

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


def publish_to_site(rows):
    if DRY_RUN:
        print(f"[dry-run] Site publicaria {len(rows)} cupom(ns).")
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
        f"Publica {len(new_offers)} cupom(ns) manual(is)"
    )

    print(f"[site-coupon] publicado(s) {len(new_offers)} cupom(ns) no site.")


def main():
    state = load_json(STATE_PATH, {"posted_ids": [], "site_ids": []})
    posted_ids = set(state.get("posted_ids") or [])
    site_ids = set(state.get("site_ids") or [])

    rows = read_rows()

    selected_for_telegram = [
        row for row in rows
        if row["coupon_id"] not in posted_ids
    ][:POST_COUNT]

    selected_for_site = [
        row for row in rows
        if row["coupon_id"] not in site_ids
    ][:POST_COUNT]

    print(f"[manual-coupons] pendentes Telegram: {len(selected_for_telegram)}")
    print(f"[manual-coupons] pendentes Site: {len(selected_for_site)}")

    if POST_TELEGRAM:
        for row in selected_for_telegram:
            post_to_telegram(row)

            if not DRY_RUN:
                posted_ids.add(row["coupon_id"])
    else:
        print("[manual-coupons] POST_TELEGRAM=false")

    if PUBLISH_SITE:
        publish_to_site(selected_for_site)

        if not DRY_RUN:
            for row in selected_for_site:
                site_ids.add(row["coupon_id"])
    else:
        print("[manual-coupons] PUBLISH_SITE=false")

    if not DRY_RUN:
        state["posted_ids"] = sorted(posted_ids)
        state["site_ids"] = sorted(site_ids)
        state["updated_at"] = iso_now()
        save_json(STATE_PATH, state)

    print("[manual-coupons] concluído.")


if __name__ == "__main__":
    main()
