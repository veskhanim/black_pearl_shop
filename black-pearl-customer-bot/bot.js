require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const fetch = require('node-fetch');

const bot = new TelegramBot(process.env.BOT_TOKEN, {polling: true});
const API = process.env.APPS_SCRIPT_URL;
const MINI_APP = process.env.MINI_APP_URL;

bot.onText(/\/start/, async (msg) => {
  const user = msg.from;
  try {
    await fetch(API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'upsertUser', telegram_id: user.id, username: user.username || '', first_name: user.first_name || '', last_name: user.last_name || ''})
    });
  } catch(e) {}
  
  bot.sendMessage(msg.chat.id, 
    ` <b>Добро пожаловать в BLACK PEARL</b>\n\n` +
    `✦ K-pop мерч с душой моря ✦\n\n` +
    `🦪 Альбомы и фотокарточки\n` +
    `💎 Лайтстики и мерч\n` +
    `🌊 Лимитки и эксклюзивы`,
    {
      parse_mode: 'HTML',
      reply_markup: {
        inline_keyboard: [
          [{text: '🖤 Открыть магазин', web_app: {url: MINI_APP}}],
          [{text: '✦ Написать менеджеру', url: 'https://t.me/blackpearl_manager'}]
        ]
      }
    }
  );
});

bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;
  const userId = msg.from.id;
  
  if (msg.text === '🖤 Открыть магазин') {
    return bot.sendMessage(msg.chat.id, '🌊 BLACK PEARL', {
      reply_markup: {inline_keyboard: [[{text: '✦ Открыть', web_app: {url: MINI_APP}}]]}
    });
  }
  
  if (msg.text === '🦪 Мои заказы') {
    try {
      const res = await fetch(`${API}?action=getOrders&userId=${userId}`);
      const orders = await res.json();
      if (!orders.length) {
        return bot.sendMessage(msg.chat.id, ' У тебя пока нет заказов ✨', {
          reply_markup: {inline_keyboard: [[{text: '🖤 В магазин', web_app: {url: MINI_APP}}]]}
        });
      }
      const emoji = {pending: '', paid: '💎', shipped: '', ready: '📦', delivered: '✅'};
      const text = ` <b>Твои заказы (${orders.length})</b>\n\n` +
        orders.slice(0, 5).map(o => {
          let line = `<b>${o.order_id}</b>\n${emoji[o.status]} ${o.status} •  ${Number(o.total).toLocaleString('ru')} ₽`;
          if (o.deadline) line += `\n⏰ Дедлайн: ${o.deadline}`;
          return line;
        }).join('\n\n');
      bot.sendMessage(msg.chat.id, text, {
        parse_mode: 'HTML',
        reply_markup: {inline_keyboard: [[{text: '✦ Подробно', web_app: {url: MINI_APP}}]]}
      });
    } catch(e) { bot.sendMessage(msg.chat.id, '❌ Ошибка'); }
    return;
  }
  
  if (msg.text === '📦 Коробки') {
    try {
      const res = await fetch(`${API}?action=getBoxes&userId=${userId}`);
      const boxes = await res.json();
      const ready = boxes.filter(b => b.status === 'ready');
      if (!ready.length) return bot.sendMessage(msg.chat.id, '📦 Пока нет коробок к получению ✦');
      const text = `📦 <b>Готовы к получению (${ready.length})</b>\n\n` +
        ready.map(b => `<b>${b.box_id}</b>\n🔑 Код: <code>${b.pickup_code}</code>\n📍 ${b.pickup_location}\n📅 С ${b.ready_date}`).join('\n\n');
      bot.sendMessage(msg.chat.id, text, {parse_mode: 'HTML'});
    } catch(e) { bot.sendMessage(msg.chat.id, '❌ Ошибка'); }
    return;
  }
  
  if (msg.text === '💳 Оплаты') {
    try {
      const res = await fetch(`${API}?action=getPayments&userId=${userId}`);
      const payments = await res.json();
      if (!payments.length) return bot.sendMessage(msg.chat.id, '💳 Пока нет оплат');
      const text = `💳 <b>История оплат</b>\n\n` +
        payments.map(p => `<b>${p.payment_id}</b>\n🦪 ${p.order_id}\n💎 ${Number(p.amount).toLocaleString('ru')} ₽ • ${p.method}\n📅 ${p.paid_at}` + (p.deadline ? `\n⏰ ${p.deadline}` : '')).join('\n\n');
      bot.sendMessage(msg.chat.id, text, {parse_mode: 'HTML'});
    } catch(e) { bot.sendMessage(msg.chat.id, '❌ Ошибка'); }
  }
});

console.log('🖤 BLACK PEARL Customer Bot запущен');