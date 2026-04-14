import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

PROXY_URL = os.getenv("PROXY_URL", "http://yFXbdb:YRH2NR@72.56.181.103:8000")
session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None

bot = Bot(token=TOKEN, session=session) if session else Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    await message.answer(f'Привет, {message.from_user.first_name}! Готов записывать Ваши напоминания')

@dp.message(Command('help'))
async def cmd_help(message: types.Message):
    await message.answer(f'Мои доступные команды: \n' '/start - запуск бота \n' '/help - справка')

async def main():
    # Fail fast if proxy can't reach Telegram Bot API
    await bot.get_me()
    # Through some proxies long-polling connections are cut; smaller timeout is more stable.
    await dp.start_polling(bot, polling_timeout=5)

if __name__ == '__main__':
    asyncio.run(main())