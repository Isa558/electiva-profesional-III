const test = require('node:test');
const assert = require('node:assert/strict');
const { REQUIRED_HEADERS, validateHeaders, validateQuestionRow } = require('../shared/importer');

test('accepts the complete template header set', () => {
  assert.equal(validateHeaders(REQUIRED_HEADERS).valid, true);
});

test('reports missing template headers', () => {
  const result = validateHeaders(['categoria', 'enunciado']);
  assert.equal(result.valid, false);
  assert.ok(result.missing.includes('correcta'));
});

test('accepts a valid multiple-choice question', () => {
  const result = validateQuestionRow({
    categoria: 'Matemáticas',
    tipo: 'MULTIPLE',
    enunciado: '¿Cuánto es 2 + 2?',
    puntaje_defecto: '1',
    opcion_a: '3',
    opcion_b: '4',
    opcion_c: '5',
    opcion_d: '',
    correcta: 'B',
  }, 2);
  assert.deepEqual(result.errors, []);
  assert.equal(result.data.correctLetter, 'B');
  assert.equal(result.data.options.length, 3);
});

test('accepts the expected true/false options', () => {
  const result = validateQuestionRow({
    categoria: 'Ciencias',
    tipo: 'VERDADERO_FALSO',
    enunciado: 'El agua es H2O.',
    puntaje_defecto: '1',
    opcion_a: 'Verdadero',
    opcion_b: 'Falso',
    correcta: 'V',
  }, 3);
  assert.deepEqual(result.errors, []);
  assert.equal(result.data.correctLetter, 'A');
});

test('maps F to the false option and rejects A/B in true/false rows', () => {
  const baseRow = {
    categoria: 'Ciencias',
    tipo: 'VERDADERO_FALSO',
    enunciado: 'El agua hierve a 100 grados Celsius.',
    opcion_a: 'Verdadero',
    opcion_b: 'Falso',
  };
  const falseAnswer = validateQuestionRow({ ...baseRow, correcta: 'f' }, 4);
  assert.deepEqual(falseAnswer.errors, []);
  assert.equal(falseAnswer.data.correctLetter, 'B');

  const legacyAnswer = validateQuestionRow({ ...baseRow, correcta: 'A' }, 5);
  assert.equal(legacyAnswer.data, null);
  assert.ok(legacyAnswer.errors.includes('En Verdadero/Falso, correcta debe ser V o F.'));
});

test('rejects a correct answer that points to an empty option', () => {
  const result = validateQuestionRow({
    categoria: 'Matemáticas',
    tipo: 'MULTIPLE',
    enunciado: 'Pregunta',
    puntaje_defecto: '1',
    opcion_a: 'Una opción',
    opcion_b: '',
    opcion_c: '',
    opcion_d: '',
    correcta: 'B',
  }, 4);
  assert.ok(result.errors.includes('La opción marcada como correcta no tiene texto.'));
  assert.equal(result.data, null);
});

test('rejects invalid scores and incomplete multiple-choice options', () => {
  const result = validateQuestionRow({
    categoria: 'Matemáticas',
    tipo: 'MULTIPLE',
    enunciado: 'Pregunta',
    puntaje_defecto: '0',
    opcion_a: 'A',
    opcion_b: '',
    opcion_c: 'C',
    opcion_d: '',
    correcta: 'A',
  }, 5);
  assert.ok(result.errors.some((error) => error.includes('puntaje')));
  assert.ok(result.errors.some((error) => error.includes('consecutivas')));
});

test('rejects values that exceed the database column limits', () => {
  const result = validateQuestionRow({
    categoria: 'C'.repeat(101),
    tipo: 'MULTIPLE',
    enunciado: 'Pregunta',
    puntaje_defecto: '1000',
    opcion_a: 'A',
    opcion_b: 'B',
    correcta: 'A',
  }, 6);
  assert.ok(result.errors.some((error) => error.includes('100 caracteres')));
  assert.ok(result.errors.some((error) => error.includes('999.99')));
});