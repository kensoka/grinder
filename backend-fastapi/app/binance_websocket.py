import asyncio
from binance import AsyncClient, BinanceSocketManager
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BinanceWebSocket:
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()  # Binance WebSocket expects lowercase symbol
        self.async_client = None
        self.bsm = None

    async def start(self):
        """Initialize the WebSocket connection."""
        try:
            # Initialize the asynchronous Binance client
            self.async_client = await AsyncClient.create()

            # Initialize the Binance Socket Manager
            self.bsm = BinanceSocketManager(self.async_client)
            logger.info(f"WebSocket for {self.symbol} started.")
        except Exception as e:
            logger.error(f"Error occurred during WebSocket initialization: {e}")

    async def stop(self):
        """Stop the WebSocket connection."""
        if self.async_client:
            await self.async_client.close_connection()
            logger.info(f"WebSocket for {self.symbol} stopped.")
