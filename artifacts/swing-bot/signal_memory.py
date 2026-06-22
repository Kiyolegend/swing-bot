"""
Signal Memory — prevents the same setup firing more than once per session.

Stores one key PER SYMBOL PER STRATEGY so that:
  - parallel multi-symbol scanning doesn't overwrite keys across symbols, and
  - one strategy firing for a symbol doesn't erase the memory of a different
    strategy that already fired for the same symbol.
"""

import json
import os
import threading


class SignalMemory:
    def __init__(self):
        self._path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_memory.json")
        self._lock = threading.Lock()
        self._keys: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self):
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and "keys" in data:
                raw = data["keys"]
                self._keys = {}
                for sym, val in raw.items():
                    if isinstance(val, dict) and all(
                        isinstance(v, dict) and "key" in v
                        for v in val.values()
                    ):
                        self._keys[sym] = {
                            strat: {"key": tuple(v["key"]), "bias": v["bias"]}
                            for strat, v in val.items()
                            if v.get("key")
                        }
                    elif isinstance(val, dict) and "key" in val and val.get("key"):
                        k = tuple(val["key"])
                        strat = k[1] if len(k) > 1 else ""
                        self._keys[sym] = {
                            strat: {"key": k, "bias": val.get("bias")}
                        }
        except Exception:
            self._keys = {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump({"keys": {
                    sym: {
                        strat: {"key": list(v["key"]), "bias": v["bias"]}
                        for strat, v in strategies.items()
                    }
                    for sym, strategies in self._keys.items()
                }}, f)
        except Exception:
            pass

    def _make_key(self, decision: dict) -> tuple:
        swing_hi = decision.get("swing_hi", 0)
        swing_lo = decision.get("swing_lo", 0)
        return (
            decision.get("symbol", ""),
            decision.get("strategy", ""),
            decision.get("type", ""),
            round(swing_hi, 3),
            round(swing_lo, 3),
       )

    def is_duplicate(self, decision: dict, state: dict) -> bool:
        with self._lock:
            symbol      = decision.get("symbol", "")
            strategy    = decision.get("strategy", "")
            sym_entries = self._keys.get(symbol)
            if sym_entries is None:
                return False
            entry = sym_entries.get(strategy)
            if entry is None:
                return False
            new_key  = self._make_key(decision)
            new_bias = state.get("bias", {}).get("4h", "neutral")
            if new_key != entry["key"]:
                return False
            if new_bias != entry["bias"]:
                sym_entries.pop(strategy, None)
                if not sym_entries:
                    del self._keys[symbol]
                self._save()
                return False
            return True

    def record(self, decision: dict, state: dict):
        with self._lock:
            sym      = decision.get("symbol", "")
            strategy = decision.get("strategy", "")
            if sym not in self._keys:
                self._keys[sym] = {}
            self._keys[sym][strategy] = {
                "key":  self._make_key(decision),
                "bias": state.get("bias", {}).get("4h", "neutral"),
            }
            self._save()

    def clear(self):
        with self._lock:
            self._keys = {}
            self._save()
