def determine_state(pressure_score, rs_score, breakout_score, catalyst_score):
    """Определение состояния сигнала"""
    if pressure_score >= 95 and rs_score >= 90 and breakout_score >= 95 and catalyst_score >= 86:
        return "TRIGGERED"
    elif pressure_score >= 85 and rs_score >= 80 and breakout_score >= 85 and catalyst_score >= 71:
        return "READY"
    elif pressure_score >= 75 and rs_score >= 65 and breakout_score >= 70 and catalyst_score >= 50:
        return "WATCH"
    else:
        return "NO_SIGNAL"
    
def is_breakout_confirmed(df, resistance_level):
    """Проверка подтверждения пробития"""
    current_price = df['Close'].iloc[-1]
    volume = df['Volume'].iloc[-1]
    avg_volume_20d = df['Volume'].rolling(20).mean().iloc[-1]
    
    price_above_resistance = current_price > resistance_level
    volume_surge = volume > (avg_volume_20d * 1.5)
    
    return price_above_resistance and volume_surge
