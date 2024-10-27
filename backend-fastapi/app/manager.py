import asyncio
import logging
from gridstrat import GridStrategy
from models.models import TradingParameters, ActiveOrder, TradeHistory
from sqlalchemy import delete
from sqlalchemy.future import select
from database import async_session
from typing import Optional, Dict, List
from schemas.schemas import TradingParametersSchema, ActiveOrderSchema, TradeHistorySchema
import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='grid_trading.log'
)

class TradingBotManager:
    _instance: Optional[GridStrategy] = None
    _bot_task: Optional[asyncio.Task] = None
    _start_time: Optional[datetime.datetime] = None

    @classmethod
    async def is_running(cls) -> bool:
        return cls._bot_task is not None and not cls._bot_task.done()

    @classmethod
    async def start_bot(cls, parameters: dict):
        if await cls.is_running():
            await cls.stop_bot()
        
        cls._instance = GridStrategy(**parameters)
        cls._bot_task = asyncio.create_task(cls._instance.execute_strategy())
        cls._start_time = datetime.datetime.now()  # Добавляем время старта

    @classmethod
    async def stop_bot(cls):
        if cls._instance:
            try:
                # Устанавливаем флаг остановки
                cls._instance.stop_flag = True
                
                # Отменяем все активные ордера и ждем подтверждения
                await cls._instance.cancel_all_orders()
                
                # Очищаем историю ордеров в базе данных
                async with async_session() as session:
                    await session.execute(delete(ActiveOrder))
                    await session.commit()
                
                # Закрываем все сессии и соединения
                await cls._instance.close_all_sessions()
                
                # Отменяем задачу бота если она существует
                if cls._bot_task and not cls._bot_task.done():
                    cls._bot_task.cancel()
                    try:
                        await cls._bot_task
                    except asyncio.CancelledError:
                        pass
                
                cls._instance = None
                cls._bot_task = None
                cls._start_time = None
                
                logging.info("Бот успешно остановлен и все сессии закрыты.")
                return True
                
            except Exception as e:
                logging.error(f"Ошибка при остановке бота: {e}")
                raise e  # Пробрасываем ошибку для обработки на уровне API

    @classmethod
    async def update_parameters(cls, parameters: dict):
        await cls.stop_bot()
        await cls.start_bot(parameters)

    @classmethod
    async def get_parameters(cls) -> dict:
        async with async_session() as session:
            result = await session.execute(select(TradingParameters).first())
            params = result.scalar_one_or_none()
            if params:
                return params.dict()
            return {}


    @classmethod
    async def get_current_price(cls) -> Optional[float]:
        if cls._instance:
            return cls._instance.current_price
        return None

    @classmethod
    async def get_initial_price(cls) -> Optional[float]:
        if cls._instance:
            return cls._instance.initial_price
        return None

    @classmethod
    async def get_deviation(cls) -> Optional[float]:
        if cls._instance and cls._instance.initial_price:
            return (cls._instance.current_price - cls._instance.initial_price) / cls._instance.initial_price
        return None

    @classmethod
    async def get_real_time_data(cls):
        if cls._instance:
            return await cls._instance.get_real_time_data()
        return None

    @classmethod
    async def get_realized_profit_a(cls) -> float:
        if cls._instance:
            return cls._instance.realized_profit_a
        return 0.0

    @classmethod
    async def get_realized_profit_b(cls) -> float:
        if cls._instance:
            return cls._instance.realized_profit_b
        return 0.0

    @classmethod
    def get_instance(cls) -> Optional[GridStrategy]:
        return cls._instance

    @classmethod
    async def get_current_parameters(cls) -> Optional[dict]:
        if cls._instance:
            return {
                "symbol": cls._instance.symbol,
                "asset_a_funds": cls._instance.asset_a_funds,
                "asset_b_funds": cls._instance.asset_b_funds,
                "grids": cls._instance.grids,
                "deviation_threshold": cls._instance.deviation_threshold,
                "trail_price": cls._instance.trail_price,
                "only_profitable_trades": cls._instance.only_profitable_trades,
                "growth_factor": cls._instance.growth_factor,
                "use_granular_distribution": cls._instance.use_granular_distribution
            }
        return None

    @classmethod
    async def get_start_time(cls) -> Optional[datetime.datetime]:
        return cls._start_time if cls._start_time else None

    @classmethod
    async def get_total_profit(cls) -> float:
        async with async_session() as session:
            result = await session.execute(select(TradeHistory))
            trades = result.scalars().all()
            return sum(trade.profit for trade in trades)

    