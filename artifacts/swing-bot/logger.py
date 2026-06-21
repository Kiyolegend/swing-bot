"""
Trade Logger — logs every engine decision to console and file.
"""

import os
import json
from datetime import datetime, timezone

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _timestamp(broker_ts: float | None = None) -> str:
    dt = (datetime.fromtimestamp(broker_ts, tz=timezone.utc)
          if broker_ts else datetime.now(timezone.utc))
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _logfile(broker_ts: float | None = None) -> str:
    dt = (datetime.fromtimestamp(broker_ts, tz=timezone.utc)
          if broker_ts else datetime.now(timezone.utc))
    date = dt.strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"trades_{date}.jsonl")


def log_scan(state: dict, decision: dict | None):
    """Log one engine scan cycle."""
    price   = state.get("current_price", 0)
    bias    = state.get("bias", {})
    session = state.get("sessions", [])

    if decision and decision.get("trade"):
        tag = f"  ✅ SIGNAL: {decision['type']} | {decision['strategy']}"
    else:
        tag = "  ○  no signal"

    print(f"[{_timestamp()}]  price={price:.3f}  "
          f"D1={bias.get('d1','?'):8s}  4H={bias.get('4h','?'):8s}  "
          f"1H={bias.get('1h','?'):8s}  session={session}")
    print(tag)

    if decision and decision.get("trade"):
        print(f"     reason   : {decision.get('reason', '')}")
        print(f"     entry    : {decision.get('entry', 0):.3f}")
        print(f"     SL       : {decision.get('sl', 0):.3f}")
        print(f"     TP       : {decision.get('tp', 0):.3f}")
        print(f"     R:R      : {decision.get('rr', 0)}")
        print(f"     confidence: {decision.get('confidence', 0)}%")
    print()


def log_trade(decision: dict, executed: bool, mode: str = "SIMULATION", broker_ts: float | None = None):
    """Persist a trade decision to the daily log file."""
    entry = {
        "timestamp": _timestamp(broker_ts),
        "mode": mode,
        "executed": executed,
        **decision,
    }
    with open(_logfile(broker_ts), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_blocked(reason: str):
    print(f"  🔒 BLOCKED: {reason}\n")


def log_error(msg: str):
    print(f"  ❌ ERROR: {msg}\n")


def log_separator():
    print("─" * 70)
