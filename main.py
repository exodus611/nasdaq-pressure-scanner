#!/usr/bin/env python3
import os, sys, re, json, time, datetime, threading
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import uvicorn
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from alpaca.data import StockHistoricalDataClient, StockBarsRequest, TimeFrame, DataFeed
from alpaca.data.timeframe import TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from ta.volatility import AverageTrueRange
from ta.trend import PSARIndicator

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
DEEPSEEK_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")

print("="*70)
for name, val in [("ALPACA_API_KEY",ALPACA_KEY),("ALPACA_SECRET_KEY",ALPACA_SECRET),("DEEPSEEK_API_KEY",DEEPSEEK_KEY)]:
    print(f"  {name}: {'OK' if val else 'MISSING'}")
if not ALPACA_KEY or not ALPACA_SECRET:
    print("❌ Добавь ALPACA ключи в Railway Variables"); sys.exit(1)
if not DEEPSEEK_KEY:
    print("❌ Добавь DEEPSEEK_API_KEY в Railway Variables"); sys.exit(1)
print("✅ Все ключи найдены\n")

CACHE_FILE = "tickers_cache.json"
CACHE_TTL_HRS = 24
TICKER_SOURCES = [
    {"name":"Alpaca NASDAQ","type":"alpaca_nasdaq"},
    {"name":"Alpaca All US","type":"alpaca_all"},
    {"name":"Nasdaq.com API","type":"nasdaq_api",
     "url":"https://api.nasdaq.com/api/screener/stocks?tableType=traded&exchange=NASDAQ&limit=10000",
     "headers":{"User-Agent":"Mozilla/5.0","Accept":"application/json","Referer":"https://www.nasdaq.com/"}},
    {"name":"NASDAQ FTP","type":"ftp_txt",
     "url":"https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt",
     "headers":{"User-Agent":"Mozilla/5.0"}},
    {"name":"GitHub backup","type":"plain_list",
     "url":"https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt",
     "headers":{}},
]

def _is_valid_ticker(s):
    if not s or len(s)>6: return False
    if "$" in s or "." in s: return False
    if re.search(r"[A-Z]{4,}(WS|W|U|R)$",s): return False
    return True

def _load_ticker_cache():
    if not os.path.exists(CACHE_FILE): return []
    try:
        with open(CACHE_FILE) as f: cache=json.load(f)
        cached_at=datetime.datetime.fromisoformat(cache["cached_at"])
        if datetime.datetime.now()-cached_at<timedelta(hours=CACHE_TTL_HRS):
            print(f"  💾 Кэш: {len(cache['tickers'])} тикеров"); return cache["tickers"]
        print("  ⏰ Кэш устарел")
    except: pass
    return []

def _save_ticker_cache(tickers):
    try:
        with open(CACHE_FILE,"w") as f: json.dump({"cached_at":datetime.datetime.now().isoformat(),"tickers":tickers},f)
        print(f"  💾 Кэш сохранён: {len(tickers)}")
    except Exception as e: print(f"  ⚠️ {e}")

def _fetch_alpaca_tickers(nasdaq_only=True):
    try:
        client=TradingClient(ALPACA_KEY,ALPACA_SECRET,paper=True)
        assets=client.get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE,asset_class=AssetClass.US_EQUITY))
        tickers=[a.symbol for a in assets if a.tradable and
                 (not nasdaq_only or (a.exchange and "NASDAQ" in a.exchange.upper())) and _is_valid_ticker(a.symbol)]
        print(f"  ✅ Alpaca {'NASDAQ' if nasdaq_only else 'All'}: {len(tickers)}"); return tickers
    except Exception as e: print(f"  ❌ Alpaca: {e}"); return []

