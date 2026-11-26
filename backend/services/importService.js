const pool = require('../db/pool');
const { validateQuestionRow } = require('../../shared/importer');

async function saveImport(fileName, rows) {
  const preparedRows = rows.map((row, index) => {
    const rowNumber = Number.isInteger(row?.rowNumber) && row.rowNumber > 1 ? row.rowNumber : index + 2;
    const values = row?.values && typeof row.values === 'object' ? row.values : {};
    return validateQuestionRow(values, rowNumber);
  });
  const validRows = preparedRows.filter((row) => row.data);
  const failedRows = preparedRows.filter((row) => !row.data);
  const connection = await pool.getConnection();

  try {
    await connection.beginTransaction();
    const importResult = await connection.query(`
      INSERT INTO importaciones
        (cuestionario_id, nombre_archivo, fecha_importacion, total_filas, total_exitosas, total_fallidas)
      VALUES (NULL, ?, NOW(), ?, ?, ?)
    `, [fileName, preparedRows.length, validRows.length, failedRows.length]);
    const importId = importResult.insertId;

    for (const row of validRows) {
      const question = row.data;
      const categoryResult = await connection.query(`
        INSERT INTO categorias (nombre, activo)
        VALUES (?, TRUE)
        ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id), activo = TRUE
      `, [question.category]);
      const questionResult = await connection.query(`
        INSERT INTO preguntas
          (categoria_id, tipo, texto_base, enunciado, retroalimentacion, puntaje_defecto, activo)
        VALUES (?, ?, ?, ?, ?, ?, TRUE)
      `, [categoryResult.insertId, question.type, question.baseText, question.stem, question.feedback, question.defaultScore]);

      for (const option of question.options) {
        await connection.query(`
          INSERT INTO opciones_respuesta (pregunta_id, letra, texto, es_correcta)
          VALUES (?, ?, ?, ?)
        `, [questionResult.insertId, option.letter, option.text, option.letter === question.correctLetter]);
      }
    }

    for (const row of failedRows) {
      await connection.query(`
        INSERT INTO importacion_errores (importacion_id, fila_excel, campo_con_error, mensaje_error)
        VALUES (?, ?, ?, ?)
      `, [importId, row.rowNumber, 'validación', row.errors.join(' ')]);
    }

    await connection.commit();
    return {
      importId,
      total: preparedRows.length,
      successful: validRows.length,
      failed: failedRows.length,
    };
  } catch (error) {
    try {
      await connection.rollback();
    } catch (rollbackError) {
      console.error('Import rollback failed:', rollbackError.message);
    }
    throw error;
  } finally {
    connection.release();
  }
}

module.exports = { saveImport };