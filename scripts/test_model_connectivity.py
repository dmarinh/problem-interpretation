# -*- coding: utf-8 -*-
"""
Model Connectivity Test

Quick smoke-test for every model in benchmarks/config.py.
Sends a trivial "ping" prompt and reports success, latency, and failure reason.

Usage:
    python scripts/test_model_connectivity.py
    python scripts/test_model_connectivity.py --tier 4       # local only
    python scripts/test_model_connectivity.py --model "Claude Haiku 4.5"
"""

import asyncio
import argparse
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from benchmarks.config import MODELS

PING_PROMPT = "Reply with exactly one word: ready"

# ANSI colours (disabled on non-TTY)
_USE_COLOUR = sys.stdout.isatty()
GREEN  = "\033[32m" if _USE_COLOUR else ""
RED    = "\033[31m" if _USE_COLOUR else ""
YELLOW = "\033[33m" if _USE_COLOUR else ""
RESET  = "\033[0m"  if _USE_COLOUR else ""


async def ping_model(model_config: dict) -> dict:
    """Send a single minimal completion and return a status dict."""
    import litellm

    name        = model_config["name"]
    lm          = model_config["litellm_model"]
    env_var     = model_config.get("api_key_env_var")
    api_base    = model_config.get("api_base")

    api_key = os.getenv(env_var) if env_var else None
    if env_var and not api_key:
        return {
            "name": name,
            "litellm_model": lm,
            "status": "SKIP",
            "reason": f"env var {env_var} not set",
            "latency_s": None,
        }

    kwargs: dict = {
        "model": lm,
        "messages": [{"role": "user", "content": PING_PROMPT}],
        "max_tokens": 10,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base

    t0 = time.perf_counter()
    try:
        resp = await litellm.acompletion(**kwargs)
        latency = time.perf_counter() - t0
        raw = resp.choices[0].message.content
        reply = raw.strip() if raw else "(empty — likely thinking-only response)"
        return {
            "name": name,
            "litellm_model": lm,
            "status": "OK",
            "reason": repr(reply),
            "latency_s": round(latency, 2),
        }
    except Exception as exc:
        latency = time.perf_counter() - t0
        return {
            "name": name,
            "litellm_model": lm,
            "status": "FAIL",
            "reason": f"{type(exc).__name__}: {exc}",
            "latency_s": round(latency, 2),
        }


def _status_line(r: dict) -> str:
    status = r["status"]
    if status == "OK":
        colour, symbol = GREEN, "OK  "
    elif status == "SKIP":
        colour, symbol = YELLOW, "SKIP"
    else:
        colour, symbol = RED, "FAIL"

    lat = f"  {r['latency_s']:.2f}s" if r["latency_s"] is not None else ""
    return (
        f"  {colour}[{symbol}]{RESET}  "
        f"{r['name']:<26}  {r['litellm_model']:<45}"
        f"{lat}\n"
        f"          {r['reason']}"
    )


async def main(tiers: list[int] | None, model_name: str | None):
    candidates = MODELS
    if tiers:
        candidates = [m for m in candidates if m.get("tier") in tiers]
    if model_name:
        candidates = [m for m in candidates if m["name"] == model_name]

    if not candidates:
        print("No models matched the filter.")
        return

    print(f"\nPinging {len(candidates)} model(s)...\n")

    # Run all pings concurrently
    results = await asyncio.gather(*(ping_model(m) for m in candidates))

    ok   = [r for r in results if r["status"] == "OK"]
    fail = [r for r in results if r["status"] == "FAIL"]
    skip = [r for r in results if r["status"] == "SKIP"]

    for r in results:
        print(_status_line(r))
        print()

    print("─" * 60)
    print(
        f"  {GREEN}OK{RESET} {len(ok)}   "
        f"{RED}FAIL{RESET} {len(fail)}   "
        f"{YELLOW}SKIP{RESET} {len(skip)}"
    )
    if fail:
        print(f"\n{RED}Failed models need attention before running benchmarks.{RESET}")
    if skip:
        print(f"{YELLOW}Skipped models: add the missing API key(s) to .env to include them.{RESET}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test connectivity for benchmark models")
    parser.add_argument(
        "--tier", type=int, action="append", dest="tiers",
        metavar="N", help="Only test tier N (repeatable, e.g. --tier 1 --tier 4)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        metavar="NAME", help='Test only this model by display name (e.g. "Claude Haiku 4.5")'
    )
    args = parser.parse_args()
    asyncio.run(main(tiers=args.tiers, model_name=args.model))
