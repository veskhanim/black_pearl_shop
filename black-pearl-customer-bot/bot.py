import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# ID канала для уведомлений (обязательно!)
NOTIFICATION_CHANNEL_ID = os.getenv('NOTIFICATION_CHANNEL_ID')
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
    user_id = user.id
    
    # Регистрируем/обновляем пользователя
    try:
        async with session.post(API_URL, json={
            'action': 'upsertUser',
            'telegram_id': user_id,
            'username': username,
            'first_name': user.first_name or '',
            'last_name': user.last_name or ''
        }) as resp:
            result = await resp.json()
            is_new_user = result.get('action') == 'created'
            print(f"👤 Пользователь {user_id} (@{username}): {result.get('action')}")
    except Exception as e:
        print(f"❌ Ошибка upsertUser: {e}")
        is_new_user = False
    
    # Если пользователь новый — уведомляем админов
    if is_new_user:
        await notify_new_user(
            user_id=user_id,
            username=username,
            first_name=user.first_name or '',
            last_name=user.last_name or '',
            session=session
        )
    
    # Если есть username — обновляем telegram_id в существующей записи
    if username:
        try:
            async with session.post(API_URL, json={
                'action': 'updateTelegramIdByUsername',
                'username': username,
                'telegram_id': user_id
            }) as resp:
                result = await resp.json()
                if result.get('action') == 'updated':
                    print(f"✅ Обновлён telegram_id для @{username}: {user_id}")
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

# ===== УВЕДОМЛЕНИЕ О НОВОМ ПОЛЬЗОВАТЕЛЕ =====
async def notify_new_user(user_id: int, username: str, first_name: str, last_name: str, session: aiohttp.ClientSession):
    """Отправляет уведомление в канал о новом пользователе"""
    if not NOTIFICATION_CHANNEL_ID:
        print(f"⚠️ NOTIFICATION_CHANNEL_ID не настроен — уведомление пропущено")
        return
    
    try:
        # Формируем ссылку на пользователя
        if username:
            user_link = f"@{username}"
            profile_link = f"https://t.me/{username}"
        else:
            user_link = f"id:{user_id}"
            profile_link = f"tg://user?id={user_id}"
        
        # Формируем имя
        full_name = f"{first_name or ''} {last_name or ''}".strip() or '—'
        
        # Сообщение
        text = (
            f"👤 <b>Новый пользователь!</b>\n\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"👤 <b>Username:</b> {user_link}\n"
            f"📛 <b>Имя:</b> {full_name}\n\n"
            f"🔗 <a href='{profile_link}'>Открыть профиль</a>"
        )
        
        # Отправляем в канал
        await bot.send_message(
            chat_id=NOTIFICATION_CHANNEL_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
        print(f"✅ Уведомление отправлено в канал о пользователе {user_id}")
        
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления в канал: {e}")
        
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
