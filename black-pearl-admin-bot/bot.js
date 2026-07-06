require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');
const parser = require('./parser');

const bot = new TelegramBot(process.env.BOT_TOKEN, {polling: true});
const API = process.env.APPS_SCRIPT_URL;

const ROLES = {
  manager: ['create', 'status', 'payment', 'box', 'pickup', 'orders', 'stats', 'users', 'parse', 'theme'],
  warehouse: ['box', 'pickup', 'orders', 'status', 'parse'],
  courier: ['pickup', 'orders']
};

let adminsCache = null;
let cacheTime = 0;

async function getAdmins() {
  if (adminsCache && Date.now() - cacheTime < 60000) return adminsCache;
  try {
    const res = await fetch(`${API}?action=getAdmins`);
    adminsCache = await res.json();
    cacheTime = Date.now();
    return adminsCache;
  } catch(e) { return []; }
}

async function getAdmin(userId) {
  const admins = await getAdmins();
  return admins.find(a => String(a.telegram_id) === String(userId));
}

function canDo(role, action) { return ROLES[role]?.includes(action) || false; }

async function apiGet(action, params = {}) {
  const url = new URL(API);
  url.searchParams.set('action', action);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url.toString());
  return res.json();
}

async function apiPost(data) {
  const res = await fetch(API, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  return res.json();
}

const STATUS_EMOJI = {pending: '⏳', paid: '💎', shipped: '🌊', ready: '📦', delivered: '✅'};
const STATUS_LABELS = {pending: 'Ожидает оплаты', paid: 'Оплачен', shipped: 'В пути', ready: 'Готов к выдаче', delivered: 'Получен'};

// /start
bot.onText(/\/start/, async (msg) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin) return bot.sendMessage(msg.chat.id, '🖤 <b>BLACK PEARL</b>\n\n⛔ У тебя нет доступа.', {parse_mode: 'HTML'});
  
  bot.sendMessage(msg.chat.id, 
    `🖤 <b>BLACK PEARL — Admin Panel</b>\n\n` +
    `👋 Привет, <b>${admin.name}</b>!\n` +
    `🎭 Роль: <b>${admin.role}</b>\n\n` +
    `📋 <b>Команды:</b>\n` +
    `/orders — активные заказы\n` +
    `/order &lt;id&gt; — детали заказа\n` +
    `/create — создать заказ вручную\n` +
    `/bulk — массовое создание\n` +
    `/status &lt;id&gt; &lt;статус&gt; — изменить статус\n` +
    `/payment &lt;id&gt; &lt;сумма&gt; — отметить оплату\n` +
    `/box &lt;order_id&gt; &lt;код&gt; &lt;адрес&gt; — создать коробку\n` +
    `/pickup &lt;box_id&gt; — выдать коробку\n` +
    `/stats — статистика\n` +
    `/users — список клиентов\n` +
    `/theme [название] — сменить тему ✨\n\n` +
    `🔗 <b>Парсинг постов:</b>\n` +
    `Просто пришли ссылку на пост:\n` +
    `<code>https://t.me/channel/123</code>`,
    {parse_mode: 'HTML'}
  );
});

// Обработка ссылок на посты
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;
  const admin = await getAdmin(msg.from.id);
  if (!admin) return;
  
  const linkMatch = msg.text.match(/https?:\/\/t\.me\/([a-zA-Z0-9_]+)\/(\d+)/);
  if (!linkMatch) return;
  
  const channelUsername = linkMatch[1];
  const messageId = parseInt(linkMatch[2]);
  
  let chatId;
  try {
    const chat = await bot.getChat('@' + channelUsername);
    chatId = chat.id;
  } catch(e) {
    return bot.sendMessage(msg.chat.id, '❌ Бот не добавлен в канал как админ');
  }
  
  let postText;
  try {
    const forwarded = await bot.forwardMessage(msg.chat.id, chatId, messageId);
    postText = forwarded.text || forwarded.caption || '';
    setTimeout(() => bot.deleteMessage(msg.chat.id, forwarded.message_id).catch(() => {}), 1000);
  } catch(e) {
    return bot.sendMessage(msg.chat.id, '❌ Не могу прочитать пост');
  }
  
  if (!postText) return bot.sendMessage(msg.chat.id, '❌ Пост пустой');
  
  const postType = parser.detectPostType(postText);
  
  if (postType === 'unknown') {
    return bot.sendMessage(msg.chat.id, '🔍 Не могу определить тип поста\n\nЧто это?', {
      reply_markup: {
        inline_keyboard: [
          [{text: '📝 Пост записи', callback_data: `preview:signup:${Buffer.from(postText).toString('base64')}`}],
          [{text: '📦 Пост с позициями', callback_data: `preview:signup_positions:${Buffer.from(postText).toString('base64')}`}],
          [{text: '💳 Пост оплаты', callback_data: `preview:payment:${Buffer.from(postText).toString('base64')}`}]
        ]
      }
    });
  }
  
  await showPreview(msg.chat.id, admin, postType, postText);
});

