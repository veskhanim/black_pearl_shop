import re
import aiohttp
import os
API_URL = os.getenv('APPS_SCRIPT_URL')

# ===== ФУНКЦИИ ПАРСИНГА (без изменений) =====

def detect_post_type(text: str) -> str:
    if re.search(r'@\w+\s*[-—]\s*\d+', text) and not re.search(r'^\d+\.\s+.+@', text, re.MULTILINE):
        return 'payment'
    if re.search(r'^\d+\.\s+.+?@', text, re.MULTILINE):
        return 'signup_positions'
    if (re.search(r'очередь', text, re.IGNORECASE) or re.search(r'по\s+\d+\s*₽', text, re.IGNORECASE)) and re.search(r'@\w+', text):
        return 'signup'
    return 'unknown'

def parse_signup_post(text: str, admins_by_icon: dict = None) -> dict:
    """
    Парсит пост записи с очередями.
    admins_by_icon: словарь {icon: {name, telegram_id}} для поиска админов по иконкам.
    """
    if admins_by_icon is None:
        admins_by_icon = {}
    
    result = {'postTitle': None, 'price': None, 'entries': []}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    if not lines:
        return result
    
    # Заголовок
    result['postTitle'] = lines[0]
    
    # Цена: число перед ₽
    price_match = re.search(r'(\d[\d\s]*?)\s*₽', text)
    if price_match:
        price_str = price_match.group(1).replace(' ', '')
        if price_str:
            result['price'] = int(price_str)
    
    # Разбиваем на очереди
    queues = []
    current_queue = None
    current_lines = []
    
    for line in lines:
        queue_match = re.match(r'^(\d+)\s+очередь', line, re.IGNORECASE)
        if queue_match:
            if current_queue is not None and current_lines:
                queues.append({'number': current_queue, 'lines': current_lines})
            current_queue = int(queue_match.group(1))
            current_lines = []
        elif current_queue is not None:
            current_lines.append(line)
        else:
            if current_queue is None:
                current_queue = 1
                current_lines.append(line)
    
    if current_queue is not None and current_lines:
        queues.append({'number': current_queue, 'lines': current_lines})
    
    # Паттерн для извлечения эмодзи (любой эмодзи в конце строки)
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "]+", 
        flags=re.UNICODE
    )
    
    # Парсим записи
    for queue in queues:
        for line in queue['lines']:
            # Паттерн 1: "Имя @username //дата"
            m = re.match(
                r'^([А-Яа-яA-Za-zёЁ]+)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$', 
                line
            )
            if m:
                result['entries'].append({
                    'name': m.group(1),
                    'username': m.group(2),
                    'deadline': m.group(3),
                    'queue': queue['number'],
                    'telegramId': None,
                    'role': 'client'
                })
                continue
            
            # Паттерн 2: "Имя" + эмодзи (слот админа)
            m2 = re.match(r'^([А-Яа-яA-Za-zёЁ]+)\s+(.+)$', line)
            if m2:
                name = m2.group(1)
                rest = m2.group(2).strip()
                
                # Проверяем, есть ли эмодзи в rest
                emojis = emoji_pattern.findall(rest)
                if emojis:
                    icon = emojis[0]  # берём первый эмодзи
                    
                    # Ищем админа по иконке
                    if icon in admins_by_icon:
                        admin = admins_by_icon[icon]
                        print(f"🎭 Слот админа: {name} {icon} → @{admin['name']}")
                        result['entries'].append({
                            'name': name,
                            'username': admin['name'],  # имя админа как username
                            'telegramId': admin['telegram_id'],
                            'deadline': None,
                            'queue': queue['number'],
                            'role': 'admin',
                            'icon': icon
                        })
                    else:
                        print(f"⏭️ Неизвестный эмодзи {icon} для {name} — пропускаем")
                else:
                    # Просто имя без username и без эмодзи — пропускаем
                    print(f"⏭️ Свободный слот в очереди {queue['number']}: {name}")
                continue
            
            # Паттерн 3: просто имя без всего
            m3 = re.match(r'^([А-Яа-яA-Za-zёЁ]+)\s*$', line)
            if m3:
                print(f"⏭️ Свободный слот в очереди {queue['number']}: {m3.group(1)}")
                continue
    
    return result

