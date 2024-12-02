import asyncio
import datetime
import json
import logging
import uvicorn
from database import async_session, init_db
from binance_client import BinanceClient
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from strategies.gridstrat import GridStrategy
#from strategies.otherstrat import OtherStrategy  # Импорт других стратегий
from kline_manager import KlineManager
from manager import TradingBotManager
from models.models import (
    BaseBot, 
    GridBotConfig, 
    ActiveOrder, 
    TradeHistory, 
    OrderHistory
)
from sqlalchemy import delete, func, update
from sqlalchemy.future import select
from starlette.websockets import WebSocketState
from typing import Dict, List, Set, Optional, Callable, Union
import signal
import sys

# Отключаем ненужные логи
logging.getLogger('websockets').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('aiohttp').setLevel(logging.ERROR)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

# Создаем логгер для websocket
ws_logger = logging.getLogger('websocket')
ws_logger.setLevel(logging.DEBUG)

router = APIRouter()
active_connections: Set[WebSocket] = set()

app = FastAPI(title="Trading Bot Manager")
app.include_router(router)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Хранилище KlineManager по WebSocket соединениям
kline_managers: Dict[int, KlineManager] = {}
kline_tasks: Dict[int, asyncio.Task] = {} 

active_tasks = {}  # Словарь для отслеживания активных задач

async def get_task_key(bot_id: int, task_type: str) -> str:
    return f"{bot_id}_{task_type}"

async def is_task_running(bot_id: int, task_type: str) -> bool:
    task_key = await get_task_key(bot_id, task_type)
    return task_key in active_tasks and not active_tasks[task_key].done()

@app.on_event("startup")
async def startup_event():
    await init_db()

