import ccxt, pandas as pd, requests, os, io, time
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=20)
    except: pass

def send_photo(fig, cap):
    try:
        buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=130,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"},
            files={"photo":buf}, timeout=25)
    except Exception as e: print(e)

send_text(f"🚀 <b>Bot started {datetime.utcnow().strftime('%H:%M UTC')}</b>\nScanning...")

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
            if low>low60*1.20: continue
            if (w['c']>w['o']).sum()<1: continue
            if sum(is_doji(r['o'],r['h'],r['l'],r['c']) or is_hammer(r['o'],r['h'],r['l'],r['c']) for _,r in w.iterrows())<1: continue
            if w['rsi'].min()>50 and df['rsi'].iloc[end]>55: continue
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
    ax.set_title(f"{sym} {exn} RSI{res['rsi']:.1f}"); ax.grid(alpha=0.2)
    return fig

# EXCHANGES THAT WORK IN US GITHUB - NO BYBIT
EXS=[('MEXC',ccxt.mexc),('OKX',ccxt.okx),('GATE',ccxt.gateio),('BITGET',ccxt.bitget),('KUCOIN',ccxt.kucoin)]

total=0; scanned=0; errors=[]
for exn, cls in EXS:
    try:
        ex=cls({'enableRateLimit':True,'options':{'defaultType':'swap'}})
        ex.load_markets()
        syms=[s for s in ex.markets if 'USDT' in s and (':USDT' in s or '/USDT' in s)][:500]
        print(f"{exn} {len(syms)}")
        for sym in syms:
            try:
                ohlcv=ex.fetch_ohlcv(sym,'1D',limit=90)
                if len(ohlcv)<70: continue
                df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
                scanned+=1
                res=scan(df)
                if res:
                    clean=sym.split('/')[0].split(':')[0]
                    fig=chart(res,clean,exn)
                    cap=f"🔥 <b>{clean} {exn}</b> {res['ws']}c RSI{res['rsi']:.1f}\nPrice {res['curr']:.6f} SL {res['sl']:.6f} TP {res['tp']:.6f}"
                    send_photo(fig,cap); total+=1
                    time.sleep(0.5)
                    if total>=20: break
            except: continue
    except Exception as e:
        print(f"{exn} fail {e}"); errors.append(f"{exn} fail"); continue

send_text(f"✅ <b>Done</b> Scanned {scanned} Found {total}\nErrors: {', '.join(errors) if errors else 'none'}")
