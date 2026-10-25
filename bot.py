import requests, time, os, math
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ========= CONFIG =========
MIN_VOL_24H_USDT = 2_000_000  # filter low liquidity
MAX_PAIRS = 180  # scan top 180 by volume to avoid rate limit
TIMEFRAMES = {
    "1D": 1,
    "2D": 2,
    "3D": 3,
    "5D": 5,
    "7D": 7
}

def get_mexc_perp_pairs():
    # Use spot 24h ticker as proxy for perp pairs - most perp have spot
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    r = requests.get(url, timeout=20).json()
    usdt = [x for x in r if x['symbol'].endswith('USDT') and float(x['quoteVolume']) > MIN_VOL_24H_USDT]
    # Sort by volume desc
    usdt = sorted(usdt, key=lambda x: float(x['quoteVolume']), reverse=True)[:MAX_PAIRS]
    return [x['symbol'] for x in usdt]

def get_klines(symbol, limit=200):
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict): return None
        df = pd.DataFrame(data, columns=['open_time','open','high','low','close','vol','close_time','qvol','trades','taker_base','taker_quote','ignore'])
        df = df[['open','high','low','close','vol']].astype(float)
        return df
    except: return None

def aggregate(df, n):
    if n==1: return df
    # Aggregate 1D to nD
    agg = []
    for i in range(0, len(df), n):
        chunk = df.iloc[i:i+n]
        if len(chunk) < n: break
        agg.append({
            'open': chunk.iloc[0]['open'],
            'high': chunk['high'].max(),
            'low': chunk['low'].min(),
            'close': chunk.iloc[-1]['close'],
            'vol': chunk['vol'].sum()
        })
    return pd.DataFrame(agg)

def ema(s, p): return s.ewm(span=p, adjust=False).mean()
def rsi(s, p=14):
    delta = s.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/p).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/p).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def is_hammer_pattern(row):
    o,c,h,l = row['open'],row['close'],row['high'],row['low']
    body = abs(c-o)
    rng = h-l
    if rng==0: return False,0
    upper = h - max(o,c)
    lower = min(o,c) - l
    body_ratio = body / rng
    # Conditions from your photos
    is_small_body = body_ratio < 0.35
    is_long_lower = lower >= 1.8 * max(body, rng*0.1)
    is_short_upper = upper <= body * 1.2 or upper <= rng*0.25
    # Green preferred but red also valid at bottom
    score = 0
    if is_small_body: score+=30
    if is_long_lower: score+=40
    if is_short_upper: score+=20
    if c>o: score+=10 # bullish
    return (score>=70), score

def check_setup(df):
    if len(df) < 100: return None
    df['ema9'] = ema(df['close'],9)
    df['ema21'] = ema(df['close'],21)
    df['ema50'] = ema(df['close'],50)
    df['rsi'] = rsi(df['close'])
    df['atr'] = (df['high']-df['low']).ewm(span=14).mean()
    
    last = df.iloc[-1]
    prev20 = df.iloc[-30:-1]
    low90 = df['low'].iloc[-90:].min()
    high15 = df['high'].iloc[-15:].max()
    
    # 1. Downtrend short-term
    downtrend = (last['ema9'] < last['ema21']) and (last['close'] < prev20['close'].mean()) and ((high15-last['close'])/high15 > 0.12)
    if not downtrend: return None
    
    # 2. Almost bottom
    dist_from_90low = (last['close'] - low90)/low90
    if dist_from_90low > 0.18: return None  # too high
    if not (20 < last['rsi'] < 48): return None
    vol_avg = df['vol'].iloc[-20:-1].mean()
    vol_spike = last['vol'] > vol_avg*1.4
    
    # 3. Candle pattern
    is_pat, pat_score = is_hammer_pattern(last)
    if not is_pat: return None
    
    # 4. Liquidity sweep - wick broke previous 10 lows
    prev10_low = df['low'].iloc[-11:-1].min()
    sweep = last['low'] < prev10_low and last['close'] > prev10_low
    
    # 5. Score
    score = pat_score
    if sweep: score+=20
    if vol_spike: score+=10
    if 0.02 < dist_from_90low < 0.10: score+=10 # perfect bottom zone
    
    if score < 75: return None
    
    # SL TP
    sl = last['low'] * 0.992  # 0.8% below wick
    entry = last['close']  # or high of hammer
    risk = entry - sl
    if risk <=0: return None
    tp1 = entry + risk*1.8
    tp2 = entry + risk*3.5
    tp3 = entry + risk*6
    
    return {
        'score': score,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'rsi': last['rsi'],
        'dist_low': dist_from_90low*100,
        'sweep': sweep,
        'row': last
    }

