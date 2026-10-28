import ccxt, pandas as pd, requests, os, io, time
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ========== LOOSENED PARAMS - EDIT HERE IF STILL TOO TIGHT ==========
BOTTOM_TOL = 1.20      # was 1.08 -> now 20% above 60D low (was 8%)
RSI_MAX_LOW = 50       # was 38 -> now RSI <50 at bottom (was 38)
RSI_MAX_CURR = 55      # was 40 -> now current RSI <55 (was 40)
VOL_EXHAUST_MULT = 1.3 # was 0.9 -> now allow up to 1.3x avg (was 0.9)
VOL_SPIKE_MULT = 0.8   # was 1.2 -> now need only 0.8x avg on green (was 1.2)
EMA_TOL = 1.08         # was 1.03 -> looser downtrend
# =====================================================================

def send_text(msg):
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=15)
        print(f"TG {r.status_code}")
    except Exception as e: print(f"TG text fail {e}")

def send_photo(fig, caption):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        requests.post(url, data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                      files={"photo": buf}, timeout=20)
    except Exception as e: print(f"TG photo fail {e}")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def is_doji(o,h,l,c): return (h-l)>0 and abs(c-o)/(h-l) < 0.35  # loosened 0.25->0.35
def is_hammer(o,h,l,c):
    body = abs(c-o); 
    if body==0: return False
    lower = min(o,c)-l; upper = h-max(o,c)
    return lower > body*1.3 and upper < body*1.2  # loosened
def is_star(o,h,l,c):
    body = abs(c-o); rng=h-l
    if rng==0: return False
    upper = h-max(o,c); lower = min(o,c)-l
    return (upper > body*1.0 or lower > body*1.0) and body/rng < 0.55  # loosened
def is_bullish_candle(o,h,l,c): return is_doji(o,h,l,c) or is_hammer(o,h,l,c) or is_star(o,h,l,c) or (c>o and (c-l)/(h-l+1e-9) > 0.3)

def scan_reversal(df):
    if len(df) < 80: return None
    df = df.iloc[:-1].copy()  # previous closed only
    df['ema6'] = ema(df['c'],6); df['ema12'] = ema(df['c'],12); df['ema20'] = ema(df['c'],20)
    df['rsi'] = rsi(df['c'],14); df['vol_ma20'] = df['v'].rolling(20).mean()
    
    for end in range(len(df)-1, len(df)-10, -1):
        for win_size in [2,3,4,5,6,7,8]:
            start = end - win_size +1
            if start < 10: continue
            window = df.iloc[start:end+1]
            
            low_window = window['l'].min()
            low_60 = df.iloc[max(0,end-60):end]['l'].min()
            if low_window > low_60 * BOTTOM_TOL: continue
            
            # Loosened downtrend: price below EMA20 OR EMA6 < EMA20*1.08
            ema_down = df['ema6'].iloc[end] < df['ema20'].iloc[end]*EMA_TOL
            below_ema = (df['c'].iloc[end-12:end] < df['ema20'].iloc[end-12:end]).sum() >= 6  # was 10/15
            if not (ema_down or below_ema): continue
            
            green_cnt = (window['c'] > window['o']).sum()
            if green_cnt < 1: continue
            
            bullish_cnt = sum(is_bullish_candle(r['o'],r['h'],r['l'],r['c']) for _,r in window.iterrows())
            if bullish_cnt < 1: continue
            
            # Volume - LOOSENED
            vol_window_avg = window['v'].mean()
            vol_20_avg = df['vol_ma20'].iloc[end] or vol_window_avg
            green_vols = [r['v'] for _,r in window.iterrows() if r['c']>r['o']]
            max_green_vol = max(green_vols) if green_vols else 0
            vol_exhaustion = vol_window_avg < vol_20_avg * VOL_EXHAUST_MULT
            vol_spike_green = max_green_vol > vol_20_avg * VOL_SPIKE_MULT
            if not (vol_exhaustion or vol_spike_green): continue
            
            # RSI - LOOSENED from 38/40 to 50/55
            rsi_window = window['rsi'].min()
            rsi_curr = df['rsi'].iloc[end]
            if rsi_window > RSI_MAX_LOW and rsi_curr > RSI_MAX_CURR: continue
            
            curr_price = df.iloc[end]['c']
            sl = low_window * 0.96  # 4% below
            risk = curr_price - sl
            if risk <=0: continue
            tp1 = curr_price + risk*1.5; tp2 = curr_price + risk*2.8; tp3 = df['ema20'].iloc[end]
            
            return {
                'end_idx': end, 'start_idx': start, 'win_size': win_size,
                'bottom': low_window, 'curr': curr_price, 'green': int(green_cnt),
                'bullish': int(bullish_cnt), 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
                'ema6': df['ema6'].iloc[end], 'ema12': df['ema12'].iloc[end], 'ema20': df['ema20'].iloc[end],
                'low_60': low_60, 'vol_avg': vol_window_avg, 'vol_ma20': vol_20_avg,
                'vol_spike': vol_spike_green, 'rsi': rsi_curr, 'rsi_low': rsi_window, 'df': df
            }
    return None

