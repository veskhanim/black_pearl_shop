import re
import os

API_URL = os.getenv('APPS_SCRIPT_URL')

# ===== ОПРЕДЕЛЕНИЕ ТИПА ПОСТА =====
def detect_post_type(text: str) -> str:
    """Определяет тип поста: signup_positions, signup, payment или unknown"""
    # Пост оплаты: @user - сумма (но нет очередей и позиций)
    if re.search(r'@\w+\s*[-—]\s*\d+', text) and not re.search(r'^\d+\.\s+.+@', text, re.MULTILINE) and not re.search(r'очередь', text, re.IGNORECASE):
        return 'payment'
    
    # Пост с позициями: "1. Название @user"
    if re.search(r'^\d+\.\s+.+?@', text, re.MULTILINE):
        return 'signup_positions'
    
    # Пост записи с очередями
    has_queues = bool(re.search(r'очередь', text, re.IGNORECASE))
    has_price = bool(re.search(r'\d[\d\s]*\s*₽', text, re.IGNORECASE))
    has_usernames = bool(re.search(r'@\w+', text))
    
    if (has_queues or has_price) and has_usernames:
        return 'signup'
    
    return 'unknown'

# ===== ПАТТЕРН ЭМОДЗИ =====
emoji_pattern = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
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

# ===== ПАРСИНГ ПОСТА С ПОЗИЦИЯМИ =====
def parse_positions_post(text: str) -> dict:
    result = {'postTitle': None, 'hashtag': None, 'priceList': {}, 'positions': []}
    lines = [l.strip() for l in text.split('\n')]
    
    result['postTitle'] = next((l for l in lines if l), 'Без названия')
    
    hashtag_match = re.search(r'#([a-zA-Z0-9_а-яА-Я]+)', text)
    if hashtag_match:
        result['hashtag'] = '#' + hashtag_match.group(1)
    
    # Справочник цен
    first_pos_idx = next((i for i, l in enumerate(lines) if re.match(r'^\d+\.\s+', l)), len(lines))
    for line in lines[:first_pos_idx]:
        match = re.match(r'^(.+?)\s+(?:по\s+)?(\d[\d\s]*)\s*(?:₽|руб|rub|сум)', line, re.IGNORECASE)
        if match:
            name = match.group(1).strip().rstrip('!,').strip()
            price = int(match.group(2).replace(' ', ''))
            if name and price:
                result['priceList'][name.lower()] = {'name': match.group(1).strip(), 'price': price}
    
    # Разбивка на блоки позиций
    blocks = []
    current_block = None
    for line in lines:
        pos_match = re.match(r'^(\d+)\.\s+(.+?)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$', line)
        if pos_match:
            if current_block: blocks.append(current_block)
            current_block = {
                'positionNum': int(pos_match.group(1)),
                'positionName': pos_match.group(2).strip(),
                'mainBuyer': pos_match.group(3),
                'mainDeadline': pos_match.group(4),
                'queueLines': []
            }
        elif current_block:
            current_block['queueLines'].append(line)
    if current_block: blocks.append(current_block)
    
    # Парсинг очередей
    for block in blocks:
        position = {
            'number': block['positionNum'],
            'name': block['positionName'],
            'mainBuyer': {'username': block['mainBuyer'], 'deadline': block['mainDeadline']},
            'queue': []
        }
        for line in block['queueLines']:
            clean = line.strip()
            if not clean or re.match(r'^очередь', clean, re.IGNORECASE): continue
            m = re.match(r'^([а-яА-Яa-zA-ZёЁ]+)\s*:\s*@?([a-zA-Z0-9_]+)?(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$', clean)
            if m and m.group(2):
                position['queue'].append({'member': m.group(1), 'username': m.group(2), 'deadline': m.group(3)})
        result['positions'].append(position)
        
    return result

# ===== ПАРСИНГ ПОСТА ЗАПИСИ (с поддержкой эмодзи-админов) =====
def parse_signup_post(text: str, admins_by_icon: dict = None) -> dict:
    """
    Парсит пост записи с очередями.
    Поддерживает цену в рублях (₽) и долларах ($).
    """
    if admins_by_icon is None:
        admins_by_icon = {}
    
    result = {'postTitle': None, 'price': None, 'currency': 'RUB', 'entries': []}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    if not lines:
        return result
    
    result['postTitle'] = lines[0]
    
    # Цена в рублях: число перед ₽
    price_rub_match = re.search(r'(\d[\d\s]*?)\s*₽', text)
    if price_rub_match:
        price_str = price_rub_match.group(1).replace(' ', '')
        if price_str:
            result['price'] = int(price_str)
            result['currency'] = 'RUB'
    else:
        # Цена в долларах: число перед $ или "X$"
        price_usd_match = re.search(r'(\d[\d\s]*?)\s*\$', text)
        if price_usd_match:
            price_str = price_usd_match.group(1).replace(' ', '')
            if price_str:
                result['price'] = int(price_str)
                result['currency'] = 'USD'
    
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
            
            # Паттерн 2: "Имя" + что-то (эмодзи или свободный слот)
            m2 = re.match(r'^([А-Яа-яA-Za-zёЁ]+)\s+(.+)$', line)
            if m2:
                name = m2.group(1)
                rest = m2.group(2).strip()
                
                emojis = emoji_pattern.findall(rest)
                if emojis:
                    icon = emojis[0]
                    if icon in admins_by_icon:
                        admin = admins_by_icon[icon]
                        print(f"🎭 Слот админа: {name} {icon} → {admin['name']}")
                        result['entries'].append({
                            'name': name,
                            'username': admin['name'],
                            'telegramId': admin['telegram_id'],
                            'deadline': None,
                            'queue': queue['number'],
                            'role': 'admin',
                            'icon': icon
                        })
                    else:
                        print(f"️ Неизвестный эмодзи {icon} для {name} — пропускаем")
                else:
                    print(f"⏭️ Свободный слот в очереди {queue['number']}: {name}")
                continue
            
            # Паттерн 3: просто имя без всего
            m3 = re.match(r'^([А-Яа-яA-Za-zёЁ]+)\s*$', line)
            if m3:
                print(f"⏭️ Свободный слот в очереди {queue['number']}: {m3.group(1)}")
                continue
    
    return result

# ===== ПАРСИНГ ПОСТА ОПЛАТЫ =====
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

# ===== ПОИСК ЦЕНЫ ПО НАЗВАНИЮ ПОЗИЦИИ =====
def find_price_for_position(position_name: str, price_list: dict) -> int:
    exact = price_list.get(position_name.lower())
    if exact: return exact['price']
    for key, val in price_list.items():
        if position_name.lower() in key or key in position_name.lower():
            return val['price']
    return 0

# ===== АВТОДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЕЙ =====
async def ensure_users_in_db(usernames: list, session):
    """
    Проверяет пользователей и создаёт отсутствующих.
    Возвращает (user_map, new_users)
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
    
async def is_user_blocked(username: str, session) -> bool:
    """Проверяет, заблокирован ли пользователь"""
    if not username:
        return False
    
    try:
        async with session.post(API_URL, json={
            'action': 'checkUserByUsername',
            'username': username
        }) as resp:
            result = await resp.json()
            return result.get('blocked', False)
    except Exception as e:
        print(f"❌ Ошибка проверки блокировки @{username}: {e}")
        return False
