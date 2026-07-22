from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import OfferCopy, Product


class Storage:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posted_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_key TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                product_id TEXT NOT NULL,
                title TEXT NOT NULL,
                title_norm TEXT,
                url TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                affiliate_url TEXT,
                score REAL,
                caption TEXT,
                telegram_message_id TEXT,
                posted_at TEXT NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT
            )
            """
        )

        self._ensure_column("posted_products", "title_norm", "TEXT")

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posted_key ON posted_products(product_key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posted_hash ON posted_products(url_hash)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posted_at ON posted_products(posted_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posted_market_title ON posted_products(marketplace, title_norm)")

        # Preenche title_norm em registros antigos.
        rows = self.conn.execute(
            """
            SELECT id, title
            FROM posted_products
            WHERE title_norm IS NULL OR title_norm = ''
            """
        ).fetchall()

        for row in rows:
            self.conn.execute(
                "UPDATE posted_products SET title_norm = ? WHERE id = ?",
                (self.normalize_title(row["title"]), row["id"]),
            )

        self.conn.commit()

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    @staticmethod
    def url_hash(url: str) -> str:
        return hashlib.sha256((url or "").encode("utf-8")).hexdigest()

    @staticmethod
    def normalize_title(value: str) -> str:
        text = str(value or "").strip().lower()

        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")

        text = re.sub(r"[^a-z0-9À-ÿ]+", " ", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()

        # Mantém uma chave longa o bastante para diferenciar modelos,
        # mas curta o bastante para pegar duplicatas visuais.
        return text[:140]

    def was_recently_posted(self, product: Product, days: int) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        uhash = self.url_hash(product.url)
        title_norm = self.normalize_title(product.title)

        row = self.conn.execute(
            """
            SELECT id FROM posted_products
            WHERE dry_run = 0
              AND posted_at >= ?
              AND (
                    product_key = ?
                 OR url_hash = ?
                 OR (
                        marketplace = ?
                    AND title_norm = ?
                    AND title_norm IS NOT NULL
                    AND title_norm != ''
                 )
              )
            LIMIT 1
            """,
            (
                cutoff,
                product.key,
                uhash,
                product.marketplace,
                title_norm,
            ),
        ).fetchone()

        return row is not None

    def mark_posted(
        self,
        product: Product,
        offer_copy: OfferCopy,
        telegram_message_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        title_norm = self.normalize_title(product.title)

        self.conn.execute(
            """
            INSERT INTO posted_products
            (product_key, marketplace, product_id, title, title_norm, url, url_hash, affiliate_url, score,
             caption, telegram_message_id, posted_at, dry_run, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product.key,
                product.marketplace,
                product.id,
                product.title,
                title_norm,
                product.url,
                self.url_hash(product.url),
                product.affiliate_url,
                product.score,
                offer_copy.caption,
                telegram_message_id,
                datetime.now(timezone.utc).isoformat(),
                1 if dry_run else 0,
                json.dumps(product.raw, ensure_ascii=False, default=str),
            ),
        )

        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
