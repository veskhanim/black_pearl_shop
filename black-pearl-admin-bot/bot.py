import os
import time
import asyncio
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from parser import (
    detect_post_type, parse_positions_post, 
    parse_signup_post, parse_payment_post, 
    find_price_for_position
)

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_URL = os.getenv('APPS_SCRIPT_URL')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ===== ГЛОБАЛЬНАЯ СЕССИЯ (простой и надёжный подход) =====
session = None

# ===== ХРАНИЛИЩЕ ПОСТОВ =====
posts_storage = {}
post_counter = 0

def save_post(text: str, post_type: str, admin_id: int) -> str:
    global post_counter
    post_counter += 1
    post_id = f"p{post_counter}_{int(time.time())}"
    posts_storage[post_id] = {
        'text': text, 
        'type': post_type, 
        'admin_id': admin_id,
        'created': time.time()
    }
    # Удаляем старые (старше 1 часа)
    cutoff = time.time() - 3600
    expired = [k for k, v in posts_storage.items() if v['created'] < cutoff]
    for k in expired:
        del posts_storage[k]
    return post_id

# ===== ПОЛУЧЕНИЕ АДМИНОВ =====
admins_cache = []
cache_time = 0

async def get_admin(user_id: int):
    global admins_cache, cache_time
    if admins_cache and time.time() - cache_time < 60:
        admins = admins_cache
    else:
        try:
            async with session.get(f"{API_URL}?action=getAdmins") as resp:
                data = await resp.json()
                if isinstance(data, list):
                    admins_cache = data
                    cache_time = time.time()
                    admins = data
                else:
                    print(f" getAdmins вернул не массив: {data}")
                    return None
        except Exception as e:
            print(f" Ошибка getAdmins: {e}")
            return None
    
    for a in admins:
        if str(a.get('telegram_id')) == str(user_id):
            active = a.get('is_active')
            if active is True or str(active).upper() == 'TRUE':
                return a
    return None

async def api_post(data: dict):
    async with session.post(API_URL, json=data) as resp:
        return await resp.json()

async def api_get(action: str, params: dict = None):
    url = f"{API_URL}?action={action}"
    if params:
        for k, v in params.items():
            url += f"&{k}={v}"
    async with session.get(url) as resp:
        return await resp.json()

# ===== /start =====
@router.message(Command("start"))
async def cmd_start(message: Message):
    print(f" /start от {message.from_user.id} ({message.from_user.username})")
    admin = await get_admin(message.from_user.id)
    if not admin:
        return await message.answer("🖤 <b>BLACK PEARL</b>\n\n⛔ У тебя нет доступа.", parse_mode="HTML")
    
    text = (
        f"🖤 <b>BLACK PEARL — Admin Panel</b>\n\n"
        f"👋 Привет, <b>{admin['name']}</b>!\n"
        f"🎭 Роль: <b>{admin['role']}</b>\n\n"
        f"📋 <b>Команды:</b>\n"
        f"/orders — активные заказы\n"
        f"/create — создать заказ вручную\n"
        f"/stats — статистика\n"
        f"/theme [название] — сменить тему\n\n"
        f"📝 <b>Парсинг:</b> просто отправь текст поста!"
    )
    await message.answer(text, parse_mode="HTML")

# ===== ОБРАБОТКА ТЕКСТА ПОСТОВ =====
@router.message(F.text & ~F.text.startswith("/"))
async def handle_post_text(message: Message):
    print(f" Текст от {message.from_user.id}: {message.text[:50]}...")
    
    admin = await get_admin(message.from_user.id)
    if not admin:
        print(f" Пользователь {message.from_user.id} не админ")
        return
    
    post_type = detect_post_type(message.text)
    print(f" Тип поста: {post_type}")
    
    if post_type == 'unknown':
        return await message.answer(
            "🤔 Не похоже на пост для парсинга.\n\n"
            "Отправь текст поста с записями, позициями или оплатами."
        )
    
    await show_preview(message.chat.id, admin, post_type, message.text)

