from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..config import AppConfig
from ..models import Candidate

log = logging.getLogger("ssqgl.steam")

_STEAM_FEATURED_CATEGORIES = "https://store.steampowered.com/api/featuredcategories"
_STEAM_SEARCH_RESULTS = "https://store.steampowered.com/search/results/"
_STEAM_APPDETAILS = "https://store.steampowered.com/api/appdetails"
_STEAM_APPREVIEWS = "https://store.steampowered.com/appreviews/{appid}"

_DSAPID_RE = re.compile(r'data-ds-appid="(\d+)"')


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


def _sha_int(s: str) -> int:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _extract_search_items(payload: dict) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    items = payload.get("items")
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get("name")
            logo = it.get("logo")
            if isinstance(name, str) and isinstance(logo, str) and "/apps/" in logo:
                try:
                    tail = logo.split("/apps/", 1)[1]
                    ap = int(tail.split("/", 1)[0])
                    out.append((ap, name))
                except Exception:
                    pass
        if out:
            return out

    html = payload.get("results_html")
    if isinstance(html, str):
        for m in _DSAPID_RE.finditer(html):
            try:
                ap = int(m.group(1))
                out.append((ap, f"Steam App {ap}"))
            except Exception:
                pass
    return out


def _request_json_with_retry(
    session: requests.Session,
    url: str,
    params: dict,
    timeout: int,
    tag: str,
    retry_cfg: dict,
) -> dict:
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


def steam_discover_candidates(cfg: AppConfig, day: date) -> List[Candidate]:
    if not cfg.sources.steam.enabled:
        return []

    dcfg = cfg.sources.steam.discovery or {}
    cc = str(dcfg.get("cc", "KR"))
    lang = str(dcfg.get("l", "koreana"))
    target = int(dcfg.get("target_appids", 5000))
    ttl = int(dcfg.get("cache_ttl_hours", 336))
    retry_cfg = dcfg.get("retry", {}) if isinstance(dcfg.get("retry"), dict) else {}

    channels = dcfg.get("channels", [])
    if not isinstance(channels, list) or not channels:
        channels = [
            {"kind": "featuredcategories", "bucket": "top_sellers", "take": 200},
            {"kind": "featuredcategories", "bucket": "new_releases", "take": 200},
            {"kind": "search", "filter": "popularnew", "start_mode": "sequential", "pages": 10, "count": 50, "take": 800},
            {"kind": "search", "filter": "popular", "start_mode": "random_deep", "pages": 30, "count": 50, "take": 2000, "max_start_blocks": 400},
        ]

    s = requests.Session()
    s.headers.update({"User-Agent": "ssqgl-gamepicker/0.2 (discovery)"})

    # small cache for discovery to avoid re-downloading the same search pages in one day
    cache = _Cache(Path(".cache") / "steam" / "discovery", ttl_hours=ttl)

    seed = cfg.seed_policy.template.format(date=day.isoformat(), phrase=cfg.seed_policy.phrase) + cfg.snapshot.seed_suffix
    rng = random.Random(_sha_int("disc|" + seed))

    by_appid: Dict[int, Candidate] = {}

    def upsert(appid: int, title: str, label: str, pop_hint: int, extra: dict):
        if appid not in by_appid:
            by_appid[appid] = Candidate(
                id=f"steam:{appid}",
                title=title,
                source="steam",
                url=f"https://store.steampowered.com/app/{appid}",
                app_type="Game",
                genres=[label],  # discovery label (later overwritten by real genres)
                tags=[],
                raw={
                    "discovery": [extra],
                    "pop_hint": pop_hint,
                },
            )
        else:
            c = by_appid[appid]
            if isinstance(c.raw, dict):
                c.raw.setdefault("discovery", []).append(extra)
                # keep the *lowest* pop_hint (0 is most popular/front)
                try:
                    c.raw["pop_hint"] = min(int(c.raw.get("pop_hint", 1)), int(pop_hint))
                except Exception:
                    c.raw["pop_hint"] = pop_hint

    log.info("Steam discovery start | target_appids=%d channels=%d", target, len(channels))

    for ci, ch in enumerate(channels, 1):
        if len(by_appid) >= target:
            break
        if not isinstance(ch, dict):
            continue

        kind = str(ch.get("kind", "")).strip()
        take = int(ch.get("take", 200))
        log.info("Steam channel [%d/%d] kind=%s take=%d", ci, len(channels), kind, take)

        if kind == "featuredcategories":
            bucket = str(ch.get("bucket", "top_sellers"))
            key = f"fc_{cc}_{lang}_{bucket}"
            data = cache.get_json(key)
            if data is None:
                data = _request_json_with_retry(
                    s, _STEAM_FEATURED_CATEGORIES, {"cc": cc, "l": lang}, 20, f"featuredcategories({bucket})", retry_cfg
                )
                cache.set_json(key, data)

            node = data.get(bucket)
            items = node.get("items") if isinstance(node, dict) else None
            if not isinstance(items, list):
                log.warning("  featuredcategories bucket=%s missing", bucket)
                continue

            label = f"FEATURED:{bucket}"
            pop_hint = 0
            got = 0
            for it in items:
                if got >= take or len(by_appid) >= target:
                    break
                if not isinstance(it, dict):
                    continue
                appid = _safe_int(it.get("id"))
                title = it.get("name")
                if appid is None or not isinstance(title, str):
                    continue
                upsert(appid, title, label, pop_hint, {"kind": "featuredcategories", "bucket": bucket})
                got += 1

            log.info("  featuredcategories bucket=%s -> added~=%d total=%d", bucket, got, len(by_appid))

        elif kind == "search":
            flt = str(ch.get("filter", "popular"))
            start_mode = str(ch.get("start_mode", "sequential"))
            pages = max(1, int(ch.get("pages", 1)))
            count = max(10, min(50, int(ch.get("count", 50))))
            max_blocks = max(1, int(ch.get("max_start_blocks", 160)))

            label = f"SEARCH:{flt}:{start_mode}"
            got_total = 0

            for pi in range(pages):
                if got_total >= take or len(by_appid) >= target:
                    break

                if start_mode in ("sequential", "front"):
                    start = pi * count
                    pop_hint = 0 if start == 0 else 1
                elif start_mode == "random_deep":
                    start = rng.randint(0, max_blocks) * 50
                    pop_hint = 2
                else:
                    start = pi * count
                    pop_hint = 1

                cache_key = f"sr_{cc}_{lang}_{flt}_{start}_{count}"
                payload = cache.get_json(cache_key)
                if payload is None:
                    payload = _request_json_with_retry(
                        s,
                        _STEAM_SEARCH_RESULTS,
                        {
                            "filter": flt,
                            "category1": "998",
                            "cc": cc,
                            "l": lang,
                            "start": str(start),
                            "count": str(count),
                            "json": "1",
                        },
                        25,
                        f"search({flt},start={start})",
                        retry_cfg,
                    )
                    cache.set_json(cache_key, payload)

                items = _extract_search_items(payload)
                log.info("  search page %d/%d start=%d -> got=%d", pi + 1, pages, start, len(items))

                for appid, title in items:
                    if got_total >= take or len(by_appid) >= target:
                        break
                    upsert(appid, title, label, pop_hint, {"kind": "search", "filter": flt, "start": start, "count": count})
                    got_total += 1

            log.info("  search filter=%s -> added~=%d total=%d", flt, got_total, len(by_appid))

        else:
            log.warning("  unknown channel kind=%s (skipped)", kind)

    out = list(by_appid.values())
    log.info("Steam discovery done | discovered=%d", len(out))
    return out


