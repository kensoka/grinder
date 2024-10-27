import axios from 'axios';
import { TradingParameters} from '../types';

const api = axios.create({
  baseURL: '/api'
});

const WS_URL = `ws://localhost:8000/ws`;

export const botService = {
  start: (params: TradingParameters) => api.post('/bot/start', params),
  stop: () => api.post('/bot/stop'),
  getWebSocketUrl: () => WS_URL
};
