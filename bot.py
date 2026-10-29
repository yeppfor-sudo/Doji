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
        buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=140,bbox_inches='tight')
        buf.seek(0); plt.close(fig)
        r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id":CHAT_ID,"caption":cap,"parse_mode":"HTML"},
            files={"photo":buf}, timeout=25)
        print(f"sent {r.status_code}")
    except Exception as e: print(e)

send_text(f"🚀 <b>1D BOTTOM + 4H EMA BREAKOUT Scan {datetime.utcnow().strftime('%H:%M UTC')}</b>\nScan 1D + Confirm 4H")

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=(d.where(d>0,0)).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def is_doji(o,h,l,c): return (h-l)>0 and abs(c-o)/(h-l)<0.25
def is_hammer(o,h,l,c): 
    b=abs(c-o)
    if b==0 or (h-l)==0: return False
    lower=min(o,c)-l; upper=h-max(o,c)
    return lower > b*1.8 and upper < b*0.5

def scan_1d(df):
    if len(df)<80: return None
    df=df.iloc[:-1].copy()
    df['ema20']=ema(df['c'],20); df['rsi']=rsi(df['c'],14)
    for end in range(len(df)-1, len(df)-6, -1):
        for ws in [2,3,4,5]:
            s=end-ws+1; w=df.iloc[s:end+1]
            low=w['l'].min(); low60=df.iloc[max(0,end-60):end]['l'].min(); low90=df.iloc[max(0,end-90):end]['l'].min()
            curr=df.iloc[end]['c']
            if low > low60*1.08: continue
            if low > low90*1.12: continue
            if curr > low*1.06: continue
            if df['rsi'].iloc[end] > 38: continue
            if w['rsi'].min() > 32: continue
            if sum(1 for _,r in w.iterrows() if is_hammer(r['o'],r['h'],r['l'],r['c']) or is_doji(r['o'],r['h'],r['l'],r['c'])) < 1: continue
            if (w['c'] > w['o']).sum() < 1: continue
            if curr <= w['c'].min(): continue
            sl=low*0.97; risk=curr-sl
            if risk<=0: continue
            return {'s':s,'e':end,'ws':ws,'low':low,'curr':curr,'sl':sl,'tp':curr+risk*3.0,'df':df,'rsi':df['rsi'].iloc[end],'low60':low60}
    return None

def check_4h_breakout(df_4h):
    """Return True if bullish candle closed above 20EMA on 4H"""
    if len(df_4h)<30: return None
    df_4h=df_4h.iloc[:-1].copy() # last closed 4h candle
    df_4h['ema20']=ema(df_4h['c'],20)
    last=df_4h.iloc[-1]; prev=df_4h.iloc[-2]
    # Condition: Bullish candle + Close above EMA20 + Previous close below EMA (fresh breakout) OR just above
    bullish = last['c'] > last['o']
    above_ema = last['c'] > last['ema20']
    # Fresh breakout preferred: prev was below or touching
    fresh = prev['c'] <= prev['ema20']*1.01
    if bullish and above_ema:
        return {'fresh': fresh, 'df': df_4h, 'last': last, 'ema20': last['ema20']}
    return None

def chart_1d(res,sym,exn):
    df=res['df'].tail(90)
    fig,ax=plt.subplots(figsize=(11,4.5))
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=3.5)
    ax.plot(df.index,res['df']['ema20'].tail(90),color='#5b4cff',lw=1.2,label='EMA20 D')
    ax.axvspan(res['s'],res['e'],color='lightgreen',alpha=0.25)
    ax.axhline(res['sl'],color='red',ls='--'); ax.axhline(res['tp'],color='green')
    ax.set_title(f"{sym} 1D FUTURES {exn} {res['ws']}c RSI{res['rsi']:.1f} - MAIN",fontsize=11); ax.grid(alpha=0.2); ax.legend()
    return fig