async def show_preview(chat_id: int, admin: dict, post_type: str, text: str):
    post_id = save_post(text, post_type, admin['telegram_id'])
    preview = ""
    
    if post_type == 'signup_positions':
        parsed = parse_positions_post(text)
        preview = f"🔍 <b>Пост с позициями</b>\n\n📦 <b>{parsed['postTitle']}</b>\n"
        if parsed['hashtag']:
            preview += f"🏷️ {parsed['hashtag']}\n"
        preview += "\n💎 <b>Справочник цен:</b>\n"
        for p in parsed['priceList'].values():
            preview += f"  • {p['name']}: {p['price']} ₽\n"
        
        total_entries = sum(1 + len(p['queue']) for p in parsed['positions'])
        preview += f"\n📋 Позиций: <b>{len(parsed['positions'])}</b>\n"
        preview += f"👥 Записей: <b>{total_entries}</b>\n\n"
        
        for pos in parsed['positions'][:3]:
            preview += f"<b>Позиция {pos['number']}: {pos['name']}</b>\n"
            preview += f"  👑 Главный: @{pos['mainBuyer']['username']}"
            if pos['mainBuyer'].get('deadline'):
                preview += f" ⏰ {pos['mainBuyer']['deadline']}"
            preview += f"\n  🔢 Очередь ({len(pos['queue'])} чел.)\n\n"
        
        if len(parsed['positions']) > 3:
            preview += f"... и ещё {len(parsed['positions']) - 3} позиций\n\n"
    
    elif post_type == 'signup':
        parsed = parse_signup_post(text)
        preview = f"🔍 <b>Пост записи</b>\n\n📦 <b>{parsed['postTitle']}</b>\n"
        preview += f"💎 Цена: <b>{parsed.get('price') or '—'} ₽</b>\n"
        preview += f"👥 Записей: <b>{len(parsed['entries'])}</b>\n\n"
        for e in parsed['entries'][:5]:
            preview += f"  • {e['name']} (@{e['username']})"
            if e.get('deadline'):
                preview += f" ⏰ {e['deadline']}"
            preview += "\n"
    
    elif post_type == 'payment':
        parsed = parse_payment_post(text)
        total = sum(e['amount'] for e in parsed['entries'])
        preview = f"💳 <b>Пост оплаты</b>\n\n"
        preview += f"Записей: <b>{len(parsed['entries'])}</b>\n"
        preview += f"💎 Сумма: <b>{total} ₽</b>\n\n"
        for e in parsed['entries'][:10]:
            preview += f"• @{e['username']} — {e['amount']} ₽\n"
    
    preview += "\n✅ Создать?"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Создать", callback_data=f"ok:{post_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"no:{post_id}")
    ]])
    
    await bot.send_message(chat_id, preview, parse_mode="HTML", reply_markup=keyboard)

