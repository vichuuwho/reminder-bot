import asyncio
from mailbox import Message
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

PROXY_URL = "http://FS1BWP:8dzZBV@168.196.239.154:9116"
session = AiohttpSession(proxy=PROXY_URL)

bot = Bot(token=TOKEN, session=session)
dp = Dispatcher()

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    await message.answer(f'Привет, {message.from_user.first_name}! Готов записывать Ваши напоминания')

@dp.message(Command('help'))
async def cmd_help(message: types.Message):
    await message.answer(f'Мои доступные команды: \n' '/start - запуск бота \n' '/help - справка')

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())