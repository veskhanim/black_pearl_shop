// Запуск обоих ботов
require('dotenv').config();
const { spawn } = require('child_process');

console.log('🖤 BLACK PEARL — запуск всех сервисов...');

// Админ-бот
const adminBot = spawn('node', ['admin-bot/bot.js'], {
  stdio: 'inherit',
  env: { ...process.env }
});

adminBot.on('error', (err) => {
  console.error('❌ Ошибка запуска admin-bot:', err.message);
});

adminBot.on('exit', (code) => {
  console.log(`⚠️  admin-bot завершился с кодом ${code}`);
});

// Клиентский бот
const customerBot = spawn('node', ['customer-bot/bot.js'], {
  stdio: 'inherit',
  env: { ...process.env }
});

customerBot.on('error', (err) => {
  console.error('❌ Ошибка запуска customer-bot:', err.message);
});

customerBot.on('exit', (code) => {
  console.log(`⚠️  customer-bot завершился с кодом ${code}`);
});

// Корректное завершение
process.on('SIGTERM', () => {
  console.log('🛑 SIGTERM — завершение...');
  adminBot.kill();
  customerBot.kill();
});

process.on('SIGINT', () => {
  console.log(' SIGINT — завершение...');
  adminBot.kill();
  customerBot.kill();
});
