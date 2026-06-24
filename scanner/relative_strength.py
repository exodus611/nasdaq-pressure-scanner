import pandas as pd
import numpy as np

def calculate_rs_score(ticker_df, qqq_df, spy_df):
    """Расчет Relative Strength Score (30%)"""
    def calculate_return(df):
        if len(df) < 5:
            return 0
        return (df['Close'].iloc[-1] / df['Close'].iloc[-5] - 1) * 100
    
    ticker_return = calculate_return(ticker_df)
    qqq_return = calculate_return(qqq_df)
    spy_return = calculate_return(spy_df)
    
    rs_vs_qqq = (ticker_return / qqq_return) * 100 if qqq_return != 0 else 100
    rs_vs_spy = (ticker_return / spy_return) * 100 if spy_return != 0 else 100
    
    rs_score = (
        min(200, max(0, rs_vs_qqq)) * 0.70 + 
        min(200, max(0, rs_vs_spy)) * 0.30
    )
    
    if qqq_return < 0 and ticker_return > 0:
        rs_score = min(200, rs_score + 50)
    
    return rs_score, {
        'rs_vs_qqq': rs_vs_qqq,
        'rs_vs_spy': rs_vs_spy,
        'ticker_return': ticker_return,
        'qqq_return': qqq_return,
        'spy_return': spy_return
    }
