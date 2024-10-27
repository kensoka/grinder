import React, { useState } from 'react';
import { botService } from '../services/api';
import { TradingParameters } from '../types';

const defaultParams: TradingParameters = {
  symbol: "ETHUSDT",
  asset_a_funds: 1000,
  asset_b_funds: 0.1,
  grids: 10,
  deviation_threshold: 0.004,
  growth_factor: 0.5,
  use_granular_distribution: true,
  trail_price: true,
  only_profitable_trades: false
};

export const BotControl: React.FC = () => {
  const [params, setParams] = useState<TradingParameters>(defaultParams);
  const [isLoading, setIsLoading] = useState(false); // Добавляем состояние загрузки

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setParams(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : type === 'number' ? parseFloat(value) : value
    }));
  };

  const handleStart = async () => {
    try {
      await botService.start(params);
      alert('Bot started successfully');
    } catch (error) {
      alert('Error starting bot');
    }
  };

  const handleStop = async () => {
    try {
      setIsLoading(true);
      await botService.stop();
      alert('Bot stopped successfully');
    } catch (error) {
      console.error('Error stopping bot:', error);
      alert('Error stopping bot: ' + (error as Error).message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bot-control">
      <h2>Bot Control</h2>
      <form onSubmit={(e) => { e.preventDefault(); handleStart(); }}>
        <div className="form-grid">
          <div className="form-group">
            <label>Trading Pair:</label>
            <input
              type="text"
              name="symbol"
              value={params.symbol}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label>Asset A Funds:</label>
            <input
              type="number"
              name="asset_a_funds"
              value={params.asset_a_funds}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label>Asset B Funds:</label>
            <input
              type="number"
              name="asset_b_funds"
              value={params.asset_b_funds}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label>Number of Grids:</label>
            <input
              type="number"
              name="grids"
              value={params.grids}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label>Deviation Threshold:</label>
            <input
              type="number"
              name="deviation_threshold"
              step="0.001"
              value={params.deviation_threshold}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label>Growth Factor:</label>
            <input
              type="number"
              name="growth_factor"
              step="0.1"
              value={params.growth_factor}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group checkbox">
            <label>
              <input
                type="checkbox"
                name="use_granular_distribution"
                checked={params.use_granular_distribution}
                onChange={handleInputChange}
              />
              Use Granular Distribution
            </label>
          </div>

          <div className="form-group checkbox">
            <label>
              <input
                type="checkbox"
                name="trail_price"
                checked={params.trail_price}
                onChange={handleInputChange}
              />
              Trail Price
            </label>
          </div>

          <div className="form-group checkbox">
            <label>
              <input
                type="checkbox"
                name="only_profitable_trades"
                checked={params.only_profitable_trades}
                onChange={handleInputChange}
              />
              Only Profitable Trades
            </label>
          </div>
        </div>

        <div className="button-group">
          <button 
            type="submit" 
            className="start-button"
            disabled={isLoading}
          >
            Start Bot
          </button>
          <button 
            type="button" 
            onClick={handleStop} 
            className="stop-button"
            disabled={isLoading}
          >
            {isLoading ? 'Stopping...' : 'Stop Bot'}
          </button>
        </div>
      </form>
    </div>
  );
};