@app.post("/api/bot/start")
async def start_bot(params: dict):
    async with async_session() as session:
        try:
            base_asset = params.get('baseAsset')
            quote_asset = params.get('quoteAsset')
            base_asset_funds = params.get('asset_b_funds')
            quote_asset_funds = params.get('asset_a_funds')
            
            binance_client = BinanceClient(api_key=params['api_key'], api_secret=params['api_secret'], testnet=params.get('testnet'))
            
            await binance_client.is_balance_sufficient(base_asset, quote_asset, base_asset_funds, quote_asset_funds)
            
            #TODO: проверка на наличие средств на балансе

            # Создаем бота в БД
            bot = BaseBot(
                name=f"Bot_{params['symbol']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
                type=params['type'],
                symbol=params['symbol'],
                api_key=params['api_key'],
                api_secret=params['api_secret'],
                testnet=params.get('testnet', True),
                status='active'
            )
            session.add(bot)
            await session.commit()
            await session.refresh(bot)
            
            # Запускаем бота через менеджер
            await TradingBotManager.start_bot(
                bot_id=bot.id,
                bot_type=params['type'],
                parameters=params
            )
            
            return {"status": "success", "bot_id": bot.id}
            
        except Exception as e:
            logging.error(f"Ошибка при создании бота: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            await session.rollback()


@app.post("/api/bot/{bot_id}/stop")
async def stop_bot(bot_id: int):
    try:
        await TradingBotManager.stop_bot(bot_id)
        return {"status": "Bot stopped successfully", "bot_id": bot_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                ws_logger.error(f"Ошибка при отправке сообщения: {e}")
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    ws_logger.info(f"WebSocket подключен: {websocket.client}")
    connection_id = id(websocket)

    try:
        while True:
            if websocket.client_state == WebSocketState.DISCONNECTED:
                break

            try:
                subscription_message = await websocket.receive_json()
                bot_id = subscription_message.get("bot_id")
                msg_type = subscription_message.get("type")

                if not bot_id or not msg_type:
                    continue

                task_key = await get_task_key(bot_id, msg_type)
                
                # Проверяем, не запущена ли уже задача этого типа
                if await is_task_running(bot_id, msg_type):
                    ws_logger.debug(f"Task {task_key} is already running")
                    continue

                # Создаем и запускаем новую задачу
                if msg_type == "status":
                    task = asyncio.create_task(bot_status_service(bot_id))
                elif msg_type == "active_orders":
                    task = asyncio.create_task(active_orders_service(bot_id))
                elif msg_type == "order_history":
                    task = asyncio.create_task(order_history_service(bot_id))
                elif msg_type == "trade_history":
                    task = asyncio.create_task(trade_history_service(bot_id))
                else:
                    continue

                # Сохраняем задачу в словаре активных задач
                active_tasks[task_key] = task
                
                # Добавляем callback для удаления завершенной задачи
                def remove_task(future):
                    active_tasks.pop(task_key, None)
                
                task.add_done_callback(remove_task)

            except WebSocketDisconnect:
                ws_logger.info(f"WebSocket отключен: {websocket.client}")
                await asyncio.sleep(5)
                try:
                    await manager.connect(websocket)
                    ws_logger.info(f"WebSocket переподключен: {websocket.client}")
                except Exception as reconnect_error:
                    ws_logger.error(f"Ошибка при переподключении: {reconnect_error}")
                continue
            except Exception as e:
                ws_logger.error(f"Ошибка обработки сообщения: {e}")
                await asyncio.sleep(0.1)
                continue

    finally:
        # Отменяем все задачи при отключении
        for task_key, task in list(active_tasks.items()):
            if not task.done():
                task.cancel()
        active_tasks.clear()
        manager.disconnect(websocket)
        ws_logger.info(f"WebSocket соединение закрыто: {websocket.client}")

async def shutdown_bots():
    async with async_session() as session:
        try:
            # Обновляем статус всех ботов на неактивный
            await session.execute(
                update(BaseBot)
                .values(status='inactive', updated_at=datetime.datetime.utcnow())
            )
            await session.commit()
            
            # Останавливаем все активные боты
            for bot_id in list(TradingBotManager._bots.keys()):
                try:
                    await TradingBotManager.stop_bot(bot_id)
                except Exception as e:
                    logging.error(f"Error stopping bot {bot_id} during shutdown: {e}")
                    
        except Exception as e:
            await session.rollback()
            logging.error(f"Error updating bot statuses during shutdown: {e}")
            raise

def signal_handler(sig, frame):
    logging.info(f"Received signal {sig}")
    # Вместо создания нового loop используем существующий
    try:
        loop = asyncio.get_running_loop()
        if loop and loop.is_running():
            loop.create_task(shutdown_bots())
    except RuntimeError:
        # Если loop не найден, создаем новый
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(shutdown_bots())
    finally:
        sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler) # kill <pid>

@app.on_event("shutdown")
async def shutdown_event():
    await shutdown_bots()

async def clear_database(bot_id: int):
    """Очищает таблицы в базе данных для конкретного бота или все таблицы."""
    async with async_session() as session:
        try:
            if bot_id is not None:
                # Очищаем данные только для конкретного бота
                await session.execute(delete(ActiveOrder).where(ActiveOrder.bot_id == bot_id))
                await session.execute(delete(TradeHistory).where(TradeHistory.bot_id == bot_id))
                await session.execute(delete(OrderHistory).where(OrderHistory.bot_id == bot_id))
            else:
                # Оищаем все данные
                await session.execute(delete(ActiveOrder))
                await session.execute(delete(TradeHistory))
                await session.execute(delete(OrderHistory))
            await session.commit()
            logging.info(f"База данных успешно очищена{' для бота ' + str(bot_id) if bot_id else ''}")
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при очистке базы данных: {e}")
            raise

@app.get("/api/bots")
async def get_bots():
    """Возвращает список всех активных ботов"""
    try:
        async with async_session() as session:
            result = await session.execute(select(BaseBot))
            bots = result.scalars().all()
            return {"bots": [
                {
                    "id": bot.id,
                    "type": bot.type,
                    "symbol": bot.symbol,
                    "status": bot.status,
                    "uptime": (datetime.datetime.now() - bot.created_at).total_seconds()
                }
                for bot in bots
            ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/bot/{bot_id}")
async def delete_bot(bot_id: int):
    """Останавливает бота и удаляет его данные из базы"""
    try:
        await TradingBotManager.stop_bot(bot_id)
        await clear_database(bot_id)
        async with async_session() as session:
            bot = await session.get(BaseBot, bot_id)
            if bot:
                await session.delete(bot)
                await session.commit()
                logging.info(f"Бот {bot_id} удален из баы данных")
        return {"status": "Bot deleted successfully", "bot_id": bot_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def bot_status_service(bot_id: int):
    async with async_session() as session:
        while True:
            try:
                ws_logger.debug(f"bot_status_service: bot_id = {bot_id}")
                parameters = await TradingBotManager.get_current_parameters(bot_id)
                if parameters is None:
                    await asyncio.sleep(5)
                    continue
                bot_status_data = {
                    "status": parameters["status"],
                    "current_price": parameters["current_price"],
                    "deviation": parameters["deviation"],
                        
                    "realized_profit_a": parameters["realized_profit_a"],
                    "realized_profit_b": parameters["realized_profit_b"],
                    "total_profit_usdt": parameters["total_profit_usdt"],
                        
                    "active_orders_count": parameters["active_orders_count"],
                    "completed_trades_count": parameters["completed_trades_count"],
                        
                    "running_time": parameters["running_time"],

                    "unrealized_profit_a": parameters["unrealized_profit_a"],
                    "unrealized_profit_b": parameters["unrealized_profit_b"],
                    "unrealized_profit_usdt": parameters["unrealized_profit_usdt"],
                        
                    "initial_parameters": parameters["initial_parameters"],
                }   
                
                await manager.broadcast({
                    "type": "bot_status_data", 
                    "bot_id": bot_id,
                    "payload": bot_status_data
                })
                
                await asyncio.sleep(1)
                
            except Exception as e:
                ws_logger.error(f"Ошибка при отправке bot_status_data: {e}")
                await asyncio.sleep(5)


async def active_orders_service(bot_id: int):
    async with async_session() as session:
        while True:
            try:
                ws_logger.debug(f"active_orders_service: bot_id = {bot_id}")
                active_orders_data = [
                    {
                        "order_id": order.order_id,
                        "order_type": order.order_type,
                        "isInitial": order.isInitial,
                        "price": order.price,
                        "quantity": order.quantity,
                        "created_at": order.created_at.isoformat()
                    }
                    for order in await TradingBotManager.get_active_orders_list(bot_id)
                ]
                
                await manager.broadcast({
                    "type": "active_orders_data", 
                    "bot_id": bot_id,
                    "payload": active_orders_data
                })
                
                await asyncio.sleep(1)
                
            except Exception as e:
                ws_logger.error(f"Ошибка при отправке active_orders_data: {e}")
                await asyncio.sleep(5)


async def order_history_service(bot_id: int):
    async with async_session() as session:
        while True:
            try:
                ws_logger.debug(f"order_history_service: bot_id = {bot_id}")
                order_history_data = [
                    {
                "order_id": order.order_id,
                "order_type": order.order_type,
                "price": order.price,
                "quantity": order.quantity,
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat()
            }
            for order in await TradingBotManager.get_order_history_list(bot_id)
                ]
                
                await manager.broadcast({
                    "type": "order_history_data", 
                    "bot_id": bot_id,
                    "payload": order_history_data
                })
                
                await asyncio.sleep(1)
                
            except Exception as e:
                ws_logger.error(f"Ошибка при отправке order_history_data: {e}")
                await asyncio.sleep(5)

async def trade_history_service(bot_id: int):
    async with async_session() as session:
        while True:
            try:
                ws_logger.debug(f"trade_history_service: bot_id = {bot_id}")
                trade_history_data = [
                    {
                        "buy_price": trade.buy_price,
                        "sell_price": trade.sell_price,
                        "quantity": trade.quantity,
                        "profit": trade.profit,
                        "profit_asset": trade.profit_asset,
                        "status": trade.status,
                        "trade_type": trade.trade_type,
                        "buy_order_id": trade.buy_order_id,
                        "sell_order_id": trade.sell_order_id,
                        "executed_at": trade.executed_at.isoformat()
                    }
                    for trade in await TradingBotManager.get_all_trades_list(bot_id)
                ]
                
                await manager.broadcast({
                    "type": "trade_history_data", 
                    "bot_id": bot_id,
                    "payload": trade_history_data
                })
                
                await asyncio.sleep(1)
                
            except Exception as e:
                ws_logger.error(f"Ошибка при отправке trade_history_data: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

