const fetch = require('node-fetch');
const API = process.env.APPS_SCRIPT_URL;

const PRICE_REGEX = /^(.+?)\s+(?:по\s+)?(\d[\d\s]*)\s*(₽|руб|rub|сум)/gim;
const POSITION_REGEX = /^(\d+)\.\s+(.+?)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$/gim;
const QUEUE_MEMBER_REGEX = /^([а-яА-Яa-zA-ZёЁ]+)\s*:\s*@?([a-zA-Z0-9_]+)?(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$/gim;
const OLD_PRICE_REGEX = /по\s+(\d[\d\s]*)\s*(₽|руб|rub|сум)/i;
const PAY_REGEX = /@([a-zA-Z0-9_]+)\s*[-—]\s*([\d\s]+)\s*(₽|руб|rub|сум)?(?:\s*\/\/\s*(\d{2}\.\d{2}))?/g;

function detectPostType(text) {
  if (/@[\w]+\s*[-—]\s*\d+/.test(text) && !/^\d+\.\s+.+@/m.test(text)) return 'payment';
  if (/^\d+\.\s+.+?@/m.test(text)) return 'signup_positions';
  if ((/очередь/i.test(text) || /по\s+\d+\s*₽/i.test(text)) && /@[\w]+/.test(text)) return 'signup';
  return 'unknown';
}

function parsePositionsPost(text) {
  const result = {postTitle: null, hashtag: null, priceList: {}, positions: []};
  const lines = text.split('\n').map(l => l.trim());
  result.postTitle = lines.find(l => l.length > 0) || 'Без названия';
  
  const hashtagMatch = text.match(/#([a-zA-Z0-9_а-яА-Я]+)/);
  if (hashtagMatch) result.hashtag = '#' + hashtagMatch[1];
  
  const firstPositionIdx = lines.findIndex(l => /^\d+\.\s+/.test(l));
  const headerLines = lines.slice(0, firstPositionIdx > 0 ? firstPositionIdx : lines.length);
  
  headerLines.forEach(line => {
    const match = line.match(/^(.+?)\s+(?:по\s+)?(\d[\d\s]*)\s*(₽|руб|rub|сум)/i);
    if (match) {
      const name = match[1].trim().replace(/[!,]$/,'').trim();
      const price = parseInt(match[2].replace(/\s/g, ''));
      if (name && price) result.priceList[name.toLowerCase()] = {name: match[1].trim(), price};
    }
  });
  
  const blocks = splitIntoPositionBlocks(text);
  blocks.forEach(block => {
    const position = parsePositionBlock(block);
    if (position) result.positions.push(position);
  });
  
  return result;
}

function splitIntoPositionBlocks(text) {
  const blocks = [];
  const lines = text.split('\n');
  let currentBlock = null;
  
  lines.forEach(line => {
    const posMatch = line.match(/^(\d+)\.\s+(.+?)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$/);
    if (posMatch) {
      if (currentBlock) blocks.push(currentBlock);
      currentBlock = {
        header: line, queueLines: [],
        positionNum: parseInt(posMatch[1]),
        positionName: posMatch[2].trim(),
        mainBuyer: posMatch[3],
        mainDeadline: posMatch[4] || null
      };
    } else if (currentBlock) {
      currentBlock.queueLines.push(line);
    }
  });
  
  if (currentBlock) blocks.push(currentBlock);
  return blocks;
}

function parsePositionBlock(block) {
  const position = {
    number: block.positionNum,
    name: block.positionName,
    mainBuyer: {username: block.mainBuyer, deadline: block.mainDeadline},
    queue: []
  };
  
  block.queueLines.forEach(line => {
    const clean = line.trim();
    if (!clean || /^очередь/i.test(clean)) return;
    
    const match = clean.match(/^([а-яА-Яa-zA-ZёЁ]+)\s*:\s*@?([a-zA-Z0-9_]+)?(?:\s*\/\/\s*(\d{2}\.\d{2}))?\s*$/);
    if (match) {
      const username = match[2] || null;
      if (!username) return;
      position.queue.push({member: match[1], username, deadline: match[3] || null});
    }
  });
  
  return position;
}

function parseSignupPost(text) {
  const result = {postTitle: null, price: null, entries: []};
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  result.postTitle = lines[0];
  
  const priceMatch = text.match(OLD_PRICE_REGEX);
  if (priceMatch) result.price = parseInt(priceMatch[1].replace(/\s/g, ''));
  
  const queues = splitByQueues(text);
  queues.forEach(q => parseQueueEntries(q.text, q.number, result.entries));
  
  return result;
}

function splitByQueues(text) {
  const queues = [];
  const lines = text.split('\n');
  let currentQueue = null;
  let currentText = [];
  
  lines.forEach(line => {
    const m = line.match(/^(\d+)\s+очередь/i);
    if (m) {
      if (currentQueue !== null && currentText.length > 0) queues.push({number: currentQueue, text: currentText.join('\n')});
      currentQueue = parseInt(m[1]);
      currentText = [];
    } else if (currentQueue !== null) {
      currentText.push(line);
    } else {
      if (currentQueue === null) currentQueue = 1;
      currentText.push(line);
    }
  });
  
  if (currentQueue !== null && currentText.length > 0) queues.push({number: currentQueue, text: currentText.join('\n')});
  return queues;
}

function parseQueueEntries(queueText, queueNumber, entries) {
  queueText.split('\n').map(l => l.trim()).filter(Boolean).forEach(line => {
    if (/^\d+\s+очередь/i.test(line)) return;
    const m = line.match(/^([А-Яа-яA-Za-z]+)\s+@([a-zA-Z0-9_]+)(?:\s*\/\/\s*(\d{2}\.\d{2}))?/);
    if (m) {
      entries.push({name: m[1], username: m[2], deadline: m[3] || null, queue: queueNumber});
      return;
    }
    const m2 = line.match(/^([А-Яа-яA-Za-z]+)\s*$/);
    if (m2) entries.push({name: m2[1], username: null, deadline: null, queue: queueNumber});
  });
}

function parsePaymentPost(text) {
  const entries = [];
  let match;
  while ((match = PAY_REGEX.exec(text)) !== null) {
    entries.push({username: match[1], amount: parseInt(match[2].replace(/\s/g, '')), deadline: match[4] || null});
  }
  return {entries};
}

async function findUserByUsername(username) {
  try {
    const res = await fetch(`${API}?action=findUser&username=${encodeURIComponent(username)}`);
    const data = await res.json();
    return data && data.telegram_id ? data.telegram_id : null;
  } catch(e) { return null; }
}

function findPriceForPosition(positionName, priceList) {
  const exact = priceList[positionName.toLowerCase()];
  if (exact) return exact.price;
  for (const key in priceList) {
    if (positionName.toLowerCase().includes(key) || key.includes(positionName.toLowerCase())) return priceList[key].price;
  }
  return null;
}

async function processPositionsPost(text, adminName) {
  const parsed = parsePositionsPost(text);
  if (!parsed.positions.length) return {success: false, error: 'Не найдено ни одной позиции'};
  
  const allEntries = [];
  parsed.positions.forEach(pos => {
    const price = findPriceForPosition(pos.name, parsed.priceList);
    allEntries.push({username: pos.mainBuyer.username, name: pos.mainBuyer.username, positionNumber: pos.number, positionName: pos.name, role: 'main', deadline: pos.mainBuyer.deadline, price});
    pos.queue.forEach(q => {
      allEntries.push({username: q.username, name: q.member, positionNumber: pos.number, positionName: pos.name, role: 'queue', deadline: q.deadline, price});
    });
  });
  
  for (const entry of allEntries) {
    if (entry.username) entry.telegramId = await findUserByUsername(entry.username);
  }
  
  const res = await fetch(API, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'createOrdersFromPositions', postTitle: parsed.postTitle, hashtag: parsed.hashtag, priceList: parsed.priceList, admin: adminName, entries: allEntries})
  });
  return res.json();
}

async function processSignupPost(text, adminName) {
  const parsed = parseSignupPost(text);
  if (!parsed.postTitle) return {success: false, error: 'Не найдено название'};
  if (!parsed.price) return {success: false, error: 'Не найдена цена (формат: "по XXX₽")'};
  if (!parsed.entries.length) return {success: false, error: 'Нет записей'};
  
  for (const entry of parsed.entries) {
    if (entry.username) entry.telegramId = await findUserByUsername(entry.username);
  }
  
  const res = await fetch(API, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'createOrdersFromPost', postTitle: parsed.postTitle, price: parsed.price, admin: adminName, entries: parsed.entries})
  });
  return res.json();
}

async function processPaymentPost(text, adminName) {
  const parsed = parsePaymentPost(text);
  if (!parsed.entries.length) return {success: false, error: 'Нет записей об оплате'};
  for (const entry of parsed.entries) entry.telegramId = await findUserByUsername(entry.username);
  
  const res = await fetch(API, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'createPaymentsFromPost', admin: adminName, entries: parsed.entries})
  });
  return res.json();
}

module.exports = {
  detectPostType, parsePositionsPost, parseSignupPost, parsePaymentPost,
  processPositionsPost, processSignupPost, processPaymentPost
};