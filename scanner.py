import requests
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from ema20_filter import check_1d_ema20, send_daily_report

# --- Fetch ALL MEXC Perpetual symbols ---
def get_all_perp_symbols():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    symbols = []
    for c in data:
        sym = c.get("symbol", "")
        # Only USDT perpetual, active, not test
        if not sym.endswith("USDT"):
            continue
        if c.get("state") not in (0, None) and c.get("state") != 1:
            # state 1 = active on MEXC, keep if unknown too
            pass
        # Skip leveraged tokens / weird
        if any(x in sym for x in ["_3L", "_3S", "_5L", "_5S", "UP", "DOWN"]):
            continue
        symbols.append(sym)
    # Remove duplicates, sort
    symbols = sorted(list(set(symbols)))
    print(f"Found {len(symbols)} perpetuals")
    return symbols

def fetch_perp_candles(symbol, limit=120):
    # MEXC Futures kline: https://contract.mexc.com/api/v1/contract/kline/BTC_USDT?interval=Day1
    # Symbol format for futures is BTC_USDT, not BTCUSDT
    fut_sym = symbol[:-4] + "_USDT" if symbol.endswith("USDT") else symbol
    url = f"https://contract.mexc.com/api/v1/contract/kline/{fut_sym}"
    r = requests.get(url, params={"interval": "Day1"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    data = j.get("data")
    if not data:
        raise ValueError(f"No kline data: {j}")

    # Format 1: dict of lists {time:[], open:[], high:[], low:[], close:[], vol:[]}
    if isinstance(data, dict) and "time" in data:
        df = pd.DataFrame({
            "time": data["time"],
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "vol": data.get("vol", [0]*len(data["time"])),
        })
    # Format 2: list of lists [time, open, high, low, close, vol, ...]
    elif isinstance(data, list):
        df = pd.DataFrame(data)
        df = df.iloc[:, :6]
        df.columns = ["time", "open", "high", "low", "close", "vol"]
    else:
        raise ValueError(f"Unknown kline format: {type(data)}")

    df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)
    # Drop still-forming candle
    return df.iloc[:-1].reset_index(drop=True)

def detect_breakout_retest(df):
    if len(df) < 30:
        return None
    look = df.iloc[-21:-1]
    retest = df.iloc[-1]
    prev = df.iloc[-2]
    level_high = look["high"].max()
    if prev["close"] > level_high and retest["low"] <= level_high * 1.003 and retest["close"] > level_high:
        return {"level": float(level_high), "direction": "long"}
    level_low = look["low"].min()
    if prev["close"] < level_low and retest["high"] >= level_low * 0.997 and retest["close"] < level_low:
        return {"level": float(level_low), "direction": "short"}
    return None

def scan_one(symbol):
    try:
        df = fetch_perp_candles(symbol)
        cand = detect_breakout_retest(df)
        if not cand:
            return None
        hit = check_1d_ema20(df, cand["level"], cand["direction"])
        if hit:
            print(f"{symbol}: PASS {hit['direction']} close {hit['close']:.6g}")
            return {"pair": symbol, "df": df, **hit}
        else:
            print(f"{symbol}: breakout but EMA20 filter failed")
            return None
    except Exception as e:
        print(f"{symbol}: ERROR {e}")
        return None

def main():
    symbols = get_all_perp_symbols()
    results = []
    # 15 threads = ~300 pairs in 2-3 mins, inside 20 min timeout
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = {ex.submit(scan_one, s): s for s in symbols}
        for f in as_completed(futures):
            res = f.result()
            if res:
                results.append(res)
    print(f"Done. Scanned {len(symbols)}, {len(results)} passed.")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    send_daily_report(results, today)

if __name__ == "__main__":
    main()
