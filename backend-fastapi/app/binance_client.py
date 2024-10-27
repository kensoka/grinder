from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import asyncio
import hmac
import hashlib
import time
import aiohttp
import logging

class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.session = aiohttp.ClientSession()

        # Set the base URL based on the testnet parameter
        if self.testnet:
            self.BASE_URL = 'https://testnet.binance.vision'
        else:
            self.BASE_URL = 'https://api.binance.com'

        # Initialize the Binance client with API keys
        self.client = Client(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet
        )

    def get_current_price(self, symbol: str) -> float:
        """Fetch the current price for a given trading pair."""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except (BinanceAPIException, BinanceRequestException) as e:
            print(f"An error occurred while fetching the current price from Binance: {str(e)}")
            print(f"Error type: {type(e).__name__}")
            print(f"Error code: {getattr(e, 'code', 'N/A')}")
            print(f"Error message: {getattr(e, 'message', str(e))}")
            return None

    def place_order(self, symbol: str, side: str, quantity: float, order_type: str = 'MARKET'):
        """Place an order on Binance."""
        try:
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity
            )
            return order
        except (BinanceAPIException, BinanceRequestException) as e:
            print(f"An error occurred while placing an order: {str(e)}")
            return None

    async def place_order_async(self, symbol, side, quantity, price, order_type='LIMIT', time_in_force='GTC'):
        """Place an order on Binance asynchronously."""
        endpoint = '/api/v3/order'
        timestamp = int(time.time() * 1000)
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': order_type.upper(),
            'timeInForce': time_in_force,
            'quantity': str(quantity),
            'price': f"{price:.8f}",
            'recvWindow': '5000',
            'timestamp': str(timestamp)
        }
        
        # Create the query string and generate the signature
        query_string = '&'.join([f"{key}={value}" for key, value in params.items()])
        signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        params['signature'] = signature

        headers = {
            'X-MBX-APIKEY': self.api_key
        }

        # Log the parameters and headers for debugging


        # Make the POST request to place the order
        async with self.session.post(f"{self.BASE_URL}{endpoint}", params=params, headers=headers) as resp:
            response = await resp.json()
            logging.debug(f"Response: {response}")
            return response

    async def get_current_price_async(self, symbol: str) -> float:
        """Fetch the current price for a given trading pair asynchronously."""
        async with aiohttp.ClientSession() as session:
            try:
                url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
                async with session.get(url) as response:
                    data = await response.json()
                    return float(data['price'])
            except (BinanceAPIException, BinanceRequestException) as e:
                print(f"An error occurred while fetching the current price from Binance: {str(e)}")
                return None

    async def close(self):
        # Close the aiohttp session
        await self.session.close()
