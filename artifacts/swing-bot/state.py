"""
State Builder — fetches all data from STRUCT.ai and builds a unified snapshot.

Swing edition: fetches 1H (entry TF) + 4H (structure) + D1 (bias/direction).
Also fetches 5M just for a fresh current price tick.
"""

import requests
from datetime import datetime, timezone
import config
from config import STRUCT_API_BASE
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

TIMEOUT = 15

# ── Zone visit tracker ────────────────────────────────────────────────────────
# Remembers per-symbol whether price has touched the D1 golden zone this swing.
# Stays True until a new swing_hi/swing_lo pair is detected (swing resets it).
_zone_cache: dict[str, bool]         = {}
_zone_cache_swing: dict[str, tuple]  = {}   # tracks which swing the flag belongs to

def _check_zone_visited(sym: str, price: float,
                        swing_hi: float, swing_lo: float, pip: float) -> bool:
    """Return True if price has touched the D1 golden zone (38.2–61.8%) this swing."""
    if not swing_hi or not swing_lo or swing_hi <= swing_lo:
        return False

    # If the swing has changed, reset the flag for this symbol
    current_swing = (round(swing_hi, 5), round(swing_lo, 5))
    if _zone_cache_swing.get(sym) != current_swing:
        _zone_cache[sym]       = False
        _zone_cache_swing[sym] = current_swing

    if _zone_cache.get(sym, False):
        return True   # already confirmed this swing — sticky

    rng         = swing_hi - swing_lo
    zone_top    = swing_hi - 0.382 * rng
    zone_bottom = swing_hi - 0.618 * rng
    BUFFER_PIPS = 10

    if (zone_bottom - BUFFER_PIPS * pip) <= price <= (zone_top + BUFFER_PIPS * pip):
        _zone_cache[sym] = True

    return _zone_cache.get(sym, False)


def _get(path: str, params: dict = None) -> dict | None:
    try:
        r = requests.get(f"{STRUCT_API_BASE}/{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] STRUCT.ai /{path} failed: {e}")
        return None


def _analysis(interval: str, outputsize: int = 200, symbol: str = None) -> dict | None:
    return _get("analysis", {"symbol": symbol or config.SYMBOL, "interval": interval, "outputsize": outputsize})


