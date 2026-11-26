const REQUIRED_HEADERS = [
  'categoria',
  'tipo',
  'texto_base',
  'enunciado',
  'retroalimentacion',
  'puntaje_defecto',
  'opcion_a',
  'opcion_b',
  'opcion_c',
  'opcion_d',
  'correcta',
];

function cellText(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object' && Array.isArray(value.richText)) {
    return value.richText.map((part) => part.text || '').join('').trim();
  }
  if (typeof value === 'object' && value.text) return String(value.text).trim();
  return String(value).trim();
}

function validateHeaders(headers) {
  const normalized = headers.map((header) => cellText(header).toLowerCase());
  const missing = REQUIRED_HEADERS.filter((header) => !normalized.includes(header));
  return { valid: missing.length === 0, missing, normalized };
}

function validateQuestionRow(row, rowNumber) {
  const values = Object.fromEntries(
    Object.entries(row).map(([key, value]) => [key, cellText(value)]),
  );
  const errors = [];
  const category = values.categoria;
  const type = values.tipo.toUpperCase();
  const stem = values.enunciado;
  const correctInput = values.correcta.toUpperCase();
  const correct = type === 'VERDADERO_FALSO'
    ? ({ V: 'A', F: 'B' }[correctInput] || correctInput)
    : correctInput;
  const optionLetters = ['A', 'B', 'C', 'D'];
  const options = optionLetters
    .map((letter) => ({ letter, text: values[`opcion_${letter.toLowerCase()}`] || '' }))
    .filter((option) => option.text !== '');
  const scoreValue = values.puntaje_defecto || '';
  const score = scoreValue === '' ? 1 : Number(scoreValue.replace(',', '.'));

  if (!category) errors.push('La categoría es obligatoria.');
  if (category.length > 100) errors.push('La categoría no puede superar 100 caracteres.');
  if (!['MULTIPLE', 'VERDADERO_FALSO'].includes(type)) {
    errors.push('El tipo debe ser MULTIPLE o VERDADERO_FALSO.');
  }
  if (!stem) errors.push('El enunciado es obligatorio.');
  if (!Number.isFinite(score) || score <= 0) errors.push('El puntaje debe ser un número mayor que cero.');
  if (Number.isFinite(score) && score > 999.99) errors.push('El puntaje no puede superar 999.99.');
  if (scoreValue && !/^\d+(?:\.\d{1,2})?$/.test(scoreValue.replace(',', '.'))) {
    errors.push('El puntaje admite como máximo dos decimales.');
  }
  if (type === 'VERDADERO_FALSO') {
    if (!['V', 'F'].includes(correctInput)) errors.push('En Verdadero/Falso, correcta debe ser V o F.');
  } else if (!['A', 'B', 'C', 'D'].includes(correct)) {
    errors.push('En selección múltiple, correcta debe ser A, B, C o D.');
  }

  if (type === 'MULTIPLE') {
    if (options.length < 2) errors.push('Una pregunta de selección múltiple requiere al menos dos opciones.');
    if (options.some((option, index) => option.letter !== optionLetters[index])) {
      errors.push('Las opciones deben estar completas y consecutivas desde A.');
    }
  }

  if (type === 'VERDADERO_FALSO') {
    const normalizedOptions = options.map((option) => option.text.toLocaleLowerCase());
    if (
      options.length !== 2
      || options[0]?.letter !== 'A'
      || options[1]?.letter !== 'B'
      || normalizedOptions[0] !== 'verdadero'
      || normalizedOptions[1] !== 'falso'
    ) {
      errors.push('Verdadero/Falso requiere A = Verdadero y B = Falso.');
    }
  }

  if (correct && !options.some((option) => option.letter === correct)) {
    errors.push('La opción marcada como correcta no tiene texto.');
  }

  return {
    rowNumber,
    data: errors.length === 0
      ? {
          category,
          type,
          baseText: values.texto_base || null,
          stem,
          feedback: values.retroalimentacion || null,
          defaultScore: score,
          options,
          correctLetter: correct,
        }
      : null,
    errors,
  };
}

const importerApi = { REQUIRED_HEADERS, cellText, validateHeaders, validateQuestionRow };

if (typeof module !== 'undefined' && module.exports) module.exports = importerApi;
if (typeof window !== 'undefined') window.QuestionImporter = importerApi;