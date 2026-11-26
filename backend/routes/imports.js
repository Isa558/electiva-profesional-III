const express = require('express');
const pool = require('../db/pool');
const { saveImport } = require('../services/importService');
const { createQuestionTemplate } = require('../services/templateService');

const router = express.Router();

router.get('/template', async (request, response) => {
  try {
    const buffer = await createQuestionTemplate();
    response.type('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    response.attachment('plantilla_banco_preguntas.xlsx');
    response.send(Buffer.from(buffer));
  } catch (error) {
    console.error('Excel template generation failed:', error.message);
    response.status(500).json({ error: 'No se pudo generar la plantilla Excel.' });
  }
});

router.get('/', async (request, response) => {
  try {
    const imports = await pool.query(`
      SELECT id, nombre_archivo AS fileName, fecha_importacion AS date,
             total_filas AS total, total_exitosas AS successful, total_fallidas AS failed
      FROM importaciones
      ORDER BY id DESC
      LIMIT 100
    `);
    response.json(imports);
  } catch (error) {
    console.error('Import history failed:', error.message);
    response.status(500).json({ error: 'No se pudo consultar el historial en MariaDB.' });
  }
});

router.post('/', async (request, response) => {
  const { fileName, rows } = request.body || {};
  if (typeof fileName !== 'string' || !fileName.trim() || fileName.length > 255) {
    return response.status(400).json({ error: 'El nombre del archivo no es válido.' });
  }
  if (!Array.isArray(rows) || rows.length === 0 || rows.length > 5000) {
    return response.status(400).json({ error: 'La importación debe contener entre 1 y 5000 filas.' });
  }

  try {
    const result = await saveImport(fileName.trim(), rows);
    response.status(201).json(result);
  } catch (error) {
    console.error('Question import failed:', error.message);
    response.status(500).json({
      error: 'No se pudo guardar la importación. Comprueba la conexión y el esquema SQL.',
    });
  }
});

module.exports = router;