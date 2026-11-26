const express = require('express');
const pool = require('../db/pool');

const router = express.Router();

router.get('/', async (request, response) => {
  let connection;
  try {
    connection = await pool.getConnection();
    await connection.ping();
    response.json({ connected: true, database: process.env.DB_NAME || 'test' });
  } catch (error) {
    console.error('MariaDB health check failed:', error.message);
    response.status(503).json({
      connected: false,
      message: 'No se pudo conectar a MariaDB. Revisa la configuración local de .env.',
    });
  } finally {
    connection?.release();
  }
});

module.exports = router;