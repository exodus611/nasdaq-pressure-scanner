import pandas as pd
import numpy as np

def calculate_pressure_score(df):
    """Расчет Pressure Score (40%)"""
    if df.empty or len(df) < 20:
        return 0, {}
    
    avg_volume_20d = df['Volume'].rolling(20).mean().iloc[-1]
    volume_compression = (df['Volume'].iloc[-1] / avg_volume_20d) * 100
    volume_score = 100 - min(100, volume_compression)
    
    avg_atr_20d = df['ATR'].rolling(20).mean().iloc[-1]
    atr_compression = (df['ATR'].iloc[-1] / avg_atr_20d) * 100
    atr_score = 100 - min(100, atr_compression)
    
    df['Range'] = df['High'] - df['Low']
    avg_range_20d = df['Range'].rolling(20).mean().iloc[-1]
    range_compression = (df['Range'].iloc[-1] / avg_range_20d) * 100
    range_score = 100 - min(100, range_compression)
    
    higher_lows = 1 if df['Low'].iloc[-1] > df['Low'].iloc[-5] else 0
    
    resistance = df['High'].max() * 1.02
    breakout_distance = ((resistance - df['Close'].iloc[-1]) / resistance) * 100
    distance_score = min(100, breakout_distance)
    
    pressure_score = (
        volume_score * 0.25 + 
        atr_score * 0.25 + 
        range_score * 0.20 + 
        higher_lows * 15 + 
        distance_score * 0.15
    )
    
    return pressure_score, {
        'volume_compression': volume_compression,
        'atr_compression': atr_compression,
        'range_compression': range_compression,
        'higher_lows': higher_lows,
        'breakout_distance': breakout_distance
    }
