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
    except Exception as e: print(f"photo err {e}")

send_text(f"🚀 <b>V5 VOL 1.2x {datetime.utcnow().strftime('%H:%M UTC')}</b>\nTight+EMA Cross+Vol Pop 1.2x")

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

def scan_tight_ema_live(df_1d):
    if len(df_1d)<80: return None
    df_1d=df_1d.copy()
    df_1d['ema20']=ema(df_1d['c'],20); df_1d['ema50']=ema(df_1d['c'],50); df_1d['rsi']=rsi(df_1d['c'],14)
    last_c=df_1d['c'].iloc[-1]; last_ema=df_1d['ema20'].iloc[-1]
    prev_c=df_1d['c'].iloc[-2]; prev_ema=df_1d['ema20'].iloc[-2]
    cross = prev_c <= prev_ema*1.008 and last_c > last_ema
    if not cross: return None
    for ws in [2,3,4,5]:
        s=len(df_1d)-ws; w=df_1d.iloc[s:]
        low=w['l'].min(); low60=df_1d.iloc[max(0,len(df_1d)-61):-1]['l'].min(); low90=df_1d.iloc[max(0,len(df_1d)-91):-1]['l'].min()
        curr=last_c
        if low > low60*1.10: continue
        if low > low90*1.15: continue
        if curr > low*1.28: continue
        if df_1d['rsi'].iloc[-1] > 62: continue
        if w['rsi'].min() > 38: continue
        if sum(1 for _,r in w.iterrows() if is_hammer(r['o'],r['h'],r['l'],r['c']) or is_doji(r['o'],r['h'],r['l'],r['c'])) < 1: continue
        if (w['c'] > w['o']).sum() < 1: continue
        range_w=w['h'].max()-w['l'].min()+1e-9
        wick_ok=(w['c'].min()-low)/range_w>0.08
        ema_slope=df_1d['ema20'].iloc[-1] > df_1d['ema20'].iloc[-3]*0.983
        ema50_ok=curr > df_1d['ema50'].iloc[-1]*0.88
        vol_trend=w['v'].iloc[-2:].mean() > w['v'].iloc[:2].mean()*0.50
        pump_5d=curr/df_1d['c'].iloc[-6] if len(df_1d)>=6 else 1
        if not (wick_ok and ema_slope and ema50_ok and vol_trend): continue
        if pump_5d>1.14: continue
        if df_1d['rsi'].iloc[-6:-1].max()>72: continue
        sl=low*0.968; risk=curr-sl
        if risk<=0: continue
        return {'s':s,'e':len(df_1d)-1,'ws':ws,'low':low,'curr':curr,'sl':sl,'tp1':curr+risk*1.8,'tp2':curr+risk*3.2,'df':df_1d,'rsi':df_1d['rsi'].iloc[-1],'ema20':last_ema,'prev_c':prev_c,'prev_ema':prev_ema,'pump5':pump_5d}
    return None

def scan_pop_live(df_4h):
    if len(df_4h)<30: return None
    df_4h=df_4h.copy()
    df_4h['ema20']=ema(df_4h['c'],20); df_4h['rsi']=rsi(df_4h['c'],14)
    df_4h['vol_ma20']=df_4h['v'].rolling(20).mean()
    last=df_4h.iloc[-1]; prev=df_4h.iloc[-2]
    vol_pop=last['v'] > last['vol_ma20']*1.2  # EDITED: 1.2x (was 1.85x)
    ema_break=last['c'] > last['ema20'] and prev['c'] <= prev['ema20']*1.02
    bullish=last['c'] > last['o']
    rsi_ok=last['rsi']>38 and last['rsi']<72
    if vol_pop and ema_break and bullish and rsi_ok:
        return {'df':df_4h,'last':last,'vol_mult':last['v']/last['vol_ma20']}
    return None

def chart_1d(res,sym,exn):
    df=res['df'].tail(90)
    fig,ax=plt.subplots(figsize=(11,4.5))
    for i in range(len(df)-1):
        row=df.iloc[i]
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([df.index[i],df.index[i]],[row['l'],row['h']],color=col,lw=1)
        ax.plot([df.index[i],df.index[i]],[row['o'],row['c']],color=col,lw=3.5)
    last=df.iloc[-1]; li=df.index[-1]
    col_live='#00b26a' if last['c']>=last['o'] else '#ff3b30'
    ax.plot([li,li],[last['l'],last['h']],color=col_live,lw=2,ls='--')
    ax.plot([li,li],[last['o'],last['c']],color=col_live,lw=5,alpha=0.9)
    ax.scatter(li, last['c'], color='gold', s=280, edgecolor='black', zorder=6, marker='*')
    ax.plot(df.index, df['ema20'].tail(90), color='#5b4cff', lw=1.8, label='EMA20 1D')
    ax.plot(df.index, df['ema50'].tail(90), color='orange', lw=1.0, alpha=0.7, label='EMA50')
    ax.axvspan(res['s'], res['e'], color='lightgreen', alpha=0.22)
    ax.axhline(res['sl'], color='red', ls='--', label=f"SL {res['sl']:.4f}")
    ax.axhline(res['tp1'], color='green', ls='-', label=f"TP1 {res['tp1']:.4f}")
    ax.axhline(res['tp2'], color='darkgreen', ls='-', label=f"TP2 {res['tp2']:.4f}")
    ax.set_title(f"{sym} 1D LIVE {exn} {res['ws']}c RSI{res['rsi']:.1f} CROSS {res['curr']:.4f}>{res['ema20']:.4f} Pump{res['pump5']:.2f}x", fontsize=10, color='green')
    ax.legend(fontsize=6.5); ax.grid(alpha=0.2)
    return fig

