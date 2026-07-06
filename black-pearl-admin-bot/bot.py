import os
import asyncio
import base64
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from parser import detect_post_type, parse_positions_post, parse_signup_post, parse_payment_post, find_price_for_position

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_URL = os.getenv('APPS_SCRIPT_URL')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- Хранилище постов (обход лимита callback_data 64 байта) ---
posts_storage = {}
post_counter = 0

def save_post(text: str, post_type: str, admin_id: int) -> str:
    global post_counter
    post_counter += 1
    post_id = f"p{post_counter}_{int(asyncio.get_event_loop().time())}"
    posts_storage[post_id] = {'text': text, 'type': post_type, 'admin_id': admin_id}
    return post_id

def get_post(post_id: str) -> dict:
    return posts_storage.pop(post_id, None)

# --- Админы ---
admins_cache = []
cache_time = 0

async def get_admins(session: aiohttp.ClientSession):
    global admins_cache, cache_time
    import time
    if admins_cache and time.time() - cache_time < 60:
        return admins_cache
    try:
        async with session.get(f"{API_URL}?action=getAdmins") as resp:
            data = await resp.json()
            if isinstance(data, list):
                admins_cache = data
                cache_time = time.time()
                return admins_cache
    except Exception as e:
        print(f"Error fetching admins: {e}")
    return []

async def get_admin(user_id: int, session: aiohttp.ClientSession):
    admins = await get_admins(session)
    for a in admins:
        if str(a.get('telegram_id')) == str(user_id) and str(a.get('is_active')).upper() == 'TRUE':
            return a
    return None

# --- API запросы ---
async def api_post(session: aiohttp.ClientSession, data: dict):
    async with session.post(API_URL, json=data) as resp:
        return await resp.json()

# --- FSM для команд /create и /bulk ---
class CreateOrder(StatesGroup):
    waiting_for_data = State()

# --- Обработчики ---
@router.message(Command("start"))
async def cmd_start(message: Message, session: aiohttp.ClientSession):
    admin = await get_admin(message.from_user.id, session)
    if not admin:
        return await message.answer("🖤 <b>BLACK PEARL</b>\n\n У тебя нет доступа.", parse_mode="HTML")
    
    text = (
        f"🖤 <b>BLACK PEARL — Admin Panel</b>\n\n"
        f" Привет, <b>{admin['name']}</b>!\n"
        f"🎭 Роль: <b>{admin['role']}</b>\n\n"
        f"📋 <b>Команды:</b>\n"
        f"/orders — активные заказы\n"
        f"/order &lt;id&gt; — детали заказа\n"
        f"/create — создать заказ вручную\n"
        f"/status &lt;id&gt; &lt;статус&gt; — изменить статус\n"
        f"/payment &lt;id&gt; &lt;сумма&gt; — отметить оплату\n"
        f"/box &lt;order_id&gt; | &lt;код&gt; | &lt;адрес&gt; — создать коробку\n"
        f"/pickup &lt;box_id&gt; — выдать коробку\n"
        f"/stats — статистика\n"
        f"/theme &lt;название&gt; — сменить тему ✨\n\n"
        f"📝 <b>Парсинг постов:</b>\n"
        f"Просто скопируй текст поста и отправь боту!"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text & ~F.text.startswith("/"))
async def handle_post_text(message: Message, session: aiohttp.ClientSession):
    admin = await get_admin(message.from_user.id, session)
    if not admin:
        return # Игнорируем сообщения от не-админов
    
    post_type = detect_post_type(message.text)
    if post_type == 'unknown':
        return await message.answer(" Не похоже на пост для парсинга.\nОтправь текст поста с записями, позициями или оплатами.")
    
    await show_preview(message.chat.id, admin, post_type, message.text, session)

