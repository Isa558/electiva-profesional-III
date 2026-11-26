const test = require('node:test');
const assert = require('node:assert/strict');
const ExcelJS = require('exceljs');
const { REQUIRED_HEADERS } = require('../shared/importer');
const { createQuestionTemplate } = require('../backend/services/templateService');

test('Excel template documents V/F correct values as V and F', async () => {
  const buffer = await createQuestionTemplate();
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(buffer);

  const template = workbook.getWorksheet('Plantilla');
  const headers = template.getRow(1).values.slice(1);
  const correctColumn = headers.indexOf('correcta') + 1;
  const trueFalseAnswers = [template.getCell(3, correctColumn).value, template.getCell(4, correctColumn).value];
  const instructions = workbook.getWorksheet('Instrucciones').getSheetValues().flat().join(' ');

  assert.deepEqual(headers, REQUIRED_HEADERS);
  assert.deepEqual(trueFalseAnswers, ['V', 'F']);
  assert.match(instructions, /V para Verdadero o F para Falso/);
});