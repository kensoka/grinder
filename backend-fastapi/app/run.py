from main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
    
"""
{
    "symbol": "ETHUSDT",
    "asset_a_funds": 1000,
    "asset_b_funds": 0.5,
    "grids": 10,
    "deviation_threshold": 0.004,
    "growth_factor": 0.5,
    "use_granular_distribution": true,
    "trail_price": true,
    "only_profitable_trades": false
}
"""