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

def parse_positions_post(text: str) -> dict:
    result = {'postTitle': None, 'hashtag': None, 'priceList': {}, 'positions': []}
    lines = [l.strip() for l in text.split('\n')]
    
    result['postTitle'] = next((l for l in lines if l), 'Без названия')
    
    hashtag_match = re.search(r'#([a-zA-Z0-9_а-яА-Я]+)', text)
    if hashtag_match:
        result['hashtag'] = '#' + hashtag_match.group(1)
    
    first_pos_idx = next((i for i, l in enumerate(lines) if re.match(r'^\d+\.\s+', l)), len(lines))
    for line in lines[:first_pos_idx]:
        match = re.match(r'^(.+?)\s+(?:по\s+)?(\d[\d\s]*)\s*(?:₽|руб|rub|сум)', line, re.IGNORECASE)
        if match:
            name = match.group(1).strip().rstrip('!,').strip()
            price = int(match.group(2).replace(' ', ''))
            if name and price:
                result['priceList'][name.lower()] = {'name': match.group(1).strip(), 'price': price}
    
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
