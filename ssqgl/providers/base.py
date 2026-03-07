from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..config import AppConfig
from ..models import Candidate

class Provider(ABC):
    name: str

    @abstractmethod
    def fetch(self, cfg: AppConfig) -> List[Candidate]:
        raise NotImplementedError