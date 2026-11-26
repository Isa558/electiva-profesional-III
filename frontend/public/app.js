(() => {
  const { REQUIRED_HEADERS, validateHeaders, validateQuestionRow } = window.QuestionImporter;
  const state = { file: null, rows: [], validRows: [], questions: [], history: [], lastImport: null };
  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
  async function requestApi(endpoint, options = {}) {
    const response = await fetch(`/api${endpoint}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.message || result.error || 'Error al comunicarse con el servidor.');
    return result;
  }

  function renderDatabaseStatus(connected) {
    const status = byId('database-status');
    status.dataset.connected = String(connected);
    byId('database-status-text').textContent = connected ? 'MySQL conectado' : 'MySQL desconectado';
    status.title = connected ? 'Conexión activa con la base de datos' : 'Revisa la configuración local de MySQL';
  }

  async function refreshDatabaseData(showError = false) {
    try {
      const health = await requestApi('/health');
      if (!health.connected) throw new Error('La API no tiene conexión con MySQL.');
      const [questions, history] = await Promise.all([
        requestApi('/questions'),
        requestApi('/imports'),
      ]);
      state.questions = questions;
      state.history = history;
      renderDatabaseStatus(true);
    } catch (error) {
      state.questions = [];
      state.history = [];
      renderDatabaseStatus(false);
      if (showError) notify(error.message);
    }
    renderDashboard();
    renderBank();
  }

  function notify(message) {
    const toast = byId('toast');
    toast.textContent = message;
    toast.classList.add('visible');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.classList.remove('visible'), 3500);
  }

  function navigate(view) {
    document.querySelectorAll('.page-content').forEach((page) => page.classList.add('hidden'));
    const target = byId(`view-${view}`);
    if (!target) return;
    target.classList.remove('hidden');
    document.querySelectorAll('.nav-item, .mobile-nav button').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
    const activeNav = document.querySelector(`.nav-item[data-view="${view}"]`);
    byId('breadcrumb-current').textContent = activeNav?.textContent.trim() || target.querySelector('h1')?.textContent || view;
    if (view === 'banco') renderBank();
    if (view === 'reportes') renderHistory();
    if (view === 'configuracion') renderCategoryCount();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function renderDashboard() {
    const questions = state.questions;
    const history = state.history;
    const categories = new Set(questions.map((question) => question.category));
    byId('metric-questions').textContent = questions.length.toLocaleString('es');
    byId('nav-question-count').textContent = questions.length > 99 ? '99+' : questions.length;
    byId('other-category-count').textContent = categories.size;
    document.querySelectorAll('[data-category-count]').forEach((element) => {
      const category = element.dataset.categoryCount.toLocaleLowerCase();
      element.textContent = questions.filter((question) => question.category.toLocaleLowerCase() === category).length;
    });
    if (history[0]) {
      byId('recent-import-detail').textContent = `${history[0].successful} preguntas añadidas · ${history[0].fileName}`;
      byId('recent-import-time').textContent = new Date(history[0].date).toLocaleDateString('es', { day: 'numeric', month: 'short' });
    } else {
      byId('recent-import-detail').textContent = 'Aún no hay importaciones en este espacio';
      byId('recent-import-time').textContent = '—';
    }
  }

  function renderCategoryCount() {
    const categories = new Set(state.questions.map((question) => question.category));
    byId('settings-category-count').textContent = `${categories.size} ${categories.size === 1 ? 'categoría' : 'categorías'}`;
  }

  function renderBank() {
    const questions = state.questions;
    const search = byId('question-search').value.trim().toLocaleLowerCase();
    const visibleQuestions = questions.filter((question) => `${question.category} ${question.stem}`.toLocaleLowerCase().includes(search));
    byId('bank-count-label').textContent = `${visibleQuestions.length} ${visibleQuestions.length === 1 ? 'pregunta' : 'preguntas'}`;
    byId('bank-empty').classList.toggle('hidden', visibleQuestions.length > 0);
    byId('bank-body').innerHTML = visibleQuestions.map((question) => `<tr>
      <td>${escapeHtml(question.category)}</td>
      <td><span class="state-pill state-valid">${question.type === 'MULTIPLE' ? 'Selección múltiple' : 'Verdadero / Falso'}</span></td>
      <td title="${escapeHtml(question.stem)}">${escapeHtml(question.stem)}</td>
      <td>${question.options.length}</td>
      <td>${escapeHtml(question.defaultScore)}</td>
    </tr>`).join('');
  }

  function renderHistory() {
    const history = state.history;
    const container = byId('import-history');
    if (!history.length) {
      container.innerHTML = '<div class="history-empty">Todavía no se han procesado archivos en este navegador.</div>';
      return;
    }
    container.innerHTML = `<div class="history-row"><span>ARCHIVO</span><span>FECHA</span><span>VÁLIDAS</span><span>FALLIDAS</span><span>FILAS</span></div>${history.map((item) => `<div class="history-row"><strong title="${escapeHtml(item.fileName)}">${escapeHtml(item.fileName)}</strong><span>${new Date(item.date).toLocaleString('es')}</span><span>${item.successful}</span><span>${item.failed}</span><span>${item.total}</span></div>`).join('')}`;
  }

  function selectFile(file) {
    byId('upload-error').classList.add('hidden');
    if (!file) return;
    const extensionOkay = /\.xlsx$/i.test(file.name);
    if (!extensionOkay) {
      showUploadError('El archivo debe tener formato .xlsx. Abre los archivos .xls antiguos en Excel y guárdalos como Libro de Excel (.xlsx).');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      showUploadError('El archivo supera el límite de 10 MB.');
      return;
    }
    state.file = file;
    byId('file-name').textContent = file.name;
    byId('file-size').textContent = `${Math.max(1, Math.round(file.size / 1024))} KB`;
    byId('file-selected').classList.remove('hidden');
    byId('validate-file').disabled = false;
    byId('confirm-import').disabled = true;
    byId('confirm-import').innerHTML = '<span>＋</span> Importar válidas';
    byId('results-panel').classList.add('hidden');
    byId('import-success').classList.add('hidden');
    byId('step-review').classList.remove('done');
    byId('step-import').classList.remove('done');
  }

  function showUploadError(message) {
    byId('upload-error').textContent = message;
    byId('upload-error').classList.remove('hidden');
    byId('validate-file').disabled = true;
  }

  async function reviewFile() {
    if (!state.file || !window.ExcelJS) {
      showUploadError('No está disponible el lector local de Excel. Recarga la aplicación e inténtalo de nuevo.');
      return;
    }
    const button = byId('validate-file');
    button.disabled = true;
    button.innerHTML = '<span>◌</span> Revisando archivo…';
    try {
      const workbook = new ExcelJS.Workbook();
      await workbook.xlsx.load(await state.file.arrayBuffer());
      const worksheet = workbook.worksheets[0];
      const sheetName = worksheet?.name;
      if (!worksheet) throw new Error('El archivo no contiene hojas de cálculo.');
      const matrix = [];
      worksheet.eachRow({ includeEmpty: true }, (row, rowNumber) => {
        matrix[rowNumber - 1] = Array.from({ length: REQUIRED_HEADERS.length }, (_, index) => row.getCell(index + 1).value ?? '');
      });
      if (!matrix.length) throw new Error('La hoja está vacía. Agrega encabezados y al menos una fila.');
      const headerCheck = validateHeaders(matrix[0]);
      if (!headerCheck.valid) throw new Error(`Faltan encabezados obligatorios: ${headerCheck.missing.join(', ')}.`);
      const rows = [];
      matrix.slice(1).forEach((cells, index) => {
        if (!cells) return;
        if (!cells.some((value) => String(value ?? '').trim() !== '')) return;
        const row = {};
        REQUIRED_HEADERS.forEach((header) => {
          const position = headerCheck.normalized.indexOf(header);
          row[header] = position < 0 ? '' : cells[position] ?? '';
        });
        const result = validateQuestionRow(row, index + 2);
        rows.push({ ...result, source: row });
      });
      if (rows.length === 0) throw new Error('No se encontraron filas con preguntas debajo de los encabezados.');
      state.rows = rows;
      state.validRows = rows.filter((row) => row.data);
      state.sheetName = sheetName;
      renderReview();
      byId('upload-error').classList.add('hidden');
      byId('step-review').classList.add('done');
      byId('step-import').classList.remove('done');
    } catch (error) {
      showUploadError(error.message || 'No fue posible leer este archivo. Revisa que sea un Excel válido.');
    } finally {
      button.innerHTML = '<span>✓</span> Revisar archivo';
      button.disabled = !state.file;
    }
  }

  function renderReview() {
    const rows = state.rows;
    byId('results-panel').classList.remove('hidden');
    byId('review-filename').textContent = `${state.file.name} · Hoja “${state.sheetName}”`;
    byId('rows-total').textContent = rows.length;
    byId('rows-valid').textContent = state.validRows.length;
    byId('rows-errors').textContent = rows.length - state.validRows.length;
    byId('confirm-import').disabled = state.validRows.length === 0;
    const preview = rows.slice(0, 100).map((row) => {
      const data = row.data || row.source;
      const status = row.data
        ? '<span class="state-pill state-valid">Lista para importar</span>'
        : `<div class="row-error-list"><strong>Fila ${row.rowNumber}</strong><ul>${row.errors.map((error) => `<li>${escapeHtml(error)}</li>`).join('')}</ul></div>`;
      return `<tr><td>${row.rowNumber}</td><td>${escapeHtml(data.category ?? data.categoria)}</td><td>${escapeHtml(data.type ?? data.tipo)}</td><td title="${escapeHtml(data.stem ?? data.enunciado)}">${escapeHtml(data.stem ?? data.enunciado)}</td><td>${escapeHtml(data.defaultScore ?? data.puntaje_defecto)}</td><td>${status}</td></tr>`;
    }).join('');
    const extraRows = rows.length > 100 ? `<tr><td colspan="6">Se muestran las primeras 100 de ${rows.length} filas revisadas.</td></tr>` : '';
    byId('preview-body').innerHTML = preview + extraRows;
    byId('import-success').classList.add('hidden');
    byId('results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function confirmImport() {
    if (!state.validRows.length || !state.file) return;
    const button = byId('confirm-import');
    button.disabled = true;
    button.innerHTML = '<span>◌</span> Guardando en MySQL…';
    try {
      const result = await requestApi('/imports', {
        method: 'POST',
        body: JSON.stringify({
          fileName: state.file.name,
          rows: state.rows.map(({ rowNumber, source }) => ({ rowNumber, values: source })),
        }),
      });
      state.lastImport = result;
      byId('success-detail').textContent = `${result.successful} preguntas guardadas${result.failed ? ` · ${result.failed} filas omitidas por errores` : ''}.`;
      byId('import-success').classList.remove('hidden');
      button.innerHTML = '<span>✓</span> Importación guardada en MySQL';
      byId('step-import').classList.add('done');
      renderDatabaseStatus(true);
      await refreshDatabaseData();
      notify(`${result.successful} preguntas guardadas en MySQL.`);
    } catch (error) {
      button.disabled = false;
      button.innerHTML = '<span>＋</span> Reintentar importación';
      showUploadError(error.message);
      renderDatabaseStatus(false);
      return;
    }
  }

  document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.view)));
  document.querySelectorAll('[data-go]').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.go)));
  byId('excel-file').addEventListener('change', (event) => selectFile(event.target.files[0]));
  byId('validate-file').addEventListener('click', reviewFile);
  byId('confirm-import').addEventListener('click', confirmImport);
  byId('remove-file').addEventListener('click', () => {
    state.file = null;
    state.rows = [];
    state.validRows = [];
    byId('excel-file').value = '';
    byId('file-selected').classList.add('hidden');
    byId('validate-file').disabled = true;
    byId('confirm-import').disabled = true;
    byId('confirm-import').innerHTML = '<span>＋</span> Importar válidas';
    byId('results-panel').classList.add('hidden');
    byId('step-review').classList.remove('done');
    byId('step-import').classList.remove('done');
  });
  byId('question-search').addEventListener('input', renderBank);
  byId('format-guide').addEventListener('click', () => notify(`Columnas: ${REQUIRED_HEADERS.join(' · ')}. En correcta usa A-D para selección múltiple y V o F para verdadero/falso.`));

  const dropZone = byId('drop-zone');
  ['dragenter', 'dragover'].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add('drag-over');
  }));
  ['dragleave', 'drop'].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove('drag-over');
  }));
  dropZone.addEventListener('drop', (event) => selectFile(event.dataTransfer.files[0]));

  refreshDatabaseData(true);
})();