def chart_4h(res_pop,res_1d,sym,exn):
    df=res_pop['df'].tail(80)
    fig,ax=plt.subplots(figsize=(11,4.5))
    for i in range(len(df)-1):
        row=df.iloc[i]
        col='#00b26a' if row['c']>=row['o'] else '#ff3b30'
        ax.plot([df.index[i],df.index[i]],[row['l'],row['h']],color=col,lw=1)
        ax.plot([df.index[i],df.index[i]],[row['o'],row['c']],color=col,lw=3.5)
    last=res_pop['last']; li=df.index[-1]
    col_live='#00b26a' if last['c']>=last['o'] else '#ff3b30'
    ax.plot([li,li],[last['l'],last['h']],color=col_live,lw=2,ls='--')
    ax.plot([li,li],[last['o'],last['c']],color=col_live,lw=5,alpha=0.9)
    ax.scatter(li, last['c'], color='gold', s=280, edgecolor='black', zorder=6, marker='*')
    ax.plot(df.index, df['ema20'].tail(80), color='#ff8c00', lw=1.8, label='EMA20 4H')
    ax.set_title(f"{sym} 4H POP {exn} Vol {res_pop['vol_mult']:.1f}x >1.2x {last['c']:.6f}>EMA", fontsize=11, color='green')
    ax.legend(fontsize=7); ax.grid(alpha=0.2)
    return fig

BLACKLIST = {'BTC','ETH','BNB','SOL','XRP','ETHFI','BTCDOM','SOLV','XRPBULL','XRPBEAR','SPCX','SPX','STOCK','NVDA','AAPL','TSLA','MSFT','GOOGL','AMZN','META','ADA','DOGE','SHIB','AVAX','DOT','LINK','LTC','BCH','TRX','UNI','ATOM','ETC'}
EXS = [('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType': 'swap'}})]

total=0; sent=set()
for exn, cls, opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[m['symbol'] for m in ex.markets.values() if 'USDT' in m['symbol'] and (m.get('type') in ['future','swap'] or ':USDT' in m['symbol'])][:450]
        send_text(f"📊 {exn}: {len(syms)} LIVE 1.2x")
        for sym in syms:
            clean=sym.split('/')[0].split(':')[0]
            if any(b in clean.upper() for b in BLACKLIST): continue
            if 'STOCK' in sym.upper() or 'SPX' in clean.upper(): continue
            if clean in sent: continue
            try:
                ohlcv_1d=ex.fetch_ohlcv(sym,'1d',limit=110)
                if len(ohlcv_1d)<80: continue
                df_1d=pd.DataFrame(ohlcv_1d,columns=['t','o','h','l','c','v'])
                res1=scan_tight_ema_live(df_1d)
                if not res1: continue
                ohlcv_4h=ex.fetch_ohlcv(sym,'4h',limit=80)
                if len(ohlcv_4h)<30: continue
                df_4h=pd.DataFrame(ohlcv_4h,columns=['t','o','h','l','c','v'])
                res4=scan_pop_live(df_4h)
                if not res4: continue
                sent.add(clean)
                fig1=chart_1d(res1,clean,exn)
                cap1=f"🔥 <b>{clean} 1D LIVE {exn}</b> Vol {res4['vol_mult']:.1f}x\nLIVE {res1['curr']:.6f} CROSS > {res1['ema20']:.6f}\nSL {res1['sl']:.6f} TP1 {res1['tp1']:.6f} TP2 {res1['tp2']:.6f}"
                send_photo(fig1,cap1); time.sleep(0.5)
                fig2=chart_4h(res4,res1,clean,exn)
                cap2=f"💥 <b>{clean} 4H POP {exn} Vol {res4['vol_mult']:.1f}x >1.2x</b>\nEnter Now"
                send_photo(fig2,cap2); total+=1; time.sleep(0.8)
            except: continue
    except Exception as e: send_text(f"⚠️ {exn} {str(e)[:120]}")

send_text(f"✅ <b>Done VOL 1.2x</b> Found {total}\n1D EMA CROSS + 4H Vol >1.2x")
