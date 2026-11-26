const path = require('node:path');
require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

const app = require('./app');
const pool = require('./db/pool');

const port = Number(process.env.PORT || 4173);
const server = app.listen(port, '127.0.0.1', () => {
  console.log(`Aulabase disponible en http://127.0.0.1:${port}`);
});

async function shutdown() {
  server.close(async () => {
    await pool.end();
    process.exit(0);
  });
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);