def _fetch_http_tickers(src):
    for attempt in range(3):
        try:
            r=requests.get(src["url"],headers=src.get("headers",{}),timeout=30)
            if r.status_code!=200: time.sleep((attempt+1)*5); continue
            raw=[]
            if src["type"]=="nasdaq_api": raw=[row.get("symbol","").strip() for row in r.json().get("data",{}).get("rows",[])]
            elif src["type"]=="ftp_txt":
                for line in r.text.strip().split("\n")[1:]:
                    parts=line.split("|")
                    if len(parts)>=2: raw.append(parts[0].strip())
            elif src["type"]=="plain_list": raw=[t.strip() for t in r.text.strip().split("\n") if t.strip()]
            valid=[t for t in raw if _is_valid_ticker(t)]
            print(f"  ✅ {src['name']}: {len(valid)}"); return valid if len(valid)>500 else []
        except Exception as e: print(f"  ⚠️ {src['name']}: {e}"); time.sleep((attempt+1)*5)
    return []

def get_tickers():
    print("📦 Загрузка тикеров...")
    cached=_load_ticker_cache()
    if cached: return cached
    for src in TICKER_SOURCES:
        tickers=_fetch_alpaca_tickers(src["type"]=="alpaca_nasdaq") if src["type"].startswith("alpaca") else _fetch_http_tickers(src)
        if tickers and len(tickers)>500: _save_ticker_cache(tickers); return tickers
    print("❌ Тикеры не загружены!"); return []

def _fix_yfinance_df(df,ticker):
    if isinstance(df.columns,pd.MultiIndex):
        lvl=df.columns.get_level_values(1)
        df=df.xs(ticker,axis=1,level=1) if ticker in lvl else df.droplevel(1,axis=1)
    return df

def load_via_alpaca_iex(tickers,days=180):
    client=StockHistoricalDataClient(ALPACA_KEY,ALPACA_SECRET)
    end,start=datetime.datetime.now(),datetime.datetime.now()-timedelta(days=days)
    all_data,bs={},50
    total=(len(tickers)+bs-1)//bs
    print(f"  📡 Alpaca IEX: {len(tickers)} тикеров, {total} батчей...")
    for i in range(0,len(tickers),bs):
        batch,bn=tickers[i:i+bs],i//bs+1
        try:
            bars=client.get_stock_bars(StockBarsRequest(symbol_or_symbols=batch,
                timeframe=TimeFrame(1,TimeFrameUnit.Day),start=start,end=end,limit=1000,feed=DataFeed.IEX))
            loaded=0
            for sym in batch:
                if sym in bars and bars[sym] and len(bars[sym])>=20:
                    df=pd.DataFrame([{"Open":b.open,"High":b.high,"Low":b.low,"Close":b.close,"Volume":b.volume,"Date":b.timestamp} for b in bars[sym]])
                    df.set_index("Date",inplace=True); df.sort_index(inplace=True); all_data[sym]=df; loaded+=1
            if bn%10==0 or bn==total: print(f"    Batch {bn}/{total}: {loaded}/{len(batch)}",flush=True)
        except Exception as e:
            if bn%10==0 or bn==total: print(f"    Batch {bn}/{total}: ERR {str(e)[:60]}",flush=True)
    return all_data

def _dl_yahoo(ticker,days):
    try:
        df=yf.download(ticker,period=f"{days}d",interval="1d",progress=False)
        if df.empty: return ticker,None
        df=_fix_yfinance_df(df,ticker)
        return ticker,df if len(df)>=20 else None
    except: return ticker,None

def load_via_yahoo_fallback(tickers,days=180):
    print(f"  📡 Yahoo: {len(tickers)} тикеров (x5)...")
    all_data,done={},0
    with ThreadPoolExecutor(max_workers=5) as ex:
        for future in as_completed({ex.submit(_dl_yahoo,t,days):t for t in tickers}):
            ticker,df=future.result(); done+=1
            if df is not None: all_data[ticker]=df
            if done%200==0: print(f"    {done}/{len(tickers)} ({len(all_data)} OK)",flush=True)
    print(f"    ✅ Yahoo: {len(all_data)}"); return all_data

def load_ohlcv(tickers,days=180):
    print("\n📊 Alpaca IEX → Yahoo Finance")
    alpaca=load_via_alpaca_iex(tickers,days)
    missing=[t for t in tickers if t not in alpaca]
    yahoo=load_via_yahoo_fallback(missing,days) if missing else {}
    all_data={**alpaca,**yahoo}
    print(f"✅ ИТОГО: {len(all_data)}/{len(tickers)}"); return all_data

