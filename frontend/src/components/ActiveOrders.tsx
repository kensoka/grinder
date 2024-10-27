import React, { useState } from 'react';
import useWebSocket from 'react-use-websocket';
import { ActiveOrder } from '../types';
import { botService } from '../services/api';

export const ActiveOrders: React.FC = () => {
  const [orders, setOrders] = useState<ActiveOrder[]>([]);

  useWebSocket(botService.getWebSocketUrl(), {
    onMessage: (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'orders') {
        setOrders(data.payload || []);
      }
    },
    shouldReconnect: () => true,
    reconnectInterval: 3000,
  });

  return (
    <div className="active-orders">
      <h2>Active Orders</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Type</th>
            <th>Price</th>
            <th>Quantity</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {orders.length > 0 ? (
            orders.map((order) => (
              <tr key={order.order_id}>
                <td>{order.order_id}</td>
                <td>{order.order_type}</td>
                <td>${order.price.toFixed(2)}</td>
                <td>{order.quantity}</td>
                <td>{order.created_at}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>No active orders</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
