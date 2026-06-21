"""
MT5 Executor — sends real orders to MetaTrader 5.

Used when SIMULATION_MODE = False.
Requires the MetaTrader5 Python package and MT5 terminal to be open and logged in.

Optional environment variables (only needed if you want the engine to log in
programmatically rather than using the already-logged-in MT5 terminal):
  MT5_LOGIN    — account number (integer)
  MT5_PASSWORD — account password
  MT5_SERVER   — broker server name (e.g. "ICMarkets-Live01")

Normal usage: just open MT5, log in manually, then start the engine.
The engine will connect to the already-running terminal automatically.
"""

import os
import sys
import os.path as _p
sys.path.insert(0, _p.join(_p.dirname(__file__), ".."))
import config


def _connect():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("  [ERROR] MetaTrader5 package not installed. Run: pip install MetaTrader5")
        return None

    if not mt5.initialize():
        print(f"  [ERROR] MT5 initialize() failed: {mt5.last_error()}")
        print("          Is MetaTrader 5 open on this machine?")
        return None

    account_info = mt5.account_info()
    if account_info is not None:
        return mt5

    login    = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server   = os.getenv("MT5_SERVER", "")

    if not login or not password:
        print("  [ERROR] MT5 is running but not logged in, and no credentials found.")
        print("          Either log into MT5 manually before starting the engine,")
        print("          or set MT5_LOGIN / MT5_PASSWORD environment variables.")
        mt5.shutdown()
        return None

    if not mt5.login(int(login), password=password, server=server):
        print(f"  [ERROR] MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return None

    return mt5


def place_order(decision: dict, lot: float) -> int:
    """Send a market order to MT5. Returns ticket number on success, 0 on failure."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("  [ERROR] MetaTrader5 package not installed.")
        return 0

    mt5_inst = _connect()
    if mt5_inst is None:
        return 0

    try:
        signal_sym = decision.get("symbol", config.SYMBOL)
        sym_cfg    = config.get_symbol_cfg(signal_sym)
        mt5_symbol = sym_cfg["mt5_name"]

        trade_type = mt5.ORDER_TYPE_BUY if decision["type"] == "BUY" else mt5.ORDER_TYPE_SELL
        price_info = mt5.symbol_info_tick(mt5_symbol)

        if price_info is None:
            print(f"  [ERROR] Cannot get price for {mt5_symbol}.")
            print(f"          Check that {mt5_symbol} is visible in MT5 Market Watch.")
            return 0

        fill_price = price_info.ask if decision["type"] == "BUY" else price_info.bid

        sym_info = mt5.symbol_info(mt5_symbol)
        if sym_info is not None and sym_info.filling_mode & 1:
            filling = mt5.ORDER_FILLING_FOK
        elif sym_info is not None and sym_info.filling_mode & 2:
            filling = mt5.ORDER_FILLING_IOC
        else:
            filling = mt5.ORDER_FILLING_RETURN
        print(f"  [MT5] Using filling mode: {filling} (broker filling_mode={getattr(sym_info, 'filling_mode', 'N/A')})")

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       mt5_symbol,
            "volume":       lot,
            "type":         trade_type,
            "price":        fill_price,
            "sl":           decision["sl"],
            "tp":           decision["tp"],
            "deviation":    20,             # wider deviation OK for swing entries
            "magic":        202402,         # 202402 = swing engine (202401 = scalping)
            "comment":      f"SWING:{decision['strategy'][:10]}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)

        if result is None:
            print(f"  [ERROR] MT5 order_send returned None: {mt5.last_error()}")
            return 0

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"\n  ORDER FILLED  ticket={result.order}")
            print(f"  {decision['type']} {lot} lots {mt5_symbol} @ {fill_price:.5f}")
            print(f"  SL={decision['sl']:.5f}  TP={decision['tp']:.5f}\n")
            return result.order
        else:
            print(f"  [ERROR] Order failed: retcode={result.retcode} | {result.comment}")
            return 0

    finally:
        mt5.shutdown()


def has_open_position(symbol: str) -> bool:
    """Check whether MT5 currently has any open swing position on this symbol."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return False

    mt5_inst = _connect()
    if mt5_inst is None:
        return False

    try:
        sym_cfg    = config.get_symbol_cfg(symbol)
        mt5_symbol = sym_cfg["mt5_name"]
        positions  = mt5.positions_get(symbol=mt5_symbol)
        if positions is None:
            return False
        return any(p.magic == 202402 for p in positions)

    finally:
        mt5.shutdown()


def check_breakeven_all(tracker: dict) -> None:
    """
    Move SL to breakeven when price has moved 1.5R in our favour on the 4H chart.
    Swing trades use 4H for breakeven check (vs 15M in scalping).
    Called once per engine scan cycle.
    """
    if not tracker:
        return

    try:
        import MetaTrader5 as mt5
    except ImportError:
        return

    mt5_inst = _connect()
    if mt5_inst is None:
        return

    try:
        for ticket, info in list(tracker.items()):
            if info.get("moved"):
                continue

            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                del tracker[ticket]
                continue

            entry   = info["entry"]
            sl_orig = info["sl_orig"]
            one_r   = abs(entry - sl_orig)
            pip     = 0.01 if entry > 50 else 0.0001

            if one_r <= 0:
                continue

            # Use 4H candles for swing breakeven check
            rates = mt5.copy_rates_from_pos(info["mt5_symbol"], mt5.TIMEFRAME_H4, 1, 1)
            if not rates:
                continue

            close = float(rates[0]["close"])

            if info["direction"] == "BUY":
                if close < entry + 1.5 * one_r:
                    continue
                new_sl = round(entry + pip, 5)
            else:
                if close > entry - 1.5 * one_r:
                    continue
                new_sl = round(entry - pip, 5)

            pos    = positions[0]
            result = mt5.order_send({
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   info["mt5_symbol"],
                "position": ticket,
                "sl":       new_sl,
                "tp":       pos.tp if pos.tp > 0 else info["tp"],
            })
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                info["moved"] = True
                print(f"  [BE] ✅ ticket={ticket} {info['direction']} SL → breakeven {new_sl}")
    finally:
        mt5.shutdown()