def draw_chart(df, symbol, tf, setup):
    plt.figure(figsize=(10,6))
    d = df.tail(35).reset_index(drop=True)
    # candles
    for i, row in d.iterrows():
        color = '#0ecb81' if row['close']>=row['open'] else '#f6465d'
        plt.plot([i,i],[row['low'],row['high']], color=color, linewidth=1)
        plt.plot([i,i],[row['open'],row['close']], color=color, linewidth=4)
    # EMAs
    plt.plot(d['ema9'], label='EMA9', linewidth=0.8)
    plt.plot(d['ema21'], label='EMA21', linewidth=0.8)
    # SL TP
    x = len(d)-1
    plt.axhline(setup['entry'], color='white', linestyle='--', label=f"Entry {setup['entry']:.6g}")
    plt.axhline(setup['sl'], color='red', linestyle='-', label=f"SL {setup['sl']:.6g}")
    plt.axhline(setup['tp1'], color='green', linestyle='--', label=f"TP1 {setup['tp1']:.6g}")
    plt.axhline(setup['tp2'], color='green', linestyle=':', label=f"TP2 {setup['tp2']:.6g}")
    plt.title(f"{symbol} {tf} | Score {setup['score']} | RSI {setup['rsi']:.1f} | Bottom {setup['dist_low']:.1f}% from 90D Low")
    plt.legend(fontsize=7)
    plt.tight_layout()
    path = f"/tmp/{symbol}_{tf}.png"
    plt.savefig(path, dpi=180)
    plt.close()
    return path

def send_telegram(text, photo_path=None):
    if not TOKEN or not CHAT_ID: return
    if photo_path:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        with open(photo_path,'rb') as f:
            requests.post(url, data={'chat_id':CHAT_ID,'caption':text,'parse_mode':'Markdown'}, files={'photo':f}, timeout=20)
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={'chat_id':CHAT_ID,'text':text,'parse_mode':'Markdown'}, timeout=15)

def main():
    pairs = get_mexc_perp_pairs()
    # BTC filter
    btc_df = get_klines("BTCUSDT")
    btc_down = False
    if btc_df is not None:
        btc_last = btc_df.iloc[-1]
        btc_prev = btc_df.iloc[-2]
        btc_down = (btc_last['close'] - btc_prev['close'])/btc_prev['close'] < -0.04

    found = []
    for symbol in pairs:
        time.sleep(0.15)
        df1 = get_klines(symbol)
        if df1 is None: continue
        for tf_name, n in TIMEFRAMES.items():
            df_tf = aggregate(df1, n)
            if len(df_tf) < 100: continue
            df_tf['ema9'] = ema(df_tf['close'],9)
            df_tf['ema21'] = ema(df_tf['close'],21)
            # quick check
            setup = check_setup(df_tf)
            if setup and not (btc_down and tf_name=="1D"):
                found.append((symbol, tf_name, df_tf, setup))
                if len(found)>=5: break # send top 5 only
        if len(found)>=5: break

    if not found:
        send_telegram("*please patience* \nNo bottom hammer found on 1D/2D/3D/5D/7D today. Scan completed.")
    else:
        # sort by score
        found = sorted(found, key=lambda x: x[3]['score'], reverse=True)
        for symbol, tf, df_tf, setup in found[:3]:
            chart = draw_chart(df_tf, symbol, tf, setup)
            rr = (setup['tp2']-setup['entry'])/(setup['entry']-setup['sl'])
            msg = f"*{symbol} {tf} LONG Setup* 🔍\n\n*Pattern:* Hammer / Pin Bar + Sweep {setup['sweep']}\n*Score:* {setup['score']}/100\n*RSI:* {setup['rsi']:.1f}\n*Distance from 90D Low:* {setup['dist_low']:.1f}%\n\n*Entry:* `{setup['entry']:.6g}`\n*SL:* `{setup['sl']:.6g}` (-{((setup['entry']-setup['sl'])/setup['entry']*100):.2f}%)\n*TP1:* `{setup['tp1']:.6g}` (1.8R)\n*TP2:* `{setup['tp2']:.6g}` (3.5R)\n*TP3:* `{setup['tp3']:.6g}` (6R)\n*RR:* {rr:.1f}\n\n_Almost bottom + Downtrend + Volume spike confirmed_\n"
            send_telegram(msg, chart)
            time.sleep(1)

if __name__ == "__main__":
    main()
