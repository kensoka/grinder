from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class TradingParametersSchema(BaseModel):
    symbol: str
    asset_a_funds: float
    asset_b_funds: float
    grids: int
    deviation_threshold: float
    trail_price: bool
    only_profitable_trades: bool
    growth_factor: float
    use_granular_distribution: bool

class ActiveOrderSchema(BaseModel):
    order_id: str
    order_type: str
    price: float
    quantity: float
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class TradeHistorySchema(BaseModel):
    id: Optional[int] = None
    buy_price: float
    sell_price: float
    quantity: float
    profit: float
    executed_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
