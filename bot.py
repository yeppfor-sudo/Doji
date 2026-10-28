import ccxt, pandas as pd, requests, os, io, time
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
        print(msg)
    except: pass

def send_photo(fig, cap):
    try:
        buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=130,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"},
            files={"photo":buf}, timeout=25)
    except Exception as e: print(e)

send_text(f"🚀 <b>FUTURES Bot {datetime.utcnow().strftime('%H:%M UTC')}</b>\nScanning BINANCE+MEXC+OKX...")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def is_doji(o,h,l,c): return (h-l)>0 and abs(c-o)/(h-l)<0.35
def is_hammer(o,h,l,c): b=abs(c-o); return b>0 and (min(o,c)-l)>b*1.2

def scan(df):
    if len(df)<70: return None
    df=df.iloc[:-1].copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    for end in range(len(df)-1, len(df)-11, -1):
        for ws in [2,3,4,5,6,7,8]:
            s=end-ws+1; w=df.iloc[s:end+1]
            low=w['l'].min(); low60=df.iloc[max(0,end-60):end]['l'].min()
            if low>low60*1.25: continue
            if (w['c']>w['o']).sum()<1: continue
            if sum(is_doji(r['o'],r['h'],r['l'],r['c']) or is_hammer(r['o'],r['h'],r['l'],r['c']) for _,r in w.iterrows())<1: continue
            if w['rsi'].min()>52 and df['rsi'].iloc[end]>58: continue
            curr=df.iloc[end]['c']; sl=low*0.96; risk=curr-sl
            if risk<=0: continue
            return {'s':s,'e':end,'ws':ws,'curr':curr,'sl':sl,'tp':curr+risk*2.8,'df':df,'rsi':df['rsi'].iloc[end]}
    return None

def chart(res,sym,exn):
    df=res['df'].tail(80)
    fig,ax=plt.subplots(figsize=(10,4))
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=3)
    ax.plot(df.index,res['df']['ema20'].tail(80),color='#5b4cff',lw=1)
    ax.axvspan(res['s'],res['e'],color='lightgreen',alpha=0.3)
    ax.axhline(res['sl'],color='red',ls='--'); ax.axhline(res['tp'],color='green')
    ax.set_title(f"{sym} FUTURES {exn} RSI{res['rsi']:.1f}"); ax.grid(alpha=0.2)
    return fig

# FUTURES - BINANCE ADDED FIRST
EXS = [
    ('BINANCE', ccxt.binance, {'enableRateLimit': True, 'options': {'defaultType': 'future'}}),
    ('BINANCE-PERP', ccxt.binanceusdm, {'enableRateLimit': True}),
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
]

total=0; scanned=0
for exn, cls, opts in EXS:
    try:
        ex=cls(opts)
        ex.load_markets()
        syms=[]
        for m in ex.markets.values():
            if 'USDT' in m['symbol'] and (m.get('type')=='future' or m.get('type')=='swap' or m.get('swap') or ':USDT' in m['symbol']):
                syms.append(m['symbol'])
        if not syms:
            syms=[s for s in ex.markets if 'USDT' in s]
        syms=syms[:350]
        
        send_text(f"📊 {exn} FUTURES: {len(syms)} pairs")
        print(f"{exn} FUTURES {len(syms)}")
        
        for sym in syms:
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1d',limit=90)
                if len(ohlcv)<70: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                scanned+=1
                res=scan(df)
                if res:
                    clean=sym.split('/')[0].split(':')[0]
                    fig=chart(res,clean,exn)
                    cap=f"🔥 <b>{clean} FUTURES {exn}</b> {res['ws']}c RSI{res['rsi']:.1f}\nPrice {res['curr']:.6f} SL {res['sl']:.6f} TP {res['tp']:.6f}\nType: PERP"
                    send_photo(fig,cap); total+=1
                    time.sleep(0.4)
                    if total>=20: break
            except: continue
        if total>=20: break
    except Exception as e:
        send_text(f"⚠️ {exn} blocked/skipped: {str(e)[:150]}")
        continue

send_text(f"✅ <b>FUTURES Done</b> Scanned {scanned} Found {total}\nWith BINANCE+MEXC+OKX+GATE+BITGET")
