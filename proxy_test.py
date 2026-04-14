import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = "http://yFXbdb:YRH2NR@72.56.181.103:8000"  # тот же, что для aiogram

async def main():
    url = f"https://api.telegram.org/bot{TOKEN}/getMe"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, proxy=PROXY_URL, timeout=20) as r:
            print(r.status)
            print(await r.text())

asyncio.run(main())