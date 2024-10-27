export interface TradingParameters {
    symbol: string;
    asset_a_funds: number;
    asset_b_funds: number;
    grids: number;
    deviation_threshold: number;
    trail_price: boolean;
    only_profitable_trades: boolean;
    growth_factor: number;
    use_granular_distribution: boolean;
}

export interface ActiveOrder {
    order_id: string;
    order_type: 'buy' | 'sell';
    price: number;
    quantity: number;
    created_at?: string;
}

export interface TradeHistory {
    buy_price: number;
    sell_price: number;
    quantity: number;
    profit: number;
    executed_at?: string;
}

export interface BotStatus {
    status: 'running' | 'stopped';
    current_price: number | null;
    total_profit: number;
    active_orders_count: number;
    completed_trades_count: number;
    running_time: string | null;
  }