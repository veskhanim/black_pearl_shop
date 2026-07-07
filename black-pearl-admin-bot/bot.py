import os
import time
import asyncio
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from parser import (
    detect_post_type, 
    parse_positions_post, 
    parse_signup_post, 
    parse_payment_post, 
    find_price_for_position,
    ensure_users_in_db
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
        f" <b>BLACK PEARL — Admin Panel</b>\n\n"
        f"👋 Привет, <b>{admin['name']}</b>!\n"
        f"🎭 Роль: <b>{admin['role']}</b>\n\n"
        f"📋 <b>Команды:</b>\n"
        f"/orders — активные заказы\n"
        f"/create — создать заказ вручную\n"
        f"/stats — статистика\n"
        f"/theme [название] — сменить тему\n"
        f"/block username причина — заблокировать 🔒\n"
        f"/unblock username — разблокировать 🔓\n"
        f"/blocked — список заблокированных\n\n"
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
        await callback.answer(" Нет прав", show_alert=True)
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
    
    # Показываем прогресс
    await callback.message.edit_text("⏳ <b>Создаю записи...</b>\n\nЭто займёт до 30 секунд \n\n📝 Обрабатываю пост...", parse_mode="HTML")
    
    try:
        text = post_data['text']
        p_type = post_data['type']
        result = {}
        new_users = []  # список новых пользователей
        
        if p_type == 'signup_positions':
            parsed = parse_positions_post(text)
            
            # Собираем все username
            all_usernames = set()
            for pos in parsed['positions']:
                all_usernames.add(pos['mainBuyer']['username'])
                for q in pos['queue']:
                    if q.get('username'):
                        all_usernames.add(q['username'])
            
            # Автодобавляем пользователей
            print(f"👥 Проверяем {len(all_usernames)} пользователей...")
            user_map, new_users = await ensure_users_in_db(list(all_usernames), session)
            
            # Обновляем сообщение с прогрессом
            progress_text = f"⏳ <b>Создаю записи...</b>\n\n"
            progress_text += f"👥 Найдено пользователей: <b>{len(all_usernames)}</b>\n"
            if new_users:
                progress_text += f"🆕 Новых: <b>{len(new_users)}</b>\n"
            progress_text += f"\n📝 Создаю заказы..."
            await callback.message.edit_text(progress_text, parse_mode="HTML")
            
            entries = []
            for pos in parsed['positions']:
                price = find_price_for_position(pos['name'], parsed['priceList'])
                
                main_username = pos['mainBuyer']['username']
                entries.append({
                    'username': main_username,
                    'name': main_username,
                    'positionNumber': pos['number'],
                    'positionName': pos['name'],
                    'role': 'main',
                    'deadline': pos['mainBuyer'].get('deadline'),
                    'price': price,
                    'telegramId': user_map.get(main_username)
                })
                
                for q in pos['queue']:
                    q_username = q.get('username')
                    if q_username:
                        entries.append({
                            'username': q_username,
                            'name': q['member'],
                            'positionNumber': pos['number'],
                            'positionName': pos['name'],
                            'role': 'queue',
                            'deadline': q.get('deadline'),
                            'price': price,
                            'telegramId': user_map.get(q_username)
                        })
            
            result = await api_post({
                'action': 'createOrdersFromPositions',
                'postTitle': parsed['postTitle'],
                'hashtag': parsed.get('hashtag'),
                'priceList': parsed.get('priceList'),
                'admin': admin['name'],
                'entries': entries
            })
        
        elif p_type == 'signup':
            # Загружаем админов с иконками
            admins_by_icon = await get_admins_with_icons()
            parsed = parse_signup_post(text, admins_by_icon)
            
            all_usernames = set()
            for e in parsed['entries']:
                if e.get('username'):
                    all_usernames.add(e['username'])
            
            print(f"👥 Проверяем {len(all_usernames)} пользователей...")
            user_map, new_users = await ensure_users_in_db(list(all_usernames), session)
            
            # Показываем прогресс с конвертацией
            currency_symbol = '$' if parsed.get('currency') == 'USD' else '₽'
            price_display = f"{parsed.get('price', 0)}{currency_symbol}"
            
            progress_text = f"⏳ <b>Создаю записи...</b>\n\n"
            progress_text += f"💎 Цена: <b>{price_display}</b>\n"
            if parsed.get('currency') == 'USD':
                # Получаем курс
                try:
                    rate_data = await api_get('getUsdRate')
                    usd_rate = rate_data.get('rate', 90)
                    rub_price = parsed.get('price', 0) * usd_rate
                    progress_text += f"💱 Курс: {usd_rate}₽/$ → <b>{rub_price}₽</b>\n"
                except:
                    pass
            progress_text += f"\n👥 Найдено пользователей: <b>{len(all_usernames)}</b>\n"
            if new_users:
                progress_text += f"🆕 Новых: <b>{len(new_users)}</b>\n"
            progress_text += f"\n📝 Создаю заказы..."
            await callback.message.edit_text(progress_text, parse_mode="HTML")
            
            for e in parsed['entries']:
                if e.get('username'):
                    if e.get('role') == 'admin':
                        e['telegramId'] = e.get('telegramId') or user_map.get(e['username'])
                    else:
                        e['telegramId'] = user_map.get(e['username'])
            
            result = await api_post({
                'action': 'createOrdersFromPost',
                'postTitle': parsed['postTitle'],
                'price': parsed.get('price'),
                'currency': parsed.get('currency', 'RUB'),  # ← Передаём валюту
                'admin': admin['name'],
                'entries': parsed['entries']
            })    
        
        elif p_type == 'payment':
            parsed = parse_payment_post(text)
            
            all_usernames = set()
            for e in parsed['entries']:
                if e.get('username'):
                    all_usernames.add(e['username'])
            
            print(f"👥 Проверяем {len(all_usernames)} пользователей...")
            user_map, new_users = await ensure_users_in_db(list(all_usernames), session)
            
            progress_text = f" <b>Создаю записи...</b>\n\n"
            progress_text += f"👥 Найдено пользователей: <b>{len(all_usernames)}</b>\n"
            if new_users:
                progress_text += f"🆕 Новых: <b>{len(new_users)}</b>\n"
            progress_text += f"\n Создаю оплаты..."
            await callback.message.edit_text(progress_text, parse_mode="HTML")
            
            for e in parsed['entries']:
                if e.get('username'):
                    e['telegramId'] = user_map.get(e['username'])
            
            result = await api_post({
                'action': 'createPaymentsFromPost',
                'admin': admin['name'],
                'entries': parsed['entries']
            })
        
        # Формируем финальное сообщение
        if result.get('success'):
            msg = f"✅ <b>Создано: {result.get('created', 0)}</b>\n"
            if result.get('skipped'):
                msg += f"️ <b>Пропущено: {result['skipped']}</b>\n"
            
            # Показываем новых пользователей
            if new_users:
                msg += f"\n <b>Новых пользователей: {len(new_users)}</b>\n"
                for u in new_users[:10]:  # показываем первые 10
                    msg += f"  • @{u}\n"
                if len(new_users) > 10:
                    msg += f"  ... и ещё {len(new_users) - 10}\n"
            
            msg += "\n"
            
            # Список заказов с пометкой ролей
            for o in result.get('orders', []):
                username = o.get('username', '')
                is_new = username in new_users
                role = o.get('role', '')
                
                # Определяем маркер
                if role == 'admin':
                    marker = " 🎭"  # админ
                elif is_new:
                    marker = " 🆕"  # новый пользователь
                else:
                    marker = ""
                
                if o.get('skipped'):
                    msg += f"⏭️ {o.get('name') or username} — {o.get('reason')}{marker}\n"
                else:
                    icon = "👑" if o.get('role') == 'main' else "🔢"
                    msg += f"{icon} <code>{o.get('orderId')}</code> @{username}{marker}"
                    if o.get('deadline'):
                        msg += f" ⏰ {o['deadline']}"
                    msg += f" • 💎 {o.get('total', 0)} ₽\n"
            
            for r in result.get('results', []):
                username = r.get('username', '')
                is_new = username in new_users
                marker = " 🆕" if is_new else ""
                
                if r.get('skipped'):
                    msg += f"⏭️ @{username} — {r.get('reason')}{marker}\n"
                else:
                    msg += f"🦪 <code>{r.get('orderId')}</code> → @{username}{marker} •  {r.get('amount', 0)} ₽\n"
            
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
async def cmd_orders(message: Message, session: aiohttp.ClientSession):
    admin = await get_admin(message.from_user.id, session)
    if not admin:
        return
    
    orders = await api_get('getOrders', {'userId': 'all'})
    if not isinstance(orders, list):
        return await message.answer(f"❌ Ошибка: {orders}")
    
    # Показываем только неоплаченные и не отменённые
    active = [o for o in orders if o.get('status') in ['Ожидает', 'Оплачен']]
    if not active:
        return await message.answer("✅ Нет активных заказов")
    
    text = f"🌊 <b>Активные заказы ({len(active)})</b>\n\n"
    for o in active[:15]:
        text += f"🦪 <b>{o.get('order_id')}</b>\n"
        text += f"├ {o.get('status')}\n"
        text += f" 💎 {o.get('total', 0)} ₽\n"
        text += f"└ 👤 {o.get('telegram_id')}\n\n"
    
    await message.answer(text, parse_mode="HTML")

# ===== /stats =====
@router.message(Command("status"))
async def cmd_status(message: Message, session: aiohttp.ClientSession):
    admin = await get_admin(message.from_user.id, session)
    if not admin:
        return
    
    orders = await api_get('getOrders', {'userId': 'all'})
    if not isinstance(orders, list):
        orders = []
    
    pending = len([o for o in orders if o.get('status') == 'Ожидает'])
    paid = len([o for o in orders if o.get('status') == 'Оплачен'])
    cancelled = len([o for o in orders if o.get('status') == 'Отменён'])
    refund = len([o for o in orders if o.get('status') == 'Возврат'])
    
    text = (
        f"📊 <b>BLACK PEARL — Статистика</b>\n\n"
        f"🦪 Всего заказов: <b>{len(orders)}</b>\n\n"
        f"⏳ Ожидают оплаты: {pending}\n"
        f"💎 Оплачены: {paid}\n"
        f"❌ Отменены: {cancelled}\n"
        f"↩️ Возврат: {refund}"
    )
    await message.answer(text, parse_mode="HTML")

# Кэш админов с иконками
admins_icons_cache = {}
admins_icons_time = 0

async def get_admins_with_icons():
    """Загружает словарь {icon: {name, telegram_id}}"""
    global admins_icons_cache, admins_icons_time
    
    if admins_icons_cache and time.time() - admins_icons_time < 60:
        return admins_icons_cache
    
    try:
        async with session.get(f"{API_URL}?action=getAdminsWithIcons") as resp:
            data = await resp.json()
            if isinstance(data, list):
                admins_icons_cache = {
                    a['icon']: {
                        'name': a['name'],
                        'telegram_id': a['telegram_id']
                    }
                    for a in data if a.get('icon')
                }
                admins_icons_time = time.time()
                print(f"🎭 Загружено {len(admins_icons_cache)} админов с иконками")
                return admins_icons_cache
    except Exception as e:
        print(f"❌ Ошибка getAdminsWithIcons: {e}")
    
    return {}
    
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

# ===== /block =====
@router.message(Command("block"))
async def cmd_block(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return await message.answer("⛔ Только для админов")
    
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer(
            "🔒 <b>Блокировка пользователя</b>\n\n"
            "Формат: <code>/block username причина</code>\n\n"
            "Пример: <code>/block bad_user спам и мошенничество</code>",
            parse_mode="HTML"
        )
    
    username = parts[1].lstrip('@')
    reason = parts[2]
    
    try:
        result = await api_post({
            'action': 'blockUser',
            'username': username,
            'reason': reason,
            'blockedBy': admin['name']
        })
        
        if result.get('success'):
            await message.answer(
                f"🔒 <b>Пользователь заблокирован!</b>\n\n"
                f"👤 @{username}\n"
                f"📝 Причина: {reason}\n"
                f"👮 Заблокировал: {admin['name']}\n\n"
                f"Пользователь больше не сможет открыть мини-приложение.",
                parse_mode="HTML"
            )
        else:
            await message.answer(f"❌ Ошибка: {result.get('error')}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

# ===== /unblock =====
@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return await message.answer("⛔ Только для админов")
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer(
            "🔓 <b>Разблокировка пользователя</b>\n\n"
            "Формат: <code>/unblock username</code>\n\n"
            "Пример: <code>/unblock bad_user</code>",
            parse_mode="HTML"
        )
    
    username = parts[1].lstrip('@')
    
    try:
        result = await api_post({
            'action': 'unblockUser',
            'username': username
        })
        
        if result.get('success'):
            await message.answer(
                f"🔓 <b>Пользователь разблокирован!</b>\n\n"
                f"👤 @{username}\n"
                f"👮 Разблокировал: {admin['name']}",
                parse_mode="HTML"
            )
        else:
            await message.answer(f"❌ Ошибка: {result.get('error')}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

# ===== /blocked =====
@router.message(Command("blocked"))
async def cmd_blocked(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return await message.answer("⛔ Только для админов")
    
    try:
        blocked = await api_get('getBlockedUsers')
        
        if not blocked or not isinstance(blocked, list) or not len(blocked):
            return await message.answer("✅ Нет заблокированных пользователей")
        
        text = f" <b>Заблокированные ({len(blocked)})</b>\n\n"
        for u in blocked[:20]:
            text += f"👤 <b>@{u.get('username', 'unknown')}</b>\n"
            text += f"   📝 {u.get('reason', 'Без причины')}\n"
            text += f"   🆔 {u.get('telegram_id')}\n\n"
        
        if len(blocked) > 20:
            text += f"... и ещё {len(blocked) - 20}\n"
        
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

import time
from datetime import datetime

# ===== /ping — быстрая проверка =====
@router.message(Command("ping"))
async def cmd_ping(message: Message):
    await message.answer("🏓 Pong! Бот работает.")

# ===== /status — проверка всех сервисов =====
@router.message(Command("status"))
async def cmd_status(message: Message):
    admin = await get_admin(message.from_user.id)
    if not admin:
        return await message.answer(" Только для админов")
    
    await message.answer("⏳ Проверяю сервисы...")
    
    start_time = time.time()
    results = {}
    
    # 1. Проверка Apps Script API
    try:
        api_start = time.time()
        async with session.get(f"{API_URL}?action=test") as resp:
            api_data = await resp.json()
        api_time = round((time.time() - api_start) * 1000)
        
        if api_data.get('success'):
            results['apps_script'] = {
                'status': '🟢',
                'time': f"{api_time} мс",
                'details': 'API работает'
            }
        else:
            results['apps_script'] = {
                'status': '',
                'time': f"{api_time} мс",
                'details': f"Ответ: {api_data.get('message', 'неизвестно')}"
            }
    except Exception as e:
        results['apps_script'] = {
            'status': '🔴',
            'time': '—',
            'details': str(e)[:50]
        }
    
    # 2. Проверка получения админов
    try:
        admins_start = time.time()
        admins = await get_admins()
        admins_time = round((time.time() - admins_start) * 1000)
        
        results['admins'] = {
            'status': '🟢' if admins else '🟡',
            'time': f"{admins_time} мс",
            'details': f"Админов: {len(admins)}"
        }
    except Exception as e:
        results['admins'] = {
            'status': '🔴',
            'time': '—',
            'details': str(e)[:50]
        }
    
    # 3. Проверка получения заказов
    try:
        orders_start = time.time()
        async with session.get(f"{API_URL}?action=getOrders&userId=all") as resp:
            orders_data = await resp.json()
        orders_time = round((time.time() - orders_start) * 1000)
        
        orders_count = len(orders_data) if isinstance(orders_data, list) else 0
        results['orders'] = {
            'status': '🟢',
            'time': f"{orders_time} мс",
            'details': f"Заказов: {orders_count}"
        }
    except Exception as e:
        results['orders'] = {
            'status': '🔴',
            'time': '—',
            'details': str(e)[:50]
        }
    
    # 4. Проверка Telegram Bot API
    try:
        me = await bot.get_me()
        results['telegram'] = {
            'status': '🟢',
            'time': '—',
            'details': f"Бот: @{me.username}"
        }
    except Exception as e:
        results['telegram'] = {
            'status': '',
            'time': '—',
            'details': str(e)[:50]
        }
    
    # 5. Статистика из кэша
    total_time = round((time.time() - start_time) * 1000)
    
    # Формируем ответ
    text = f"📊 <b>Статус сервисов</b>\n\n"
    text += f"⏱️ Проверка: {datetime.now().strftime('%H:%M:%S')}\n\n"
    
    # Apps Script
    api = results['apps_script']
    text += f"{api['status']} <b>Apps Script API</b> — {api['time']}\n"
    text += f"   {api['details']}\n\n"
    
    # Админы
    adm = results['admins']
    text += f"{adm['status']} <b>Кэш админов</b> — {adm['time']}\n"
    text += f"   {adm['details']}\n\n"
    
    # Заказы
    ord = results['orders']
    text += f"{ord['status']} <b>Заказы</b> — {ord['time']}\n"
    text += f"   {ord['details']}\n\n"
    
    # Telegram
    tg = results['telegram']
    text += f"{tg['status']} <b>Telegram Bot</b>\n"
    text += f"   {tg['details']}\n\n"
    
    # Итого
    text += f"{'─' * 20}\n"
    text += f"⚡ <b>Общее время:</b> {total_time} мс\n"
    
    # Определяем общий статус
    has_red = any(r['status'] == '🔴' for r in results.values())
    has_yellow = any(r['status'] == '' for r in results.values())
    
    if has_red:
        text += f"🔴 <b>Есть проблемы!</b>"
    elif has_yellow:
        text += f"🟡 <b>Внимание</b>"
    else:
        text += f"🟢 <b>Всё работает</b>"
    
    await message.answer(text, parse_mode="HTML")
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
