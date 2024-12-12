import axios from 'axios';
import { TradingParameters } from '../types';

const api = axios.create({
  baseURL: '/api'
});

const WS_URL = `ws://https://1d93-2a02-2698-6c2e-cd71-b5bc-cb6-845f-620e.ngrok-free.app//ws`;

export const botService = {
  start: (params: TradingParameters) => api.post('/bot/start', params),
  stop: (botId: number) => api.post(`/bot/${botId}/stop`),
  getBots: () => api.get('/bots'),
  getWebSocketUrl: () => WS_URL,
  getBotStatus: async (botId: number): Promise<string> => {
    try {
      const response = await api.get(`/bots`);
      const bot = response.data.bots.find((b: any) => b.id === botId);
      return bot?.status || 'inactive';
    } catch (error) {
      console.error('Error getting bot status:', error);
      return 'inactive';
    }
  }
}; 