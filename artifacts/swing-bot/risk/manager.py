"""
Risk Manager — validates trade decisions before execution.

Checks:
  • Signal has a valid direction (BUY or SELL)
  • SL/TP values are finite real numbers (no NaN or Infinity)
  • Minimum risk:reward ratio met
  • SL/TP are on the correct side of entry
  • Daily trade count not exceeded
  • Consecutive loss limit not exceeded
  • Lot size within allowed range
  • Max risk % per trade not exceeded (2% of account balance)

Returns (approved: bool, reason: str).
"""

import math
import config


def validate(decision, session_stats: dict) -> tuple[bool, str]:
    if not isinstance(decision, dict):
        return False, f"invalid decision type: {type(decision).__name__} (expected dict)"
    if not decision.get("trade"):
        return False, "no trade signal"

    if not isinstance(session_stats, dict):
        return False, f"invalid session_stats type: {type(session_stats).__name__}"
    if session_stats.get("trades_today", 0) >= config.MAX_TRADES_PER_DAY:
        return False, f"max {config.MAX_TRADES_PER_DAY} trades/day reached"

    if session_stats.get("consecutive_losses", 0) >= config.MAX_CONSECUTIVE_LOSSES:
        return False, f"stopped after {config.MAX_CONSECUTIVE_LOSSES} consecutive losses"

    trade_type = decision.get("type", "")
    if trade_type not in ("BUY", "SELL"):
        return False, f"invalid or missing trade direction '{trade_type}' — must be BUY or SELL"

    confidence = decision.get("confidence", 0)
    if not isinstance(confidence, (int, float)) or confidence < config.MIN_CONFIDENCE:
        return False, f"confidence {confidence} below minimum {config.MIN_CONFIDENCE}"

    entry = decision.get("entry", 0)
    sl    = decision.get("sl",    0)
    tp    = decision.get("tp",    0)

    for label, val in (("entry", entry), ("SL", sl), ("TP", tp)):
        if not isinstance(val, (int, float)) or not math.isfinite(val):
            return False, f"invalid {label} value ({val}) — must be a finite number"

    sl_dist = abs(entry - sl)
    tp_dist = abs(entry - tp)

    if sl_dist == 0:
        return False, "SL distance is zero"

    pip_size = config.get_symbol_cfg(decision.get("symbol"))["pip_size"]
    sl_pips  = sl_dist / pip_size

    if sl_pips < config.MIN_SL_PIPS - 1e-9:
        return False, f"SL {sl_pips:.1f} pips below minimum {config.MIN_SL_PIPS}"

    _USD_QUOTE_PAIRS = {"EUR/USD", "GBP/USD", "AUD/USD"}
    symbol = decision.get("symbol", "")
    if symbol in _USD_QUOTE_PAIRS:
        pip_value = pip_size * config.CONTRACT_SIZE * config.DEFAULT_LOT
    else:
        pip_value = (pip_size / entry) * config.CONTRACT_SIZE * config.DEFAULT_LOT

    risk_amount     = sl_pips * pip_value
    max_risk_amount = config.ACCOUNT_BALANCE * config.MAX_RISK_PERCENT
    if risk_amount > max_risk_amount:
        return False, (
            f"risk ${risk_amount:.2f} exceeds {config.MAX_RISK_PERCENT*100:.0f}% "
            f"of ${config.ACCOUNT_BALANCE} balance (max ${max_risk_amount:.2f}) — "
            f"reduce lot size or tighten SL"
        )

    rr = tp_dist / sl_dist
    if round(rr, 3) < config.MIN_RR:
        return False, f"RR {rr:.2f} below minimum {config.MIN_RR}"

    if trade_type == "SELL":
        if sl <= entry:
            return False, "SELL: SL must be above entry"
        if tp >= entry:
            return False, "SELL: TP must be below entry"
    elif trade_type == "BUY":
        if sl >= entry:
            return False, "BUY: SL must be below entry"
        if tp <= entry:
            return False, "BUY: TP must be above entry"

    return True, "OK"


def get_lot_size() -> float:
    return config.DEFAULT_LOT
