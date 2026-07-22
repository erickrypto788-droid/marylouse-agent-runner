from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


@dataclass
class Product:
    marketplace: str
    id: str
    title: str
    price: Optional[float]
    url: str
    image_url: Optional[str] = None
    old_price: Optional[float] = None
    currency: str = "BRL"
    rating: Optional[float] = None
    sales_count: Optional[int] = None
    commission_rate: Optional[float] = None
    commission_value: Optional[float] = None
    shipping_text: Optional[str] = None
    category: Optional[str] = None
    affiliate_url: Optional[str] = None
    score: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def discount_percent(self) -> float:
        if self.price is None or self.old_price is None:
            return 0.0
        if self.old_price <= 0 or self.old_price <= self.price:
            return 0.0
        return round(((self.old_price - self.price) / self.old_price) * 100, 2)

    @property
    def key(self) -> str:
        return f"{self.marketplace}:{self.id}"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["discount_percent"] = self.discount_percent
        data["key"] = self.key
        return data


@dataclass
class OfferCopy:
    approved: bool
    title_short: str
    hook: str
    caption: str
    hashtags: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
