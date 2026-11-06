import requests
import pandas as pd
import time
import random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from ema20_filter import check_1d_ema20, send_daily_report

MAX_WORKERS = 3
MAX_RETRIES = 5

def get_all_perp_symbols():
    # Use ticker = only LIVE contracts. detail = includes dead/delisted ones (caused 1001)
    url = "https://contract.mexc.com/api/v1/contract/ticker"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    symbols = []
    for c in data:
        sym = c.get("symbol", "")  # Already in BTC_USDT format - use AS-IS
        if not sym.endswith("USDT"):
            continue
        if "STOCK" in sym or "INDEX" in sym:
            continue
        if any(x in sym for x in ["_3L", "_3S", "_5L", "_5S"]):
            continue
        symbols.append(sym)
    symbols = sorted(list(set(symbols)))
    print(f"Found {len(symbols)} live perpetuals")
    return symbols

def fetch_perp_candles(symbol):
    # symbol is already BTC_USDT - DO NOT transform it
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}"
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, params={"interval": "Day1"}, timeout=20)
            r.raise_for_status()
            j = r.json()
            code = j.get("code")
            # 1001 = contract does not exist - dead, skip immediately, no retry
            if code == 1001:
                raise ValueError("dead contract, skip")
            # 510 = rate limit - wait and retry
            if code == 510 or "rate limit" in str(j.get("message", "")).lower():
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"{symbol}: rate limited, retry {attempt+1} in {wait:.1f}s")
                time.sleep(wait)
                continue
            data = j.get("data")
            if not data:
                raise ValueError(f"No kline data: {j}")
            if isinstance(data, dict) and "time" in data:
                df = pd.DataFrame({
                    "time": data["time"],
                    "open": data["open"],
                    "high": data["high"],
                    "low": data["low"],
                    "close": data["close"],
                    "vol": data.get("vol", [0]*len(data["time"])),
                })
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
            return df.iloc[:-1].reset_index(drop=True)
        except ValueError as e:
            if "dead contract" in str(e):
                raise  # skip, don't retry
            last_err = e
            raise
        except Exception as e:
            last_err = e
            if "rate limit" in str(e).lower() or "510" in str(e):
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            raise
    raise last_err

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
        time.sleep(random.uniform(0.1, 0.4))
        df = fetch_perp_candles(symbol)
        cand = detect_breakout_retest(df)
        if not cand:
            return None
        hit = check_1d_ema20(df, cand["level"], cand["direction"])
        if hit:
            print(f"{symbol}: PASS {hit['direction']} close {hit['close']:.6g}")
            return {"pair": symbol, "df": df, **hit}
        return None
    except Exception as e:
        # Don't spam log for dead contracts
        if "dead contract" not in str(e) and "No kline data" not in str(e):
            print(f"{symbol}: ERROR {e}")
        return None

def main():
    symbols = get_all_perp_symbols()
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
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
