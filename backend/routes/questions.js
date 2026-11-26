const express = require('express');
const pool = require('../db/pool');

const router = express.Router();

router.get('/', async (request, response) => {
  try {
    const questions = await pool.query(`
      SELECT p.id, c.nombre AS category, p.tipo AS type, p.texto_base AS baseText,
             p.enunciado AS stem, p.retroalimentacion AS feedback,
             p.puntaje_defecto AS defaultScore
      FROM preguntas p
      INNER JOIN categorias c ON c.id = p.categoria_id
      WHERE p.activo = TRUE
      ORDER BY p.id DESC
    `);
    if (questions.length === 0) return response.json([]);

    const questionIds = questions.map((question) => question.id);
    const placeholders = questionIds.map(() => '?').join(', ');
    const options = await pool.query(`
      SELECT pregunta_id AS questionId, letra AS letter, texto AS text, es_correcta AS isCorrect
      FROM opciones_respuesta
      WHERE pregunta_id IN (${placeholders})
      ORDER BY pregunta_id, letra
    `, questionIds);
    const optionsByQuestion = new Map();
    options.forEach((option) => {
      const grouped = optionsByQuestion.get(option.questionId) || [];
      grouped.push({ letter: option.letter, text: option.text, isCorrect: Boolean(option.isCorrect) });
      optionsByQuestion.set(option.questionId, grouped);
    });
    response.json(questions.map((question) => ({
      ...question,
      defaultScore: Number(question.defaultScore),
      options: optionsByQuestion.get(question.id) || [],
    })));
  } catch (error) {
    console.error('Question list failed:', error.message);
    response.status(500).json({ error: 'No se pudieron consultar las preguntas en MariaDB.' });
  }
});

module.exports = router;