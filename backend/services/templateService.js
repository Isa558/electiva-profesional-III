const ExcelJS = require('exceljs');
const { REQUIRED_HEADERS } = require('../../shared/importer');

async function createQuestionTemplate() {
  const workbook = new ExcelJS.Workbook();
  const worksheet = workbook.addWorksheet('Plantilla');
  const examples = [
    ['Ciencias', 'MULTIPLE', 'Conceptos básicos', '¿Cuál es el planeta más cercano al Sol?', 'Mercurio es el planeta más próximo al Sol.', 1, 'Venus', 'Mercurio', 'Marte', 'Júpiter', 'B'],
    ['Ciencias', 'VERDADERO_FALSO', '', 'La Tierra gira alrededor del Sol.', '', 1, 'Verdadero', 'Falso', '', '', 'V'],
    ['Ciencias', 'VERDADERO_FALSO', '', 'Los mamíferos son invertebrados.', '', 1, 'Verdadero', 'Falso', '', '', 'F'],
  ];
  worksheet.addRow(REQUIRED_HEADERS);
  examples.forEach((example) => worksheet.addRow(example));
  worksheet.columns = REQUIRED_HEADERS.map((header) => ({
    width: Math.max(header.length + 3, header === 'enunciado' ? 43 : 19),
  }));
  worksheet.getRow(1).font = { bold: true, color: { argb: 'FFFFFFFF' } };
  worksheet.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF315D45' } };
  worksheet.views = [{ state: 'frozen', ySplit: 1 }];

  const guide = workbook.addWorksheet('Instrucciones');
  [
    ['PLANTILLA DE IMPORTACIÓN · BANCO DE PREGUNTAS'],
    ['Completa una pregunta por fila en la hoja Plantilla. Conserva los encabezados tal cual.'],
    ['Columnas obligatorias', REQUIRED_HEADERS.join(', ')],
    ['tipo', 'MULTIPLE o VERDADERO_FALSO'],
    ['correcta', 'Selección múltiple: A, B, C o D. Verdadero/Falso: V para Verdadero o F para Falso.'],
    ['puntaje_defecto', 'Número mayor que cero. Si se deja vacío, se asigna 1.'],
    ['Verdadero/Falso', 'opcion_a = Verdadero y opcion_b = Falso; opcion_c y opcion_d vacías.'],
    ['Selección múltiple', 'Usa opciones consecutivas desde A, sin saltos entre opciones.'],
    ['texto_base y retroalimentacion', 'Campos opcionales.'],
  ].forEach((row) => guide.addRow(row));
  guide.columns = [{ width: 30 }, { width: 100 }];
  return workbook.xlsx.writeBuffer();
}

module.exports = { createQuestionTemplate };