async function showPreview(chatId, admin, type, text) {
  if (type === 'signup_positions') {
    const parsed = parser.parsePositionsPost(text);
    let preview = `🔍 <b>Пост с позициями</b>\n\n`;
    preview += `📦 <b>${parsed.postTitle}</b>\n`;
    if (parsed.hashtag) preview += `🏷️ ${parsed.hashtag}\n`;
    preview += `\n💎 <b>Справочник цен:</b>\n`;
    Object.values(parsed.priceList).forEach(p => { preview += `  • ${p.name}: ${p.price.toLocaleString('ru')} ₽\n`; });
    preview += `\n📋 <b>Позиций: ${parsed.positions.length}</b>\n`;
    
    let totalEntries = 0;
    parsed.positions.forEach(p => { totalEntries += 1 + p.queue.length; });
    preview += ` <b>Всего записей: ${totalEntries}</b>\n\n`;
    
    parsed.positions.forEach(pos => {
      preview += `<b>Позиция ${pos.number}: ${pos.name}</b>\n`;
      preview += `  👑 Главный: @${pos.mainBuyer.username}`;
      if (pos.mainBuyer.deadline) preview += ` ⏰ ${pos.mainBuyer.deadline}`;
      preview += '\n';
      if (pos.queue.length > 0) {
        preview += `  🔢 Очередь (${pos.queue.length}):\n`;
        pos.queue.forEach(q => {
          preview += `    • ${q.member}: @${q.username}`;
          if (q.deadline) preview += ` ⏰ ${q.deadline}`;
          preview += '\n';
        });
      }
      preview += '\n';
    });
    
    preview += `✅ Создать заказы?`;
    
    bot.sendMessage(chatId, preview, {
      parse_mode: 'HTML',
      reply_markup: {inline_keyboard: [[
        {text: '✅ Создать все', callback_data: `confirm:signup_positions:${Buffer.from(text).toString('base64')}`},
        {text: '❌ Отмена', callback_data: 'cancel'}
      ]]}
    });
    return;
  }
  
  if (type === 'signup') {
    const parsed = parser.parseSignupPost(text);
    let preview = `🔍 <b>Пост записи</b>\n\n`;
    preview += `📦 <b>${parsed.postTitle}</b>\n`;
    preview += `💎 Цена: <b>${parsed.price?.toLocaleString('ru') || '—'} ₽</b>\n`;
    preview += `👥 Записей: <b>${parsed.entries.length}</b>\n\n`;
    
    const byQueue = {};
    parsed.entries.forEach(e => {
      if (!byQueue[e.queue]) byQueue[e.queue] = [];
      byQueue[e.queue].push(e);
    });
    
    Object.keys(byQueue).sort((a, b) => a - b).forEach(q => {
      preview += `<b>Очередь ${q}:</b>\n`;
      byQueue[q].forEach(e => {
        preview += `  • ${e.name}`;
        if (e.username) preview += ` (@${e.username})`;
        if (e.deadline) preview += `  ${e.deadline}`;
        preview += '\n';
      });
      preview += '\n';
    });
    
    preview += `✅ Создать заказы?`;
    
    bot.sendMessage(chatId, preview, {
      parse_mode: 'HTML',
      reply_markup: {inline_keyboard: [[
        {text: '✅ Создать', callback_data: `confirm:signup:${Buffer.from(text).toString('base64')}`},
        {text: '❌ Отмена', callback_data: 'cancel'}
      ]]}
    });
    return;
  }
  
  if (type === 'payment') {
    const parsed = parser.parsePaymentPost(text);
    let preview = `💳 <b>Пост оплаты</b>\n\n`;
    preview += `Записей: <b>${parsed.entries.length}</b>\n`;
    preview += `💎 Сумма: <b>${parsed.entries.reduce((s, e) => s + e.amount, 0).toLocaleString('ru')} ₽</b>\n\n`;
    parsed.entries.forEach(e => {
      preview += `• @${e.username} — ${e.amount.toLocaleString('ru')} ₽`;
      if (e.deadline) preview += ` ⏰ ${e.deadline}`;
      preview += '\n';
    });
    preview += `\n✅ Создать записи об оплате?`;
    
    bot.sendMessage(chatId, preview, {
      parse_mode: 'HTML',
      reply_markup: {inline_keyboard: [[
        {text: '✅ Создать', callback_data: `confirm:payment:${Buffer.from(text).toString('base64')}`},
        {text: '❌ Отмена', callback_data: 'cancel'}
      ]]}
    });
  }
}