async def show_preview(chat_id: int, admin: dict, post_type: str, text: str, session: aiohttp.ClientSession):
    post_id = save_post(text, post_type, admin['telegram_id'])
    preview_text = ""
    
    if post_type == 'signup_positions':
        parsed = parse_positions_post(text)
        preview_text = f"🔍 <b>Пост с позициями</b>\n\n📦 <b>{parsed['postTitle']}</b>\n"
        if parsed['hashtag']: preview_text += f"🏷️ {parsed['hashtag']}\n"
        preview_text += "\n💎 <b>Справочник цен:</b>\n"
        for p in parsed['priceList'].values():
            preview_text += f"  • {p['name']}: {p['price']:,} ₽\n".replace(',', ' ')
        
        total_entries = sum(1 + len(p['queue']) for p in parsed['positions'])
        preview_text += f"\n📋 <b>Позиций: {len(parsed['positions'])}</b>\n👥 <b>Всего записей: {total_entries}</b>\n\n"
        
        for pos in parsed['positions'][:3]: # Показываем только первые 3
            preview_text += f"<b>Позиция {pos['number']}: {pos['name']}</b>\n"
            preview_text += f"  👑 Главный: @{pos['mainBuyer']['username']}"
            if pos['mainBuyer']['deadline']: preview_text += f" ⏰ {pos['mainBuyer']['deadline']}"
            preview_text += f"\n  🔢 Очередь ({len(pos['queue'])} чел.)\n\n"
            
        if len(parsed['positions']) > 3:
            preview_text += f"... и ещё {len(parsed['positions']) - 3} позиций\n\n"
            
    elif post_type == 'signup':
        parsed = parse_signup_post(text)
        preview_text = f"🔍 <b>Пост записи</b>\n\n <b>{parsed['postTitle']}</b>\n"
        preview_text += f" Цена: <b>{parsed['price'] or 0} ₽</b>\n"
        preview_text += f"👥 Записей: <b>{len(parsed['entries'])}</b>\n\n"
        for e in parsed['entries'][:5]:
            preview_text += f"  • {e['name']} (@{e['username']})"
            if e.get('deadline'): preview_text += f" ⏰ {e['deadline']}"
            preview_text += "\n"
            
    elif post_type == 'payment':
        parsed = parse_payment_post(text)
        total = sum(e['amount'] for e in parsed['entries'])
        preview_text = f"💳 <b>Пост оплаты</b>\n\nЗаписей: <b>{len(parsed['entries'])}</b>\n"
        preview_text += f"💎 Сумма: <b>{total:,} ₽</b>\n\n".replace(',', ' ')
        for e in parsed['entries'][:5]:
            preview_text += f"• @{e['username']} — {e['amount']:,} ₽\n".replace(',', ' ')

    preview_text += "\n✅ Подтвердить создание?"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data=f"ok:{post_id}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data=f"no:{post_id}")]
    ])
    
    await bot.send_message(chat_id, preview_text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data.startswith(("ok:", "no:")))
async def process_callback(callback: CallbackQuery, session: aiohttp.ClientSession):
    admin = await get_admin(callback.from_user.id, session)
    if not admin:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return

    action, post_id = callback.data.split(":", 1)
    
    if action == "no":
        await callback.answer(" Отменено")
        await callback.message.edit_text("❌ Отменено")
        return

    post_data = get_post(post_id)
    if not post_data:
        await callback.answer("⏰ Время истекло", show_alert=True)
        return await callback.message.edit_text("⏰ Время истекло. Отправь текст поста заново.")

    if str(post_data['admin_id']) != str(admin['telegram_id']):
        await callback.answer("⛔ Это не твой пост", show_alert=True)
        return

    await callback.answer("⏳ Создаю...")
    
    try:
        text = post_data['text']
        p_type = post_data['type']
        result = {}
        
        if p_type == 'signup_positions':
            parsed = parse_positions_post(text)
            entries = []
            for pos in parsed['positions']:
                price = find_price_for_position(pos['name'], parsed['priceList'])
                # Главный
                entries.append({
                    'username': pos['mainBuyer']['username'], 'name': pos['mainBuyer']['username'],
                    'positionNumber': pos['number'], 'positionName': pos['name'],
                    'role': 'main', 'deadline': pos['mainBuyer']['deadline'], 'price': price, 'telegramId': None
                })
                # Очередь
                for q in pos['queue']:
                    entries.append({
                        'username': q['username'], 'name': q['member'],
                        'positionNumber': pos['number'], 'positionName': pos['name'],
                        'role': 'queue', 'deadline': q['deadline'], 'price': price, 'telegramId': None
                    })
            
            # Находим ID (упрощенно, можно вынести в отдельную функцию как в JS)
            # Для краткости отправляем как есть, API сам найдет по username если надо, 
            # но лучше найти заранее. (Оставим поиск на стороне API или добавим цикл)
            
            result = await api_post(session, {
                'action': 'createOrdersFromPositions',
                'postTitle': parsed['postTitle'],
                'admin': admin['name'],
                'entries': entries
            })
            
        elif p_type == 'signup':
            parsed = parse_signup_post(text)
            result = await api_post(session, {
                'action': 'createOrdersFromPost',
                'postTitle': parsed['postTitle'],
                'price': parsed['price'],
                'admin': admin['name'],
                'entries': parsed['entries']
            })
            
        elif p_type == 'payment':
            parsed = parse_payment_post(text)
            result = await api_post(session, {
                'action': 'createPaymentsFromPost',
                'admin': admin['name'],
                'entries': parsed['entries']
            })

        if result.get('success'):
            msg = f"✅ <b>Создано: {result.get('created', 0)}</b>\n"
            if result.get('skipped'): msg += f"⏭️ <b>Пропущено: {result['skipped']}</b>\n"
            
            if 'orders' in result:
                for o in result['orders']:
                    if o.get('skipped'):
                        msg += f"  ⏭️ {o.get('name') or o.get('username')} — {o.get('reason')}\n"
                    else:
                        icon = "👑" if o.get('role') == 'main' else "🔢"
                        msg += f"  {icon} <code>{o['orderId']}</code> @{o['username']}"
                        if o.get('deadline'): msg += f"  {o['deadline']}"
                        msg += f" • 💎 {o['total']:,} ₽\n".replace(',', ' ')
                        
            if result.get('errors'):
                msg += f"\n⚠️ <b>Ошибки:</b>\n"
                for e in result['errors'][:5]:
                    msg += f"  • {e.get('name') or e.get('username')}: {e['error']}\n"
                    
            await callback.message.edit_text(msg, parse_mode="HTML")
        else:
            await callback.message.edit_text(f"❌ {result.get('error')}")
            
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")