# ===== CALLBACK (кнопки подтверждения) =====
@router.callback_query(F.data.startswith(("ok:", "no:")))
async def process_callback(callback: CallbackQuery):
    admin = await get_admin(callback.from_user.id)
    if not admin:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return
    
    parts = callback.data.split(":", 1)
    action = parts[0]
    post_id = parts[1] if len(parts) > 1 else ""
    
    if action == "no":
        posts_storage.pop(post_id, None)
        await callback.answer("❌ Отменено")
        await callback.message.edit_text("❌ Отменено")
        return
    
    post_data = posts_storage.pop(post_id, None)
    if not post_data:
        await callback.answer("⏰ Время истекло", show_alert=True)
        await callback.message.edit_text("⏰ Время истекло. Отправь пост заново.")
        return
    
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
                entries.append({
                    'username': pos['mainBuyer']['username'],
                    'name': pos['mainBuyer']['username'],
                    'positionNumber': pos['number'],
                    'positionName': pos['name'],
                    'role': 'main',
                    'deadline': pos['mainBuyer'].get('deadline'),
                    'price': price,
                    'telegramId': None
                })
                for q in pos['queue']:
                    entries.append({
                        'username': q['username'],
                        'name': q['member'],
                        'positionNumber': pos['number'],
                        'positionName': pos['name'],
                        'role': 'queue',
                        'deadline': q.get('deadline'),
                        'price': price,
                        'telegramId': None
                    })
            
            result = await api_post({
                'action': 'createOrdersFromPositions',
                'postTitle': parsed['postTitle'],
                'hashtag': parsed['hashtag'],
                'priceList': parsed['priceList'],
                'admin': admin['name'],
                'entries': entries
            })
        
        elif p_type == 'signup':
            parsed = parse_signup_post(text)
            result = await api_post({
                'action': 'createOrdersFromPost',
                'postTitle': parsed['postTitle'],
                'price': parsed.get('price'),
                'admin': admin['name'],
                'entries': parsed['entries']
            })
        
        elif p_type == 'payment':
            parsed = parse_payment_post(text)
            result = await api_post({
                'action': 'createPaymentsFromPost',
                'admin': admin['name'],
                'entries': parsed['entries']
            })
        
        # Формируем ответ
        if result.get('success'):
            msg = f"✅ <b>Создано: {result.get('created', 0)}</b>\n"
            if result.get('skipped'):
                msg += f"⏭️ <b>Пропущено: {result['skipped']}</b>\n"
            msg += "\n"
            
            for o in result.get('orders', []):
                if o.get('skipped'):
                    msg += f"⏭️ {o.get('name') or o.get('username')} — {o.get('reason')}\n"
                else:
                    icon = "👑" if o.get('role') == 'main' else "🔢"
                    msg += f"{icon} <code>{o.get('orderId')}</code> @{o.get('username', '')}"
                    if o.get('deadline'):
                        msg += f" ⏰ {o['deadline']}"
                    msg += f" • 💎 {o.get('total', 0)} ₽\n"
            
            for r in result.get('results', []):
                if r.get('skipped'):
                    msg += f"⏭️ @{r.get('username')} — {r.get('reason')}\n"
                else:
                    msg += f"🦪 <code>{r.get('orderId')}</code> → @{r.get('username')} • 💎 {r.get('amount', 0)} ₽\n"
            
            if result.get('errors'):
                msg += f"\n⚠️ <b>Ошибки ({len(result['errors'])}):</b>\n"
                for e in result['errors'][:5]:
                    msg += f"  • {e.get('name') or e.get('username')}: {e.get('error')}\n"
            
            await callback.message.edit_text(msg, parse_mode="HTML")
        else:
            await callback.message.edit_text(f"❌ {result.get('error', 'Неизвестная ошибка')}")
    
    except Exception as e:
        print(f"❌ Ошибка при создании: {e}")
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")