def chart_4h(res_4h,sym,exn):
    df=res_4h['df'].tail(80)
    fig,ax=plt.subplots(figsize=(11,4.5))
    for idx,row in df.iterrows():
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([idx,idx],[row['l'],row['h']],color=col,lw=1)
        ax.plot([idx,idx],[row['o'],row['c']],color=col,lw=3.5)
    ax.plot(df.index,df['ema20'],color='#ff8c00',lw=1.5,label='EMA20 4H')
    # highlight breakout candle
    ax.scatter(df.index[-1], res_4h['last']['c'], color='gold', s=120, edgecolor='black', zorder=5, label='4H BREAKOUT')
    ax.set_title(f"{sym} 4H FUTURES {exn} Close {res_4h['last']['c']:.6f} > EMA20 {res_4h['ema20']:.6f} - ENTRY",fontsize=11, color='green' if res_4h['fresh'] else 'black')
    ax.legend(); ax.grid(alpha=0.2)
    return fig

BLACKLIST = {'BTC','ETH','BNB','SOL','XRP','ETHFI','BTCDOM','SOLV','XRPBULL','XRPBEAR',
             'SPCX','SPX','STOCK','NVDA','AAPL','TSLA','MSFT','GOOGL','AMZN','META',
             'ADA','DOGE','SHIB','AVAX','DOT','LINK','LTC','BCH','TRX','UNI','ATOM','ETC',
             'KWEB','QQQ','SPY'}

EXS = [
    ('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
]

total=0; scanned=0; sent_symbols=set()
for exn, cls, opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])]
        syms=syms[:500]
        send_text(f"📊 {exn}: {len(syms)} pairs - 1D scan + 4H breakout check")
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0]
            if any(b in clean.upper() for b in BLACKLIST): continue
            if 'STOCK' in sym.upper() or 'SPX' in clean.upper(): continue
            if clean in sent_symbols: continue
            try:
                # 1. SCAN 1D MAIN
                ohlcv_1d=ex.fetch_ohlcv(sym,'1d',limit=100)
                if len(ohlcv_1d)<80: continue
                df_1d=pd.DataFrame(ohlcv_1d,columns=['t','o','h','l','c','v'])
                res_1d=scan_1d(df_1d)
                if not res_1d: continue
                
                # 2. CONFIRM 4H BREAKOUT
                ohlcv_4h=ex.fetch_ohlcv(sym,'4h',limit=100)
                df_4h=pd.DataFrame(ohlcv_4h,columns=['t','o','h','l','c','v'])
                res_4h=check_4h_breakout(df_4h)
                if not res_4h: continue # skip if no 4H breakout
                
                scanned+=1
                sent_symbols.add(clean)
                
                # 3. SEND 2 PHOTOS
                fig1=chart_1d(res_1d,clean,exn)
                cap1=f"📈 <b>{clean} 1D FUTURES {exn}</b>\n{res_1d['ws']}c RSI {res_1d['rsi']:.1f}\nPrice {res_1d['curr']:.6f} SL {res_1d['sl']:.6f} TP {res_1d['tp']:.6f}\nMAIN CHART - Bottom Found"
                send_photo(fig1,cap1)
                time.sleep(0.5)
                
                fig2=chart_4h(res_4h,clean,exn)
                fresh_txt = "FRESH BREAKOUT 🔥" if res_4h['fresh'] else "Above EMA"
                cap2=f"⚡ <b>{clean} 4H BREAKOUT {exn}</b> {fresh_txt}\nBullish Close {res_4h['last']['c']:.6f}\nAbove 20EMA {res_4h['ema20']:.6f}\nENTRY TIMEFRAME - Trade Setup\n1D SL {res_1d['sl']:.6f}"
                send_photo(fig2,cap2)
                total+=1
                time.sleep(0.8)
                
            except Exception as e:
                # print(e)
                continue
    except Exception as e:
        send_text(f"⚠️ {exn} {str(e)[:100]}"); continue

send_text(f"✅ <b>Done</b> Scanned {scanned} 1D bottoms with 4H breakout | Found {total} pairs | 2 photos each")
