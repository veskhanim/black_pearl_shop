import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_URL = os.getenv('APPS_SCRIPT_URL')
MINI_APP_URL = os.getenv('MINI_APP_URL')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

async def session_middleware(handler, event, data):
    async with aiohttp.ClientSession() as session:
        data['session'] = session
        return await handler(event, data)

dp.update.middleware(session_middleware)

@router.message(Command("start"))
async def cmd_start(message: Message, session: aiohttp.ClientSession):
    user = message.from_user
    # Регистрируем пользователя
    await session.post(API_URL, json={
        'action': 'upsertUser',
        'telegram_id': user.id,
        'username': user.username or '',
        'first_name': user.first_name or '',
        'last_name': user.last_name or ''
    })
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖤 Открыть магазин", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton(text="✦ Написать менеджеру", url="https://t.me/blackpearl_manager")]
    ])
    
    text = (
        "🖤 <b>Добро пожаловать в BLACK PEARL</b>\n\n"
        "✦ K-pop мерч с душой моря ✦\n\n"
        " Альбомы и фотокарточки\n"
        "💎 Лайтстики и мерч\n"
        "🌊 Лимитки и эксклюзивы"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(F.text == " Мои заказы")
async def my_orders(message: Message, session: aiohttp.ClientSession):
    async with session.get(f"{API_URL}?action=getOrders&userId={message.from_user.id}") as resp:
        orders = await resp.json()
        
    if not orders:
        return await message.answer("🦪 У тебя пока нет заказов ✨")
        
    text = f"🦪 <b>Твои заказы ({len(orders)})</b>\n\n"
    for o in orders[:5]:
        text += f"<b>{o['order_id']}</b>\n"
        text += f"💎 {int(o['total']):,} ₽ • Статус: {o['status']}\n"
        if o.get('deadline'): text += f" Дедлайн: {o['deadline']}\n"
        text += "\n"
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Подробно в приложении", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(F.text == "📦 Коробки")
async def my_boxes(message: Message, session: aiohttp.ClientSession):
    async with session.get(f"{API_URL}?action=getBoxes&userId={message.from_user.id}") as resp:
        boxes = await resp.json()
        
    ready = [b for b in boxes if b.get('status') == 'ready']
    if not ready:
        return await message.answer("📦 Пока нет коробок к получению ✦")
        
    text = f"📦 <b>Готовы к получению ({len(ready)})</b>\n\n"
    for b in ready:
        text += f"<b>{b['box_id']}</b>\n"
        text += f"🔑 Код: <code>{b['pickup_code']}</code>\n"
        text += f"📍 {b['pickup_location']}\n\n"
        
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "💳 Оплаты")
async def my_payments(message: Message, session: aiohttp.ClientSession):
    async with session.get(f"{API_URL}?action=getPayments&userId={message.from_user.id}") as resp:
        payments = await resp.json()
        
    if not payments:
        return await message.answer(" Пока нет оплат")
        
    text = " <b>История оплат</b>\n\n"
    for p in payments:
        text += f"<b>{p['payment_id']}</b>\n"
        text += f" {p['order_id']} • 💎 {int(p['amount']):,} ₽\n"
        text += f"📅 {p['paid_at']}\n\n"
        
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == " Открыть магазин")
async def open_shop(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Открыть", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    await message.answer("🌊 BLACK PEARL", reply_markup=keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
