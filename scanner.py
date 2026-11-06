import requests
import pandas as pd
from datetime import datetime, timezone
from ema20_filter import check_1d_ema20, send_daily_report

# Add / remove pairs here
PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","TONUSDT",
]

def fetch_closed_candles(pair, limit=120):
    # MEXC Spot klines - public, no key
    url = "https://api.mexc.com/api/v3/klines"
    r = requests.get(url, params={"symbol": pair, "interval": "1d", "limit": limit}, timeout=20)
    r.raise_for_status()
    data = r.json()
    # MEXC returns: [openTime, open, high, low, close, volume, closeTime, ...]
    df = pd.DataFrame(data, columns=["time","open","high","low","close","vol","closeTime","qv","n","tb","tq","ig"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    for c in ["open","high","low","close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open","high","low","close"])
    # Drop still-forming candle (last one)
    return df.iloc[:-1].reset_index(drop=True)

def detect_breakout_retest(df):
    # Last candle = retest candle. Lookback = 20 bars before it
    if len(df) < 30:
        return None
    look = df.iloc[-21:-1]  # 20 bars before retest
    retest = df.iloc[-1]
    prev = df.iloc[-2]
    # LONG: breakout above 20-bar high, then retest held
    level_high = look["high"].max()
    if prev["close"] > level_high and retest["low"] <= level_high * 1.003 and retest["close"] > level_high:
        return {"level": float(level_high), "direction": "long"}
    # SHORT: breakout below 20-bar low, then retest held
    level_low = look["low"].min()
    if prev["close"] < level_low and retest["high"] >= level_low * 0.997 and retest["close"] < level_low:
        return {"level": float(level_low), "direction": "short"}
    return None

def main():
    results = []
    for pair in PAIRS:
        try:
            df = fetch_closed_candles(pair)
            cand = detect_breakout_retest(df)
            if not cand:
                print(f"{pair}: no breakout")
                continue
            hit = check_1d_ema20(df, cand["level"], cand["direction"])
            if hit:
                print(f"{pair}: PASS {hit}")
                results.append({"pair": pair, "df": df, **hit})
            else:
                print(f"{pair}: breakout but EMA20 filter failed")
        except Exception as e:
            print(f"{pair}: ERROR {e}")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    send_daily_report(results, today)
    print(f"Done. {len(results)} passed.")

if __name__ == "__main__":
    main()
