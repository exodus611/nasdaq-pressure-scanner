import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient, StockBarsRequest, TimeFrame, DataFeed
from alpaca.data.timeframe import TimeFrameUnit
from ta.volatility import AverageTrueRange
from ta.trend import PSARIndicator

def get_alpaca_client():
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("ALPACA_API_KEY и ALPACA_SECRET_KEY не установлены!")
    return StockHistoricalDataClient(api_key, secret_key)

def load_ohlcv(tickers, days=180):
    """Загрузка OHLCV через Alpaca с IEX feed (бесплатный план)"""
    client = get_alpaca_client()
    end = datetime.now()
    start = end - timedelta(days=days)
    all_data = {}
    
    # ВАЖНО: IEX feed для бесплатного плана
    # SIP feed требует платной подписки
    feed = DataFeed.IEX
    
    batch_size = 50  # Меньше для надёжности
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    
    print(f"  📡 Загрузка через Alpaca (IEX feed): {len(tickers)} тикеров, {total_batches} батчей...")
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        batch_num = i // batch_size + 1
        
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                start=start,
                end=end,
                limit=1000,
                feed=feed
            )
            bars = client.get_stock_bars(request)
            
            loaded_count = 0
            for symbol in batch:
                if symbol in bars and bars[symbol]:
                    df = pd.DataFrame([{
                        'Open': bar.open,
                        'High': bar.high,
                        'Low': bar.low,
                        'Close': bar.close,
                        'Volume': bar.volume,
                        'Date': bar.timestamp
                    } for bar in bars[symbol]])
                    
                    if not df.empty:
                        df.set_index('Date', inplace=True)
                        df.sort_index(inplace=True)
                        if len(df) >= 20:  # Минимум 20 дней для расчётов
                            all_data[symbol] = df
                            loaded_count += 1
            
            if batch_num % 5 == 0 or batch_num == total_batches:
                print(f"    Batch {batch_num}/{total_batches}: {loaded_count}/{len(batch)} тикеров", flush=True)
            
        except Exception as e:
            err_msg = str(e)
            if "subscription" in err_msg.lower() or "sip" in err_msg.lower():
                print(f"    ⚠️ Batch {batch_num}: Ошибка подписки - {err_msg[:100]}")
            else:
                print(f"    ⚠️ Batch {batch_num}: {err_msg[:100]}")
    
    print(f"  ✅ Всего загружено: {len(all_data)} тикеров")
    return all_data

def load_market_data():
    """Загрузка данных QQQ и SPY для расчёта Relative Strength"""
    print("  📡 Загрузка QQQ и SPY для расчёта RS...")
    return load_ohlcv(['QQQ', 'SPY', 'SPY', 'IWM'], days=30)

def calculate_technical_indicators(df):
    """Расчет технических индикаторов"""
    if df is None or df.empty or len(df) < 20:
        return df
    
    df = df.copy()
    
    try:
        # ATR
        atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
        df['ATR'] = atr.average_true_range()
    except:
        df['ATR'] = 0
    
    try:
        # PSAR
        psar = PSARIndicator(high=df['High'], low=df['Low'], close=df['Close'], step=0.02, max_step=0.2)
        df['PSAR'] = psar.psar()
    except:
        df['PSAR'] = df['Close']
    
    return df

def get_resistance_levels(df, window=20):
    """Определение уровней сопротивления"""
    if df is None or df.empty or len(df) < window:
        return [df['High'].max() * 1.02 if not df.empty else 100]
    
    resistance = []
    for i in range(window, len(df)):
        recent_max = df['High'].iloc[max(0, i-window):i].max()
        if df['High'].iloc[i] >= recent_max * 0.98:
            resistance.append(df['High'].iloc[i])
    
    if not resistance:
        return [df['High'].max() * 1.02]
    
    # Возвращаем последние 5 уникальных уровней
    unique_levels = []
    for level in resistance[-10:]:
        if not unique_levels or abs(level - unique_levels[-1]) / unique_levels[-1] > 0.02:
            unique_levels.append(level)
    
    return unique_levels[-5:] if unique_levels else [df['High'].max() * 1.02]
