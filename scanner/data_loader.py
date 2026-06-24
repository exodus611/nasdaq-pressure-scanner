import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient, StockBarsRequest, TimeFrame
from ta.volatility import AverageTrueRange
from ta.trend import PSARIndicator

def get_alpaca_client():
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise ValueError("ALPACA_API_KEY и ALPACA_SECRET_KEY не установлены в переменных окружения!")
    return StockHistoricalDataClient(api_key, secret_key)

def load_ohlcv(tickers, days=180):
    """Загрузка OHLCV через Alpaca для основных тикеров"""
    client = get_alpaca_client()
    end = datetime.now()
    start = end - timedelta(days=days)
    all_data = {}
    
    batch_size = 100
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                limit=5000
            )
            bars = client.get_stock_bars(request)
            
            for symbol in batch:
                if symbol in bars and bars[symbol]:
                    df = pd.DataFrame([{
                        'Open': bar.open,
                        'High': bar.high,
                        'Low': bar.low,
                        'Close': bar.close,
                        'Volume': bar.volume
                    } for bar in bars[symbol]])
                    df['Date'] = pd.to_datetime([bar.timestamp for bar in bars[symbol]])
                    df.set_index('Date', inplace=True)
                    df.sort_index(inplace=True)
                    all_data[symbol] = df
        except Exception as e:
            print(f"⚠️ Error loading {batch}: {e}")
    
    return all_data

def load_market_data():
    """Загрузка данных QQQ и SPY"""
    return load_ohlcv(['QQQ', 'SPY'], days=10)

def calculate_technical_indicators(df):
    """Расчет технических индикаторов"""
    if df.empty or len(df) < 20:
        return df
    
    # ATR
    atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
    df['ATR'] = atr.average_true_range()
    
    # PSAR
    psar = PSARIndicator(high=df['High'], low=df['Low'], close=df['Close'], step=0.02, max_step=0.2)
    df['PSAR'] = psar.psar()
    
    return df

def get_resistance_levels(df, window=20):
    """Определение уровней сопротивления"""
    if df.empty:
        return []
    
    resistance = []
    for i in range(window, len(df)):
        if df['High'].iloc[i] > df['High'].iloc[i-window:i].max():
            resistance.append(df['High'].iloc[i])
    
    return resistance[-5:] if resistance else [df['High'].max() * 1.02]
