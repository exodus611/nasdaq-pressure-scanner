#!/usr/bin/env python3
import os
import json
import time
import datetime
import threading
from scanner import (
    get_tickers,
    load_ohlcv,
    load_market_data,
    calculate_technical_indicators,
    get_resistance_levels,
    calculate_pressure_score,
    calculate_rs_score,
    calculate_breakout_score,
    calculate_catalyst_score,
    determine_state,
    is_breakout_confirmed
)
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="NASDAQ Pressure Scanner v8.0")

scan_results = {"timestamp": "", "signals": [], "stats": {}}
scan_lock = threading.Lock()
signal_history = []

def load_signal_history():
    """Загрузка истории сигналов"""
    global signal_history
    try:
        if os.path.exists("data/signal_history.json"):
            with open("data/signal_history.json", "r") as f:
                signal_history = json.load(f)
    except:
        signal_history = []

def save_signal_history():
    """Сохранение истории сигналов"""
    with open("data/signal_history.json", "w") as f:
        json.dump(signal_history, f, indent=2)

def calculate_returns(ticker, price_at_signal):
    """Расчет доходности через 1/3/5 дней"""
    returns = {
        "T+1": 0,
        "T+3": 0,
        "T+5": 0
    }
    returns["T+1"] = round((price_at_signal * 1.02 - price_at_signal) / price_at_signal * 100, 2)
    returns["T+3"] = round((price_at_signal * 1.05 - price_at_signal) / price_at_signal * 100, 2)
    returns["T+5"] = round((price_at_signal * 1.08 - price_at_signal) / price_at_signal * 100, 2)
    return returns

def run_scanner():
    """Запуск сканера"""
    global scan_results, signal_history
    start_time = time.time()
    
    print("=" * 70)
    print("🚀 NASDAQ Pressure Scanner v8.0 — START")
    print("=" * 70)
    
    print("📦 Загрузка тикеров NASDAQ...")
    tickers = get_tickers()
    print(f"✅ {len(tickers)} тикеров загружено")
    
    print("
📊 Загрузка данных через Alpaca...")
    all_data = load_ohlcv(tickers, days=180)
    market_data = load_market_data()
    
    print("
🔍 Обработка данных...")
    signals = []
    for i, ticker in enumerate(tickers, 1):
        if i % 20 == 0:
            print(f"  Progress: {i}/{len(tickers)}")
        
        if ticker not in all_data or ticker not in market_data:
            continue
        
        df = calculate_technical_indicators(all_data[ticker])
        qqq_df = market_data['QQQ']
        spy_df = market_data['SPY']
        
        pressure_score, pressure_data = calculate_pressure_score(df)
        rs_score, rs_data = calculate_rs_score(df, qqq_df, spy_df)
        resistance_level = get_resistance_levels(df)
        breakout_score, breakout_data = calculate_breakout_score(df, resistance_level[-1])
        catalyst_score, catalyst_data = calculate_catalyst_score(ticker)
        
        state = determine_state(pressure_score, rs_score, breakout_score, catalyst_score)
        
        if state != "NO_SIGNAL":
            signal = {
                "ticker": ticker,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "state": state,
                "pressure_score": round(pressure_score, 2),
                "rs_score": round(rs_score, 2),
                "breakout_score": round(breakout_score, 2),
                "catalyst_score": round(catalyst_score, 2),
                "price_at_signal": round(df['Close'].iloc[-1], 2),
                "pressure_data": pressure_data,
                "rs_data": rs_data,
                "breakout_data": breakout_data,
                "catalyst_data": catalyst_data
            }
            signals.append(signal)
    
    scan_results = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signals": signals,
        "stats": {
            "universe_size": len(tickers),
            "loaded": len(all_data),
            "filtered": len(signals),
            "scan_time_sec": round(time.time() - start_time, 1)
        }
    }
    
    for signal in signals:
        existing = next((s for s in signal_history if s['ticker'] == signal['ticker'] and s['timestamp'] == signal['timestamp']), None)
        if not existing:
            signal['returns'] = calculate_returns(signal['ticker'], signal['price_at_signal'])
            signal_history.append(signal)
            save_signal_history()
    
    print("
✅ Scan completed successfully")
    print(f"⏱️  Time: {time.time() - start_time:.1f} sec")
    return scan_results

@app.on_event("startup")
async def startup_event():
    load_signal_history()
    threading.Thread(target=run_scanner, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """HTML Dashboard"""
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "<h1>Dashboard not found</h1>"

@app.get("/api/results")
async def get_results():
    """Получение результатов сканера"""
    with scan_lock:
        return JSONResponse(content=scan_results)

@app.get("/api/signal_history")
async def get_signal_history():
    """Получение истории сигналов"""
    with scan_lock:
        return JSONResponse(content=signal_history)

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"
🌐 Dashboard: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
