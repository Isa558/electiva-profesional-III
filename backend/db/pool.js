const mariadb = require('mariadb');

module.exports = mariadb.createPool({
  host: process.env.DB_HOST || '127.0.0.1',
  port: Number(process.env.DB_PORT || 3307),
  database: process.env.DB_NAME || 'test',
  user: process.env.DB_USER || 'root',
  password: process.env.DB_PASSWORD || '',
  connectionLimit: 8,
  decimalAsNumber: true,
  bigIntAsNumber: true,
  insertIdAsNumber: true,
  charset: 'utf8mb4',
});