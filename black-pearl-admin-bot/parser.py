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
    result = {'postTitle': None, 'price': None, 'entries': []}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if lines: result['postTitle'] = lines[0]
    
    price_match = re.search(r'по\s+(\d[\d\s]*)\s*(?:₽|руб|rub|сум)', text, re.IGNORECASE)
    if price_match: result['price'] = int(price_match.group(1).replace(' ', ''))
    
    for line in lines[1:]:
        m = re.match(r'^([А-Яа-яA-Za-z]+)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?', line)
        if m:
            result['entries'].append({
                'name': m.group(1), 'username': m.group(2), 
                'deadline': m.group(3), 'queue': 1, 'telegramId': None
            })
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
    Проверяет всех пользователей в базе и создаёт отсутствующих.
    Возвращает словарь {username: telegram_id}
    """
    user_map = {}
    
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
                    action = result.get('action')
                    if action == 'created':
                        print(f"✅ Создан пользователь: @{username}")
                    else:
                        print(f" Найден пользователь: @{username} (ID: {result.get('telegram_id')})")
                else:
                    print(f"❌ Ошибка upsertUserByUsername для @{username}: {result.get('error')}")
                    user_map[username] = None
                    
        except Exception as e:
            print(f" Ошибка запроса для @{username}: {e}")
            user_map[username] = None
    
    return user_map
