import ccxt, pandas as pd, requests, os, io, time
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
    except: pass

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff()
    g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def scan(df):
    if len(df)<70: return None
    df=df.copy()
    df['ema20']=ema(df['c'],20)
    df['rsi']=rsi(df['c'],14)
    df['vol_ma']=df['v'].rolling(20).mean()
    last=df.iloc[-1]
    low7=df.iloc[-8:-1]['l'].min()
    low60=df.iloc[-61:-1]['l'].min()
    if last['l'] > low7*1.12: return None
    if last['l'] > low60*1.25: return None
    if last['rsi'] > 65 or last['rsi'] < 18: return None
    for ws in [4,5]:
        s=len(df)-ws-1; e=len(df)-1
        w=df.iloc[s:e+1]
        low=w['l'].min(); high=w['h'].max()
        if (high-low)/low > 0.12: continue
        if not (last['c'] > last['o'] and last['c'] >= last['ema20']*0.98): continue
        sl=low*0.95; risk=last['c']-sl
        if risk<=0 or risk/last['c']>0.15: continue
        score=(1.12-low/low7)*10 + (50-last['rsi'])*0.2 + (last['v']/last['vol_ma'] if last['vol_ma']>0 else 0)
        return {'low':low,'high':high,'curr':last['c'],'sl':sl,'tp1':last['c']+risk*1.8,'tp2':last['c']+risk*3.2,'df':df,'rsi':last['rsi'],'vol':last['v']/last['vol_ma'] if last['vol_ma']>0 else 0,'ws':ws,'low7':low7,'score':score,'ema20':last['ema20']}
    return None

def chart(res,sym,exn):
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
    ax.plot(df.index, df['ema20'].tail(70), color='#5b4cff', lw=1.8)
    ax.axhline(res['high'], color='orange', ls=':', lw=2)
    ax.axhline(res['sl'], color='red', ls='--')
    ax.set_title(f"{sym} GREEN CLOSE TOUCH {exn} RSI {res['rsi']:.1f}", fontsize=11, color='green', fontweight='bold')
    ax.grid(alpha=0.2)
    return fig

send_text(f"🚀 Scanning {datetime.utcnow().strftime('%H:%M UTC')}")

BLACKLIST={'BTC','ETH','BNB','SOL','XRP'}
EXS=[('MEXC',ccxt.mexc,{'enableRateLimit':True}),('OKX',ccxt.okx,{'enableRateLimit':True}),('GATE',ccxt.gate,{'enableRateLimit':True}),('BITGET',ccxt.bitget,{'enableRateLimit':True})]

found=[]
for exn,cls,opts in EXS:
    try:
        ex=cls(opts); ex.options['defaultType']='swap'; ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and ':USDT' in m['symbol']][:350]
        for sym in syms:
            clean=sym.split('/')[0]
            if any(b in clean.upper() for b in BLACKLIST): continue
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=80)
                if len(ohlcv)<70: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                res=scan(df)
                if res: found.append((res['score'],clean,exn,res))
            except: continue
    except: continue

top=sorted(found, key=lambda x: x[0], reverse=True)[:10]
send_text(f"📊 Found {len(found)} total → Sending TOP {len(top)}")
for score,clean,exn,res in top:
    fig=chart(res,clean,exn)
    cap=f"🔥 {clean} {exn} 4c RSI{res['rsi']:.1f}\nPrice {res['curr']:.6f} SL {res['sl']:.6f} TP {res['tp1']:.6f}\nGreen Close Touch {res['high']:.4f} Vol {res['vol']:.1f}x\nTIGHT BOTTOM Rank {top.index((score,clean,exn,res))+1}/{len(top)}"
    buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=140,bbox_inches='tight'); buf.seek(0); plt.close(fig)
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"}, files={"photo":buf}, timeout=25)
    time.sleep(0.6)

send_text(f"✅ Done {len(found)} → TOP {len(top)}")
