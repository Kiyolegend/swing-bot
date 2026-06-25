import time as _time

STRUCT_API_BASE = "http://localhost:8001/trading-api"

# ── Active symbol (change this to switch which pair the engine scans) ─────────
SYMBOL = "USD/JPY"

# ── Symbol table — pip sizes and MT5 names for each supported pair ────────────
SYMBOL_CONFIG = {
    "USD/JPY": {"mt5_name": "USDJPYm", "pip_size": 0.01,   "digits": 3, "spread_pips": 1.0, "commission_pips": 1.0, "pip_value_per_lot": 6.50},
    "EUR/USD": {"mt5_name": "EURUSDm", "pip_size": 0.0001, "digits": 5, "spread_pips": 1.0, "commission_pips": 0.8, "pip_value_per_lot": 10.00},
    "GBP/USD": {"mt5_name": "GBPUSDm", "pip_size": 0.0001, "digits": 5, "spread_pips": 1.2, "commission_pips": 1.0, "pip_value_per_lot": 10.00},
    "EUR/JPY": {"mt5_name": "EURJPYm", "pip_size": 0.01,   "digits": 3, "spread_pips": 1.4, "commission_pips": 1.6, "pip_value_per_lot": 6.50},
    "GBP/JPY": {"mt5_name": "GBPJPYm", "pip_size": 0.01,   "digits": 3, "spread_pips": 3.5, "commission_pips": 2.2, "pip_value_per_lot": 6.50},
    "AUD/USD": {"mt5_name": "AUDUSDm", "pip_size": 0.0001, "digits": 5, "spread_pips": 1.2, "commission_pips": 0.9, "pip_value_per_lot": 10.00},
    "USD/CAD": {"mt5_name": "USDCADm", "pip_size": 0.0001, "digits": 5, "spread_pips": 1.5, "commission_pips": 1.4, "pip_value_per_lot": 7.30},
    "USD/CHF": {"mt5_name": "USDCHFm", "pip_size": 0.0001, "digits": 5, "spread_pips": 1.5, "commission_pips": 0.7, "pip_value_per_lot": 11.10},
}

# ── Disabled pairs — re-enable any by removing from this set ─────────────────
# Swing trading spreads are far less critical (wide SL absorbs cost easily),
# but keeping the same disabled list for consistency. Enable GBP/JPY and
# EUR/JPY with care — they move 150+ pips/day and need wider stops.
DISABLED_SYMBOLS = {"GBP/JPY", "EUR/JPY", "USD/CAD"}

def get_spread_pips(symbol: str = None) -> float:
    return SYMBOL_CONFIG.get(symbol or SYMBOL, SYMBOL_CONFIG["USD/JPY"]).get("spread_pips", 1.0)

def get_commission_pips(symbol: str = None) -> float:
    return SYMBOL_CONFIG.get(symbol or SYMBOL, SYMBOL_CONFIG["USD/JPY"]).get("commission_pips", 0.5)

def get_total_cost_pips(symbol: str = None) -> float:
    return get_spread_pips(symbol) + get_commission_pips(symbol)

SCAN_SYMBOLS = [s for s in SYMBOL_CONFIG.keys() if s not in DISABLED_SYMBOLS]

def get_symbol_cfg(symbol: str = None) -> dict:
    return SYMBOL_CONFIG.get(symbol or SYMBOL, SYMBOL_CONFIG["USD/JPY"])

MT5_SYMBOL = get_symbol_cfg()["mt5_name"]

# ── Account & position sizing ─────────────────────────────────────────────────
# Swing trades use wider stops (25-80 pips), so lot size must be smaller
# to keep risk within 2% of account balance.
# At 0.01 lot on USD/JPY: 1 pip = ~$0.065 → 50-pip SL = ~$3.25 (2.4% of $135)
# Adjust DEFAULT_LOT and ACCOUNT_BALANCE to match your real account.
ACCOUNT_BALANCE  = 145.0
DEFAULT_LOT      = 0.01
MAX_LOT          = 0.05
MAX_RISK_PERCENT = 0.02   # 2% per trade (swing SLs are wide — keep risk tight)
CONTRACT_SIZE    = 100000

# ── Trade quality gates ───────────────────────────────────────────────────────
# Swing trades need higher R:R to justify the multi-day hold and wider SL.
MIN_RR     = 3.0   # absolute minimum — strategies must offer at least 3:1
TARGET_RR  = 4.0   # preferred target used by force-fire fallback
NET_MIN_RR = 2.5   # after spread + commission deduction

# ── SL sizing ────────────────────────────────────────────────────────────────
# Swing SLs are placed beyond D1 structure — minimum 25 pips.
# Buffer is larger because D1/4H zones have more price noise than 5m.
MIN_SL_PIPS    = 25
SL_BUFFER_PIPS = 12

# ── Confidence & trade limits ─────────────────────────────────────────────────
MIN_CONFIDENCE      = 75   # swing setups are rarer — accept slightly lower bar
MAX_TRADES_PER_DAY  = 5   # one high-quality swing per session maximum
MAX_CONSECUTIVE_LOSSES = 2

# ── Engine scan interval ──────────────────────────────────────────────────────
# Swing trades develop on D1/4H — scanning every 5 minutes is plenty.
# Change to 900 (15 min) when running overnight.
LOOP_INTERVAL = 300   # seconds (5 minutes)

SIMULATION_MODE = True

NEAR_LEVEL_PIPS = 20   # wider proximity threshold for D1/4H S&R levels
PIP_SIZE = get_symbol_cfg()["pip_size"]


def get_broker_ts(state: dict) -> int:
    try:
        candles = (state.get("1h") or {}).get("candles") or []
        if candles:
            t = int(candles[-1]["time"])
            if t > 1_000_000_000:
                return t
    except Exception:
        pass
    try:
        import ntplib as _ntplib
        c = _ntplib.NTPClient()
        r = c.request("pool.ntp.org", version=3, timeout=2)
        return int(r.tx_time)
    except Exception:
        pass
    return int(_time.time())


def fib_extension_tp(state: dict, direction: str, entry: float) -> float | None:
    """127.2% Fibonacci extension TP using D1 swing. Returns None if swing data missing."""
    try:
        d1 = state.get("d1") or {}
        h4 = state.get("4h") or {}
        hi = d1.get("swing_hi") if (d1.get("swing_hi") and d1.get("swing_lo")) else h4.get("swing_hi")
        lo = d1.get("swing_lo") if (d1.get("swing_hi") and d1.get("swing_lo")) else h4.get("swing_lo")
        if not hi or not lo or hi <= lo:
            return None
        rng = hi - lo
        tp  = (hi + 0.272 * rng) if direction == "bullish" else (lo - 0.272 * rng)
        if direction == "bullish" and tp <= entry: return None
        if direction == "bearish" and tp >= entry: return None
        return round(tp, 5)
    except Exception:
        return None
    

SW4_NEAR_EXTREME_PIPS  = 50
SW4_MIN_CONFIDENCE     = 80
SW4_MIN_RR             = 4.0
SW4_SL_BUFFER_PIPS     = 15
SW4_TP_PRIMARY_FIB     = 0.382
SW4_TP_EXTENSION_FIB   = 0.618
