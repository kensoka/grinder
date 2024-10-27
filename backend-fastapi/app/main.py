from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict, List, Set
import logging
import uvicorn
from gridstrat import GridStrategy
from schemas.schemas import TradingParametersSchema
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
import datetime
from manager import TradingBotManager
from schemas.schemas import TradingParametersSchema
from database import async_session
from sqlalchemy.future import select
from models.models import ActiveOrder, TradeHistory
import asyncio
from sqlalchemy import delete


# Отключаем логи SQLAlchemy
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

# Настраиваем основное логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# Отключаем ненужные логи
logging.getLogger('websockets').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('aiohttp').setLevel(logging.ERROR)

router = APIRouter()
active_connections: Set[WebSocket] = set()


app = FastAPI(title="Grid Trading Bot")
app.include_router(router)


# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Store bot instance
bot_instance: Dict[str, GridStrategy] = {}


@app.on_event("startup")
async def startup_event():
    await init_db()

@app.post("/api/bot/start")
async def start_bot(params: TradingParametersSchema):
    try:
        # Очищаем базу данных перед запуском новой стратегии
        await clear_database()
        
        strategy = GridStrategy(
            symbol=params.symbol,
            asset_a_funds=params.asset_a_funds,
            asset_b_funds=params.asset_b_funds,
            grids=params.grids,
            deviation_threshold=params.deviation_threshold,
            growth_factor=params.growth_factor,
            use_granular_distribution=params.use_granular_distribution,
            trail_price=params.trail_price,
            only_profitable_trades=params.only_profitable_trades
        )
        
        bot_instance["bot"] = strategy
        await strategy.execute_strategy()
        return {"status": "Bot started successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bot/stop")
async def stop_bot():
    if "bot" in bot_instance:
        try:
            bot_instance["bot"].stop()
            await bot_instance["bot"].close()
            del bot_instance["bot"]
            return {"status": "Bot stopped successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error stopping bot: {str(e)}")
    raise HTTPException(status_code=404, detail="Bot is not running")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                await self.disconnect(connection)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            try:
                # Получаем статус бота
                is_running = await TradingBotManager.is_running()
                current_price = await TradingBotManager.get_current_price()
                total_profit = await TradingBotManager.get_total_profit()
                
                # Получаем время работы
                start_time = await TradingBotManager.get_start_time()
                running_time = str(datetime.datetime.now() - start_time) if start_time else None

                # Получаем данные из базы
                async with async_session() as session:
                    # Получаем активные ордера
                    result_orders = await session.execute(select(ActiveOrder))
                    active_orders = result_orders.scalars().all()
                    active_orders_count = len(active_orders)
                    
                    # Получаем историю сделок
                    result_trades = await session.execute(select(TradeHistory))
                    trade_history = result_trades.scalars().all()
                    completed_trades_count = len(trade_history)

                # Отправляем статус
                status_update = {
                    "type": "status_update",
                    "data": {
                        "status": is_running,
                        "current_price": current_price,
                        "total_profit": total_profit,
                        "active_orders_count": active_orders_count,
                        "completed_trades_count": completed_trades_count,
                        "running_time": running_time
                    }
                }
                await manager.broadcast(status_update)

                # Отправляем данные об ордерах и сделках
                orders_data = [
                    {
                        "order_id": order.order_id,
                        "order_type": order.order_type,
                        "price": order.price,
                        "quantity": order.quantity,
                        "created_at": order.created_at.isoformat()
                    }
                    for order in active_orders
                ]

                trades_data = [
                    {
                        "buy_price": trade.buy_price,
                        "sell_price": trade.sell_price,
                        "quantity": trade.quantity,
                        "profit": trade.profit,
                        "executed_at": trade.executed_at.isoformat()
                    }
                    for trade in trade_history
                ]

                await manager.broadcast({"type": "orders", "payload": orders_data})
                await manager.broadcast({"type": "trades", "payload": trades_data})

                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error sending updates: {e}")
                break
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        manager.disconnect(websocket)

@app.on_event("shutdown")
async def shutdown_event():
    if "bot" in bot_instance:
        try:
            bot_instance["bot"].stop()
            await bot_instance["bot"].close()
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")

async def clear_database():
    """Очищает все таблицы в базе данных."""
    async with async_session() as session:
        try:
            # Очищаем таблицу активных ордеров
            await session.execute(delete(ActiveOrder))
            # Очищаем таблицу истории торгов
            await session.execute(delete(TradeHistory))
            await session.commit()
            logging.info("База данных успешно очищена")
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при очистке базы данных: {e}")
            raise

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