def get_active_sessions(reference_ts: int = None) -> list[str]:
    """Returns list of currently active sessions using broker time."""
    if reference_ts is not None:
        now_utc = datetime.fromtimestamp(reference_ts, tz=timezone.utc)
    else:
        now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    _ref_dt = datetime.fromtimestamp(reference_ts, tz=timezone.utc) if reference_ts else datetime.now(timezone.utc)
    lo = int(_ref_dt.astimezone(ZoneInfo("Europe/London")).utcoffset().total_seconds() // 3600)
    ny = int(_ref_dt.astimezone(ZoneInfo("America/New_York")).utcoffset().total_seconds() // 3600)
    sessions = []
    if 0 <= hour < 9:                sessions.append("asian")
    if (8 - lo) <= hour < (17 - lo): sessions.append("london")
    if (8 - ny) <= hour < (17 - ny): sessions.append("ny")
    return sessions


def is_tradeable_session(sessions: list[str]) -> bool:
    return any(s in sessions for s in ["london", "ny"])


def sanitize_state(state: dict) -> dict | None:
    """Validate and normalise a state dict. Returns None if fundamentally unusable."""
    import math
    if not isinstance(state, dict):
        return None

    price = state.get("current_price")
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None

    bias = state.get("bias") or {}
    state["bias"] = {
        "d1":  bias.get("d1")  or "neutral",
        "4h":  bias.get("4h")  or "neutral",
        "1h":  bias.get("1h")  or "neutral",
    }

    for tf in ("1h", "4h", "d1"):
        tf_data = state.get(tf) or {}
        state[tf] = {
            "trend":     tf_data.get("trend")     or "neutral",
            "structure": tf_data.get("structure") or [],
            "bos":       tf_data.get("bos")       or [],
            "choch":     tf_data.get("choch")      or [],
            "zones":     tf_data.get("zones") if isinstance(tf_data.get("zones"), list) else [],
            "candles":   tf_data.get("candles")    or [],
            "sr_levels": tf_data.get("sr_levels")  or [],
            "swing_hi":  tf_data.get("swing_hi"),
            "swing_lo":  tf_data.get("swing_lo"),
            "zone_visited": tf_data.get("zone_visited", False),
        }

    if "sr_levels" not in state:
        state["sr_levels"] = []
    if not isinstance(state.get("sessions"), list):
        state["sessions"] = []
    if "tradeable_session" not in state:
        state["tradeable_session"] = False

    return state


def build_state(symbol: str = None) -> dict | None:
    """Fetch all STRUCT.ai endpoints and return a unified state object.

    Swing TF priorities:
      5M  — current price tick only (cheapest live price)
      1H  — entry timeframe (OB/FVG/zone reaction)
      4H  — structure timeframe (BOS, S/R, swing points)
      D1  — bias timeframe (overall direction, major swing)

    NOTE: STRUCT.ai's /analysis endpoint uses the same intervals as the
    scalping engine. D1 maps to "d1" — if your Repo 1 version does not
    expose D1 yet, the engine falls back to 4H bias for direction.
    """
    sym = symbol or config.SYMBOL
    print(f"  Fetching {sym} from STRUCT.ai...", end=" ", flush=True)

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_bias = ex.submit(_get, "mtf-bias",   {"symbol": sym})
        f_5m   = ex.submit(_analysis, "5m",   50, sym)    # price tick only
        f_1h   = ex.submit(_analysis, "1h",  200, sym)    # entry TF
        f_4h   = ex.submit(_analysis, "4h",  150, sym)    # structure TF
        f_d1   = ex.submit(_analysis, "d1",   60, sym)    # bias TF (may be None if unsupported)
        f_sr   = ex.submit(_get, "sr-levels", {"symbol": sym, "outputsize": 300})

        bias = f_bias.result()
        a5m  = f_5m.result()
        a1h  = f_1h.result()
        a4h  = f_4h.result()
        a_d1 = f_d1.result()   # None if STRUCT.ai doesn't expose D1 yet
        sr   = f_sr.result()

    if not all([bias, a1h, a4h, sr]):
        print("FAILED — missing required data from STRUCT.ai")
        return None

    # Price: use 5M last close if available, otherwise 1H last close
    candles_price_src = (a5m or {}).get("candles") or a1h.get("candles", [])
    if not candles_price_src:
        print("FAILED — no candles for price")
        return None

    current_price = candles_price_src[-1].get("close")
    if not isinstance(current_price, (int, float)) or current_price <= 0:
        print("FAILED — invalid price")
        return None

    latest_ts = candles_price_src[-1].get("time")
    sessions  = get_active_sessions(reference_ts=latest_ts)

    # MTF bias — use D1 when available, fall back to 4H as the "highest" bias
    bias_d1  = (a_d1 or {}).get("trend", {}).get("trend") if a_d1 else None
    bias_4h  = bias.get("bias_4h",  {}).get("trend") or "neutral"
    bias_1h  = bias.get("bias_1h",  {}).get("trend") or "neutral"

    # Effective D1 direction: real D1 data > 4H MTF bias > neutral
    effective_d1 = bias_d1 or bias_4h or "neutral"

    # ── API contract guard ────────────────────────────────────────────────────
    _REQUIRED_1H = {"bos", "choch", "zones", "structure_labels", "candles"}
    _missing = _REQUIRED_1H - set(a1h.keys())
    if _missing:
        print(f"FAILED — Repo 1 /analysis response missing fields: {_missing}")
        return None

    print(
        f"OK  [price={current_price:.3f}  sessions={sessions}  "
        f"bias=D1:{effective_d1}/4H:{bias_4h}/1H:{bias_1h}]"
    )

    _d1_hi = (a_d1 or {}).get("trend", {}).get("last_high_price")
    _d1_lo = (a_d1 or {}).get("trend", {}).get("last_low_price")

    return sanitize_state({
        "symbol":            sym,
        "current_price":     current_price,
        "sessions":          sessions,
        "tradeable_session": is_tradeable_session(sessions),
        "reference_ts":      latest_ts,
        "bias": {
            "d1":  effective_d1,
            "4h":  bias_4h,
            "1h":  bias_1h,
        },
        "1h": {
            "trend":     a1h.get("trend", {}).get("trend", "neutral"),
            "structure": a1h.get("structure_labels", []),
            "bos":       a1h.get("bos", []),
            "choch":     a1h.get("choch", []),
            "zones":     a1h.get("zones", []),
            "candles":   a1h.get("candles", []),
        },
        "4h": {
            "trend":     a4h.get("trend", {}).get("trend", "neutral"),
            "structure": a4h.get("structure_labels", []),
            "bos":       a4h.get("bos", []),
            "choch":     a4h.get("choch", []),
            "zones":     a4h.get("zones", []),
            "candles":   a4h.get("candles", []),
            "swing_hi":  a4h.get("trend", {}).get("last_high_price"),
            "swing_lo":  a4h.get("trend", {}).get("last_low_price"),
        },
        "d1": {
            "trend":     effective_d1,
            "structure": (a_d1 or {}).get("structure_labels", []),
            "bos":       (a_d1 or {}).get("bos", []),
            "choch":     (a_d1 or {}).get("choch", []),
            "zones":     (a_d1 or {}).get("zones", []),
            "candles":   (a_d1 or {}).get("candles", []),
            "swing_hi":  _d1_hi if (_d1_hi and _d1_lo) else a4h.get("trend", {}).get("last_high_price"),
            "swing_lo":  _d1_lo if (_d1_hi and _d1_lo) else a4h.get("trend", {}).get("last_low_price"),
            "zone_visited": _check_zone_visited( 
                sym      = sym,
                price    = current_price,
                swing_hi = _d1_hi if (_d1_hi and _d1_lo) else a4h.get("trend", {}).get("last_high_price"),
                swing_lo = _d1_lo if (_d1_hi and _d1_lo) else a4h.get("trend", {}).get("last_low_price"),
                pip      = config.get_symbol_cfg(sym)["pip_size"],
            ),
        },
        "sr_levels": sr.get("levels", []),
    })