def steam_enrich_candidates(cfg: AppConfig, candidates: List[Candidate], day: date) -> Tuple[List[Candidate], dict]:
    """
    Enrich ONLY the steam candidates passed in. Caller should pass the shortlist subset.
    """
    if not candidates:
        return [], {"kept": 0, "dropped": 0}

    dcfg = cfg.sources.steam.discovery or {}
    ecfg = cfg.sources.steam.enrich or {}

    cc = str(dcfg.get("cc", "KR"))
    lang = str(dcfg.get("l", "koreana"))
    ttl = int(dcfg.get("cache_ttl_hours", 336))

    safety = dcfg.get("content_safety", {}) if isinstance(dcfg.get("content_safety"), dict) else {}
    max_required_age = int(safety.get("max_required_age", 17))
    exclude_desc = safety.get("exclude_content_descriptors", [1, 3, 4])
    if not isinstance(exclude_desc, list):
        exclude_desc = [1, 3, 4]
    exclude_desc_set = {int(x) for x in exclude_desc if _safe_int(x) is not None}

    min_interval = float(ecfg.get("request_min_interval_sec", 1.6))
    retry_cfg = ecfg.get("retry", {}) if isinstance(ecfg.get("retry"), dict) else {}

    cache_app = _Cache(Path(".cache") / "steam" / "appdetails", ttl_hours=ttl)
    cache_rev = _Cache(Path(".cache") / "steam" / "reviews", ttl_hours=ttl)

    s = requests.Session()
    s.headers.update({"User-Agent": "ssqgl-gamepicker/0.2 (enrich)"})

    last_call = 0.0

    def throttle():
        nonlocal last_call
        now = time.time()
        wait = (last_call + min_interval) - now
        if wait > 0:
            time.sleep(wait)
        last_call = time.time()

    kept: List[Candidate] = []
    dropped = 0
    cache_hit_app = cache_hit_rev = 0
    net_app = net_rev = 0

    total = len(candidates)
    log.info("Steam enrich start | total=%d min_interval=%.2fs", total, min_interval)

    for idx, c in enumerate(candidates, 1):
        try:
            appid = int(c.id.split(":", 1)[1])
        except Exception:
            dropped += 1
            continue

        log.info("Steam enrich [%d/%d] appid=%d", idx, total, appid)

        # preserve discovery label in raw
        if isinstance(c.raw, dict):
            c.raw.setdefault("discovery_label", _label := (c.genres[0] if c.genres else "Unknown"))

        # appdetails
        key_app = f"{appid}_{cc}_{lang}_filters_v2"
        payload = cache_app.get_json(key_app)
        if payload is None:
            net_app += 1
            throttle()
            payload = _request_json_with_retry(
                s,
                _STEAM_APPDETAILS,
                {
                    "appids": str(appid),
                    "cc": cc,
                    "l": lang,
                    "filters": "name,type,genres,metacritic,release_date,content_descriptors,required_age",
                },
                25,
                f"appdetails({appid})",
                retry_cfg,
            )
            cache_app.set_json(key_app, payload)
        else:
            cache_hit_app += 1

        node = payload.get(str(appid)) if isinstance(payload, dict) else None
        if not isinstance(node, dict) or not node.get("success"):
            dropped += 1
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            dropped += 1
            continue

        typ = data.get("type")
        if isinstance(typ, str) and typ.lower() != "game":
            dropped += 1
            continue

        required_age = _safe_int(data.get("required_age"))
        if required_age is not None and required_age > max_required_age:
            dropped += 1
            continue

        cd_list: List[int] = []
        cd = data.get("content_descriptors")
        if isinstance(cd, dict) and isinstance(cd.get("ids"), list):
            for x in cd["ids"]:
                xi = _safe_int(x)
                if xi is not None:
                    cd_list.append(xi)
        if exclude_desc_set.intersection(cd_list):
            dropped += 1
            continue

        # overwrite with real enriched fields
        c.title = str(data.get("name") or c.title)
        c.app_type = "Game"
        c.required_age = required_age
        c.content_descriptors = cd_list

        genres: List[str] = []
        if isinstance(data.get("genres"), list):
            for g in data["genres"]:
                if isinstance(g, dict) and g.get("description"):
                    genres.append(str(g["description"]))
        c.genres = genres or c.genres  # prefer enriched genres

        mc = data.get("metacritic")
        c.metascore = _safe_int(mc.get("score")) if isinstance(mc, dict) else c.metascore

        # reviews summary
        key_rev = f"{appid}_summary_v1"
        rev = cache_rev.get_json(key_rev)
        if rev is None:
            net_rev += 1
            throttle()
            rev = _request_json_with_retry(
                s,
                _STEAM_APPREVIEWS.format(appid=appid),
                {"json": "1", "filter": "summary", "language": "all"},
                25,
                f"reviews({appid})",
                retry_cfg,
            )
            cache_rev.set_json(key_rev, rev)
        else:
            cache_hit_rev += 1

        if isinstance(rev, dict) and isinstance(rev.get("query_summary"), dict):
            qs = rev["query_summary"]
            total_reviews = _safe_int(qs.get("total_reviews"))
            pos = _safe_int(qs.get("total_positive"))
            if total_reviews is not None and total_reviews > 0 and pos is not None:
                c.steam_review_count = total_reviews
                c.steam_positive_ratio = pos / total_reviews

        if isinstance(c.raw, dict):
            c.raw["steam_appdetails"] = data
            c.raw["steam_reviews"] = rev

        kept.append(c)

        if idx % 25 == 0 or idx == total:
            log.info(
                "Steam enrich progress | done=%d/%d kept=%d dropped=%d | appdetails(cache=%d net=%d) reviews(cache=%d net=%d)",
                idx, total, len(kept), dropped, cache_hit_app, net_app, cache_hit_rev, net_rev
            )

    stats = {
        "kept": len(kept),
        "dropped": dropped,
        "appdetails_cache": cache_hit_app,
        "appdetails_net": net_app,
        "reviews_cache": cache_hit_rev,
        "reviews_net": net_rev,
    }
    log.info("Steam enrich done | %s", stats)
    return kept, stats