# ===== /orders =====
@router.message(Command("orders"))
async def cmd_orders(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return
    
    orders = await api_get('getOrders', {'userId': 'all'})
    if not isinstance(orders, list):
        return await message.answer(f"❌ Ошибка: {orders}")
    
    active = [o for o in orders if o.get('status') != 'delivered']
    if not active:
        return await message.answer("✅ Нет активных заказов")
    
    text = f"🌊 <b>Активные заказы ({len(active)})</b>\n\n"
    for o in active[:15]:
        text += f"🦪 <b>{o.get('order_id')}</b>\n"
        text += f"├ {o.get('status')}\n"
        text += f"├ 💎 {o.get('total', 0)} ₽\n"
        text += f"└ 👤 {o.get('telegram_id')}\n\n"
    
    await message.answer(text, parse_mode="HTML")

# ===== /stats =====
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return
    
    stats = await api_get('getStats', {'userId': 'all'})
    text = (
        f"📊 <b>BLACK PEARL — Статистика</b>\n\n"
        f"🦪 Всего заказов: <b>{stats.get('totalOrders', 0)}</b>\n"
        f"💎 Выручка: <b>{stats.get('totalRevenue', 0)} ₽</b>\n\n"
        f"⏳ Ожидают: {stats.get('pending', 0)}\n"
        f"💎 Оплачены: {stats.get('paid', 0)}\n"
        f"🌊 В пути: {stats.get('shipped', 0)}\n"
        f"📦 Готовы: {stats.get('ready', 0)}\n"
        f"✅ Получены: {stats.get('delivered', 0)}"
    )
    await message.answer(text, parse_mode="HTML")
    
# ===== /theme =====
@router.message(Command("theme"))
async def cmd_theme(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return await message.answer(" Только для админов")
    
    parts = message.text.split(maxsplit=1)
    theme_name = parts[1].strip() if len(parts) > 1 else None
    
    # Полный список тем
    themes = [
        ('pirate', '⚓ Pirate Default (бирюзовый)'),
        ('emerald', '💚 Emerald (изумрудный)'),
        ('newjeans_ditto', '💗 NewJeans — Ditto (розовый)'),
        ('newjeans_supershy', '💕 NewJeans — Super Shy (ярко-розовый)'),
        ('bts_butter', '🧈 BTS — Butter (кремовый)'),
        ('aespa_supernova', '✨ aespa — Supernova (фиолетовый)'),
        ('aespa_drama', '🔥 aespa — Drama (красный)'),
        ('seventeen_godofmusic', '👑 SEVENTEEN — God of Music (золотой)'),
        ('straykids_rockstar', '🎸 Stray Kids — Rock-Star (рок-красный)'),
        ('lesserafim_easy', '💙 LE SSERAFIM — Easy (голубой)'),
        ('enhypen_romance', '🌙 ENHYPEN — Romance (серебро)'),
        ('ive_baddie', '💖 IVE — Baddie (черно-розовый)'),
        ('twice_withyouth', '🌸 TWICE — With YOU-th (пастель)'),
        ('blackpink_pinkvenom', '🖤 BLACKPINK — Pink Venom (неон-розовый)'),
        ('ocean', '🌊 Ocean (океанский синий)'),
        ('sunset', '🌅 Sunset (закатный)'),
        ('midnight', ' Midnight (полуночный)'),
        ('forest', '🌲 Forest (лесной)'),
        ('ruby', '❤️ Ruby (рубиновый)'),
        ('amethyst', '💜 Amethyst (аметистовый)')
    ]
    
    if not theme_name:
        # Показываем текущую тему и список
        try:
            current = await api_get('getTheme')
            current_theme = current.get('theme', 'pirate')
        except:
            current_theme = 'pirate'
        
        text = f"🎨 <b>Текущая тема:</b> {current_theme}\n\n"
        text += "<b>Доступные темы:</b>\n\n"
        for tid, tname in themes:
            marker = " ✅" if tid == current_theme else ""
            text += f"<code>/theme {tid}</code> — {tname}{marker}\n"
        
        text += "\n💡 Пример: <code>/theme emerald</code>"
        
        return await message.answer(text, parse_mode="HTML")
    
    # Проверяем, есть ли такая тема
    valid_theme = next((t for t in themes if t[0] == theme_name), None)
    if not valid_theme:
        return await message.answer(
            f"❌ Тема <b>{theme_name}</b> не найдена\n\n"
            f"Используй <code>/theme</code> без аргументов для списка",
            parse_mode="HTML"
        )
    
    # Применяем тему
    try:
        await api_post({'action': 'setTheme', 'theme': theme_name})
        await message.answer(
            f"🎨 <b>Тема изменена!</b>\n\n"
            f"{valid_theme[1]}\n\n"
            f"Все пользователи увидят новую палитру при следующем открытии приложения ✨",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
# ===== ЗАПУСК =====
async def main():
    global session
    session = aiohttp.ClientSession()
    
    print("🖤 BLACK PEARL Admin Bot запущен")
    print(f"📡 API URL: {API_URL}")
    print(f"🤖 Bot token: {BOT_TOKEN[:10]}...")
    
    try:
        await dp.start_polling(bot)
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(main())
