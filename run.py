#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from src.agent import run_once
from src.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram Affiliate Agent")
    parser.add_argument("--config", default=None, help="Caminho do config.yaml")
    parser.add_argument("--once", action="store_true", help="Executa uma rodada e finaliza")
    parser.add_argument("--dry-run", action="store_true", help="Força modo simulação, sem postar")
    parser.add_argument("--post", action="store_true", help="Força postagem real, equivalente a DRY_RUN=false")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.dry_run:
        cfg.setdefault("agent", {})["dry_run"] = True
    if args.post:
        cfg.setdefault("agent", {})["dry_run"] = False

    # Por enquanto o modo principal é execução única; agendamento pode ser feito por cron/n8n.
    result = run_once(cfg)
    print("\n[resultado]")
    print(json.dumps({k: v for k, v in result.items() if k != "posted"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
