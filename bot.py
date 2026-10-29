import ccxt, pandas as pd, requests, os, io, json
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
WATCHLIST_FILE = "bottom_ready.json"

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
        print(msg)
    except: pass

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE,'r') as f: return json.load(f)
        except: return {}
    return {}

def save_watchlist(wl):
    with open(WATCHLIST_FILE,'w') as f: json.dump(wl,f,indent=2)

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

# Looser bottom ready - will find 30-40
def is_bottom_ready(df):
    if len(df)<80: return None
    df=df.copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    df['vol_ma20']=df['v'].rolling(20).mean()
    
    last=df.iloc[-1]
    # Simple filters
    if last['rsi'] > 65 or last['rsi'] < 22: return None
    
    for ws in [4,5]:
        s=len(df)-ws-1; e=len(df)-1
        w=df.iloc[s:e+1]
        low=w['l'].min(); high=w['h'].max()
        if (high-low)/low > 0.10: continue  # tight 10%
        
        low7=df.iloc[-8:-1]['l'].min()
        low60=df.iloc[-61:-1]['l'].min()
        
        if low > low7*1.10: continue
        if low > low60*1.20: continue  # relaxed from 1.12 to 1.20
        if last['c'] > low*1.30: continue
        
        # Price below EMA20 (still bottom)
        if last['c'] > last['ema20']*1.05: continue
        
        return {'low':low,'high':high,'ws':ws,'low7':low7,'rsi':last['rsi'],'ema20':last['ema20']}
    return None

# Breakout = your GREEN CANDLE CLOSE TOUCH
def is_breakout_now(df, bottom_info):
    df=df.copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    df['vol_ma20']=df['v'].rolling(20).mean()
    last=df.iloc[-1]; prev=df.iloc[-2]
    
    cross = prev['c'] <= prev['ema20']*1.02 and last['c'] > last['ema20']
    bullish = last['c'] > last['o']
    # Close touches accumulation high (your requirement)
    touch = last['c'] >= bottom_info['high']*0.985
    
    if cross and bullish and touch and last['rsi'] < 62:
        sl=bottom_info['low']*0.96; risk=last['c']-sl
        if risk>0 and risk/last['c'] < 0.12:
            return {'curr':last['c'],'sl':sl,'tp1':last['c']+risk*1.8,'tp2':last['c']+risk*3.2,'vol':last['v']/last['vol_ma20'],'rsi':last['rsi'],'df':df,'low':bottom_info['low'],'high':bottom_info['high'],'ws':bottom_info['ws'],'low7':bottom_info['low7']}
    return None

def chart_breakout(res,sym,exn):
    df=res['df'].tail(70)
    fig,ax=plt.subplots(figsize=(12,5))
    for i in range(len(df)-1):
        r=df.iloc[i]; col='#00b26a' if r['c']>=r['o'] else '#ff3b30'
        ax.plot([df.index[i],df.index[i]],[r['l'],r['h']],color=col,lw=1)
        ax.plot([df.index[i],df.index[i]],[r['o'],r['c']],color=col,lw=3.5)
    last=df.iloc[-1]; li=df.index[-1]
    ax.plot([li,li],[last['l'],last['h']],color='lime',lw=3,ls='--')
    ax.plot([li,li],[last['o'],last['c']],color='lime',lw=7)
    ax.scatter(li, last['c'], color='gold', s=500, edgecolor='black', zorder=7, marker='*')
    ax.plot(df.index, df['ema20'].tail(70), color='#5b4cff', lw=1.8, label='EMA20')
    ax.axhline(res['high'], color='orange', ls=':', lw=2, label=f"ACC HIGH TOUCH {res['high']:.4f}")
    ax.axhline(res['sl'], color='red', ls='--', label=f"SL {res['sl']:.4f}")
    ax.axhline(res['tp1'], color='green', ls='-', label=f"TP1 {res['tp1']:.4f}")
    ax.axhline(res['tp2'], color='darkgreen', ls='-', label=f"TP2 {res['tp2']:.4f}")
    ax.set_title(f"{sym} GREEN CANDLE CLOSE TOUCH ACC HIGH {exn} Vol {res['vol']:.1f}x RSI {res['rsi']:.0f}", fontsize=11, color='green', fontweight='bold')
    ax.legend(fontsize=7, loc='upper left'); ax.grid(alpha=0.2)
    return fig

watchlist = load_watchlist()
# Clean 10 days old
now=datetime.utcnow()
watchlist = {k:v for k,v in watchlist.items() if (now - datetime.strptime(v['date'],"%Y-%m-%d")).days < 10}

BLACKLIST={'BTC','ETH','BNB','SOL','XRP','BTCDOM','SPX','STOCK','NVDA','AAPL','PEPE'}
EXS=[('MEXC',ccxt.mexc,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('OKX',ccxt.okx,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('GATE',ccxt.gate,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('BITGET',ccxt.bitget,{'enableRateLimit':True,'options':{'defaultType':'swap'}})]

# Step 1: Check existing watchlist for breakout
breakouts=[]
for pair_key, info in list(watchlist.items()):
    try:
        clean, exn = pair_key.split('_')
        for en, cls, opts in EXS:
            if en!=exn: continue
            ex=cls(opts); ex.load_markets()
            syms=[m['symbol'] for m in ex.markets.values() if clean in m['symbol'] and 'USDT' in m['symbol']]
            if not syms: continue
            ohlcv=ex.fetch_ohlcv(syms[0],'1d',limit=110)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            res=is_breakout_now(df, info)
            if res:
                breakouts.append((clean,exn,res))
                del watchlist[pair_key]
    except: continue

send_text(f"📊 Watchlist {len(watchlist)} bottoms, Today Breakouts {len(breakouts)} (Green Close Touch)")

# Send TOP 10 breakouts
for clean,exn,res in sorted(breakouts, key=lambda x: x[2]['vol'], reverse=True)[:10]:
    fig=chart_breakout(res,clean,exn)
    cap=(f"🚀 <b>{clean} BREAKOUT {exn}</b>\n"
         f"Green Candle Close {res['curr']:.6f} TOUCH Acc High {res['high']:.4f}\n"
         f"Vol {res['vol']:.1f}x RSI {res['rsi']:.0f} 7dLow {res['low7']:.4f}\n"
         f"SL {res['sl']:.6f} TP {res['tp1']:.6f}/{res['tp2']:.6f}\n"
         f"Accumulation {res['ws']}c Touch Close")
    buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=140,bbox_inches='tight'); buf.seek(0); plt.close(fig)
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"}, files={"photo":buf}, timeout=25)
    time.sleep(0.5)

# Step 2: Find new bottoms
new_bottoms=0
for exn,cls,opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])][:400]
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0]
            key=f"{clean}_{exn}"
            if key in watchlist: continue
            if any(b in clean.upper() for b in BLACKLIST): continue
            if 'STOCK' in sym.upper(): continue
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=100)
                if len(ohlcv)<80: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                res=is_bottom_ready(df)
                if res:
                    res['date']=datetime.utcnow().strftime("%Y-%m-%d")
                    watchlist[key]=res
                    new_bottoms+=1
            except: continue
    except: continue

save_watchlist(watchlist)
send_text(f"✅ Done: Breakouts {len(breakouts)} sent\nNew bottoms {new_bottoms} added\nTotal watchlist now {len(watchlist)}\n138 wala issue fixed - ab 10 best hi ayenge")
