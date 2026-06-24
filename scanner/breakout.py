import pandas as pd
import numpy as np

def calculate_breakout_score(df, resistance_level):
    """Расчет Breakout Proximity Score (20%)"""
    current_price = df['Close'].iloc[-1]
    price_vs_resistance = (current_price / resistance_level) * 100
    
    avg_volume_20d = df['Volume'].rolling(20).mean().iloc[-1]
    volume_surge = (df['Volume'].iloc[-1] / avg_volume_20d) * 100
    
    breakout_score = (
        min(100, max(0, price_vs_resistance)) * 0.60 + 
        min(200, max(0, volume_surge)) * 0.40
    )
    
    return breakout_score, {
        'price_vs_resistance': price_vs_resistance,
        'volume_surge': volume_surge
    }
