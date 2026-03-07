from __future__ import annotations

import argparse
import json
import logging
import secrets
from datetime import date
from pathlib import Path

from .config import load_config
from .models import Snapshot
from .snapshot import build_snapshot, save_snapshot
from .picker import pick_one, save_run


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _load_snapshot(path: str) -> Snapshot:
    with open(path, "r", encoding="utf-8") as f:
        return Snapshot.from_dict(json.load(f))


def cmd_snapshot(args: argparse.Namespace) -> int:
    _setup_logging(args.verbose)
    log = logging.getLogger("ssqgl.cli")

    cfg = load_config(args.config)
    log.info("Snapshot start | config=%s", args.config)

    snap = build_snapshot(cfg, day=date.today())
    out_path = save_snapshot(snap, args.out)

    log.info("Snapshot saved | path=%s", out_path)
    log.info("Candidates=%d | Notes=%s", len(snap.candidates), snap.notes)
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    _setup_logging(args.verbose)
    log = logging.getLogger("ssqgl.cli")

    cfg = load_config(args.config)
    snap = _load_snapshot(args.snapshot)

    day = date.fromisoformat(args.date) if args.date else date.today()

    seed_override = None
    if args.ranseed:
        token = secrets.token_hex(8)  # 16 hex chars
        seed_override = f"rand|{day.isoformat()}|{token}"

    result = pick_one(cfg, snap, day=day, seed_override=seed_override)
    run_path = save_run(result, args.runs)

    k = result.stratum
    log.info("Picked=%s (%s)", result.picked.title, result.picked.id)
    log.info("Gate=%s | Stratum=(genre=%s,pop=%s,src=%s)", result.gate, k.genre, k.popularity_bin, k.source)
    log.info("Utility=%.3f | Seed=%s", result.utility, result.seed)
    log.info("Run saved | %s", run_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ssqgl", description="SSQGL GamePicker")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_snapshot = sub.add_parser("snapshot", help="Build a candidate snapshot")
    p_snapshot.add_argument("--config", required=True, help="Path to config.json")
    p_snapshot.add_argument("--out", default="snapshots", help="Output directory")
    p_snapshot.add_argument("--verbose", action="store_true", help="Verbose logging (DEBUG)")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_pick = sub.add_parser("pick", help="Pick one game from a snapshot")
    p_pick.add_argument("--config", required=True, help="Path to config.json")
    p_pick.add_argument("--snapshot", required=True, help="Path to snapshot JSON")
    p_pick.add_argument("--runs", default="runs", help="Output directory for run logs")
    p_pick.add_argument("--date", default=None, help="Override date (YYYY-MM-DD). Default: today")
    p_pick.add_argument("--ranseed", action="store_true", help="Use a random seed for this pick")
    p_pick.add_argument("--verbose", action="store_true", help="Verbose logging (DEBUG)")
    p_pick.set_defaults(func=cmd_pick)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    Path("snapshots").mkdir(exist_ok=True)
    Path("runs").mkdir(exist_ok=True)
    return args.func(args)