def parse_signup_post(text: str) -> dict:
    """
    Парсит пост записи с очередями.
    Цена — первое число, за которым идёт знак ₽.
    """
    result = {'postTitle': None, 'price': None, 'entries': []}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    if not lines:
        return result
    
    # Заголовок — первая непустая строка
    result['postTitle'] = lines[0]
    
    # Цена: ищем число, за которым идёт ₽ (с пробелом или без)
    # Паттерн: число (возможно с пробелами-разделителями тысяч) + ₽
    price_match = re.search(r'(\d[\d\s]*?)\s*₽', text)
    if price_match:
        price_str = price_match.group(1).replace(' ', '')
        if price_str:
            result['price'] = int(price_str)
    
    # Разбиваем на очереди
    queues = []
    current_queue = None
    current_lines = []
    
    for line in lines:
        queue_match = re.match(r'^(\d+)\s+очередь', line, re.IGNORECASE)
        if queue_match:
            if current_queue is not None and current_lines:
                queues.append({'number': current_queue, 'lines': current_lines})
            current_queue = int(queue_match.group(1))
            current_lines = []
        elif current_queue is not None:
            current_lines.append(line)
        else:
            if current_queue is None:
                current_queue = 1
                current_lines.append(line)
    
    if current_queue is not None and current_lines:
        queues.append({'number': current_queue, 'lines': current_lines})
    
    # Парсим записи в каждой очереди
    for queue in queues:
        for line in queue['lines']:
            # Паттерн 1: "Имя @username //дата"
            m = re.match(
                r'^([А-Яа-яA-Za-zёЁ]+)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$', 
                line
            )
            if m:
                result['entries'].append({
                    'name': m.group(1),
                    'username': m.group(2),
                    'deadline': m.group(3),
                    'queue': queue['number'],
                    'telegramId': None
                })
                continue
            
            # Паттерн 2: свободный слот (без username) — пропускаем 
            # TODO Админы тоже должны писать свои ники или потом подставлять их из базы
            m2 = re.match(r'^([А-Яа-яA-Za-zёЁ]+)\s*(?:[🥰💖❤️🔥✨🌸]|\s)*$', line)
            if m2:
                print(f"⏭️ Занято админом в очереди {queue['number']}: {m2.group(1)}")
                continue
    
    return result

def parse_payment_post(text: str) -> dict:
    entries = []
    for m in re.finditer(r'@([a-zA-Z0-9_]+)\s*[-—]\s*([\d\s]+)\s*(?:₽|руб|rub|сум)?(?:\s*\/\/\s*(\d{2}\.\d{2}))?', text):
        entries.append({
            'username': m.group(1),
            'amount': int(m.group(2).replace(' ', '')),
            'deadline': m.group(3),
            'telegramId': None
        })
    return {'entries': entries}

def find_price_for_position(position_name: str, price_list: dict) -> int:
    exact = price_list.get(position_name.lower())
    if exact: return exact['price']
    for key, val in price_list.items():
        if position_name.lower() in key or key in position_name.lower():
            return val['price']
    return 0

# ===== НОВАЯ ФУНКЦИЯ: АВТОДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЕЙ =====
async def ensure_users_in_db(usernames: list, session):
    """
    Проверяет пользователей и создаёт отсутствующих.
    Возвращает (user_map, new_users) — словарь и список новых.
    """
    user_map = {}
    new_users = []
    
    for username in usernames:
        if not username:
            continue
        
        try:
            async with session.post(API_URL, json={
                'action': 'upsertUserByUsername',
                'username': username
            }) as resp:
                result = await resp.json()
                
                if result.get('success'):
                    user_map[username] = result.get('telegram_id')
                    if result.get('action') == 'created':
                        new_users.append(username)
                        print(f"✅ Создан пользователь: @{username}")
                    else:
                        print(f"🔍 Найден: @{username}")
                else:
                    print(f"❌ Ошибка для @{username}: {result.get('error')}")
                    user_map[username] = None
                    
        except Exception as e:
            print(f"❌ Ошибка запроса для @{username}: {e}")
            user_map[username] = None
    
    return user_map, new_users
