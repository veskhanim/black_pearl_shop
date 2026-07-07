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
MINI_APP_URL = os.getenv('MINI_APP_URL', '')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

session = None

async def api_get(action, params=None):
    url = f"{API_URL}?action={action}"
    if params:
        for k, v in params.items():
            url += f"&{k}={v}"
    async with session.get(url) as resp:
        return await resp.json()

@router.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    username = user.username or ''
    
    # Регистрируем/обновляем пользователя
    try:
        async with session.post(API_URL, json={
            'action': 'upsertUser',
            'telegram_id': user.id,
            'username': username,
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'blocked': 'TRUE'
        }) as resp:
            result = await resp.json()
            print(f"👤 Пользователь {user.id} (@{username}): {result.get('action')}")
    except Exception as e:
        print(f" Ошибка upsertUser: {e}")
    
    # Если есть username — обновляем telegram_id в существующей записи
    if username:
        try:
            async with session.post(API_URL, json={
                'action': 'updateTelegramIdByUsername',
                'username': username,
                'telegram_id': user.id
            }) as resp:
                result = await resp.json()
                if result.get('action') == 'updated':
                    print(f"✅ Обновлён telegram_id для @{username}: {user.id}")
        except Exception as e:
            print(f" Ошибка updateTelegramIdByUsername: {e}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖤 Открыть магазин", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    
    await message.answer(
        "🖤 <b>Добро пожаловать в BLACK PEARL</b>\n\n"
        "✦ K-pop мерч с душой моря ✦",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.message(F.text == "🦪 Мои заказы")
async def my_orders(message: Message):
    orders = await api_get('getOrders', {'userId': message.from_user.id})
    if not isinstance(orders, list) or not orders:
        return await message.answer("🦪 У тебя пока нет заказов ✨")
    
    text = f"🦪 <b>Твои заказы ({len(orders)})</b>\n\n"
    for o in orders[:5]:
        text += f"<b>{o.get('order_id')}</b>\n"
        text += f"💎 {o.get('total', 0)} ₽ • {o.get('status')}\n"
        if o.get('deadline'):
            text += f"⏰ Дедлайн: {o['deadline']}\n"
        text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Подробно", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(F.text == "📦 Коробки")
async def my_boxes(message: Message):
    boxes = await api_get('getBoxes', {'userId': message.from_user.id})
    if not isinstance(boxes, list):
        boxes = []
    ready = [b for b in boxes if b.get('status') == 'ready']
    
    if not ready:
        return await message.answer("📦 Пока нет коробок к получению ✦")
    
    text = f"📦 <b>Готовы к получению ({len(ready)})</b>\n\n"
    for b in ready:
        text += f"<b>{b['box_id']}</b>\n"
        text += f"🔑 Код: <code>{b.get('pickup_code')}</code>\n"
        text += f"📍 {b.get('pickup_location')}\n\n"
    
    await message.answer(text, parse_mode="HTML")

async def main():
    global session
    session = aiohttp.ClientSession()
    print("🖤 BLACK PEARL Customer Bot запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(main())
