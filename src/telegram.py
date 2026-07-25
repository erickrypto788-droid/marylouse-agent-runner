from __future__ import annotations

import os
from typing import Any, Dict, Optional

import time

import requests

from .models import Product, OfferCopy



def _post_with_retry(url: str, payload: dict, attempts: int = 3, timeout: int = 60):
    last_exc = None

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            return resp
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            print(f"[telegram] Timeout ao postar. Tentativa {attempt}/{attempts}")

            if attempt < attempts:
                time.sleep(2 * attempt)
                continue

        except requests.exceptions.RequestException as exc:
            last_exc = exc
            print(f"[telegram] Falha de rede ao postar. Tentativa {attempt}/{attempts}: {exc}")

            if attempt < attempts:
                time.sleep(2 * attempt)
                continue

    raise last_exc


class TelegramClient:
    def __init__(self, cfg: Dict[str, Any]):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send_offer(self, product: Product, offer_copy: OfferCopy) -> Optional[str]:
        if not self.enabled:
            raise RuntimeError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID precisam estar configurados.")

        parse_mode = self.cfg.get("telegram", {}).get("parse_mode") or None
        disable_preview = bool(self.cfg.get("telegram", {}).get("disable_web_page_preview", False))

        # Caption de foto no Telegram tem limite menor; se passar de 1024, envia texto.
        if product.image_url and len(offer_copy.caption) <= 1024:
            payload: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "photo": product.image_url,
                "caption": offer_copy.caption,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            resp = _post_with_retry(self._url("sendPhoto"), payload, attempts=3, timeout=60)
        else:
            payload = {
                "chat_id": self.chat_id,
                "text": offer_copy.caption,
                "disable_web_page_preview": disable_preview,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            resp = _post_with_retry(self._url("sendMessage"), payload, attempts=3, timeout=60)

        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram retornou erro: {data}")
        message = data.get("result", {})
        return str(message.get("message_id")) if message.get("message_id") else None
