from sqlmodel import SQLModel, Field
from typing import Optional
import datetime
from datetime import datetime

class TradingParameters(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = "BTCUSDT"
    asset_a_funds: float = 1000.0
    asset_b_funds: float = 0.1
    grids: int = 20
    deviation_threshold: float = 0.02
    trail_price: bool = True
    only_profitable_trades: bool = False
    growth_factor: float = 0.5
    use_granular_distribution: bool = True

class ActiveOrder(SQLModel, table=True):
    order_id: str = Field(primary_key=True)
    order_type: str = Field(index=True)
    price: float
    quantity: float
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        table_name = "active_order"
        arbitrary_types_allowed = True

class TradeHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    buy_price: float
    sell_price: float
    quantity: float
    profit: float
    executed_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        table_name = "trade_history"
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        arbitrary_types_allowed = True