bot.on('callback_query', async (query) => {
  const admin = await getAdmin(query.from.id);
  if (!admin) return bot.answerCallbackQuery(query.id, {text: '⛔ Нет прав'});
  
  if (query.data === 'cancel') {
    await bot.answerCallbackQuery(query.id, {text: ' Отменено'});
    return bot.editMessageText('❌ Отменено', {chat_id: query.message.chat.id, message_id: query.message.message_id});
  }
  
  if (query.data.startsWith('preview:')) {
    const [, type, textBase64] = query.data.split(':');
    const text = Buffer.from(textBase64, 'base64').toString('utf8');
    await showPreview(query.message.chat.id, admin, type, text);
    return bot.answerCallbackQuery(query.id);
  }
  
  if (query.data.startsWith('confirm:')) {
    const [, type, textBase64] = query.data.split(':');
    const text = Buffer.from(textBase64, 'base64').toString('utf8');
    await bot.answerCallbackQuery(query.id, {text: '⏳ Создаю...'});
    
    try {
      let result;
      
      if (type === 'signup_positions') {
        result = await parser.processPositionsPost(text, admin.name);
      } else if (type === 'signup') {
        result = await parser.processSignupPost(text, admin.name);
      } else if (type === 'payment') {
        result = await parser.processPaymentPost(text, admin.name);
      }
      
      if (result.success) {
        let msg = `✅ <b>Создано: ${result.created}</b>\n`;
        if (result.skipped > 0) msg += `️ <b>Пропущено: ${result.skipped}</b>\n`;
        msg += '\n';
        
        if (result.orders) {
          const byPosition = {};
          result.orders.forEach(o => {
            const key = o.positionNumber || 'main';
            if (!byPosition[key]) byPosition[key] = [];
            byPosition[key].push(o);
          });
          
          Object.keys(byPosition).sort((a, b) => a - b).forEach(posNum => {
            msg += `<b>Позиция ${posNum}:</b>\n`;
            byPosition[posNum].forEach(o => {
              if (o.skipped) {
                msg += `  ⏭️ ${o.name || o.username} — ${o.reason}\n`;
              } else {
                const icon = o.role === 'main' ? '👑' : '🔢';
                msg += `  ${icon} <code>${o.orderId}</code> @${o.username}`;
                if (o.deadline) msg += ` ⏰ ${o.deadline}`;
                msg += ` • 💎 ${o.total.toLocaleString('ru')} ₽\n`;
              }
            });
          });
        }
        
        if (result.results) {
          result.results.forEach(r => {
            if (r.skipped) {
              msg += `⏭️ @${r.username} — ${r.reason}\n`;
            } else {
              msg += `🦪 <code>${r.orderId}</code> → @${r.username} • 💎 ${r.amount.toLocaleString('ru')} ₽`;
              if (r.deadline) msg += ` ⏰ ${r.deadline}`;
              msg += '\n';
            }
          });
        }
        
        if (result.errors?.length) {
          msg += `\n⚠️ <b>Ошибки:</b>\n`;
          result.errors.slice(0, 10).forEach(e => { msg += `  • ${e.name || e.username}: ${e.error}\n`; });
        }
        
        await bot.editMessageText(msg, {chat_id: query.message.chat.id, message_id: query.message.message_id, parse_mode: 'HTML'});
      } else {
        await bot.editMessageText('❌ ' + result.error, {chat_id: query.message.chat.id, message_id: query.message.message_id});
      }
    } catch(err) {
      await bot.editMessageText('❌ Ошибка: ' + err.message, {chat_id: query.message.chat.id, message_id: query.message.message_id});
    }
  }
});