def load_market_data():
    print("\n📡 QQQ, SPY, IWM...")
    etfs=["QQQ","SPY","IWM"]
    data=load_via_alpaca_iex(etfs,days=30)
    missing=[t for t in etfs if t not in data]
    if missing: data.update(load_via_yahoo_fallback(missing,days=30))
    print(f"  ✅ ETF: {len(data)}"); return data

def calculate_technical_indicators(df):
    if df is None or df.empty or len(df)<20: return df
    df=df.copy()
    try: df["ATR"]=AverageTrueRange(high=df["High"],low=df["Low"],close=df["Close"],window=14).average_true_range()
    except: df["ATR"]=0.0
    try: df["PSAR"]=PSARIndicator(high=df["High"],low=df["Low"],close=df["Close"],step=0.02,max_step=0.2).psar()
    except: df["PSAR"]=df["Close"]
    return df

def get_resistance_levels(df,window=20):
    if df is None or df.empty or len(df)<window:
        return [df["High"].max()*1.02 if df is not None and not df.empty else 100]
    resistance=[]
    for i in range(window,len(df)):
        if df["High"].iloc[i]>=df["High"].iloc[max(0,i-window):i].max()*0.98: resistance.append(df["High"].iloc[i])
    if not resistance: return [df["High"].max()*1.02]
    unique=[]
    for level in resistance[-10:]:
        if not unique or abs(level-unique[-1])/unique[-1]>0.02: unique.append(level)
    return unique[-5:] if unique else [df["High"].max()*1.02]

def calculate_pressure_score(df):
    if df.empty or len(df)<20: return 0,{}
    avg_vol=df["Volume"].rolling(20).mean().iloc[-1]
    vol_score=100-min(100,(df["Volume"].iloc[-1]/avg_vol)*100)
    avg_atr=df["ATR"].rolling(20).mean().iloc[-1]
    atr_score=100-min(100,(df["ATR"].iloc[-1]/avg_atr)*100)
    df=df.copy(); df["Range"]=df["High"]-df["Low"]
    rng_score=100-min(100,(df["Range"].iloc[-1]/df["Range"].rolling(20).mean().iloc[-1])*100)
    higher_lows=1 if df["Low"].iloc[-1]>df["Low"].iloc[-5] else 0
    dist_score=min(100,((df["High"].max()*1.02-df["Close"].iloc[-1])/(df["High"].max()*1.02))*100)
    score=vol_score*0.25+atr_score*0.25+rng_score*0.20+higher_lows*15+dist_score*0.15
    return score,{}

def calculate_rs_score(tdf,qdf,sdf):
    def ret(df): return (df["Close"].iloc[-1]/df["Close"].iloc[-5]-1)*100 if len(df)>=5 else 0
    tr,qr,sr=ret(tdf),ret(qdf),ret(sdf)
    rs_qqq=(tr/qr*100) if qr!=0 else 100
    rs_spy=(tr/sr*100) if sr!=0 else 100
    score=min(200,max(0,rs_qqq))*0.70+min(200,max(0,rs_spy))*0.30
    if qr<0 and tr>0: score=min(200,score+50)
    return score,{}

def calculate_breakout_score(df,resistance):
    pct=(df["Close"].iloc[-1]/resistance)*100
    vol_surge=(df["Volume"].iloc[-1]/df["Volume"].rolling(20).mean().iloc[-1])*100
    return min(100,max(0,pct))*0.60+min(200,max(0,vol_surge))*0.40,{}

def calculate_catalyst_score(ticker): return 40.0,{}

def determine_state(p,rs,b,c):
    if p>=95 and rs>=90 and b>=95 and c>=86: return "TRIGGERED"
    if p>=85 and rs>=80 and b>=85 and c>=71: return "READY"
    if p>=75 and rs>=65 and b>=70 and c>=50: return "WATCH"
    return "NO_SIGNAL"

