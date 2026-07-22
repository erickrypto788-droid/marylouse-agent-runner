from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from ..models import Product


class Marketplace(ABC):
    name: str

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    @abstractmethod
    def fetch(self) -> List[Product]:
        raise NotImplementedError