// /theme
bot.onText(/\/theme(?:\s+(.+))?/, async (msg, match) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'theme')) return bot.sendMessage(msg.chat.id, ' Только для админов');
  
  const themeName = match[1]?.trim();
  
  const availableThemes = [
    {id: 'pirate', name: '⚓ Pirate Default'},
    {id: 'newjeans_ditto', name: '💗 NewJeans — Ditto'},
    {id: 'newjeans_supershy', name: '💕 NewJeans — Super Shy'},
    {id: 'bts_butter', name: '🧈 BTS — Butter'},
    {id: 'aespa_supernova', name: '✨ aespa — Supernova'},
    {id: 'aespa_drama', name: '🔥 aespa — Drama'},
    {id: 'seventeen_godofmusic', name: '👑 SEVENTEEN — God of Music'},
    {id: 'straykids_rockstar', name: '🎸 Stray Kids — Rock-Star'},
    {id: 'lesserafim_easy', name: '💙 LE SSERAFIM — Easy'},
    {id: 'enhypen_romance', name: ' ENHYPEN — Romance'},
    {id: 'ive_baddie', name: '💖 IVE — Baddie'},
    {id: 'twice_withyouth', name: ' TWICE — With YOU-th'},
    {id: 'blackpink_pinkvenom', name: '🖤 BLACKPINK — Pink Venom'}
  ];
  
  if (!themeName) {
    const currentRes = await apiGet('getTheme');
    const currentTheme = currentRes.theme || 'pirate';
    let text = `🎨 <b>Текущая тема:</b> ${currentTheme}\n\n<b>Доступные темы:</b>\n`;
    availableThemes.forEach(t => {
      const marker = t.id === currentTheme ? ' ✅' : '';
      text += `<code>/theme ${t.id}</code> — ${t.name}${marker}\n`;
    });
    bot.sendMessage(msg.chat.id, text, {parse_mode: 'HTML'});
    return;
  }
  
  const validTheme = availableThemes.find(t => t.id === themeName);
  if (!validTheme) return bot.sendMessage(msg.chat.id, `❌ Тема "${themeName}" не найдена\n\nИспользуй /theme без аргументов для списка`);
  
  try {
    await apiPost({action: 'setTheme', theme: themeName});
    bot.sendMessage(msg.chat.id, `🎨 <b>Тема изменена!</b>\n\n${validTheme.name}\n\nВсе пользователи увидят новую палитру `, {parse_mode: 'HTML'});
  } catch(err) {
    bot.sendMessage(msg.chat.id, '❌ Ошибка: ' + err.message);
  }
});

