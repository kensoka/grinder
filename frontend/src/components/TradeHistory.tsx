import React, { useState } from 'react';
import useWebSocket from 'react-use-websocket';
import { TradeHistory as TradeHistoryType } from '../types';
import { botService } from '../services/api';

export const TradeHistory: React.FC = () => {
  const [trades, setTrades] = useState<TradeHistoryType[]>([]);

  useWebSocket(botService.getWebSocketUrl(), {
    onMessage: (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'trades') {
        setTrades(data.payload || []);
      }
    },
    shouldReconnect: () => true,
    reconnectInterval: 3000,
  });

  return (
    <div className="trade-history">
      <h2>Trade History</h2>
      <table>
        <thead>
          <tr>
            <th>Buy Price</th>
            <th>Sell Price</th>
            <th>Quantity</th>
            <th>Profit</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {trades.length > 0 ? (
            trades.map((trade, index) => (
              <tr key={index}>
                <td>${trade.buy_price.toFixed(2)}</td>
                <td>${trade.sell_price.toFixed(2)}</td>
                <td>{trade.quantity}</td>
                <td>${trade.profit.toFixed(2)}</td>
                <td>{trade.executed_at}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>No trade history</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
