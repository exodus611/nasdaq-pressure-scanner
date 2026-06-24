# NASDAQ Pressure Scanner v8.0

Advanced stock scanner for identifying pre-breakout opportunities on NASDAQ.

## Features

- **Pressure Score (40%)**: Volume/ATR/Range compression analysis
- **Relative Strength (30%)**: Performance vs QQQ/SPY
- **Breakout Proximity (20%)**: Distance to resistance levels
- **Catalyst Detection (10%)**: Earnings, news, institutional activity

## Signal States

- **WATCH**: Monitoring phase (Pressure 75-84, RS 65-79)
- **READY**: Pre-entry phase (Pressure 85-94, RS 80-89)
- **TRIGGERED**: Entry confirmed (Pressure 95+, RS 90+)

## Setup

1. Add environment variables to Railway:
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`

2. Deploy and access dashboard at your Railway URL

## API Endpoints

- `/` - Dashboard
- `/api/results` - Current scan results
- `/api/signal_history` - Historical signal data
- `/api/health` - Health check