// /orders
bot.onText(/\/orders/, async (msg) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin) return;
  try {
    const orders = await apiGet('getOrders', {userId: 'all'});
    const active = orders.filter(o => !['delivered'].includes(o.status));
    if (!active.length) return bot.sendMessage(msg.chat.id, '✅ Нет активных заказов');
    const text = `🌊 <b>Активные заказы (${active.length})</b>\n\n` + 
      active.slice(0, 15).map(o => 
        `🦪 <b>${o.order_id}</b>\n├ ${STATUS_EMOJI[o.status]} ${STATUS_LABELS[o.status]}\n├ 💎 ${Number(o.total).toLocaleString('ru')} ₽\n└  ${o.telegram_id}`
      ).join('\n\n');
    bot.sendMessage(msg.chat.id, text, {parse_mode: 'HTML'});
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /order ID
bot.onText(/\/order (.+)/, async (msg, match) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin) return;
  const orderId = match[1].trim();
  try {
    const orders = await apiGet('getOrders', {userId: 'all'});
    const order = orders.find(o => String(o.order_id) === orderId);
    if (!order) return bot.sendMessage(msg.chat.id, '❌ Заказ не найден');
    const boxes = await apiGet('getBoxes', {userId: order.telegram_id});
    const box = boxes.find(b => String(b.order_id) === orderId);
    let text = ` <b>Заказ ${order.order_id}</b>\n\n`;
    text += `👤 Клиент: ${order.telegram_id}\n`;
    text += `${STATUS_EMOJI[order.status]} Статус: <b>${STATUS_LABELS[order.status]}</b>\n`;
    text += ` Сумма: ${Number(order.total).toLocaleString('ru')} ₽\n`;
    text += `📅 Создан: ${order.created_at}\n`;
    text += `📝 Создал: ${order.created_by}\n`;
    if (order.deadline) text += `⏰ Дедлайн: ${order.deadline}\n`;
    if (order.queue) text += `🔢 Очередь: ${order.queue}\n`;
    text += `\n<b>Состав:</b>\n${order.items}\n`;
    if (box) {
      text += `\n📦 <b>Коробка:</b> ${box.box_id}\n`;
      text += `🔑 Код: <code>${box.pickup_code}</code>\n`;
      text += `📍 ${box.pickup_location}`;
    }
    bot.sendMessage(msg.chat.id, text, {parse_mode: 'HTML'});
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /create
bot.onText(/\/create/, async (msg) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'create')) return bot.sendMessage(msg.chat.id, '⛔ Нет прав');
  bot.sendMessage(msg.chat.id, '📝 <b>Создание заказа</b>\n\nФормат: <code>telegram_id | товар1; товар2 | сумма</code>\n\nПример: <code>123456789 | NewJeans Ditto PB | 8450</code>', {parse_mode: 'HTML'});
  bot.once('message', async (m) => {
    if (m.from.id !== msg.from.id) return;
    if (m.text === '/cancel') return bot.sendMessage(m.chat.id, '❌ Отменено');
    const parts = m.text.split('|').map(s => s.trim());
    if (parts.length !== 3) return bot.sendMessage(m.chat.id, ' Неверный формат');
    const [telegram_id, itemsStr, total] = parts;
    try {
      const result = await apiPost({action: 'createOrder', telegram_id, items: itemsStr.split(';').map(s => s.trim()), total: Number(total), admin: admin.name});
      bot.sendMessage(m.chat.id, `✅ Заказ создан: <b>${result.orderId}</b>\n💎 ${Number(total).toLocaleString('ru')} ₽`, {parse_mode: 'HTML'});
    } catch(err) { bot.sendMessage(m.chat.id, '❌ ' + err.message); }
  });
});

// /bulk
bot.onText(/\/bulk/, async (msg) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'create')) return bot.sendMessage(msg.chat.id, ' Нет прав');
  bot.sendMessage(msg.chat.id, '📦 <b>Массовое создание</b>\n\nФормат:\n<code>Товар1; Товар2 | сумма\nid1, id2, id3</code>\n\nПример:\n<code>NewJeans Ditto PB | 5200\n123456789, 987654321</code>', {parse_mode: 'HTML'});
  bot.once('message', async (m) => {
    if (m.from.id !== msg.from.id) return;
    if (m.text === '/cancel') return bot.sendMessage(m.chat.id, '❌ Отменено');
    const lines = m.text.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return bot.sendMessage(m.chat.id, '❌ Неверный формат');
    const [itemsStr, totalStr] = lines[0].split('|').map(s => s.trim());
    const items = itemsStr.split(';').map(s => s.trim());
    const total = Number(totalStr);
    const userIds = lines[1].split(',').map(s => s.trim()).filter(Boolean);
    try {
      const result = await apiPost({action: 'createBulkOrders', userIds, items, total, admin: admin.name});
      let text = `✅ Создано заказов: <b>${result.created}</b>\n\n`;
      result.orders.forEach(o => { text += `🦪 <code>${o.orderId}</code> → 👤 ${o.userId}\n`; });
      bot.sendMessage(m.chat.id, text, {parse_mode: 'HTML'});
    } catch(err) { bot.sendMessage(m.chat.id, '❌ ' + err.message); }
  });
});

