from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass
class Candidate:
    id: str                 # e.g., "steam:730"
    title: str
    source: str             # "steam", "gog", "local", ...
    url: Optional[str] = None

    app_type: Optional[str] = None   # "Game", "DLC", "Tool", ...
    genres: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    metascore: Optional[int] = None               # 0-100 (Steam Metacritic if present; GOG rating mapped if used)
    steam_review_count: Optional[int] = None
    steam_positive_ratio: Optional[float] = None  # 0..1
    release_date: Optional[date] = None

    # content safety / age gates (Steam appdetails 기반)
    required_age: Optional[int] = None
    content_descriptors: List[int] = field(default_factory=list)

    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.release_date is not None:
            d["release_date"] = self.release_date.isoformat()
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Candidate":
        rd = d.get("release_date")
        if isinstance(rd, str):
            try:
                y, m, dd = rd.split("-")
                d["release_date"] = date(int(y), int(m), int(dd))
            except Exception:
                d["release_date"] = None
        return Candidate(**d)


@dataclass
class Snapshot:
    created_at: str
    config_fingerprint: str
    candidates: List[Candidate]
    notes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created_at": self.created_at,
            "config_fingerprint": self.config_fingerprint,
            "notes": self.notes,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Snapshot":
        return Snapshot(
            created_at=d["created_at"],
            config_fingerprint=d["config_fingerprint"],
            notes=d.get("notes", {}),
            candidates=[Candidate.from_dict(x) for x in d.get("candidates", [])],
        )