def draw_chart(res, symbol, exchange):
    df = res['df'].tail(90)
    fig, (ax1, ax2, ax3) = plt.subplots(3,1, figsize=(11,7), gridspec_kw={'height_ratios':[3,1,1]}, sharex=True)
    fig.patch.set_facecolor('white')
    for idx, row in df.iterrows():
        color = '#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax1.plot([idx, idx], [row['l'], row['h']], color=color, lw=1)
        ax1.plot([idx, idx], [row['o'], row['c']], color=color, lw=3)
    ax1.plot(df.index, df['ema6'], color='#e38bd7', lw=1.1, label=f"EMA6:{res['ema6']:.5f}")
    ax1.plot(df.index, df['ema12'], color='#f0a500', lw=1.1, label=f"EMA12:{res['ema12']:.5f}")
    ax1.plot(df.index, df['ema20'], color='#5b4cff', lw=1.2, label=f"EMA20:{res['ema20']:.5f}")
    ax1.axvspan(res['start_idx'], res['end_idx'], color='lightgreen', alpha=0.35)
    ax1.axhline(res['sl'], color='red', ls='--', lw=1.2, label=f"SL {res['sl']:.6f}")
    ax1.axhline(res['tp1'], color='#00b26a', ls=':', lw=1, label=f"TP1")
    ax1.axhline(res['tp2'], color='#00b26a', ls='-', lw=1.2, label=f"TP2 {res['tp2']:.6f}")
    ax1.set_title(f"{symbol} {exchange} 1D REVERSAL {res['win_size']}c RSI{res['rsi']:.1f} Green{res['green']}", fontsize=11, fontweight='bold')
    ax1.legend(fontsize=7, loc='upper left'); ax1.grid(alpha=0.2)
    colors = ['#00b26a' if c>=o else '#ff3b30' for c,o in zip(df['c'], df['o'])]
    ax2.bar(df.index, df['v'], color=colors, alpha=0.7)
    ax2.plot(df.index, df['vol_ma20'], color='#e38bd7', lw=1); ax2.set_ylabel("VOL"); ax2.grid(alpha=0.2)
    ax3.plot(df.index, df['rsi'], color='#5b4cff', lw=1.2)
    ax3.axhline(35, color='red', ls='--', lw=0.8, label='Oversold 35'); ax3.axhline(70, color='green', ls='--', lw=0.8)
    ax3.fill_between(df.index, 0, 35, color='lightgreen', alpha=0.2)
    ax3.set_ylabel("RSI14"); ax3.legend(fontsize=6); ax3.grid(alpha=0.2)
    plt.tight_layout(); return fig

def main():
    print(f"BOT_TOKEN exists: {bool(BOT_TOKEN)} CHAT_ID: {CHAT_ID}")
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing secrets"); return
    send_text(f"🚀 <b>Scan Started - LOOSENED FILTERS</b>\nBottom {BOTTOM_TOL*100-100:.0f}% above 60D low | RSI <{RSI_MAX_LOW}/{RSI_MAX_CURR} | Scanning...")

    exchanges = [
        ('MEXC', ccxt.mexc({'enableRateLimit':True, 'options':{'defaultType':'swap'}})),
        ('BYBIT', ccxt.bybit({'enableRateLimit':True, 'options':{'defaultType':'swap'}})),
        ('OKX', ccxt.okx({'enableRateLimit':True, 'options':{'defaultType':'swap'}})),
        ('BITGET', ccxt.bitget({'enableRateLimit':True, 'options':{'defaultType':'swap'}})),
        ('GATE', ccxt.gate({'enableRateLimit':True, 'options':{'defaultType':'swap'}})),
    ]
    total=0
    for ex_name, ex in exchanges:
        try:
            ex.load_markets()
            syms = [s for s in ex.markets if s.endswith('/USDT:USDT') and 'STOCK' not in s][:600]
            for sym in syms:
                try:
                    ohlcv = ex.fetch_ohlcv(sym, '1D', limit=120)
                    df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                    res = scan_reversal(df)
                    if res:
                        clean = sym.replace('/USDT:USDT','')
                        fig = draw_chart(res, clean, ex_name)
                        rr = (res['tp2']-res['curr'])/(res['curr']-res['sl'])
                        vol_text = "Spike" if res['vol_spike'] else "Exhaust"
                        caption = f"🔥 <b>{clean} {ex_name} 1D BOTTOM</b>\n{res['win_size']}c Green:{res['green']} Bullish:{res['bullish']}\nPrice {res['curr']:.6f} Bottom {res['bottom']:.6f} 60D Low {res['low_60']:.6f}\nEMA6 {res['ema6']:.5f} EMA12 {res['ema12']:.5f} EMA20 {res['ema20']:.5f}\n📊 Vol {vol_text} RSI {res['rsi']:.1f} (Low {res['rsi_low']:.1f})\n<b>SL:</b> {res['sl']:.6f} <b>TP2:</b> {res['tp2']:.6f} RR 1:{rr:.1f}"
                        send_photo(fig, caption)
                        total+=1; time.sleep(1.2)
                    time.sleep(0.05)
                except: time.sleep(0.2); continue
        except Exception as e:
            print(f"{ex_name} fail {e}"); continue
    send_text(f"✅ <b>Done</b> - Found {total} setups (loosened filters)")

if __name__ == "__main__": main()