DASHBOARD_HTML = """<!DOCTYPE html><html><head><title>NASDAQ Pressure Scanner v8.1</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,sans-serif;margin:20px;background:#f5f5f5}
h1{color:#333;text-align:center}.container{max-width:1200px;margin:0 auto}
.stats{display:flex;justify-content:space-around;margin:20px 0;flex-wrap:wrap;gap:10px}
.stat-box{background:white;padding:15px 25px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.1);text-align:center}
.stat-value{font-size:26px;font-weight:bold;color:#0066cc}
.signal-card{background:white;margin-bottom:20px;padding:20px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.1)}
.state-watch{border-left:4px solid #4caf50}.state-ready{border-left:4px solid #ff9800}.state-triggered{border-left:4px solid #f44336}
.signal-header{display:flex;justify-content:space-between;margin-bottom:10px}
.signal-title{font-size:18px;font-weight:bold}
.state-badge{padding:5px 10px;border-radius:4px;color:white;font-weight:bold}
.watch{background:#4caf50}.ready{background:#ff9800}.triggered{background:#f44336}
.score-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.score-box{background:#f9f9f9;padding:10px;border-radius:4px}
.score-label{font-size:12px;color:#666}.score-value{font-size:20px;font-weight:bold}
.history-table{width:100%;border-collapse:collapse;margin-top:30px}
.history-table th,.history-table td{padding:10px 12px;text-align:left;border-bottom:1px solid #ddd}
.history-table th{background:#f2f2f2}.scanning{text-align:center;padding:40px;color:#888;font-size:18px}
</style></head><body><div class="container">
<h1>NASDAQ Pressure Scanner v8.1</h1>
<div class="stats">
<div class="stat-box"><div>Универсум</div><div class="stat-value" id="u">—</div></div>
<div class="stat-box"><div>Загружено</div><div class="stat-value" id="l">—</div></div>
<div class="stat-box"><div>Сигналов</div><div class="stat-value" id="f">—</div></div>
<div class="stat-box"><div>Время</div><div class="stat-value" id="t">—</div></div>
<div class="stat-box"><div>Обновлено</div><div class="stat-value" id="ts" style="font-size:14px">—</div></div>
</div>
<h2>Текущие сигналы</h2>
<div id="sc"><div class="scanning">⏳ Сканирование...</div></div>
<h2 style="margin-top:40px">История</h2>
<table class="history-table"><thead><tr>
<th>Тикер</th><th>Статус</th><th>Дата</th><th>Цена</th>
<th>Pressure</th><th>RS</th><th>Breakout</th><th>Catalyst</th>
<th>T+1</th><th>T+3</th><th>T+5</th>
</tr></thead><tbody id="hc"></tbody></table>
</div>
<script>
async function go(){
try{
const d=(await(await fetch("/api/results")).json()),s=d.stats||{};
document.getElementById("u").textContent=s.universe_size??"—";
document.getElementById("l").textContent=s.loaded??"—";
document.getElementById("f").textContent=s.filtered??"—";
document.getElementById("t").textContent=s.scan_time_sec?s.scan_time_sec+"s":"—";
document.getElementById("ts").textContent=d.timestamp||"—";
const box=document.getElementById("sc");
if(!d.signals||!d.signals.length){box.innerHTML='<div class="scanning">Нет сигналов</div>';}
else{box.innerHTML=d.signals.map(s=>`<div class="signal-card state-${s.state.toLowerCase()}">
<div class="signal-header"><div class="signal-title">${s.ticker} $${s.price_at_signal}</div>
<span class="state-badge ${s.state.toLowerCase()}">${s.state}</span></div>
<div class="score-grid">
<div class="score-box"><div class="score-label">Pressure</div><div class="score-value">${s.pressure_score}</div></div>
<div class="score-box"><div class="score-label">RS</div><div class="score-value">${s.rs_score}</div></div>
<div class="score-box"><div class="score-label">Breakout</div><div class="score-value">${s.breakout_score}</div></div>
<div class="score-box"><div class="score-label">Catalyst</div><div class="score-value">${s.catalyst_score}</div></div>
</div></div>`).join("");}
const h=(await(await fetch("/api/signal_history")).json());
document.getElementById("hc").innerHTML=h.map(s=>`<tr>
<td><b>${s.ticker}</b></td><td><span class="state-badge ${s.state.toLowerCase()}">${s.state}</span></td>
<td>${s.timestamp}</td><td>$${s.price_at_signal}</td>
<td>${s.pressure_score}</td><td>${s.rs_score}</td><td>${s.breakout_score}</td><td>${s.catalyst_score}</td>
<td>${(s.returns||{})["T+1"]??"—"}%</td><td>${(s.returns||{})["T+3"]??"—"}%</td><td>${(s.returns||{})["T+5"]??"—"}%</td>
</tr>`).join("");
}catch(e){console.error(e)}}
setInterval(go,30000);go();
</script></body></html>"""

