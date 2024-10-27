import asyncio
import logging
from fastapi import WebSocket
from binance_client import BinanceClient
import aiohttp
from asyncio_throttle import Throttler
from binance_websocket import BinanceWebSocket
import os
import decimal
import time
from typing import List, Dict, Optional
from sqlalchemy import delete
import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session
from models.models import TradeHistory, ActiveOrder
from sqlalchemy import update

# Configure logging for the entire application
logging.basicConfig(
    level=logging.DEBUG,  # Set the default logging level to INFO
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='debug.log'
)

# Suppress debug messages from the websockets library
logging.getLogger('websockets').setLevel(logging.WARNING)

# Suppress debug messages from urllib3
logging.getLogger('urllib3').setLevel(logging.WARNING)

class GridStrategy:
    def __init__(
        self,
        symbol,
        asset_a_funds,
        asset_b_funds,
        grids,
        deviation_threshold,
        growth_factor,  # User-defined growth factor
        use_granular_distribution,  # User-defined flag for granular distribution
        trail_price=True,
        only_profitable_trades=False,
    ):
        # Securely retrieve API credentials from environment variables
        
        api_key = 'hsKMdfXQ1yLis77mvU4byyGqg6999COtK2HC4BAOp59xu0YCj7YIXoymsdhlX2Uq'
        api_secret = 'nBT901qAYhwjmPWPHCDcmey80Tu9gVhAfT8pAREy2MetF3jYChBdSgZXbhxCQO75'
        
        # Ensure the API key and secret are strings
        if not isinstance(api_key, str) or not isinstance(api_secret, str):
            raise ValueError("API key and secret must be strings")

        # Initialize the Binance client with your credentials
        self.binance_client = BinanceClient(api_key=api_key, api_secret=api_secret)
        self.symbol = symbol.upper()  # Ensure symbol is in uppercase for Binance API
        self.asset_a_funds = asset_a_funds
        self.asset_b_funds = asset_b_funds
        self.grids = grids
        self.deviation_threshold = deviation_threshold
        self.initial_price = None
        self.trail_price = trail_price
        self.grid_levels = {'buy': [], 'sell': []}
        self.buy_positions = []
        self.sell_positions = []
        self.realized_profit_a = 0
        self.realized_profit_b = 0
        self.unrealized_profit_a = 0
        self.unrealized_profit_b = 0
        self.only_profitable_trades = only_profitable_trades

        self.session = None
        self.throttler = Throttler(rate_limit=5, period=1)
        self.current_price = None  # Initialize current price
        self.websocket = BinanceWebSocket(self.symbol)  # Initialize the WebSocket
        self.stop_flag = False  # Initialize the stop flag
        self.active_orders = []  # List to store active orders
        self.trade_history = []  # List to store completed trades
        self.growth_factor = growth_factor  # Store the growth factor
        self.use_granular_distribution = use_granular_distribution  # Store the flag for granular distribution

        self.active_connections: List[WebSocket] = []

        # Check account balance
        self.check_account_balance()

        # После существующих инициализаций
        self.start_time = datetime.datetime.now()

    def check_account_balance(self):
        """Check if the account balance is sufficient for the assigned funds."""
        account_info = self.binance_client.client.get_account()
        balances = {balance['asset']: float(balance['free']) for balance in account_info['balances']}

        # Extract base and quote assets from the symbol
        base_asset, quote_asset = self.symbol[:-4], self.symbol[-4:]

        # Check if there is enough balance for asset A (quote asset)
        if balances.get(quote_asset, 0) < self.asset_a_funds:
            raise ValueError(f"Insufficient balance for {quote_asset}. Required: {self.asset_a_funds}, Available: {balances.get(quote_asset, 0)}")

        # Check if there is enough balance for asset B (base asset)
        if balances.get(base_asset, 0) < self.asset_b_funds:
            raise ValueError(f"Insufficient balance for {base_asset}. Required: {self.asset_b_funds}, Available: {balances.get(base_asset, 0)}")

        logging.info(f"Sufficient balance for {quote_asset} and {base_asset}.")

    async def update_price(self):
        """Update the current price using the WebSocket."""
        try:
            await self.websocket.start()
            logging.info("WebSocket connection started.")
            async with self.websocket.bsm.symbol_ticker_socket(symbol=self.symbol.lower()) as stream:
                while True:
                    msg = await stream.recv()
                    if msg is None:
                        break  # Exit the loop if the stream is closed
                    self.current_price = float(msg['c'])  # 'c' is the current price in the message

        except Exception as e:
            logging.error(f"Error in update_price: {e}")
            await asyncio.sleep(5)  # Wait before retrying
            await self.update_price()  # Retry updating price
        finally:
            await self.websocket.stop()
            logging.info("WebSocket connection closed.")

    async def calculate_order_size(self):
        """Calculate the order sizes using linear distribution with a growth factor."""
        # Ensure current price is available
        if self.current_price is None:
            ticker = self.binance_client.client.get_ticker(symbol=self.symbol)
            self.current_price = float(ticker['lastPrice'])

        if self.use_granular_distribution:
            # Calculate buy order sizes using linear distribution
            total_buy_funds = self.asset_a_funds
            x1 = total_buy_funds / (self.grids + (self.growth_factor * (self.grids * (self.grids - 1)) / 2))
            self.buy_order_sizes = [
                (x1 + self.growth_factor * i * x1) / self.current_price  # <-- Change: Division by current_price
                for i in range(self.grids)
            ]

            # Debug logging for buy order sizes
            logging.debug(f"Total buy funds: {total_buy_funds} USDT")
            logging.debug(f"Growth factor: {self.growth_factor}")
            logging.debug(f"Initial buy order size (x1): {x1}")

            # Calculate sell order sizes using linear distribution
            total_sell_quantity = self.asset_b_funds
            x1_sell = total_sell_quantity / (self.grids + (self.growth_factor * (self.grids * (self.grids - 1)) / 2))
            self.sell_order_sizes = [x1_sell + self.growth_factor * i * x1_sell for i in range(self.grids)]

            # Debug logging for sell order sizes
            logging.debug(f"Total sell quantity: {total_sell_quantity} BTC")
            logging.debug(f"Initial sell order size (x1_sell): {x1_sell}")
        else:
            # Calculate buy order sizes (equal distribution)
            total_buy_funds = self.asset_a_funds
            buy_funds_per_grid = total_buy_funds / self.grids
            self.buy_order_sizes = [buy_funds_per_grid / price for price in self.grid_levels['buy']]

            # Debug logging for equal distribution
            logging.debug(f"Buy funds per grid: {buy_funds_per_grid} USDT")

            # Calculate sell order sizes (equal distribution)
            total_sell_quantity = self.asset_b_funds
            sell_quantity_per_grid = total_sell_quantity / self.grids
            self.sell_order_sizes = [sell_quantity_per_grid] * len(self.grid_levels['sell'])

            # Debug logging for equal distribution
            logging.debug(f"Sell quantity per grid: {sell_quantity_per_grid} BTC")

        logging.info("Calculated order sizes for each grid level.")
        for i, price in enumerate(self.grid_levels['buy']):
            logging.info(f"Buy Level {i+1}: Price = {price}, Order Size = {self.buy_order_sizes[i]} BTC")

        for i, price in enumerate(self.grid_levels['sell']):
            logging.info(f"Sell Level {i+1}: Price = {price}, Order Size = {self.sell_order_sizes[i]} BTC")

    async def calculate_grid_levels(self, current_price):
        """Calculate grid levels based on current price and deviation threshold."""
        logging.info("Calculating grid levels based on the current price and deviation threshold.")
        step_distance = (self.deviation_threshold / self.grids) * current_price
        # Calculate buy levels (below current price) and sell levels (above current price)
        self.grid_levels['buy'] = [
            current_price - (i * step_distance) for i in range(1, self.grids + 1)
        ]
        self.grid_levels['sell'] = [
            current_price + (i * step_distance) for i in range(1, self.grids + 1)
        ]
        logging.info(f"Buy levels: {self.grid_levels['buy']}")
        logging.info(f"Sell levels: {self.grid_levels['sell']}")

    async def send_update(self, update_info):
        """Отправляет обновления через WebSocket."""
        logging.info(f"Update: {update_info}")
        
        for connection in self.active_connections:
            try:
                await connection.send_json(update_info)
            except Exception as e:
                logging.error(f"Ошибка отправки обновления: {e}")

    async def place_limit_order(self, price, order_type, order_size):
        """Place an individual limit order and log the outcome."""
        logging.info(f"Placing {order_type.upper()} order at ${price} for {order_size} units.")
        async with self.throttler:
            try:
                # Perform a balance check before placing the order
                if not self.is_balance_sufficient(order_type, price, order_size):
                    logging.error(f"Insufficient balance to place {order_type.upper()} order at ${price} for {order_size} units.")
                    return

                # Retrieve exchange info
                exchange_info = self.binance_client.client.get_symbol_info(self.symbol)
                if exchange_info is None:
                    logging.error(f"Exchange information for symbol {self.symbol} not found.")
                    return

                # Extract filters
                filters = self.extract_filters(exchange_info)
                if filters is None:
                    logging.error(f"Could not extract filters for symbol {self.symbol}.")
                    return

                # Unpack filter values
                min_price = filters['min_price']
                max_price = filters['max_price']
                tick_size = filters['tick_size']
                min_qty = filters['min_qty']
                max_qty = filters['max_qty']
                step_size = filters['step_size']
                min_notional = filters['min_notional']
                max_notional = filters['max_notional']

                # Function to calculate decimals based on tick size or step size
                def decimals(value):
                    return decimal.Decimal(str(value)).as_tuple().exponent * -1

                # Adjust price
                price_decimals = decimals(tick_size)
                price = round(price, price_decimals)

                # Adjust quantity
                qty_decimals = decimals(step_size)
                order_size = round(order_size, qty_decimals)

                # Ensure price is within min and max price
                if price < min_price or price > max_price:
                    logging.error(f"Price {price} is outside the allowed range ({min_price} - {max_price}).")
                    return

                # Ensure quantity is within min and max quantity
                if order_size < min_qty or order_size > max_qty:
                    logging.error(f"Quantity {order_size} is outside the allowed range ({min_qty} - {max_qty}).")
                    return

                # Ensure order notional is within min and max notional
                notional = price * order_size
                if notional < min_notional or notional > max_notional:
                    logging.error(f"Order notional ({notional}) is outside the allowed range ({min_notional} - {max_notional}).")
                    return

                # Log and place the order
                # logging.info(f"Attempting to place a single {order_type.upper()} order at ${price} for {order_size} units.")
                order = await self.binance_client.place_order_async(
                    self.symbol, order_type.upper(), order_size, price
                )
                
                if 'orderId' in order:
                    # Update positions and active orders
                    if order_type.lower() == 'buy':
                        self.buy_positions.append({'price': price, 'quantity': order_size})
                    elif order_type.lower() == 'sell':
                        self.sell_positions.append({'price': price, 'quantity': order_size})

                    order_id = order['orderId']
                    
                    order_data = {
                        'order_id': order_id,
                        'order_type': order_type,
                        'price': price,
                        'quantity': order_size
                    }

                    # Add to database
                    await self.add_active_order(order_data)
                    
                    # Add to memory list
                    self.active_orders.append({
                        'order_id': order_id,
                        'order_type': order_type,
                        'price': price,
                        'quantity': order_size
                    })
                    
                else:
                    # Handle API error response
                    error_code = order.get('code')
                    error_msg = order.get('msg')
                    logging.error(f"Failed to place order: {error_code} - {error_msg}")
            except Exception as e:
                logging.error(f"Error placing {order_type.upper()} order at ${price}: {str(e)}")


    async def place_batch_orders(self):
        """Place initial buy and sell orders based on grid levels in batches."""
        batch_size = 5  # Place orders in batches to avoid hitting rate limits
        logging.info("Starting to place batch orders for initial grid levels.")

        for order_type in ['buy', 'sell']:
            levels = self.grid_levels[order_type]
            order_sizes = self.buy_order_sizes if order_type == 'buy' else self.sell_order_sizes
            total_orders = len(levels)
            successful_orders = 0
            failed_orders = 0

            # Debug logging for order sizes and total orders
            logging.debug(f"Order type: {order_type}")
            logging.debug(f"Total orders: {total_orders}")
            logging.debug(f"Buy order sizes: {self.buy_order_sizes}")
            logging.debug(f"Sell order sizes: {self.sell_order_sizes}")
            logging.debug(f"Current order sizes: {order_sizes}")

            for i in range(0, total_orders, batch_size):
                batch_levels = levels[i:i + batch_size]
                batch_sizes = order_sizes[i:i + batch_size]
                logging.info(
                    f"Attempting to place batch of {len(batch_levels)} {order_type.upper()} orders for levels: {batch_levels[0]:.2f} to {batch_levels[-1]:.2f}"
                )
                tasks = []
                logging.debug(f"Entering for loop with batch_levels: {batch_levels} and batch_sizes: {batch_sizes}")
                for level_price, order_size in zip(batch_levels, batch_sizes):
                    logging.debug(f"Processing level_price: {level_price}, order_size: {order_size}")
                    # Create a task to place each limit order
                    task = self.place_limit_order(level_price, order_type, order_size)
                    tasks.append(task)
                    logging.info(f"Placing order at ${level_price:.2f} for {order_size} units.")
                    logging.debug(f"Task appended: {task}")
                logging.debug(f"Exiting for loop. Total tasks: {len(tasks)}")
                # Execute all the tasks concurrently
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Count successful and failed orders
                for result in results:
                    if isinstance(result, Exception):
                        failed_orders += 1
                    else:
                        successful_orders += 1

                logging.info(
                    f"Placed {order_type.upper()} orders for levels: {batch_levels[0]:.2f} to {batch_levels[-1]:.2f}."
                )
                logging.info(
                    f"Successful orders: {successful_orders}, Failed orders: {failed_orders}"
                )
                logging.info(
                    f"Total orders: {total_orders}, Remaining orders: {total_orders - (successful_orders + failed_orders)}"
                )
                await asyncio.sleep(2)  # Pause between batches to avoid rate limits
        logging.info("All batch orders have been placed successfully.")

    async def execute_strategy(self):
        """Execute the grid trading strategy with continuous monitoring."""
        logging.info("Starting the grid trading strategy execution.")
        
        
        price_update_task = None
        
        try:
            # Создаем одну сессию на все время работы стратегии
            self.session = aiohttp.ClientSession()
            price_update_task = asyncio.create_task(self.update_price())
            
            last_checked_price = None  # Track the last checked price
            
            while not self.stop_flag:
                start_time = time.time()  # Record the start time of the loop

                # Log message indicating waiting for price update
                logging.info("Waiting for current price to update...")

                # Ensure the current price is updated
                if self.current_price is not None and self.current_price != last_checked_price:
                    last_checked_price = self.current_price  # Update the last checked price

                    if self.initial_price is None:
                        self.initial_price = self.current_price
                        logging.info(f"Initial price set to ${self.initial_price:.2f}. Calculating grid levels and order sizes.")
                        
                        # Calculate grid levels first
                        await self.calculate_grid_levels(self.initial_price)
                        
                        # Then calculate order sizes
                        await self.calculate_order_size()
                        
                        await self.place_batch_orders()
                    # Calculate the deviation from the initial price
                    deviation = (self.current_price - self.initial_price) / self.initial_price

                    # Log the current price and deviation
                    logging.info(f"Current price: ${self.current_price:.2f}. Deviation: {deviation:.2%}.")

                    # Define tasks for checking buy and sell orders
                    async def check_buy_orders():
                        buy_prices = [buy['price'] for buy in self.buy_positions]
                        logging.info(f"Checking {len(self.buy_positions)} buy orders at prices: {buy_prices}")
                        for buy in list(self.buy_positions):
                            if self.current_price <= buy['price']:
                                logging.info(f"Buy order triggered at price ${buy['price']:.2f}")
                                sell_price = buy['price'] + ((self.deviation_threshold / self.grids) * self.initial_price)
                                await self.place_limit_order(sell_price, 'sell', buy['quantity'])
                                self.buy_positions.remove(buy)
                                profit = (sell_price - buy['price']) * buy['quantity']
                                self.realized_profit_a += profit
                                logging.info(f"Realized profit from buy-sell pair: ${profit:.2f}")
                                await self.add_trade_to_history(
                                    buy_price=buy['price'],
                                    sell_price=sell_price,
                                    quantity=buy['quantity'],
                                    profit=profit
                                )

                    async def check_sell_orders():
                        sell_prices = [sell['price'] for sell in self.sell_positions]
                        logging.info(f"Checking {len(self.sell_positions)} sell orders at prices: {sell_prices}")
                        for sell in list(self.sell_positions):
                            if self.current_price >= sell['price']:
                                logging.info(f"Sell order triggered at price ${sell['price']:.2f}")
                                buy_price = sell['price'] - ((self.deviation_threshold / self.grids) * self.initial_price)
                                await self.place_limit_order(buy_price, 'buy', sell['quantity'])
                                self.sell_positions.remove(sell)
                                profit = (sell['price'] - buy_price) * sell['quantity']
                                self.realized_profit_b += profit
                                logging.info(f"Realized profit from sell-buy pair: ${profit:.2f}")
                                await self.add_trade_to_history(
                                    buy_price=buy_price,
                                    sell_price=sell['price'],
                                    quantity=sell['quantity'],
                                    profit=profit
                                )
                    await asyncio.gather(check_buy_orders(), check_sell_orders())

                    # Log summary of the checks
                    logging.info(f"Summary: {len(self.buy_positions)} buy orders and {len(self.sell_positions)} sell orders checked.")

                    # Reset grid if deviation threshold is reached
                    if abs(deviation) >= self.deviation_threshold:
                        logging.info("Deviation threshold reached. Resetting grid.")
                        await self.cancel_all_orders()
                        await self.reset_grid(self.current_price)

                # Sleep asynchronously to wait before the next price check
                await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"Error in strategy execution: {str(e)}")
        finally:
            # Закрываем сессии только при завершении стратегии
            if price_update_task:
                await price_update_task
            await self.close_all_sessions()

    async def reset_grid(self, new_initial_price):
        """Reset the grid when the deviation threshold is reached."""
        logging.info(
            f"Resetting grid with new initial price at ${new_initial_price:.2f}."
        )
        self.initial_price = new_initial_price  # Update the initial price
        await self.calculate_grid_levels(self.initial_price)  # Recalculate grid levels based on the new price
        await self.place_batch_orders()  # Place new orders after resetting the grid

    async def cancel_all_orders(self):
        """Cancel all open orders."""
        async with self.throttler:
            try:
                logging.info("Attempting to cancel all open orders.")
                # Отменяем ордера на бирже
                cancelled_orders = await self.binance_client.cancel_all_orders_async(self.symbol)
                
                # Удаляем из базы данных
                async with async_session() as session:
                    await session.execute(delete(ActiveOrder))
                    await session.execute(delete(TradeHistory))
                    await session.commit()
                
                # Очищаем список в памяти
                self.active_orders.clear()
                self.trade_history.clear()
                
                logging.info(f"All open orders for {self.symbol} have been cancelled.")
            except Exception as e:
                logging.error(f"Error cancelling orders: {str(e)}")

    async def close(self):
        """Close all sessions and connections."""
        logging.info("Closing the trading session.")
        await self.close_all_sessions()

    async def get_real_time_data(self):
        """Возвращает данные в реальном времени для WebSocket."""
        return {
            "current_price": self.current_price,
            "initial_price": self.initial_price,
            "deviation": (self.current_price - self.initial_price) / self.initial_price if self.initial_price else 0,
            "realized_profit_a": self.realized_profit_a,
            "realized_profit_b": self.realized_profit_b,
            "active_orders_count": len(self.active_orders),
            "completed_trades_count": len(self.trade_history),
            "active_orders": [
                {
                    "order_id": order["order_id"],
                    "order_type": order["order_type"],
                    "price": order["price"],
                    "quantity": order["quantity"],
                    "created_at": order["created_at"]
                } for order in self.active_orders
            ]
        }

    def extract_filters(self, exchange_info):
        """Extract necessary filters from exchange_info."""
        filters = exchange_info.get('filters', [])
        min_price = max_price = tick_size = None
        min_qty = max_qty = step_size = None
        min_notional = max_notional = None

        for f in filters:
            filter_type = f['filterType']
            if filter_type == 'PRICE_FILTER':
                min_price = float(f['minPrice'])
                max_price = float(f['maxPrice'])
                tick_size = float(f['tickSize'])
            elif filter_type == 'LOT_SIZE':
                min_qty = float(f['minQty'])
                max_qty = float(f['maxQty'])
                step_size = float(f['stepSize'])
            elif filter_type == 'NOTIONAL':
                min_notional = float(f.get('minNotional', 0))
                max_notional = float(f.get('maxNotional', float('inf')))

        # Check if any of the filters are missing
        if None in (min_price, max_price, tick_size, min_qty, max_qty, step_size, min_notional, max_notional):
            logging.error("One or more necessary filters are missing for symbol: {}".format(self.symbol))
            return None  # You can raise an exception here if preferred

        return {
            'min_price': min_price,
            'max_price': max_price,
            'tick_size': tick_size,
            'min_qty': min_qty,
            'max_qty': max_qty,
            'step_size': step_size,
            'min_notional': min_notional,
            'max_notional': max_notional
        }

    def is_balance_sufficient(self, order_type, price, quantity):
        """Check if there is sufficient balance to place the order."""
        account_info = self.binance_client.client.get_account()
        balances = {balance['asset']: float(balance['free']) for balance in account_info['balances']}

        # Extract base and quote assets from the symbol
        base_asset = self.symbol.replace('USDT', '')  # For symbols ending with USDT
        quote_asset = 'USDT'

        if order_type.lower() == 'buy':
            required_funds = price * quantity  # Total cost in quote asset
            available_funds = balances.get(quote_asset, 0)
            if available_funds < required_funds:
                logging.error(f"Insufficient {quote_asset} balance. Required: {required_funds}, Available: {available_funds}")
                return False
        elif order_type.lower() == 'sell':
            required_quantity = quantity  # Quantity in base asset
            available_quantity = balances.get(base_asset, 0)
            if available_quantity < required_quantity:
                logging.error(f"Insufficient {base_asset} balance. Required: {required_quantity}, Available: {available_quantity}")
                return False
        return True

    async def connect(self, websocket: WebSocket):
        """Добавляет новое WebSocket соединение."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Удаляет WebSocket соединение."""
        self.active_connections.remove(websocket)

    async def send_update(self, update_info: dict):
        """Отправляет обновления всем подключенным клиентам."""
        # Логируем обновление
        logging.info(f"Update: {update_info}")

        # Отправляем обновление всем активным соединениям
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(update_info)
            except Exception as e:
                logging.error(f"Error sending update to client: {e}")
                disconnected.append(connection)

        # Удаляем отключенные соединения
        for connection in disconnected:
            self.disconnect(connection)

    async def add_trade_to_history(self, buy_price, sell_price, quantity, profit):
        """Добавляет сделку в историю и в базу данных."""
        trade_data = {
            'buy_price': buy_price,
            'sell_price': sell_price,
            'quantity': quantity,
            'profit': profit,
            'executed_at': datetime.datetime.now()  # Изменено с str на datetime объект
        }
        
        # Добавляем в локальную историю
        self.trade_history.append(trade_data)
        
        # Добавляем в базу данных
        async with async_session() as session:
            trade = TradeHistory(
                buy_price=buy_price,
                sell_price=sell_price,
                quantity=quantity,
                profit=profit,
                executed_at=trade_data['executed_at']  # Теперь передаем datetime объект
            )
            session.add(trade)
            await session.commit()

    async def add_active_order(self, order_data):
        """Добавляет активный ордер в базу данных и локальный список."""
        try:
            # Создаем объект ActiveOrder
            active_order = ActiveOrder(
                order_id=order_data["order_id"],  # Изменено с orderId
                order_type=order_data["order_type"],  # Изменено с side
                price=float(order_data["price"]),
                quantity=float(order_data["quantity"]),  # Изменено с origQty
                created_at=datetime.datetime.now()
            )
            
            # Сохраняем в базу данных
            async with async_session() as session:
                # Проверяем существование ордера
                existing_order = await session.execute(
                    select(ActiveOrder).where(ActiveOrder.order_id == active_order.order_id)
                )
                if existing_order.scalar_one_or_none():
                    # Если ордер существует, обновляем его
                    await session.execute(
                        update(ActiveOrder)
                        .where(ActiveOrder.order_id == active_order.order_id)
                        .values(
                            order_type=active_order.order_type,
                            price=active_order.price,
                            quantity=active_order.quantity,
                            created_at=active_order.created_at
                        )
                    )
                else:
                    # Если ордера нет, добавляем новый
                    session.add(active_order)
                
                await session.commit()
                
            # Обновляем локальный список
            self.active_orders = [order for order in self.active_orders if order["order_id"] != active_order.order_id]
            self.active_orders.append({
                "order_id": active_order.order_id,
                "order_type": active_order.order_type,
                "price": active_order.price,
                "quantity": active_order.quantity,
                "created_at": str(active_order.created_at)
            })
            
            # Отправляем обновление через WebSocket
            await self.send_update({
                "event": "order_placed",
                "active_orders": self.active_orders
            })
            
        except Exception as e:
            logging.error(f"Ошибка при сохранении активного ордера: {e}")

    async def load_active_orders(self):
        """Загружает активные ордера из базы данных."""
        async with async_session() as session:
            result = await session.execute(select(ActiveOrder))
            orders = result.scalars().all()
            self.active_orders = [
                {
                    'order_id': order.order_id,
                    'order_type': order.order_type,
                    'price': order.price,
                    'quantity': order.quantity,
                    'created_at': order.created_at
                }
                for order in orders
            ]

    async def close_all_sessions(self):
        """Закрывает все активные сессии."""
        try:
            if hasattr(self, 'session') and self.session:
                await self.session.close()
                self.session = None
                
            if hasattr(self, 'binance_client'):
                await self.binance_client.close()
                
            if hasattr(self, 'websocket'):
                await self.websocket.stop()
                
            # Закрываем все WebSocket соединения
            for connection in self.active_connections[:]:
                try:
                    await connection.close()
                except Exception as e:
                    logging.error(f"Ошибка закрытия WebSocket соединения: {e}")
                self.active_connections.remove(connection)
                
        except Exception as e:
            logging.error(f"Ошибка при закрытии сессий: {e}")
            
            
    async def stop(self):
        self.stop_flag = True
        await self.cancel_all_orders()
        await self.close_all_sessions()





