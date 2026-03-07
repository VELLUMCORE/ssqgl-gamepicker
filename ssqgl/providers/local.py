from __future__ import annotations

import json
from typing import List, Optional

from .base import Provider
from ..config import AppConfig
from ..models import Candidate

class LocalProvider(Provider):
    name = "local"

    def fetch(self, cfg: AppConfig) -> List[Candidate]:
        if not cfg.sources.local.enabled:
            return []
        path: Optional[str] = cfg.sources.local.path
        if not path:
            return []
        if not path.lower().endswith(".json"):
            raise ValueError("Local provider MVP supports JSON only. Provide a .json file.")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "candidates" in data:
            items = data["candidates"]
        else:
            items = data
        
        out: List[Candidate] = []
        if not isinstance(items, list):
            raise ValueError("Local candidates must be a list.")
        for d in items:
            if not isinstance(d, dict):
                continue
            title = d.get("title") or d.get("name")
            cid = d.get("id")
            if not title or not cid:
                continue
            if ":" not in str("cid"):
                cid = f"local:{cid}"
            out.append(Candidate.from_dict({**d, "id": str(cid), "title": str(title), "source": "local"}))
        return out