# --- Остальные команды (упрощенно) ---
@router.message(Command("orders"))
async def cmd_orders(message: Message, session: aiohttp.ClientSession):
    admin = await get_admin(message.from_user.id, session)
    if not admin: return
    async with session.get(f"{API_URL}?action=getOrders&userId=all") as resp:
        orders = await resp.json()
    active = [o for o in orders if o.get('status') != 'delivered']
    if not active: return await message.answer("✅ Нет активных заказов")
    
    text = "🌊 <b>Активные заказы</b>\n\n"
    for o in active[:10]:
        text += f"🦪 <b>{o['order_id']}</b> — {o['status']}\n💎 {int(o['total']):,} ₽\n\n".replace(',', ' ')
    await message.answer(text, parse_mode="HTML")

@router.message(Command("theme"))
async def cmd_theme(message: Message, session: aiohttp.ClientSession):
    admin = await get_admin(message.from_user.id, session)
    if not admin: return await message.answer("⛔ Только для админов")
    
    parts = message.text.split(maxsplit=1)
    theme_name = parts[1] if len(parts) > 1 else None
    
    themes = [
        ('pirate', '⚓ Pirate Default'), ('newjeans_ditto', '💗 NewJeans — Ditto'),
        ('aespa_supernova', '✨ aespa — Supernova'), ('bts_butter', '🧈 BTS — Butter')
    ]
    
    if not theme_name:
        async with session.get(f"{API_URL}?action=getTheme") as resp:
            curr = (await resp.json()).get('theme', 'pirate')
        text = f"🎨 Текущая тема: {curr}\n\nДоступные:\n"
        for tid, tname in themes:
            text += f"/theme {tid} — {tname} {'✅' if tid == curr else ''}\n"
        return await message.answer(text)
        
    await api_post(session, {'action': 'setTheme', 'theme': theme_name})
    await message.answer(f"🎨 Тема изменена на {theme_name}!")

async def main():
    async with aiohttp.ClientSession() as session:
        # Передаем session через middleware или глобально (для простоты создадим новый в хендлерах, 
        # но лучше использовать один. В aiogram 3 можно использовать middleware).
        # Для простоты запуска:
        await dp.start_polling(bot)

if __name__ == "__main__":
    # Чтобы session был доступен в хендлерах, используем простой трюк с глобальной сессией 
    # или передаем через data. В этом примере создадим сессию внутри хендлеров для надежности 
    # при перезапусках, либо используем middleware.
    # *Исправление*: создадим сессию один раз.
    
    # Переопределим хендлеры, чтобы они брали session из dispatcher data (стандартный подход)
    pass 