app=FastAPI(title="NASDAQ Pressure Scanner v8.1")
scan_results={"timestamp":"","signals":[],"stats":{}}
scan_lock=threading.Lock()
signal_history=[]
os.makedirs("data",exist_ok=True)

def _load_history():
    global signal_history
    try:
        if os.path.exists("data/signal_history.json"):
            with open("data/signal_history.json") as f: signal_history=json.load(f)
    except: signal_history=[]

def _save_history():
    try:
        with open("data/signal_history.json","w") as f: json.dump(signal_history,f,indent=2)
    except Exception as e: print(f"⚠️ {e}")

def run_scanner():
    global scan_results
    print("="*70+"\nNASDAQ Pressure Scanner v8.1 — START\n"+"="*70)
    t0=time.time()
    try:
        tickers=get_tickers()
        if not tickers: print("❌ Тикеры не загружены"); return
        all_data=load_ohlcv(tickers,days=180)
        market=load_market_data()
        if "QQQ" not in market or "SPY" not in market: print("❌ QQQ/SPY не загружены"); return
        signals=[]
        for i,ticker in enumerate(tickers,1):
            if i%100==0: print(f"Progress: {i}/{len(tickers)}, signals: {len(signals)}",flush=True)
            if ticker not in all_data: continue
            df=calculate_technical_indicators(all_data[ticker])
            if df is None or df.empty or len(df)<20: continue
            p,_=calculate_pressure_score(df)
            rs,_=calculate_rs_score(df,market["QQQ"],market["SPY"])
            res=get_resistance_levels(df)
            b,_=calculate_breakout_score(df,res[-1])
            c,_=calculate_catalyst_score(ticker)
            state=determine_state(p,rs,b,c)
            if state!="NO_SIGNAL":
                signals.append({"ticker":ticker,
                    "timestamp":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "state":state,"pressure_score":round(p,2),"rs_score":round(rs,2),
                    "breakout_score":round(b,2),"catalyst_score":round(c,2),
                    "price_at_signal":round(df["Close"].iloc[-1],2)})
        elapsed=round(time.time()-t0)
        with scan_lock:
            scan_results={"timestamp":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "signals":signals,"stats":{"universe_size":len(tickers),"loaded":len(all_data),
                "filtered":len(signals),"scan_time_sec":elapsed}}
        print(f"\n✅ Скан завершён за {elapsed}s — {len(signals)} сигналов")
        _save_history()
    except Exception as e:
        print(f"❌ {e}"); import traceback; traceback.print_exc()

@app.on_event("startup")
async def startup_event():
    _load_history(); threading.Thread(target=run_scanner,daemon=True).start()

@app.get("/",response_class=HTMLResponse)
async def dashboard(): return DASHBOARD_HTML

@app.get("/api/results")
async def get_results():
    with scan_lock: return JSONResponse(content=scan_results)

@app.get("/api/signal_history")
async def get_signal_history():
    with scan_lock: return JSONResponse(content=signal_history)

@app.get("/api/health")
async def health(): return {"status":"ok","timestamp":datetime.datetime.now().isoformat()}

if __name__=="__main__":
    port=int(os.environ.get("PORT",8000))
    print(f"🚀 http://0.0.0.0:{port}")
    uvicorn.run(app,host="0.0.0.0",port=port)
