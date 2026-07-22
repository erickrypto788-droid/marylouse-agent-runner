from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from .base import Marketplace
from ..config import ROOT
from ..models import Product
from ..utils import normalize_rate, to_float, to_int


class CsvMarketplace(Marketplace):
    name = "csv"

    def fetch(self) -> List[Product]:
        mcfg = self.cfg.get("marketplaces", {}).get(self.name, {})
        if not mcfg.get("enabled", False):
            return []
        path = Path(mcfg.get("path", "data/products.csv"))
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            print(f"[csv] Arquivo não encontrado: {path}")
            return []

        products: List[Product] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                marketplace = (row.get("marketplace") or "csv").strip().lower()
                product_id = (row.get("id") or row.get("product_id") or row.get("url") or "").strip()
                if not product_id:
                    continue
                products.append(
                    Product(
                        marketplace=marketplace,
                        id=product_id,
                        title=(row.get("title") or row.get("product_name") or "").strip(),
                        price=to_float(row.get("price")),
                        old_price=to_float(row.get("old_price") or row.get("original_price")),
                        currency=(row.get("currency") or "BRL").strip(),
                        url=(row.get("url") or row.get("product_url") or "").strip(),
                        image_url=(row.get("image_url") or row.get("image") or "").strip() or None,
                        rating=to_float(row.get("rating")),
                        sales_count=to_int(row.get("sales_count") or row.get("sales")),
                        commission_rate=normalize_rate(row.get("commission_rate")),
                        shipping_text=(row.get("shipping_text") or row.get("shipping") or "").strip() or None,
                        category=(row.get("category") or "").strip() or None,
                        raw=row,
                    )
                )
        return products
