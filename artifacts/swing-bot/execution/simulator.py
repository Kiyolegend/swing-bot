"""
Simulator — prints what would be executed in a live environment.
Used when SIMULATION_MODE = True in config.
"""


def place_order(decision: dict, lot: float) -> bool:
    if not isinstance(lot, (int, float)) or lot <= 0:
        print(f"\n  ❌ SIMULATION — rejected: invalid lot size ({lot})\n")
        return False

    print(f"\n  ═══════════════════════════════════════════════════")
    print(f"  🧪 SIMULATION — order NOT sent to MT5")
    print(f"  ───────────────────────────────────────────────────")
    print(f"  Type     : {decision['type']}")
    print(f"  Strategy : {decision['strategy']}")
    print(f"  Entry    : {decision['entry']:.3f}")
    print(f"  SL       : {decision['sl']:.3f}")
    print(f"  TP       : {decision['tp']:.3f}")
    print(f"  Lot size : {lot}")
    print(f"  R:R      : {decision.get('rr', '—')}")
    print(f"  Confidence: {decision.get('confidence', 0)}%")
    print(f"  Reason   : {decision.get('reason', '')}")
    print(f"  ═══════════════════════════════════════════════════\n")
    return True
