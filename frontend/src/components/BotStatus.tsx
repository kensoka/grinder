import React, { useState } from 'react';
import useWebSocket from 'react-use-websocket';
import { botService } from '../services/api';
import { BotStatus as BotStatusType } from '../types';

export const BotStatus: React.FC = () => {
  const [status, setStatus] = useState<BotStatusType | null>(null);

  useWebSocket(botService.getWebSocketUrl(), {
    onMessage: (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'status_update') {
        setStatus({
          status: data.data.status,
          current_price: data.data.current_price,
          total_profit: data.data.total_profit,
          active_orders_count: data.data.active_orders_count,
          completed_trades_count: data.data.completed_trades_count,
          running_time: data.data.running_time
        });
      }
    },
    shouldReconnect: () => true,
    reconnectInterval: 3000,
  });

  if (!status) return <div>Загрузка...</div>;

  return (
    <div className="bot-status">
      <h2>Статус бота</h2>
      <div className="status-grid">
        <div className="status-item">
          <span className="label">Status:</span>
          <span className={`value ${status.status}`}>
            {status.status === 'running' ? 'running' : 'Stopped'}
          </span>
        </div>
        
        <div className="status-item">
          <span className="label">Current Price:</span>
          <span className="value">
            {status.current_price ? `$${status.current_price.toFixed(2)}` : 'Н/Д'}
          </span>
        </div>
        
        <div className="status-item">
          <span className="label">Total Profit:</span>
          <span className={`value ${status.total_profit >= 0 ? 'positive' : 'negative'}`}>
            ${status.total_profit.toFixed(8)}
          </span>
        </div>
        
        <div className="status-item">
          <span className="label">Number of Active Orders:</span>
          <span className="value">{status.active_orders_count}</span>
        </div>
        
        <div className="status-item">
          <span className="label">Number of Completed Trades:</span>
          <span className="value">{status.completed_trades_count}</span>
        </div>
        
        {status.running_time && (
          <div className="status-item">
            <span className="label">Strategy Duration:</span>
            <span className="value">{status.running_time}</span>
          </div>
        )}
      </div>
    </div>
  );
};
