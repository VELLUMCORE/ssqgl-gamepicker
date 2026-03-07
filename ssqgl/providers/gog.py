from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

from ..config import AppConfig
from ..models import Candidate

log = logging.getLogger("ssqgl.gog")

_GOG_FILTERED = "https://embed.gog.com/games/ajax/filtered"


def _epoch_to_date(ts: Optional[int]) -> Optional[date]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
    except Exception:
        return None


@dataclass
class _Cache:
    root: Path
    ttl_hours: int

    def get_json(self, key: str) -> Optional[dict]:
        p = self.root / f"{key}.json"
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            saved = obj.get("_saved_at")
            if not saved:
                return None
            saved_dt = datetime.fromisoformat(saved)
            age = datetime.now(timezone.utc) - saved_dt
            if age.total_seconds() > self.ttl_hours * 3600:
                return None
            return obj.get("data")
        except Exception:
            return None

    def set_json(self, key: str, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"_saved_at": datetime.now(timezone.utc).isoformat(), "data": data}
        (self.root / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _request_json_with_retry(session: requests.Session, url: str, params: dict, timeout: int, tag: str, retry_cfg: dict) -> dict:
    max_attempts = int(retry_cfg.get("max_attempts", 6))
    base_sleep = float(retry_cfg.get("base_sleep_sec", 1.0))
    max_sleep = float(retry_cfg.get("max_sleep_sec", 30.0))

    attempt = 0
    sleep = base_sleep
    while True:
        attempt += 1
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                raise requests.HTTPError(f"{tag} HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt >= max_attempts:
                log.warning("%s failed (final) | attempts=%d | err=%r", tag, attempt, e)
                raise
            log.warning("%s retry | attempt=%d/%d | sleep=%.1fs | err=%r", tag, attempt, max_attempts, sleep, e)
            time.sleep(min(max_sleep, sleep))
            sleep = min(max_sleep, sleep * 1.8)


def gog_discover_candidates(cfg: AppConfig, day: date) -> List[Candidate]:
    if not cfg.sources.gog.enabled:
        return []

    dcfg = cfg.sources.gog.discovery or {}
    target = int(dcfg.get("target_products", 1500))
    sorts = dcfg.get("sorts", ["popularity", "rating"])
    if not isinstance(sorts, list) or not sorts:
        sorts = ["popularity"]

    page_mode = str(dcfg.get("page_mode", "random"))
    limit = int(dcfg.get("limit", 48))
    ttl = int(dcfg.get("cache_ttl_hours", 336))

    max_pages_tried = int(dcfg.get("max_pages_tried", 250))
    random_page_max = int(dcfg.get("random_page_max", 120))

    retry_cfg = dcfg.get("retry", {}) if isinstance(dcfg.get("retry"), dict) else {}

    cache = _Cache(Path(".cache") / "gog" / "discovery", ttl_hours=ttl)
    s = requests.Session()
    s.headers.update({"User-Agent": "ssqgl-gamepicker/0.2 (gog discovery)"})

    seen: Set[str] = set()
    out: List[Candidate] = []

    seed_int = int(day.strftime("%Y%m%d"))
    log.info("GOG discovery start | target=%d sorts=%s", target, sorts)

    for sort in sorts:
        pages = 0
        while len(out) < target and pages < max_pages_tried:
            pages += 1
            if page_mode == "random":
                page = ((seed_int + pages * 17) % random_page_max) + 1
            else:
                page = pages

            key = f"filtered_{sort}_p{page}_l{limit}"
            data = cache.get_json(key)
            if data is None:
                log.info("GOG fetch | sort=%s page=%d (NET)", sort, page)
                data = _request_json_with_retry(
                    s,
                    _GOG_FILTERED,
                    {"mediaType": "game", "sort": sort, "page": page, "limit": limit},
                    25,
                    f"gog_filtered({sort},p{page})",
                    retry_cfg,
                )
                cache.set_json(key, data)
                time.sleep(0.2)

            products = data.get("products") if isinstance(data, dict) else None
            if not isinstance(products, list) or not products:
                log.info("GOG page empty | sort=%s page=%d stop", sort, page)
                break

            added = 0
            for p in products:
                if not isinstance(p, dict):
                    continue
                pid = p.get("id")
                title = p.get("title")
                url = p.get("url")
                if not pid or not title or not url:
                    continue
                cid = f"gog:{pid}"
                if cid in seen:
                    continue
                seen.add(cid)

                category = p.get("category")
                rating = p.get("rating")
                metascore = None
                if isinstance(rating, (int, float)):
                    metascore = max(0, min(100, int(round(float(rating) * 2))))

                # discovery label for stratification (real genres later are still "category" here)
                label = f"GOG:{category}" if category else "GOG:Unknown"
                pop_hint = 0 if sort == "popularity" else (1 if sort in ("rating", "date") else 1)

                out.append(
                    Candidate(
                        id=cid,
                        title=str(title),
                        source="gog",
                        url="https://www.gog.com" + str(url),
                        app_type="Game",
                        genres=[label],
                        tags=[],
                        metascore=metascore,
                        release_date=_epoch_to_date(p.get("releaseDate")),
                        raw={"gog_product": p, "pop_hint": pop_hint, "discovery": [{"sort": sort, "page": page}]},
                    )
                )
                added += 1
                if len(out) >= target:
                    break

            log.info("GOG progress | sort=%s page=%d added=%d total=%d/%d", sort, page, added, len(out), target)

    log.info("GOG discovery done | discovered=%d", len(out))
    return out