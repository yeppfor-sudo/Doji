import requests
import pandas as pd
from datetime import datetime, timezone
from ema20_filter import check_1d_ema20, send_daily_report

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","SUIUSDT",
]

def fetch_closed_candles(pair, limit=120):
    url = "https://api.mexc.com/api/v3/klines"
    r = requests.get(url, params={"symbol": pair, "interval": "1d", "limit": limit}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        raise ValueError(f"MEXC error: {data}")
    df = pd.DataFrame(data)
    df = df.iloc[:, :6]
    df.columns = ["time", "open", "high", "low", "close", "vol"]
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
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