// /status ID STATUS
bot.onText(/\/status (.+)/, async (msg, match) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'status')) return bot.sendMessage(msg.chat.id, '⛔ Нет прав');
  const [orderId, status] = match[1].trim().split(/\s+/);
  const valid = ['pending', 'paid', 'shipped', 'ready', 'delivered'];
  if (!valid.includes(status)) return bot.sendMessage(msg.chat.id, `❌ Допустимые: ${valid.join(', ')}`);
  try {
    await apiPost({action: 'updateOrderStatus', orderId, status});
    bot.sendMessage(msg.chat.id, `✅ ${orderId} → ${STATUS_EMOJI[status]} <b>${STATUS_LABELS[status]}</b>`, {parse_mode: 'HTML'});
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /payment ID AMOUNT
bot.onText(/\/payment (.+)/, async (msg, match) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'payment')) return bot.sendMessage(msg.chat.id, ' Нет прав');
  const [orderId, amount] = match[1].trim().split(/\s+/);
  try {
    const result = await apiPost({action: 'createPayment', orderId, amount: Number(amount), admin: admin.name});
    bot.sendMessage(msg.chat.id, `💎 Оплата: ${result.paymentId}\n🦪 ${orderId} • ${Number(amount).toLocaleString('ru')} ₽`);
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /box
bot.onText(/\/box (.+)/, async (msg, match) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'box')) return bot.sendMessage(msg.chat.id, '⛔ Нет прав');
  const parts = match[1].split('|').map(s => s.trim());
  if (parts.length < 3) return bot.sendMessage(msg.chat.id, '❌ Формат: <code>/box ORDER_ID | КОД | АДРЕС</code>', {parse_mode: 'HTML'});
  const [orderId, pickupCode, pickupLocation] = parts;
  try {
    const result = await apiPost({action: 'createBox', orderId, pickupCode, pickupLocation});
    bot.sendMessage(msg.chat.id, ` ${result.boxId}\n🦪 ${orderId}\n🔑 <code>${pickupCode}</code>\n📍 ${pickupLocation}`, {parse_mode: 'HTML'});
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /pickup BOX_ID
bot.onText(/\/pickup (.+)/, async (msg, match) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'pickup')) return bot.sendMessage(msg.chat.id, '⛔ Нет прав');
  try {
    await apiPost({action: 'markBoxPicked', boxId: match[1].trim()});
    bot.sendMessage(msg.chat.id, `✅ Коробка ${match[1].trim()} выдана`);
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /stats
bot.onText(/\/stats/, async (msg) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin) return;
  try {
    const stats = await apiGet('getStats', {userId: 'all'});
    bot.sendMessage(msg.chat.id, 
      `📊 <b>BLACK PEARL — Статистика</b>\n\n` +
      `🦪 Всего заказов: <b>${stats.totalOrders}</b>\n` +
      `💎 Выручка: <b>${stats.totalRevenue.toLocaleString('ru')} ₽</b>\n\n` +
      ` Сегодня:\n  ├ Заказов: ${stats.todayOrders}\n  └ Выручка: ${stats.todayRevenue.toLocaleString('ru')} ₽\n\n` +
      `📋 Статусы:\n  ⏳ Ожидают: ${stats.pending}\n  💎 Оплачены: ${stats.paid}\n  🌊 В пути: ${stats.shipped}\n  📦 Готовы: ${stats.ready}\n  ✅ Получены: ${stats.delivered}\n\n` +
      `📦 Коробок ждут: ${stats.boxesReady}`,
      {parse_mode: 'HTML'}
    );
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

// /users
bot.onText(/\/users/, async (msg) => {
  const admin = await getAdmin(msg.from.id);
  if (!admin || !canDo(admin.role, 'users')) return bot.sendMessage(msg.chat.id, '⛔ Нет прав');
  try {
    const orders = await apiGet('getOrders', {userId: 'all'});
    const clients = {};
    orders.forEach(o => {
      if (!clients[o.telegram_id]) clients[o.telegram_id] = {count: 0, total: 0};
      clients[o.telegram_id].count++;
      clients[o.telegram_id].total += Number(o.total);
    });
    const list = Object.entries(clients).sort((a, b) => b[1].total - a[1].total).slice(0, 15);
    const text = `👥 <b>Топ клиентов</b>\n\n` + 
      list.map(([id, data], i) => `${i + 1}. <code>${id}</code>\n   └  ${data.count} • 💎 ${data.total.toLocaleString('ru')} ₽`).join('\n\n');
    bot.sendMessage(msg.chat.id, text, {parse_mode: 'HTML'});
  } catch(err) { bot.sendMessage(msg.chat.id, '❌ ' + err.message); }
});

console.log('🖤 BLACK PEARL Admin Bot запущен');