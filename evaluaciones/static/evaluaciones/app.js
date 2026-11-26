(() => {
  'use strict';

  const API_ROOT = '/api/';
  const ACCESS_KEY = 'saber-tyt-access';
  const REFRESH_KEY = 'saber-tyt-refresh';
  const PERMISSION_LABELS = {
    'users.manage': 'Administrar usuarios',
    'roles.manage': 'Administrar roles y permisos',
    'questions.manage': 'Gestionar e importar preguntas',
    'quizzes.manage': 'Configurar cuestionarios',
    'results.view_all': 'Consultar todos los resultados',
    'results.view_assigned': 'Consultar resultados de cuestionarios asignados',
    'quizzes.take': 'Responder cuestionarios',
    'results.view_own': 'Consultar resultados propios',
    'settings.manage': 'Configurar el sistema',
  };
  const NAVIGATION = [
    { page: 'dashboard', label: 'Inicio', icon: '⌂', always: true },
    { page: 'users', label: 'Usuarios', icon: '♙', permission: 'users.manage' },
    { page: 'roles', label: 'Roles y permisos', icon: '⚿', permission: 'roles.manage' },
    { page: 'categories', label: 'Categorías', icon: '▦', permission: 'questions.manage' },
    { page: 'questions', label: 'Banco de preguntas', icon: '▤', permission: 'questions.manage' },
    { page: 'imports', label: 'Importar preguntas', icon: '⇧', permission: 'questions.manage' },
    { page: 'quizzes', label: 'Cuestionarios', icon: '▣', permission: 'quizzes.manage' },
    { page: 'results', label: 'Resultados', icon: '▥', any: ['results.view_all', 'results.view_assigned'] },
    { page: 'available', label: 'Cuestionarios disponibles', icon: '▣', permission: 'quizzes.take' },
    { page: 'my-results', label: 'Mis calificaciones', icon: '◷', permission: 'results.view_own' },
    { page: 'history', label: 'Historial de intentos', icon: '◷', permission: 'results.view_own' },
    { page: 'settings', label: 'Configuración', icon: '⚙', permission: 'settings.manage' },
    { page: 'profile', label: 'Mi perfil', icon: '♧', always: true },
  ];
  const TITLES = {
    dashboard: 'Resumen general',
    users: 'Gestión de usuarios',
    roles: 'Roles y permisos',
    categories: 'Categorías y competencias',
    questions: 'Banco de preguntas',
    imports: 'Importar preguntas',
    quizzes: 'Gestión de cuestionarios',
    results: 'Resultados',
    available: 'Cuestionarios disponibles',
    'my-results': 'Mis calificaciones',
    history: 'Historial de intentos',
    profile: 'Mi perfil',
    settings: 'Configuración del sistema',
    exam: 'Evaluación en curso',
    result: 'Resultado de evaluación',
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const app = {
    access: localStorage.getItem(ACCESS_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
    user: null,
    page: 'dashboard',
    settings: null,
    permissions: [],
    activeAttempt: null,
    currentQuestion: 0,
    timerId: null,
    deadline: 0,
    submitting: false,
    pendingAnswers: new Set(),
    importDraft: null,
    importResult: null,
    modalSubmit: null,
  };

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]);
  }

  function fullName(user = app.user) {
    return [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || 'Usuario';
  }

  function initials(name) {
    return String(name || 'ST').trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
  }

  function can(permission) {
    return app.permissions.includes('*') || app.permissions.includes(permission);
  }

  function canAny(permissions) {
    return app.permissions.includes('*') || permissions.some(can);
  }

  function toast(message, type = '') {
    const item = document.createElement('div');
    item.className = `toast ${type}`.trim();
    item.textContent = message;
    $('#toast-region').append(item);
    window.setTimeout(() => item.remove(), 4500);
  }

  function showError(element, message) {
    element.textContent = message;
    element.hidden = false;
  }

  function apiError(data, fallback = 'No fue posible completar la solicitud.') {
    if (typeof data === 'string') return data;
    if (data?.detail) return data.detail;
    if (data && typeof data === 'object') {
      const first = Object.entries(data).find(([, value]) => value);
      if (first) {
        const messages = Array.isArray(first[1]) ? first[1] : [first[1]];
        return `${first[0]}: ${messages.map(String).join(' ')}`;
      }
    }
    return fallback;
  }

  async function refreshAccess() {
    if (!app.refresh) return false;
    const response = await fetch(`${API_ROOT}auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: app.refresh }),
    });
    if (!response.ok) return false;
    const tokens = await response.json();
    app.access = tokens.access;
    app.refresh = tokens.refresh || app.refresh;
    localStorage.setItem(ACCESS_KEY, app.access);
    localStorage.setItem(REFRESH_KEY, app.refresh);
    return true;
  }

  async function request(path, options = {}, retried = false) {
    const headers = new Headers(options.headers || {});
    if (app.access) headers.set('Authorization', `Bearer ${app.access}`);
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    let response;
    try {
      response = await fetch(`${API_ROOT}${path}`, { ...options, headers });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new Error('No fue posible conectar con el servidor. Verifica que Django esté activo y vuelve a intentarlo.');
      }
      throw error;
    }
    if (response.status === 401 && !retried && app.refresh && !path.startsWith('auth/token')) {
      if (await refreshAccess()) return request(path, options, true);
    }
    if (response.status === 204 || response.status === 205) return null;
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : await response.blob();
    if (!response.ok) {
      throw new Error(apiError(data, `Error ${response.status}: la solicitud no pudo completarse.`));
    }
    return data;
  }

  const api = {
    get: path => request(path),
    post: (path, data) => request(path, { method: 'POST', body: data instanceof FormData ? data : JSON.stringify(data ?? {}) }),
    patch: (path, data) => request(path, { method: 'PATCH', body: JSON.stringify(data) }),
    put: (path, data) => request(path, { method: 'PUT', body: JSON.stringify(data) }),
    delete: path => request(path, { method: 'DELETE' }),
  };

  function formatDate(value, options = { dateStyle: 'medium' }) {
    if (!value) return '—';
    const date = new Date(value);
    const displayOptions = { timeZone: app.settings?.time_zone || 'America/Bogota', ...options };
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('es-CO', displayOptions);
  }

  function dateInputValue(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function statusPill(active, enabled = 'Activo', disabled = 'Inactivo') {
    return `<span class="status-pill ${active ? 'pill-green' : 'pill-gray'}">${active ? enabled : disabled}</span>`;
  }

  function gradePill(grade, maxGrade, passGrade) {
    if (grade === null || grade === undefined) return '<span class="status-pill pill-amber">En curso</span>';
    const passed = Number(grade) >= Number(passGrade ?? 3);
    return `<span class="grade-pill ${passed ? 'pill-green' : 'pill-red'}">${passed ? 'Aprobado' : 'No aprobado'}</span>`;
  }

  function setDatabaseState(connected, message) {
    const dot = $('#db-dot');
    dot.className = `connection-dot ${connected ? 'connected' : 'disconnected'}`;
    $('#db-message').textContent = message;
  }

  function setInstitutionName(name) {
    if (!name) return;
    const loginInstitution = $('#login-institution');
    if (loginInstitution) loginInstitution.textContent = name.toLocaleUpperCase('es');
    const footer = $('#institution-name');
    if (footer) footer.textContent = name;
  }

  async function checkDatabase() {
    try {
      const result = await api.get('health/');
      setDatabaseState(result.connected, result.connected
        ? `Conexión segura a la base de datos${result.engine ? ` · ${result.engine === 'mysql' ? 'MariaDB' : result.engine}` : ''}`
        : result.message);
    } catch (error) {
      setDatabaseState(false, error.message);
    }
  }

  async function loadLoginRoles() {
    const selector = $('#login-role');
    try {
      const roles = await api.get('auth/roles/');
      selector.innerHTML = '<option value="">Selecciona tu rol</option>' + roles
        .map(role => `<option value="${escapeHtml(role.slug)}">${escapeHtml(role.name)}</option>`)
        .join('');
      selector.disabled = roles.length === 0;
      if (!roles.length) {
        selector.innerHTML = '<option value="">No hay roles activos</option>';
      }
    } catch (error) {
      selector.innerHTML = '<option value="">No fue posible cargar los roles</option>';
      selector.disabled = true;
      setDatabaseState(false, error.message);
    }
  }

  async function loadDemoAccounts() {
    try {
      const demo = await api.get('auth/demo-accounts/');
      if (!demo.enabled) return;
      const accountList = $('#demo-account-list');
      demo.accounts.forEach(account => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'demo-account';
        button.textContent = `${account.role}: ${account.email}`;
        button.addEventListener('click', () => {
          $('#login-identity').value = account.email;
          $('#login-role').value = account.role_slug;
          $('#login-password').value = demo.password;
        });
        accountList.append(button);
      });
      $('#demo-password').textContent = demo.password;
      $('#demo-accounts').hidden = false;
    } catch (error) {
      console.error('No fue posible comprobar las cuentas de demostración.', error);
    }
  }

  function renderNavigation() {
    const visible = NAVIGATION.filter(item => item.always || (item.permission && can(item.permission)) || (item.any && canAny(item.any)));
    $('#sidebar-nav').innerHTML = visible.map(item => `
      <button class="nav-item ${app.page === item.page ? 'active' : ''}" type="button" data-action="navigate" data-page="${item.page}">
        <span class="nav-icon">${item.icon}</span><span>${escapeHtml(item.label)}</span>
      </button>`).join('');
  }

  function setIdentity() {
    const name = fullName();
    const avatar = initials(name);
    $('#sidebar-name').textContent = name;
    $('#sidebar-role').textContent = app.user.role;
    $('#sidebar-avatar').textContent = avatar;
    $('#top-name').textContent = name;
    $('#top-role').textContent = app.user.role;
    $('#top-avatar').textContent = avatar;
    $('#today-label').textContent = new Date().toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    $('#current-year').textContent = new Date().getFullYear();
  }

  function showApplication() {
    $('#login-screen').hidden = true;
    $('#app-shell').hidden = false;
    setIdentity();
    renderNavigation();
    if (can('settings.manage')) {
      api.get('settings/').then(settings => {
        app.settings = settings;
        setInstitutionName(settings.institution_name);
      }).catch(error => console.error('No fue posible cargar la configuración institucional.', error));
    }
    navigate('dashboard');
  }

  function showLogin() {
    clearInterval(app.timerId);
    app.timerId = null;
    $('#app-shell').hidden = true;
    $('#login-screen').hidden = false;
    $('#login-password').value = '';
    $('#login-identity').focus();
  }

  function navigate(page) {
    if (!['exam', 'result'].includes(page) && !NAVIGATION.some(item => item.page === page && (item.always || (item.permission && can(item.permission)) || (item.any && canAny(item.any))))) {
      toast('Tu rol no tiene permiso para acceder a esta sección.', 'error');
      return;
    }
    app.page = page;
    $('#page-title').textContent = TITLES[page] || 'Simulador Saber TyT';
    $('#page-content').classList.toggle('history-page', page === 'history');
    $('#app-shell').classList.remove('menu-open');
    renderNavigation();
    const content = $('#page-content');
    content.innerHTML = '<div class="loading">Cargando información</div>';
    if (page === 'exam') return renderExam();
    if (page === 'result') return renderResult(app.lastResult);
    const pages = {
      dashboard: renderDashboard,
      users: renderUsers,
      roles: renderRoles,
      categories: renderCategories,
      questions: renderQuestions,
      imports: renderImports,
      quizzes: renderQuizzes,
      results: () => renderResults(false),
      available: renderAvailable,
      'my-results': () => renderResults(true),
      history: () => renderResults(true),
      profile: renderProfile,
      settings: renderSettings,
    };
    return Promise.resolve(pages[page]?.()).catch(error => {
      content.innerHTML = `<div class="panel empty-state"><div class="empty-icon">!</div>${escapeHtml(error.message)}</div>`;
    });
  }

  function heading(title, description, actions = '') {
    return `<div class="page-heading-row"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div><div class="heading-actions">${actions}</div></div>`;
  }

  function metric(label, value, note, icon) {
    return `<article class="metric-card"><div class="metric-top"><span>${escapeHtml(label)}</span><span class="metric-icon">${icon}</span></div><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;
  }

  function quickLink(label, page, icon) {
    return `<button type="button" class="quick-link" data-action="navigate" data-page="${page}"><span class="nav-icon">${icon}</span><span>${escapeHtml(label)}</span></button>`;
  }

  async function renderDashboard() {
    const student = can('quizzes.take') && !canAny(['users.manage', 'questions.manage', 'quizzes.manage']);
    const [usersResult, rolesResult, categoriesResult, questionsResult, quizzesResult, attemptsResult, availableResult] = await Promise.allSettled([
      can('users.manage') ? api.get('users/') : Promise.resolve([]),
      can('roles.manage') ? api.get('roles/') : Promise.resolve([]),
      can('questions.manage') ? api.get('categories/') : Promise.resolve([]),
      can('questions.manage') ? api.get('questions/') : Promise.resolve([]),
      can('quizzes.manage') ? api.get('quizzes/') : Promise.resolve([]),
      canAny(['results.view_all', 'results.view_assigned', 'results.view_own']) ? api.get('attempts/') : Promise.resolve([]),
      can('quizzes.take') ? api.get('quizzes/available/') : Promise.resolve([]),
    ]);
    const resultValue = result => result.status === 'fulfilled' ? result.value : [];
    const users = resultValue(usersResult);
    const roles = resultValue(rolesResult);
    const categories = resultValue(categoriesResult);
    const questions = resultValue(questionsResult);
    const quizzes = resultValue(quizzesResult);
    const attempts = resultValue(attemptsResult);
    const available = resultValue(availableResult);
    app.dashboardQuizzes = available;
    const completed = attempts.filter(item => item.status === 'COMPLETED');
    const grades = completed.map(item => Number(item.grade)).filter(Number.isFinite);
    const average = grades.length ? (grades.reduce((sum, grade) => sum + grade, 0) / grades.length).toFixed(2) : '—';
    const metrics = student
      ? [
        metric('Disponibles', available.length, 'Evaluaciones habilitadas', '▣'),
        metric('Intentos realizados', completed.length, 'Tu historial personal', '✓'),
        metric('Promedio general', average, 'Sobre tus calificaciones', '↗'),
        metric('Aprobados', completed.filter(item => Number(item.grade) >= Number(item.passing_grade || 3)).length, 'Según la nota mínima del cuestionario', '★'),
      ]
      : [
        metric('Usuarios', users.length, 'Cuentas registradas', '♙'),
        metric('Preguntas activas', questions.filter(item => item.is_active).length, `${categories.length} categorías`, '▤'),
        metric('Cuestionarios', quizzes.length, 'Configurados en el sistema', '▣'),
        metric('Intentos registrados', attempts.length, `${roles.length} roles configurados`, '◷'),
      ];
    const shortcuts = [];
    if (can('users.manage')) shortcuts.push(quickLink('Administrar usuarios', 'users', '♙'));
    if (can('roles.manage')) shortcuts.push(quickLink('Configurar roles y permisos', 'roles', '⚿'));
    if (can('questions.manage')) shortcuts.push(quickLink('Gestionar banco de preguntas', 'questions', '▤'));
    if (can('quizzes.manage')) shortcuts.push(quickLink('Configurar cuestionarios', 'quizzes', '▣'));
    if (canAny(['results.view_all', 'results.view_assigned'])) shortcuts.push(quickLink('Consultar resultados', 'results', '▥'));
    if (can('quizzes.take')) shortcuts.push(quickLink('Presentar evaluación', 'available', '▷'));
    if (can('results.view_own')) shortcuts.push(quickLink('Ver mis calificaciones', 'my-results', '◷'));
    if (can('results.view_own')) shortcuts.push(quickLink('Historial de intentos', 'history', '◷'));
    shortcuts.push(quickLink('Mi perfil', 'profile', '♧'));
    const recent = [...attempts].sort((a, b) => new Date(b.submitted_at || b.started_at) - new Date(a.submitted_at || a.started_at)).slice(0, 4);
    $('#page-content').innerHTML = `
      <section class="welcome-panel">
        <div class="welcome-copy"><div class="eyebrow">${escapeHtml(app.user.role.toUpperCase())} · SIMULADOR SABER TyT</div>
          <h2>${student ? `¡Hola, ${escapeHtml(app.user.first_name || app.user.username)}!` : `¡Bienvenido/a, ${escapeHtml(app.user.first_name || app.user.username)}!`}</h2>
          <p>${student ? 'Tu preparación continúa. Revisa tus evaluaciones y sigue avanzando.' : 'Aquí tienes un resumen actualizado de la actividad en la plataforma.'}</p></div>
        <div class="welcome-icon" aria-hidden="true">${student ? '✦' : '⌂'}</div>
      </section>
      <section class="metric-grid">${metrics.join('')}</section>
      <div class="dashboard-grid">
        <section class="panel"><div class="panel-title"><div><h3>Accesos rápidos</h3><p>Continúa con tus tareas en la plataforma.</p></div></div>
          <div class="quick-grid">${shortcuts.length ? shortcuts.join('') : '<div class="empty-state">No hay módulos adicionales asignados a tu rol.</div>'}</div></section>
        <section class="panel"><div class="panel-title"><div><h3>Actividad reciente</h3><p>Últimos intentos registrados.</p></div>
          ${canAny(['results.view_all', 'results.view_assigned']) ? '<button class="text-link" data-action="navigate" data-page="results">Ver todo →</button>' : ''}</div>
          ${recent.length ? recent.map(item => `<div class="activity-row"><span class="activity-badge">${item.status === 'COMPLETED' ? '✓' : '◷'}</span><span class="activity-copy"><b>${escapeHtml(item.quiz_title)}</b><small>${escapeHtml(item.student_username || app.user.username)} · ${escapeHtml(formatDate(item.submitted_at || item.started_at))}</small></span>${item.grade === null ? '<span class="status-pill pill-amber">En curso</span>' : `<span class="grade-pill ${Number(item.grade) >= Number(item.passing_grade || 3) ? 'pill-green' : 'pill-red'}">${escapeHtml(item.grade)} / ${escapeHtml(item.max_grade)}</span>`}</div>`).join('') : '<div class="empty-state">Aún no hay intentos registrados.</div>'}
        </section>
      </div>
      ${student ? `<section class="panel"><div class="panel-title"><div><h3>Cuestionarios disponibles</h3><p>Evaluaciones habilitadas para tu cuenta.</p></div><button class="text-link" data-action="navigate" data-page="available">Ver cuestionarios →</button></div>${available.length ? `<div class="quiz-card-grid">${available.slice(0, 2).map(quizCard).join('')}</div>` : '<div class="empty-state">No hay cuestionarios disponibles en este momento.</div>'}</section>` : ''}
    `;
    if (student) resumePendingAttempt();
  }

  function quizCard(quiz) {
    return `<article class="quiz-card"><div class="quiz-card-top"><h3>${escapeHtml(quiz.title)}</h3><span class="status-pill pill-green">Disponible</span></div>
      <p>${escapeHtml(quiz.description || 'Evaluación de competencias Saber TyT.')}</p>
      <div class="quiz-facts"><span>▤ ${escapeHtml(quiz.question_count)} preguntas</span><span>◷ ${escapeHtml(quiz.duration_minutes)} min</span><span>★ Nota máxima ${escapeHtml(quiz.max_grade)}</span><span>↻ ${escapeHtml(quiz.attempts_remaining)} intentos</span></div>
      ${quiz.created_by_name ? `<p class="quiz-teacher">Docente: ${escapeHtml(quiz.created_by_name)}</p>` : ''}
      <button class="btn btn-primary" type="button" data-action="start-quiz" data-id="${quiz.id}">Ver instrucciones y comenzar →</button></article>`;
  }

  function emptyTable(columns, message) {
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead></table><div class="empty-state"><div class="empty-icon">⌕</div>${escapeHtml(message)}</div></div>`;
  }

  function table(columns, rows, emptyMessage = 'No se encontraron registros.') {
    return rows.length
      ? `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`
      : emptyTable(columns, emptyMessage);
  }

  function toolbar(searchPlaceholder, extra = '') {
    return `<div class="toolbar"><div class="toolbar-group"><input class="search-field" type="search" data-table-search placeholder="${escapeHtml(searchPlaceholder)}">${extra}</div><span class="count-note" data-row-count></span></div>`;
  }

  function filterTable(searchInput) {
    const content = $('#page-content');
    const term = searchInput.value.toLocaleLowerCase('es');
    let visible = 0;
    const rows = $$('tbody tr', content);
    rows.forEach(row => {
      const matchesSearch = !term || row.dataset.search?.includes(term) || row.textContent.toLocaleLowerCase('es').includes(term);
      const statusFilter = $('[data-status-filter]', content)?.value || '';
      const matchesStatus = !statusFilter || row.dataset.active === statusFilter || row.dataset.status === statusFilter;
      const categoryFilter = $('[data-category-filter]', content)?.value || '';
      const matchesCategory = !categoryFilter || row.dataset.category === categoryFilter;
      const competencyFilter = $('[data-competency-filter]', content)?.value || '';
      const matchesCompetency = !competencyFilter || row.dataset.competency === competencyFilter;
      const typeFilter = $('[data-question-type-filter]', content)?.value || '';
      const matchesType = !typeFilter || row.dataset.type === typeFilter;
      const quizFilter = $('[data-quiz-filter]', content)?.value || '';
      const matchesQuiz = !quizFilter || row.dataset.quiz === quizFilter;
      row.hidden = !(matchesSearch && matchesStatus && matchesCategory && matchesCompetency && matchesType && matchesQuiz);
      if (!row.hidden) visible += 1;
    });
    const count = $('[data-row-count]', content);
    if (count) count.textContent = `${visible} registro${visible === 1 ? '' : 's'}`;
  }

  async function renderUsers() {
    const [users, roles] = await Promise.all([api.get('users/'), api.get('roles/')]);
    $('#page-content').innerHTML = `${heading('Usuarios del sistema', 'Crea cuentas, asigna roles y controla el acceso a la plataforma.', '<button class="btn btn-primary" data-action="user-new">＋ Crear usuario</button>')}
      ${toolbar('Buscar por nombre, correo o usuario', `<select class="select-field" data-status-filter><option value="">Todos los estados</option><option value="true">Activos</option><option value="false">Inactivos</option></select>`)}
      ${table(['USUARIO', 'CÓDIGO', 'ROL', 'CORREO', 'ESTADO', 'ACCIONES'], users.map(user => `<tr data-active="${user.is_active}" data-search="${escapeHtml(`${user.username} ${fullName(user)} ${user.email} ${user.role}`.toLocaleLowerCase('es'))}">
        <td><strong>${escapeHtml(fullName(user))}</strong><small>@${escapeHtml(user.username)}</small></td><td>${escapeHtml(user.institutional_code || '—')}</td>
        <td><span class="role-tag">${escapeHtml(user.role || 'Sin rol')}</span></td><td>${escapeHtml(user.email || '—')}</td><td>${statusPill(user.is_active)}</td>
        <td><div class="table-actions"><button class="icon-action" data-action="user-edit" data-id="${user.id}" title="Editar usuario">✎</button><button class="icon-action ${user.is_active ? 'danger' : ''}" data-action="user-toggle" data-id="${user.id}" title="${user.is_active ? 'Desactivar' : 'Activar'}">${user.is_active ? '⊘' : '✓'}</button></div></td></tr>`))}`;
    bindTableFilters();
    app.usersCache = users;
    app.rolesCache = roles.filter(role => role.is_active);
  }

  async function renderRoles() {
    const [roles, permissions] = await Promise.all([api.get('roles/'), api.get('role-permissions/')]);
    app.permissionCatalog = permissions;
    const rows = roles.map(role => `<tr data-active="${role.is_active}" data-search="${escapeHtml(`${role.name} ${role.slug} ${role.description}`.toLocaleLowerCase('es'))}">
      <td><strong>${escapeHtml(role.name)} ${role.is_system ? '<span class="status-pill pill-gray">Predeterminado</span>' : ''}</strong><small>${escapeHtml(role.description || role.slug)}</small></td>
      <td>${role.permissions.length} permisos</td><td>${statusPill(role.is_active)}</td>
      <td><div class="table-actions"><button class="icon-action" data-action="role-edit" data-id="${role.id}" title="Editar rol">✎</button><button class="icon-action ${role.is_active ? 'danger' : ''}" data-action="role-toggle" data-id="${role.id}" title="${role.is_active ? 'Desactivar' : 'Activar'}">${role.is_active ? '⊘' : '✓'}</button></div></td></tr>`);
    $('#page-content').innerHTML = `${heading('Roles y permisos', 'Define roles personalizados y asigna permisos según las responsabilidades de cada usuario.', '<button class="btn btn-primary" data-action="role-new">＋ Crear rol</button>')}
      <div class="callout">Los permisos se verifican en Django en cada solicitud; ocultar un módulo en pantalla no reemplaza la autorización del servidor.</div>
      ${toolbar('Buscar rol o descripción')}${table(['ROL', 'PERMISOS', 'ESTADO', 'ACCIONES'], rows, 'Aún no hay roles configurados.')}`;
    bindTableFilters();
    app.rolesCache = roles;
  }

  async function renderCategories() {
    const [categories, questions] = await Promise.all([api.get('categories/'), api.get('questions/')]);
    const rows = categories.map(category => {
      const count = questions.filter(question => question.category === category.id).length;
      return `<tr data-active="${category.is_active}" data-search="${escapeHtml(`${category.name} ${category.competency}`.toLocaleLowerCase('es'))}">
        <td><strong>${escapeHtml(category.name)}</strong></td><td>${escapeHtml(category.competency || '—')}</td><td>${count}</td><td>${statusPill(category.is_active)}</td>
        <td><div class="table-actions"><button class="icon-action" data-action="category-edit" data-id="${category.id}" title="Editar categoría">✎</button><button class="icon-action ${category.is_active ? 'danger' : ''}" data-action="category-toggle" data-id="${category.id}" title="${category.is_active ? 'Desactivar' : 'Activar'}">${category.is_active ? '⊘' : '✓'}</button></div></td></tr>`;
    });
    $('#page-content').innerHTML = `${heading('Materias y competencias', 'Administra las materias o asignaturas que clasifican las preguntas y sus competencias.', '<button class="btn btn-primary" data-action="category-new">＋ Nueva materia</button>')}
      ${toolbar('Buscar materia o competencia')}${table(['MATERIA / CATEGORÍA', 'COMPETENCIA', 'PREGUNTAS', 'ESTADO', 'ACCIONES'], rows)}`;
    bindTableFilters();
    app.categoriesCache = categories;
  }

  async function renderQuestions() {
    const [questions, categories] = await Promise.all([api.get('questions/'), api.get('categories/')]);
    app.questionsCache = questions;
    app.categoriesCache = categories;
    const competencies = [...new Set(questions.map(question => question.competency.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right, 'es'));
    const filters = `<select class="select-field" data-status-filter><option value="">Todos los estados</option><option value="true">Activas</option><option value="false">Inactivas</option></select>
      <select class="select-field" data-category-filter><option value="">Todas las materias</option>${categories.map(category => `<option value="${category.id}">${escapeHtml(category.name)}${category.is_active ? '' : ' (inactiva)'}</option>`).join('')}</select>
      <select class="select-field" data-competency-filter><option value="">Todas las competencias</option>${competencies.map(competency => `<option value="${escapeHtml(competency)}">${escapeHtml(competency)}</option>`).join('')}</select>
      <select class="select-field" data-question-type-filter><option value="">Todos los tipos</option><option value="MULTIPLE">Selección múltiple</option><option value="VERDADERO_FALSO">Verdadero / Falso</option></select>`;
    const rows = questions.map(question => `<tr data-active="${question.is_active}" data-category="${question.category}" data-competency="${escapeHtml(question.competency)}" data-type="${escapeHtml(question.type)}" data-search="${escapeHtml(`${question.stem} ${question.category_name} ${question.competency}`.toLocaleLowerCase('es'))}">
      <td><div class="question-preview"><strong>${escapeHtml(question.stem)}</strong><small>${escapeHtml(question.base_text || question.competency || 'Sin descripción adicional')}</small></div></td>
      <td>${escapeHtml(question.category_name)}</td><td>${escapeHtml(question.competency || '—')}</td>
      <td>${question.type === 'VERDADERO_FALSO' ? 'V / F' : 'Selección múltiple'}</td><td>${escapeHtml(question.default_score)}</td><td>${statusPill(question.is_active)}</td>
      <td><div class="table-actions"><button class="icon-action" data-action="question-edit" data-id="${question.id}" title="Editar pregunta">✎</button><button class="icon-action ${question.is_active ? 'danger' : ''}" data-action="question-toggle" data-id="${question.id}" title="${question.is_active ? 'Desactivar' : 'Activar'}">${question.is_active ? '⊘' : '✓'}</button></div></td></tr>`);
    $('#page-content').innerHTML = `${heading('Banco de preguntas', 'Crea, clasifica y administra las preguntas que conforman las evaluaciones.', '<button class="btn btn-secondary" data-action="navigate" data-page="imports">⇧ Importar Excel</button><button class="btn btn-primary" data-action="question-new">＋ Nueva pregunta</button>')}
      ${toolbar('Buscar enunciado, materia o competencia', filters)}${table(['ENUNCIADO', 'MATERIA / CATEGORÍA', 'COMPETENCIA', 'TIPO', 'PUNTAJE', 'ESTADO', 'ACCIONES'], rows, 'Aún no hay preguntas en el banco.')}`;
    bindTableFilters();
    const categoryFilter = $('[data-category-filter]');
    categoryFilter?.addEventListener('change', () => filterTable($('[data-table-search]', $('#page-content')) || { value: '' }));
  }

  async function renderImports() {
    const records = await api.get('imports/');
    const rows = records.map(record => `<tr data-search="${escapeHtml(`${record.file_name} ${record.created_by_name}`.toLocaleLowerCase('es'))}">
      <td><strong>${escapeHtml(record.file_name)}</strong><small>${escapeHtml(record.created_by_name)}</small></td>
      <td>${escapeHtml(formatDate(record.created_at))}</td><td>${record.total_rows}</td><td><span class="status-pill pill-green">${record.imported_rows}</span></td>
      <td>${record.duplicate_rows ? `<span class="status-pill pill-amber">${record.duplicate_rows}</span>` : '0'}</td>
      <td>${record.error_rows ? `<button class="text-link" data-action="import-errors" data-id="${record.id}">${record.error_rows} ver errores</button>` : '0'}</td></tr>`);
    $('#page-content').innerHTML = `${heading('Importar preguntas', 'Carga preguntas desde una plantilla Excel y verifica el contenido antes de guardarlo.', '<button class="btn btn-secondary" data-action="download-template">↓ Descargar plantilla Excel</button>')}
      <section class="panel"><div class="panel-title"><div><h3>Importación desde Excel</h3><p>Formato .xlsx · máximo 10 MB · hasta 5.000 filas.</p></div></div>
        <div class="drop-zone" id="drop-zone"><div><div class="drop-icon">⇧</div><strong>Selecciona el archivo .xlsx</strong><p>Arrastra el archivo aquí o elígelo desde tu equipo.</p><p class="file-meta" id="selected-file">Ningún archivo seleccionado</p><input type="file" id="import-file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden><div class="heading-actions" style="justify-content:center;margin-top:10px"><button class="btn btn-secondary" type="button" data-action="choose-file">Seleccionar archivo</button><button class="btn btn-primary" type="button" data-action="preview-import">Validar archivo</button></div></div></div>
        <div class="callout">En <strong>categoria</strong> escribe la materia (por ejemplo, Matemáticas o Español); en <strong>competencia</strong> y <strong>puntaje_defecto</strong> registra los datos obligatorios de cada pregunta. La materia queda registrada como categoría y se asigna a la pregunta.</div>
        <div class="callout">Primero se valida el archivo en el servidor. Si existe alguna fila inválida o duplicada, la importación completa se cancela para evitar guardar datos parciales.</div>
        <div id="import-preview" hidden></div></section>
      <section class="panel"><div class="panel-title"><div><h3>Historial de importaciones</h3><p>Resultado de las cargas anteriores realizadas en el sistema.</p></div></div>
        ${table(['ARCHIVO / RESPONSABLE', 'FECHA', 'FILAS', 'IMPORTADAS', 'DUPLICADAS', 'ERRORES'], rows, 'No se han registrado importaciones.')}</section>`;
    bindTableFilters();
    const fileInput = $('#import-file');
    fileInput.addEventListener('change', () => {
      $('#selected-file').textContent = fileInput.files[0]?.name || 'Ningún archivo seleccionado';
      app.importDraft = null;
      $('#import-preview').hidden = true;
    });
    const zone = $('#drop-zone');
    zone.addEventListener('dragover', event => { event.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', event => {
      event.preventDefault();
      zone.classList.remove('dragover');
      if (event.dataTransfer.files.length) {
        fileInput.files = event.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });
  }

  async function renderQuizzes() {
    const [quizzes, questions] = await Promise.all([api.get('quizzes/'), api.get('questions/')]);
    app.quizzesCache = quizzes;
    app.questionsCache = questions;
    const rows = quizzes.map(quiz => `<tr data-active="${quiz.is_active}" data-search="${escapeHtml(`${quiz.title} ${quiz.description}`.toLocaleLowerCase('es'))}">
      <td><strong>${escapeHtml(quiz.title)}</strong><small>${escapeHtml(quiz.description || 'Sin descripción')}</small></td>
      <td>${quiz.question_count}</td><td>${escapeHtml(quiz.duration_minutes)} min</td>
      <td>${escapeHtml(formatDate(quiz.opens_at))}<small>Cierra ${escapeHtml(formatDate(quiz.closes_at))}</small></td>
      <td>${escapeHtml(quiz.attempts_allowed)}</td><td>${statusPill(quiz.is_active, 'Habilitado', 'Deshabilitado')}</td>
      <td><div class="table-actions"><button class="icon-action" data-action="quiz-edit" data-id="${quiz.id}" title="Editar cuestionario">✎</button><button class="icon-action ${quiz.is_active ? 'danger' : ''}" data-action="quiz-toggle" data-id="${quiz.id}" title="${quiz.is_active ? 'Deshabilitar' : 'Habilitar'}">${quiz.is_active ? '⊘' : '✓'}</button></div></td></tr>`);
    $('#page-content').innerHTML = `${heading('Cuestionarios', 'Configura evaluaciones, disponibilidad, preguntas y número de intentos.', '<button class="btn btn-primary" data-action="quiz-new">＋ Crear cuestionario</button>')}
      ${toolbar('Buscar cuestionario', `<select class="select-field" data-status-filter><option value="">Todos los estados</option><option value="true">Habilitados</option><option value="false">Deshabilitados</option></select>`)}
      ${table(['CUESTIONARIO', 'PREGUNTAS', 'DURACIÓN', 'DISPONIBILIDAD', 'INTENTOS', 'ESTADO', 'ACCIONES'], rows, 'Aún no hay cuestionarios configurados.')}`;
    bindTableFilters();
  }

  async function renderAvailable() {
    const quizzes = await api.get('quizzes/available/');
    app.availableQuizzes = quizzes;
    const search = `<div class="toolbar"><input class="search-field" type="search" data-quiz-search placeholder="Buscar evaluaciones"><span class="count-note">${quizzes.length} disponible${quizzes.length === 1 ? '' : 's'}</span></div>`;
    $('#page-content').innerHTML = `${heading('Evaluaciones disponibles', 'Consulta las condiciones antes de comenzar un intento.')}
      ${search}${quizzes.length ? `<div class="quiz-card-grid">${quizzes.map(quizCard).join('')}</div>` : '<div class="panel empty-state"><div class="empty-icon">▣</div>No hay cuestionarios habilitados para tu cuenta en este momento.</div>'}`;
    $('[data-quiz-search]')?.addEventListener('input', event => {
      const term = event.target.value.toLocaleLowerCase('es');
      $$('.quiz-card', $('#page-content')).forEach(card => { card.hidden = !card.textContent.toLocaleLowerCase('es').includes(term); });
    });
  }

  async function renderResults(ownOnly) {
    const attempts = await api.get('attempts/');
    const items = ownOnly ? attempts.filter(item => item.student_username === app.user.username) : attempts;
    const historyPage = app.page === 'history';
    const columns = ownOnly
      ? historyPage
        ? ['ESTUDIANTE', 'CUESTIONARIO', 'INTENTO', 'PUNTAJE', 'NOTA', 'ESTADO', 'DURACIÓN', 'FECHA', 'REVISIÓN']
        : ['CUESTIONARIO', 'FECHA', 'CALIFICACIÓN', 'ESTADO', 'DETALLE']
      : ['ESTUDIANTE', 'CUESTIONARIO', 'INICIO', 'FINALIZACIÓN', 'CALIFICACIÓN', 'ESTADO', 'DETALLE'];
    const rows = items.map(item => {
      return ownOnly
        ? historyPage
          ? `<tr data-search="${escapeHtml(`${item.quiz_title} ${item.status} ${fullName()} ${item.student_code}`.toLocaleLowerCase('es'))}" data-status="${item.status}" data-quiz="${item.quiz}">
            <td><strong>${escapeHtml(fullName())}</strong><small>${escapeHtml(item.student_code || '')}</small></td>
            <td>${escapeHtml(item.quiz_title)}</td><td>${escapeHtml(item.attempt_number)}</td>
            <td>${item.grade === null ? '—' : `${escapeHtml(item.grade)} / ${escapeHtml(item.max_grade)}`}</td>
            <td><strong>${item.grade === null ? '—' : `${escapeHtml(item.grade)} / ${escapeHtml(item.max_grade)}`}</strong></td>
            <td>${gradePill(item.grade, item.max_grade, item.passing_grade)}</td><td>${escapeHtml(item.elapsed_minutes ?? '—')} min</td>
            <td>${escapeHtml(formatDate(item.submitted_at || item.started_at, { dateStyle: 'short', timeStyle: 'short' }))}</td>
            <td><button class="text-link" data-action="attempt-detail" data-id="${item.id}">Ver detalle</button></td></tr>`
          : `<tr data-search="${escapeHtml(`${item.quiz_title} ${item.status}`.toLocaleLowerCase('es'))}" data-status="${item.status}" data-quiz="${item.quiz}">
            <td><strong>${escapeHtml(item.quiz_title)}</strong><small>Intento ${escapeHtml(item.attempt_number)} · Nota máxima ${escapeHtml(item.max_grade)}</small></td>
            <td>${escapeHtml(formatDate(item.submitted_at || item.started_at))}</td>
            <td><strong>${item.grade === null ? 'En curso' : `${escapeHtml(item.grade)} / ${escapeHtml(item.max_grade)}`}</strong></td>
            <td>${gradePill(item.grade, item.max_grade, item.passing_grade)}</td>
            <td><button class="text-link" data-action="attempt-detail" data-id="${item.id}">Ver detalle</button></td></tr>`
        : `<tr data-search="${escapeHtml(`${item.student_username} ${item.quiz_title} ${item.status}`.toLocaleLowerCase('es'))}" data-status="${item.status}">
          <td><strong>${escapeHtml(item.student_username)}</strong></td><td>${escapeHtml(item.quiz_title)}</td>
          <td>${escapeHtml(formatDate(item.started_at))}</td><td>${escapeHtml(formatDate(item.submitted_at))}</td>
          <td>${item.grade === null ? '—' : `<strong>${escapeHtml(item.grade)} / ${escapeHtml(item.max_grade)}</strong>`}</td>
          <td>${item.status === 'COMPLETED' ? gradePill(item.grade, item.max_grade, item.passing_grade) : '<span class="status-pill pill-amber">En curso</span>'}</td>
          <td><button class="icon-action" data-action="attempt-detail" data-id="${item.id}" title="Ver detalle">↗</button></td></tr>`;
    });
    const quizFilter = [...new Map(items.map(item => [item.quiz, item.quiz_title])).entries()];
    const filters = `<select class="select-field" data-status-filter><option value="">Todos los estados</option><option value="COMPLETED">Finalizados</option><option value="IN_PROGRESS">En curso</option></select>
      <select class="select-field" data-quiz-filter><option value="">Todos los cuestionarios</option>${quizFilter.map(([id, title]) => `<option value="${id}">${escapeHtml(title)}</option>`).join('')}</select>`;
    const grades = items.filter(item => item.status === 'COMPLETED').map(item => Number(item.grade)).filter(Number.isFinite);
    const average = grades.length ? (grades.reduce((sum, grade) => sum + grade, 0) / grades.length).toFixed(2) : '—';
    const intro = ownOnly
      ? historyPage ? 'Revisa el detalle de tus evaluaciones anteriores.' : 'Consulta tus calificaciones e intentos personales.'
      : 'Consulta los resultados de los estudiantes según los permisos asignados a tu rol.';
    const exportButton = '<button class="btn btn-secondary" data-action="export-results">↓ Exportar CSV</button>';
    const title = ownOnly ? historyPage ? 'Historial de intentos' : 'Mis resultados' : 'Resultados de evaluaciones';
    const tablePanel = `<section class="panel"><div class="panel-title"><div><h3>Registro de intentos</h3><p>Los resultados se generan a partir de los intentos enviados.</p></div>${exportButton}</div>
      ${toolbar(ownOnly ? 'Buscar cuestionario' : 'Buscar estudiante o cuestionario', filters)}
      ${table(columns, rows, 'Aún no se han registrado resultados.')}</section>`;
    $('#page-content').innerHTML = `${heading(title, intro)}
      ${ownOnly && !historyPage ? `<div class="metric-grid">${metric('Evaluaciones finalizadas', grades.length, 'En tu historial', '✓')}${metric('Promedio', average, 'Sobre tus calificaciones', '↗')}${metric('Aprobadas', items.filter(item => item.status === 'COMPLETED' && Number(item.grade) >= Number(item.passing_grade || 3)).length, 'Según la nota mínima', '★')}${metric('En curso', items.filter(item => item.status === 'IN_PROGRESS').length, 'Intentos activos', '◷')}</div>` : ''}
      ${ownOnly ? tablePanel : `<section class="panel"><div class="panel-title"><div><h3>Registro de resultados</h3><p>Resultados disponibles para tu rol.</p></div>${exportButton}</div>${toolbar('Buscar estudiante o cuestionario', filters)}${table(columns, rows, 'Aún no se han registrado resultados.')}</section>`}`;
    bindTableFilters();
  }

  async function renderProfile() {
    const profile = await api.get('auth/me/');
    app.user = profile;
    setIdentity();
    $('#page-content').innerHTML = `${heading('Mi perfil', 'Edita tus datos personales y la seguridad de tu cuenta.')}
      <section class="profile-info student-profile"><div class="student-profile-heading"><div class="profile-large-avatar">${escapeHtml(initials(fullName(profile)))}</div>
        <div><h3>${escapeHtml(fullName(profile))}</h3><p>${escapeHtml(profile.role)} · ${escapeHtml(profile.is_active === false ? 'Inactivo' : 'Activo')} · Código ${escapeHtml(profile.institutional_code || 'No asignado')}</p></div></div>
        <form data-form="profile" class="form-grid student-profile-form">
          ${field('Nombre', 'first_name', profile.first_name || '', 'text', true)}
          ${field('Apellido', 'last_name', profile.last_name || '')}
          ${field('Código institucional', 'institutional_code', profile.institutional_code || 'No asignado', 'text', false, false, 'readonly')}
          ${field('Rol (no editable)', 'role_display', profile.role || '', 'text', false, false, 'readonly')}
          ${field('Correo electrónico', 'email', profile.email || '', 'email')}
          <div class="field full"><div class="heading-actions"><button class="btn btn-primary" type="submit">Guardar perfil</button><button class="btn btn-secondary" type="button" data-action="password-edit">Cambiar contraseña</button></div></div>
          <div class="field full" data-form-error hidden></div>
        </form></section>`;
  }

  async function renderSettings() {
    const settings = await api.get('settings/');
    app.settings = settings;
    $('#page-content').innerHTML = `${heading('Configuración del sistema', 'Personaliza la información institucional que identifica la plataforma.')}
      <section class="panel"><div class="panel-title"><div><h3>Información general</h3><p>Estos datos se almacenan en la base de datos del sistema.</p></div></div>
        <form data-form="settings" class="form-grid">
          ${field('Nombre del sistema', 'system_name', settings.system_name, 'text', true)}
          ${field('Institución', 'institution_name', settings.institution_name, 'text', true)}
          ${field('Correo de soporte', 'support_email', settings.support_email, 'email', true)}
          <div class="field"><label for="setting-timezone">Zona horaria</label><select name="time_zone" id="setting-timezone"><option value="America/Bogota" ${settings.time_zone === 'America/Bogota' ? 'selected' : ''}>America/Bogota</option><option value="UTC" ${settings.time_zone === 'UTC' ? 'selected' : ''}>UTC</option></select></div>
          <div class="field full"><button class="btn btn-primary" type="submit">Guardar configuración</button><span class="field-hint">Última actualización: ${escapeHtml(formatDate(settings.updated_at))}</span></div>
        </form></section>`;
  }

  function field(label, name, value = '', type = 'text', required = false, full = false, extra = '') {
    return `<div class="field ${full ? 'full' : ''}"><label for="field-${name}">${escapeHtml(label)}${required ? ' *' : ''}</label><input id="field-${name}" name="${escapeHtml(name)}" type="${escapeHtml(type)}" value="${escapeHtml(value)}" ${required ? 'required' : ''} ${extra}></div>`;
  }

  function bindTableFilters() {
    const content = $('#page-content');
    $$('[data-table-search], [data-status-filter], [data-quiz-filter], [data-category-filter], [data-competency-filter], [data-question-type-filter]', content).forEach(input => {
      input.addEventListener('input', () => filterTable($('[data-table-search]', content) || { value: '' }));
      input.addEventListener('change', () => filterTable($('[data-table-search]', content) || { value: '' }));
    });
    filterTable($('[data-table-search]', content) || { value: '' });
  }

  function modal(title, subtitle, body, options = {}) {
    const root = $('#modal-root');
    root.innerHTML = `<div class="modal ${options.wide ? 'modal-wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-header"><div><h2 id="modal-title">${escapeHtml(title)}</h2>${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ''}</div><button class="modal-close" type="button" data-action="modal-close" aria-label="Cerrar">×</button></div>
      <div class="modal-body">${body}</div>${options.footer === false ? '' : `<div class="modal-footer"><button class="btn btn-secondary" type="button" data-action="modal-close">Cancelar</button><button class="btn btn-primary" type="submit" form="${escapeHtml(options.formId || 'modal-form')}">${escapeHtml(options.submitLabel || 'Guardar cambios')}</button></div>`}</div>`;
    root.hidden = false;
    root.onclick = event => { if (event.target === root) closeModal(); };
    const firstInput = $('input:not([type="hidden"]), select, textarea', root);
    firstInput?.focus();
  }

  function closeModal() {
    $('#modal-root').hidden = true;
    $('#modal-root').replaceChildren();
  }

  function roleOptions(selectedId = '') {
    return (app.rolesCache || []).map(role => `<option value="${role.id}" ${String(role.id) === String(selectedId) ? 'selected' : ''}>${escapeHtml(role.name)}</option>`).join('');
  }

  function showUserForm(user = null) {
    const edit = Boolean(user);
    const body = `<form id="modal-form" data-form="user" data-id="${user?.id || ''}" class="form-grid">
      ${field('Nombres', 'first_name', user?.first_name || '', 'text', true)}
      ${field('Apellidos', 'last_name', user?.last_name || '')}
      ${field('Nombre de usuario', 'username', user?.username || '', 'text', true, false, edit ? 'readonly' : 'autocomplete="username"')}
      ${field('Correo electrónico', 'email', user?.email || '', 'email')}
      ${field('Código institucional', 'institutional_code', user?.institutional_code || '')}
      <div class="field"><label for="user-role">Rol *</label><select id="user-role" name="role_id" required><option value="">Selecciona un rol</option>${roleOptions(user?.assigned_role_id)}</select></div>
      ${field(edit ? 'Nueva contraseña (opcional)' : 'Contraseña inicial', 'password', '', 'password', !edit, false, 'autocomplete="new-password" minlength="8')}
      <div class="field full"><label><input type="checkbox" name="is_active" ${user?.is_active !== false ? 'checked' : ''}> Cuenta activa</label><span class="field-hint">Las cuentas desactivadas no pueden iniciar sesión.</span></div>
      <div class="field full" data-form-error hidden></div></form>`;
    modal(edit ? 'Editar usuario' : 'Crear usuario', 'Los permisos efectivos dependen del rol asignado.', body, { formId: 'modal-form' });
  }

  async function showRoleForm(role = null) {
    const roles = app.permissionCatalog || await api.get('role-permissions/');
    const permissionGroups = {
      'Administración': ['users.manage', 'roles.manage', 'settings.manage'],
      'Evaluación': ['questions.manage', 'quizzes.manage', 'quizzes.take'],
      'Resultados': ['results.view_all', 'results.view_assigned', 'results.view_own'],
    };
    const permissionsHtml = Object.entries(permissionGroups).map(([group, codes]) => `<div class="permission-section-title">${group}</div>${codes.map(code => {
      const definition = roles.find(permission => permission.code === code);
      return `<label class="permission-item"><input type="checkbox" name="permissions" value="${escapeHtml(code)}" ${role?.permissions.includes(code) ? 'checked' : ''}>
        <span><b>${escapeHtml(definition?.label || PERMISSION_LABELS[code])}</b><small>${escapeHtml(code)}</small></span></label>`;
    }).join('')}`).join('');
    const body = `<form id="modal-form" data-form="role" data-id="${role?.id || ''}" class="form-grid">
      ${field('Nombre del rol', 'name', role?.name || '', 'text', true)}
      ${field('Identificador (slug)', 'slug', role?.slug || '', 'text', true)}
      <div class="field full"><label for="role-description">Descripción</label><input id="role-description" name="description" value="${escapeHtml(role?.description || '')}"></div>
      <div class="field full"><label><input type="checkbox" name="is_active" ${role?.is_active !== false ? 'checked' : ''}> Rol activo</label><span class="field-hint">Desactivarlo bloquea el acceso a quienes lo tienen asignado.</span></div>
      <div class="field full"><label>Permisos</label><div class="permission-list">${permissionsHtml}</div></div><div class="field full" data-form-error hidden></div></form>`;
    modal(role ? 'Editar rol' : 'Crear rol', 'Asigna únicamente los permisos necesarios para este rol.', body);
    $('#field-name').addEventListener('input', () => {
      if (!role) $('#field-slug').value = slugify($('#field-name').value);
    });
    app.rolesCache = (app.rolesCache || []).filter(item => item.is_active);
  }

  function slugify(value) {
    return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  function showCategoryForm(category = null) {
    const body = `<form id="modal-form" data-form="category" data-id="${category?.id || ''}" class="form-grid">
      ${field('Nombre', 'name', category?.name || '', 'text', true)}
      ${field('Competencia', 'competency', category?.competency || '')}
      <div class="field full"><label><input type="checkbox" name="is_active" ${category?.is_active !== false ? 'checked' : ''}> Categoría activa</label></div>
      <div class="field full" data-form-error hidden></div></form>`;
    modal(category ? 'Editar categoría' : 'Nueva categoría', 'Las categorías activas pueden asignarse a preguntas nuevas.', body);
  }

  function showQuestionForm(question = null) {
    const categories = (app.categoriesCache || []).filter(category => category.is_active || String(category.id) === String(question?.category));
    const options = ['A', 'B', 'C', 'D'];
    const existing = question?.options || [];
    const body = `<form id="modal-form" data-form="question" data-id="${question?.id || ''}" class="form-grid">
      <div class="field"><label for="question-category">Materia / categoría *</label><select id="question-category" name="category" required><option value="">Selecciona una materia</option>${categories.map(category => `<option value="${category.id}" ${String(category.id) === String(question?.category) ? 'selected' : ''}>${escapeHtml(category.name)}${category.is_active ? '' : ' (inactiva)'}</option>`).join('')}</select></div>
      <div class="field"><label for="question-type">Tipo *</label><select id="question-type" name="type"><option value="MULTIPLE" ${question?.type !== 'VERDADERO_FALSO' ? 'selected' : ''}>Selección múltiple</option><option value="VERDADERO_FALSO" ${question?.type === 'VERDADERO_FALSO' ? 'selected' : ''}>Verdadero / Falso</option></select></div>
      ${field('Competencia', 'competency', question?.competency || '', 'text', true)}
      ${field('Puntaje', 'default_score', question?.default_score ?? '1', 'number', true, false, 'min="0.01" max="999.99" step="0.01')}
      <div class="field full"><label for="question-base">Texto base (opcional)</label><textarea id="question-base" name="base_text">${escapeHtml(question?.base_text || '')}</textarea></div>
      <div class="field full"><label for="question-stem">Enunciado *</label><textarea id="question-stem" name="stem" required>${escapeHtml(question?.stem || '')}</textarea></div>
      <div class="field full"><label for="question-feedback">Retroalimentación (opcional)</label><textarea id="question-feedback" name="feedback">${escapeHtml(question?.feedback || '')}</textarea></div>
      <div class="field full"><label>Opciones · marca una respuesta correcta</label><div class="option-editor">${options.map((letter, index) => {
        const option = existing.find(item => item.letter === letter);
        const defaultText = question?.type === 'VERDADERO_FALSO' ? (letter === 'A' ? 'Verdadero' : 'Falso') : '';
        return `<div class="field"><input type="radio" name="correct_option" value="${letter}" ${option?.is_correct || (!question && letter === 'A') ? 'checked' : ''} aria-label="Opción correcta ${letter}"><input type="text" name="option_${letter}" maxlength="500" value="${escapeHtml(option?.text || defaultText)}" placeholder="Opción ${letter}" ${letter === 'A' || letter === 'B' ? 'required' : ''}></div>`;
      }).join('')}</div></div>
      <div class="field full"><label><input type="checkbox" name="is_active" ${question?.is_active !== false ? 'checked' : ''}> Pregunta activa</label></div>
      <div class="field full" data-form-error hidden></div></form>`;
    modal(question ? 'Editar pregunta' : 'Crear pregunta', 'Completa los campos y define exactamente una opción correcta.', body, { wide: true });
    $('#question-type').addEventListener('change', updateQuestionTypeFields);
    updateQuestionTypeFields();
  }

  function updateQuestionTypeFields() {
    const trueFalse = $('#question-type')?.value === 'VERDADERO_FALSO';
    ['C', 'D'].forEach(letter => {
      const input = $(`[name="option_${letter}"]`);
      if (!input) return;
      input.disabled = trueFalse;
      input.required = false;
      input.value = trueFalse ? '' : input.value;
    });
    if (trueFalse) {
      $('[name="option_A"]').value = 'Verdadero';
      $('[name="option_B"]').value = 'Falso';
    }
  }

  function showQuizForm(quiz = null) {
    const selectedIds = new Set((quiz?.question_ids || []).map(Number));
    const quizQuestions = (app.questionsCache || []).filter(question => question.is_active || selectedIds.has(question.id));
    const body = `<form id="modal-form" data-form="quiz" data-id="${quiz?.id || ''}" class="form-grid">
      ${field('Nombre del cuestionario', 'title', quiz?.title || '', 'text', true, true)}
      <div class="field full"><label for="quiz-description">Descripción</label><textarea id="quiz-description" name="description">${escapeHtml(quiz?.description || '')}</textarea></div>
      ${field('Fecha y hora de apertura', 'opens_at', dateInputValue(quiz?.opens_at), 'datetime-local', true)}
      ${field('Fecha y hora de cierre', 'closes_at', dateInputValue(quiz?.closes_at), 'datetime-local', true)}
      ${field('Duración (minutos)', 'duration_minutes', quiz?.duration_minutes ?? 60, 'number', true, false, 'min="1" step="1')}
      ${field('Intentos permitidos', 'attempts_allowed', quiz?.attempts_allowed ?? 1, 'number', true, false, 'min="1" step="1')}
      ${field('Nota máxima', 'max_grade', quiz?.max_grade ?? 5, 'number', true, false, 'min="0.01" max="100" step="0.01')}
      ${field('Nota mínima para aprobar', 'passing_grade', quiz?.passing_grade ?? 3, 'number', true, false, 'min="0" max="100" step="0.01')}
      <div class="field full"><label for="quiz-questions">Preguntas * <span class="field-hint">Mantén presionada Ctrl (Windows) o ⌘ (Mac) para seleccionar varias.</span></label>
        <select id="quiz-questions" name="question_ids" multiple required size="6">${quizQuestions.map(question => `<option value="${question.id}" ${selectedIds.has(question.id) ? 'selected' : ''}>${escapeHtml(question.category_name)}${question.is_active ? '' : ' (inactiva)'} · ${escapeHtml(question.stem.slice(0, 110))}</option>`).join('')}</select></div>
      <div class="field full"><label><input type="checkbox" name="is_active" ${quiz?.is_active ? 'checked' : ''}> Cuestionario habilitado</label><span class="field-hint">Solo se mostrará dentro de su ventana de disponibilidad.</span></div>
      <div class="field full" data-form-error hidden></div></form>`;
    modal(quiz ? 'Editar cuestionario' : 'Crear cuestionario', 'Define fechas, duración, preguntas e intentos permitidos.', body, { wide: true });
  }

  function showProfileForm() {
    const user = app.user;
    const body = `<form id="modal-form" data-form="profile" class="form-grid">
      ${field('Nombres', 'first_name', user.first_name || '', 'text', true)}
      ${field('Apellidos', 'last_name', user.last_name || '')}
      ${field('Correo electrónico', 'email', user.email || '', 'email')}
      ${field('Código institucional', 'institutional_code', user.institutional_code || '')}
      <div class="field full" data-form-error hidden></div></form>`;
    modal('Editar información personal', 'El nombre de usuario y el rol son administrados por la institución.', body);
  }

  function showPasswordForm() {
    const body = `<form id="modal-form" data-form="password" class="form-grid">
      ${field('Contraseña actual', 'current_password', '', 'password', true, true, 'autocomplete="current-password"')}
      ${field('Nueva contraseña', 'new_password', '', 'password', true, true, 'autocomplete="new-password" minlength="8"')}
      ${field('Confirmar nueva contraseña', 'confirm_password', '', 'password', true, true, 'autocomplete="new-password" minlength="8')}
      <div class="field full" data-form-error hidden></div></form>`;
    modal('Cambiar contraseña', 'Usa una contraseña segura que no hayas utilizado antes.', body);
  }

  function formDataObject(form) {
    const data = new FormData(form);
    return Object.fromEntries(data.entries());
  }

  function formError(form, error) {
    const box = $('[data-form-error]', form);
    if (box) {
      box.classList.add('form-message', 'error-message');
      showError(box, error.message);
    }
    else toast(error.message, 'error');
  }

  async function submitForm(form) {
    const formType = form.dataset.form;
    const id = form.dataset.id;
    const values = formDataObject(form);
    const button = $(`[form="${form.id}"][type="submit"]`);
    if (button) button.disabled = true;
    try {
      if (formType === 'user') {
        const payload = {
          first_name: values.first_name.trim(),
          last_name: values.last_name.trim(),
          username: values.username.trim(),
          email: values.email.trim(),
          institutional_code: values.institutional_code.trim(),
          role_id: Number(values.role_id),
          is_active: form.elements.is_active.checked,
        };
        if (values.password) payload.password = values.password;
        await (id ? api.patch(`users/${id}/`, payload) : api.post('users/', payload));
      } else if (formType === 'role') {
        const selected = $$('input[name="permissions"]:checked', form).map(input => input.value);
        const payload = {
          name: values.name.trim(),
          slug: slugify(values.slug),
          description: values.description.trim(),
          permissions: selected,
          is_active: form.elements.is_active.checked,
        };
        await (id ? api.patch(`roles/${id}/`, payload) : api.post('roles/', payload));
      } else if (formType === 'category') {
        const payload = { name: values.name.trim(), competency: values.competency.trim(), is_active: form.elements.is_active.checked };
        await (id ? api.patch(`categories/${id}/`, payload) : api.post('categories/', payload));
      } else if (formType === 'question') {
        const type = values.type;
        const correct = values.correct_option;
        const options = ['A', 'B', 'C', 'D']
          .filter(letter => values[`option_${letter}`]?.trim())
          .map(letter => ({ letter, text: values[`option_${letter}`].trim(), is_correct: letter === correct }));
        const payload = {
          category: Number(values.category),
          type,
          competency: values.competency.trim(),
          base_text: values.base_text.trim(),
          stem: values.stem.trim(),
          feedback: values.feedback.trim(),
          default_score: values.default_score,
          is_active: form.elements.is_active.checked,
          options,
        };
        await (id ? api.put(`questions/${id}/`, payload) : api.post('questions/', payload));
      } else if (formType === 'quiz') {
        const payload = {
          title: values.title.trim(),
          description: values.description.trim(),
          opens_at: new Date(values.opens_at).toISOString(),
          closes_at: new Date(values.closes_at).toISOString(),
          duration_minutes: Number(values.duration_minutes),
          attempts_allowed: Number(values.attempts_allowed),
          max_grade: values.max_grade,
          passing_grade: values.passing_grade,
          question_ids: [...form.elements.question_ids.selectedOptions].map(option => Number(option.value)),
          is_active: form.elements.is_active.checked,
        };
        await (id ? api.patch(`quizzes/${id}/`, payload) : api.post('quizzes/', payload));
      } else if (formType === 'profile') {
        await api.patch('auth/me/', {
          first_name: values.first_name.trim(),
          last_name: values.last_name.trim(),
          email: values.email.trim(),
          institutional_code: app.user.institutional_code || '',
        });
        app.user = await api.get('auth/me/');
        setIdentity();
      } else if (formType === 'password') {
        if (values.new_password !== values.confirm_password) throw new Error('La confirmación no coincide con la nueva contraseña.');
        await api.post('auth/password/', { current_password: values.current_password, new_password: values.new_password });
      } else if (formType === 'settings') {
        app.settings = await api.patch('settings/', {
          system_name: values.system_name.trim(),
          institution_name: values.institution_name.trim(),
          support_email: values.support_email.trim(),
          time_zone: values.time_zone,
        });
        setInstitutionName(app.settings.institution_name);
      }
      closeModal();
      toast('Los cambios se guardaron correctamente.');
      await refreshPage();
    } catch (error) {
      formError(form, error);
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function refreshPage() {
    const page = app.page;
    if (page === 'result' || page === 'exam') return;
    await navigate(page);
  }

  async function toggleActive(resource, id, current, name) {
    const next = !current;
    const confirmation = next ? `¿Activar ${name}?` : `¿Desactivar ${name}?`;
    if (!window.confirm(confirmation)) return;
    try {
      await api.patch(`${resource}/${id}/`, { is_active: next });
      toast(`${name} ${next ? 'activado' : 'desactivado'} correctamente.`);
      await refreshPage();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  function lookup(items, id) {
    return (items || []).find(item => String(item.id) === String(id));
  }

  function openEdit(resource, id) {
    const cache = {
      users: app.usersCache,
      roles: app.rolesCache,
      categories: app.categoriesCache,
      questions: app.questionsCache,
      quizzes: app.quizzesCache,
    }[resource];
    const item = lookup(cache, id);
    if (!item) {
      toast('No se encontró el registro. Actualiza la página e inténtalo de nuevo.', 'error');
      return;
    }
    if (resource === 'users') showUserForm(item);
    else if (resource === 'roles') showRoleForm(item);
    else if (resource === 'categories') showCategoryForm(item);
    else if (resource === 'questions') showQuestionForm(item);
    else if (resource === 'quizzes') showQuizForm(item);
  }

  async function chooseQuizToStart(id) {
    const quiz = (app.dashboardQuizzes || app.availableQuizzes || []).find(item => String(item.id) === String(id));
    if (!quiz) {
      toast('No se encontró el cuestionario.', 'error');
      return;
    }
    const accepted = window.confirm(`INSTRUCCIONES\n\n${quiz.title}\n\n• ${quiz.question_count} preguntas\n• Duración: ${quiz.duration_minutes} minutos\n• Nota máxima: ${quiz.max_grade}\n• Intentos restantes: ${quiz.attempts_remaining}\n\nTu respuesta se guarda al seleccionarla. El tiempo inicia al comenzar. ¿Deseas iniciar ahora?`);
    if (!accepted) return;
    try {
      app.activeAttempt = await api.post(`quizzes/${quiz.id}/attempts/`, {});
      app.currentQuestion = 0;
      app.submitting = false;
      app.pendingAnswers.clear();
      app.answers = {};
      app.answerQueues = new Map();
      app.answerVersions = new Map();
      app.deadline = new Date(app.activeAttempt.started_at).getTime() + app.activeAttempt.duration_minutes * 60 * 1000;
      localStorage.setItem('saber-tyt-active-attempt', String(app.activeAttempt.id));
      navigate('exam');
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  async function resumePendingAttempt() {
    if (!can('quizzes.take') || !can('results.view_own')) return;
    try {
      const attempts = await api.get('attempts/');
      const attempt = attempts.find(item => item.status === 'IN_PROGRESS' && item.student_username === app.user.username);
      if (!attempt || app.page !== 'dashboard') return;
      if (window.confirm(`Tienes una evaluación en curso: “${attempt.quiz_title}”. ¿Quieres retomarla?`)) {
        app.activeAttempt = await api.get(`attempts/${attempt.id}/`);
        app.currentQuestion = 0;
        app.answers = app.activeAttempt.saved_answers || {};
        app.answerQueues = new Map();
        app.answerVersions = new Map();
        app.deadline = new Date(app.activeAttempt.started_at).getTime() + app.activeAttempt.duration_minutes * 60 * 1000;
        localStorage.setItem('saber-tyt-active-attempt', String(app.activeAttempt.id));
        navigate('exam');
      }
    } catch (error) {
      if (!error.message.includes('403')) console.error('No se pudo verificar el intento en curso.', error);
    }
  }

  function renderExam() {
    const attempt = app.activeAttempt;
    if (!attempt || !attempt.questions?.length) {
      $('#page-content').innerHTML = '<div class="panel empty-state">No se encontró una evaluación activa.</div>';
      return;
    }
    const question = attempt.questions[app.currentQuestion];
    const answers = app.answers || {};
    const selected = answers[question.id];
    const isLast = app.currentQuestion === attempt.questions.length - 1;
    $('#page-content').innerHTML = `<section class="exam-header"><div><h2>${escapeHtml(attempt.quiz_title)}</h2><p>Pregunta ${app.currentQuestion + 1} de ${attempt.questions.length} · Las respuestas se guardan automáticamente.</p></div><div class="exam-timer" id="exam-timer">--:--</div></section>
      <div class="exam-layout"><section class="exam-question"><div class="exam-question-number">PREGUNTA ${app.currentQuestion + 1} · ${escapeHtml(question.category)}</div>
        ${question.base_text ? `<div class="callout">${escapeHtml(question.base_text)}</div>` : ''}
        <h3>${escapeHtml(question.stem)}</h3>
        <div>${question.options.map(option => `<label class="exam-option ${Number(selected) === option.id ? 'selected' : ''}"><input type="radio" name="exam-option" value="${option.id}" ${Number(selected) === option.id ? 'checked' : ''}><span><b>${escapeHtml(option.letter)}.</b> ${escapeHtml(option.text)}</span></label>`).join('')}</div>
        <div class="exam-controls"><button class="btn btn-secondary" data-action="exam-prev" ${app.currentQuestion === 0 ? 'disabled' : ''}>← Anterior</button>
          ${isLast ? '<button class="btn btn-primary" data-action="exam-submit">Revisar y finalizar</button>' : '<button class="btn btn-primary" data-action="exam-next">Siguiente →</button>'}</div>
        <div class="form-message error-message" id="exam-error" hidden></div></section>
        <aside class="exam-number-panel"><h3>Navegación</h3><p>Verde = respondida. Selecciona un número para ir a una pregunta.</p><div class="question-numbers">${attempt.questions.map((item, index) => `<button class="question-number ${index === app.currentQuestion ? 'current' : ''} ${answers[item.id] ? 'answered' : ''}" data-action="exam-go" data-index="${index}" aria-label="Pregunta ${index + 1}">${index + 1}</button>`).join('')}</div>
          <p style="margin-top:12px">Respondidas: ${Object.keys(answers).length} de ${attempt.questions.length}</p></aside></div>`;
    clearInterval(app.timerId);
    updateExamTimer();
    app.timerId = window.setInterval(updateExamTimer, 1000);
    $$('input[name="exam-option"]', $('#page-content')).forEach(input => {
      input.addEventListener('change', () => saveAnswer(question.id, Number(input.value)));
    });
  }

  async function saveAnswer(questionId, optionId) {
    if (!app.answers) app.answers = {};
    if (!app.answerQueues) app.answerQueues = new Map();
    if (!app.answerVersions) app.answerVersions = new Map();
    app.answers[questionId] = optionId;
    const version = (app.answerVersions.get(questionId) || 0) + 1;
    app.answerVersions.set(questionId, version);
    app.pendingAnswers.add(questionId);
    renderExam();
    try {
      const previous = app.answerQueues.get(questionId) || Promise.resolve();
      const pending = previous.catch(() => {}).then(() =>
        api.post(`attempts/${app.activeAttempt.id}/answers/`, { question_id: questionId, option_id: optionId }));
      app.answerQueues.set(questionId, pending);
      await pending;
    } catch (error) {
      if (app.answerVersions.get(questionId) === version) {
        delete app.answers[questionId];
        renderExam();
      }
      const errorBox = $('#exam-error');
      if (errorBox) showError(errorBox, error.message);
    } finally {
      if (app.answerQueues.get(questionId) === undefined || app.answerVersions.get(questionId) === version) {
        app.pendingAnswers.delete(questionId);
      }
    }
  }

  function updateExamTimer() {
    if (!app.activeAttempt) return;
    const seconds = Math.max(0, Math.floor((app.deadline - Date.now()) / 1000));
    const timer = $('#exam-timer');
    if (timer) timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    if (seconds === 0 && !app.submitting) finishExam(false);
  }

  async function finishExam(ask = true) {
    if (!app.activeAttempt || app.submitting) return;
    const unanswered = app.activeAttempt.questions.length - Object.keys(app.answers || {}).length;
    if (ask && !window.confirm(unanswered
      ? `Tienes ${unanswered} pregunta(s) sin responder. ¿Finalizar y enviar la evaluación?`
      : '¿Estás seguro de que deseas finalizar y enviar la evaluación?')) return;
    app.submitting = true;
    clearInterval(app.timerId);
    try {
      while (app.pendingAnswers.size) await new Promise(resolve => window.setTimeout(resolve, 80));
      app.lastResult = await api.post(`attempts/${app.activeAttempt.id}/submit/`, {});
      app.activeAttempt = null;
      app.answers = {};
      app.answerQueues = new Map();
      app.answerVersions = new Map();
      localStorage.removeItem('saber-tyt-active-attempt');
      navigate('result');
    } catch (error) {
      app.submitting = false;
      toast(error.message, 'error');
      if (app.deadline > Date.now()) updateExamTimer();
    }
  }

  async function renderResult(result) {
    if (!result) {
      $('#page-content').innerHTML = '<div class="panel empty-state">No hay un resultado para mostrar.</div>';
      return;
    }
    const passed = Number(result.grade) >= Number(result.passing_grade || 3);
    $('#page-content').innerHTML = `<div class="result-hero"><div class="result-check">${passed ? '✓' : '!'}</div>
      <h2>${passed ? '¡Evaluación aprobada!' : 'Evaluación finalizada'}</h2>
      <p>${escapeHtml(result.quiz_title)} · ${escapeHtml(formatDate(result.submitted_at))}</p>
      <div class="result-grade">${escapeHtml(result.grade)} <small>/ ${escapeHtml(result.max_grade)}</small></div>
      <p>${passed ? 'Cumpliste con la nota mínima establecida.' : `La nota mínima para aprobar era ${escapeHtml(result.passing_grade)}.`}</p></div>
      <section class="panel"><div class="panel-title"><div><h3>Resumen del intento</h3><p>Tu calificación fue calculada y registrada por el servidor.</p></div></div>
        <div class="profile-detail"><span>Cuestionario</span><span>${escapeHtml(result.quiz_title)}</span></div>
        <div class="profile-detail"><span>Calificación final</span><span>${escapeHtml(result.grade)} / ${escapeHtml(result.max_grade)}</span></div>
        <div class="profile-detail"><span>Nota mínima</span><span>${escapeHtml(result.passing_grade)}</span></div>
        <div class="profile-detail"><span>Inicio</span><span>${escapeHtml(formatDate(result.started_at))}</span></div>
        <div class="profile-detail"><span>Finalización</span><span>${escapeHtml(formatDate(result.submitted_at))}</span></div>
        <div class="heading-actions" style="margin-top:16px"><button class="btn btn-primary" data-action="navigate" data-page="my-results">Ver mis calificaciones</button><button class="btn btn-secondary" data-action="navigate" data-page="available">Volver a cuestionarios</button></div></section>`;
    try { await api.get('attempts/'); } catch (error) { console.error('No se pudo actualizar el historial tras finalizar.', error); }
  }

  async function showAttemptDetails(id) {
    try {
      const attempt = await api.get(`attempts/${id}/`);
      const body = `<div class="profile-detail"><span>Estudiante</span><span>${escapeHtml(attempt.student_name || attempt.student_username)}${attempt.student_code ? ` · ${escapeHtml(attempt.student_code)}` : ''}</span></div>
        <div class="profile-detail"><span>Cuestionario</span><span>${escapeHtml(attempt.quiz_title)}</span></div>
        <div class="profile-detail"><span>Número de intento</span><span>${escapeHtml(attempt.attempt_number)}</span></div>
        <div class="profile-detail"><span>Estado</span><span>${attempt.status === 'COMPLETED' ? 'Finalizado' : 'En curso'}</span></div>
        <div class="profile-detail"><span>Inicio</span><span>${escapeHtml(formatDate(attempt.started_at))}</span></div>
        <div class="profile-detail"><span>Finalización</span><span>${escapeHtml(formatDate(attempt.submitted_at))}</span></div>
        <div class="profile-detail"><span>Duración</span><span>${escapeHtml(attempt.elapsed_minutes)} min</span></div>
        <div class="profile-detail"><span>Nota</span><span>${attempt.grade === null ? 'Pendiente' : `${escapeHtml(attempt.grade)} / ${escapeHtml(attempt.max_grade)}`}</span></div>
        <div class="callout">Las respuestas correctas no se exponen en este detalle. La calificación es calculada por Django al finalizar.</div>`;
      modal('Detalle del intento', 'Información del intento seleccionado.', body, { footer: false });
    } catch (error) { toast(error.message, 'error'); }
  }

  function showImportPreview(result, fileName) {
    app.importDraft = { rows: result.rows, fileName };
    app.importResult = result;
    const preview = $('#import-preview');
    const valid = result.valid;
    const subjects = [...new Set(result.rows.map(row => row.values?.categoria?.trim()).filter(Boolean))];
    const errorsByRow = new Map(result.errors.map(item => [String(item.rowNumber), item.errors]));
    const previewRows = result.rows.map(row => {
      const values = row.values || {};
      const type = values.tipo || '';
      const correct = type === 'VERDADERO_FALSO'
        ? ({ V: 'A', F: 'B' }[values.correcta?.toUpperCase()] || values.correcta || '')
        : values.correcta || '';
      const options = ['A', 'B', 'C', 'D']
        .filter(letter => values[`opcion_${letter.toLowerCase()}`])
        .map(letter => `<div><strong>${letter}:</strong> ${escapeHtml(values[`opcion_${letter.toLowerCase()}`])}</div>`)
        .join('');
      const rowErrors = errorsByRow.get(String(row.rowNumber)) || [];
      return `<tr><td>${escapeHtml(row.rowNumber ?? '—')}</td><td>${escapeHtml(values.categoria || '—')}</td>
        <td>${escapeHtml(values.competencia || '—')}</td><td>${type === 'VERDADERO_FALSO' ? 'Verdadero / Falso' : type === 'MULTIPLE' ? 'Selección múltiple' : escapeHtml(type || '—')}</td>
        <td><strong>${escapeHtml(values.enunciado || '—')}</strong>${values.texto_base ? `<small>Texto base: ${escapeHtml(values.texto_base)}</small>` : ''}</td>
        <td>${options || '—'}</td><td>${escapeHtml(correct || '—')}</td><td>${escapeHtml(values.puntaje_defecto || '—')}</td>
        <td>${escapeHtml(values.retroalimentacion || '—')}</td>
        <td>${rowErrors.length ? `<span class="status-pill pill-red">Corregir</span><small class="error-row">${rowErrors.map(escapeHtml).join('<br>')}</small>` : '<span class="status-pill pill-green">Válida</span>'}</td></tr>`;
    }).join('');
    preview.hidden = false;
    preview.innerHTML = `<div class="import-summary"><div class="summary-tile"><b>${result.total}</b><small>Filas revisadas</small></div><div class="summary-tile"><b>${valid}</b><small>Filas válidas</small></div><div class="summary-tile"><b>${result.failed}</b><small>Filas con errores</small></div></div>
      ${subjects.length ? `<div class="callout"><strong>Materias / categorías del archivo:</strong> ${subjects.map(escapeHtml).join(', ')}. Se crearán o reutilizarán al guardar.</div>` : ''}
      ${result.errors.length ? `<div class="callout error-row">Hay errores en el archivo. Corrige las filas señaladas y vuelve a validarlo antes de guardar.</div>
        <div class="callout">Las filas válidas y las observaciones de cada fila se muestran en la revisión. No se guardará ninguna pregunta hasta corregir todos los errores.</div>` : '<div class="callout">Validación completada. Revisa las materias, competencias, opciones, respuestas correctas y puntajes antes de confirmar.</div>'}
      <div class="table-wrap import-review-wrap"><table class="data-table import-review-table"><thead><tr><th>FILA</th><th>MATERIA / CATEGORÍA</th><th>COMPETENCIA</th><th>TIPO</th><th>ENUNCIADO / TEXTO BASE</th><th>OPCIONES</th><th>CORRECTA</th><th>PUNTAJE</th><th>RETROALIMENTACIÓN</th><th>VALIDACIÓN</th></tr></thead><tbody>${previewRows || '<tr><td colspan="10">El archivo no contiene filas para revisar.</td></tr>'}</tbody></table></div>
      <div class="heading-actions" style="margin-top:13px"><button class="btn btn-primary" data-action="commit-import" ${result.failed || !valid ? 'disabled' : ''}>Guardar preguntas válidas (${valid})</button></div>`;
  }

  async function runImportPreview() {
    const file = $('#import-file')?.files[0];
    if (!file) return toast('Selecciona un archivo Excel primero.', 'error');
    const form = new FormData();
    form.append('file', file);
    const button = $('[data-action="preview-import"]');
    button.disabled = true;
    try {
      const result = await request('imports/preview/', { method: 'POST', body: form });
      showImportPreview(result, file.name);
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  async function commitImport() {
    if (!app.importDraft) return;
    try {
      const result = await api.post('imports/commit/', {
        file_name: app.importDraft.fileName,
        rows: app.importDraft.rows,
      });
      toast(`Se importaron ${result.successful} preguntas correctamente.`);
      app.importDraft = null;
      await renderImports();
    } catch (error) {
      toast(error.message, 'error');
      await renderImports();
    }
  }

  async function showImportErrors(id) {
    try {
      const records = await api.get('imports/');
      const record = records.find(item => String(item.id) === String(id));
      if (!record) throw new Error('No se encontró el registro de importación.');
      const body = record.errors?.length
        ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>FILA</th><th>ERRORES</th></tr></thead><tbody>${record.errors.map(item => `<tr><td>${escapeHtml(item.rowNumber ?? '—')}</td><td class="error-row">${(item.errors || []).map(escapeHtml).join('<br>')}</td></tr>`).join('')}</tbody></table></div>`
        : '<div class="empty-state">Esta importación no registró errores.</div>';
      modal('Errores de importación', record.file_name, body, { footer: false });
    } catch (error) { toast(error.message, 'error'); }
  }

  function exportResults() {
    const rows = $$('tbody tr', $('#page-content')).filter(row => !row.hidden).map(row =>
      [...row.querySelectorAll('td')].map(cell => `"${cell.innerText.trim().replace(/"/g, '""')}"`).join(','));
    const header = [...$$('thead th', $('#page-content'))].map(cell => `"${cell.innerText.trim().replace(/"/g, '""')}"`).join(',');
    const blob = new Blob([`\uFEFF${[header, ...rows].join('\r\n')}`], { type: 'text/csv;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `resultados-saber-tyt-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function downloadTemplate() {
    try {
      const response = await request('imports/template/');
      const link = document.createElement('a');
      link.href = URL.createObjectURL(response);
      link.download = 'plantilla_banco_preguntas.xlsx';
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) { toast(error.message, 'error'); }
  }

  async function login(event) {
    event.preventDefault();
    const errorBox = $('#login-error');
    errorBox.hidden = true;
    const submit = $('.login-submit');
    let tokens = null;
    submit.disabled = true;
    try {
      const selectedRole = $('#login-role').value;
      if (!selectedRole) throw new Error('Selecciona el rol con el que ingresas.');
      tokens = await api.post('auth/token/', {
        username: $('#login-identity').value.trim(),
        password: $('#login-password').value,
      });
      app.access = tokens.access;
      app.refresh = tokens.refresh;
      const user = await api.get('auth/me/');
      if (user.role_slug !== selectedRole) {
        throw new Error('El rol seleccionado no coincide con el rol asignado a esta cuenta.');
      }
      app.user = user;
      app.permissions = app.user.permissions || [];
      localStorage.setItem(ACCESS_KEY, app.access);
      localStorage.setItem(REFRESH_KEY, app.refresh);
      showApplication();
    } catch (error) {
      showError(errorBox, error.message || 'Usuario o contraseña incorrectos.');
      if (tokens?.refresh) {
        try {
          await api.post('auth/logout/', { refresh: tokens.refresh });
        } catch (logoutError) {
          console.error('No fue posible invalidar el token de renovación tras un inicio de sesión fallido.', logoutError);
        }
      }
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      app.access = null;
      app.refresh = null;
      app.user = null;
      app.permissions = [];
    } finally {
      submit.disabled = false;
    }
  }

  async function logout() {
    try {
      if (app.refresh) await api.post('auth/logout/', { refresh: app.refresh });
    } catch (error) {
      console.error('No fue posible invalidar el token de renovación en el servidor.', error);
    } finally {
      clearInterval(app.timerId);
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      localStorage.removeItem('saber-tyt-active-attempt');
      app.access = null;
      app.refresh = null;
      app.user = null;
      app.permissions = [];
      app.activeAttempt = null;
      showLogin();
    }
  }

  async function handleClick(event) {
    const actionElement = event.target.closest('[data-action]');
    if (!actionElement) return;
    const { action, page, id } = actionElement.dataset;
    try {
      if (action === 'navigate') navigate(page);
      else if (action === 'logout') logout();
      else if (action === 'toggle-menu') $('#app-shell').classList.toggle('menu-open');
      else if (action === 'close-menu') $('#app-shell').classList.remove('menu-open');
      else if (action === 'modal-close') closeModal();
      else if (action === 'user-new') showUserForm();
      else if (action === 'user-edit') openEdit('users', id);
      else if (action === 'user-toggle') {
        const user = lookup(app.usersCache, id);
        await toggleActive('users', id, user.is_active, `la cuenta de ${fullName(user)}`);
      } else if (action === 'role-new') await showRoleForm();
      else if (action === 'role-edit') openEdit('roles', id);
      else if (action === 'role-toggle') {
        const role = lookup(app.rolesCache, id);
        await toggleActive('roles', id, role.is_active, `el rol ${role.name}`);
      } else if (action === 'category-new') showCategoryForm();
      else if (action === 'category-edit') openEdit('categories', id);
      else if (action === 'category-toggle') {
        const category = lookup(app.categoriesCache, id);
        await toggleActive('categories', id, category.is_active, `la categoría ${category.name}`);
      } else if (action === 'question-new') showQuestionForm();
      else if (action === 'question-edit') openEdit('questions', id);
      else if (action === 'question-toggle') {
        const question = lookup(app.questionsCache, id);
        await toggleActive('questions', id, question.is_active, 'la pregunta');
      } else if (action === 'quiz-new') showQuizForm();
      else if (action === 'quiz-edit') openEdit('quizzes', id);
      else if (action === 'quiz-toggle') {
        const quiz = lookup(app.quizzesCache, id);
        await toggleActive('quizzes', id, quiz.is_active, `el cuestionario ${quiz.title}`);
      } else if (action === 'profile-edit') showProfileForm();
      else if (action === 'password-edit') showPasswordForm();
      else if (action === 'start-quiz') await chooseQuizToStart(id);
      else if (action === 'exam-prev') {
        app.currentQuestion = Math.max(0, app.currentQuestion - 1);
        renderExam();
      } else if (action === 'exam-next') {
        app.currentQuestion = Math.min(app.activeAttempt.questions.length - 1, app.currentQuestion + 1);
        renderExam();
      } else if (action === 'exam-go') {
        app.currentQuestion = Number(actionElement.dataset.index);
        renderExam();
      } else if (action === 'exam-submit') finishExam(true);
      else if (action === 'choose-file') $('#import-file')?.click();
      else if (action === 'preview-import') runImportPreview();
      else if (action === 'commit-import') commitImport();
      else if (action === 'import-errors') showImportErrors(id);
      else if (action === 'download-template') downloadTemplate();
      else if (action === 'attempt-detail') showAttemptDetails(id);
      else if (action === 'export-results') exportResults();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  document.addEventListener('submit', event => {
    if (event.target.matches('#login-form')) login(event);
    else if (event.target.matches('[data-form]')) {
      event.preventDefault();
      submitForm(event.target);
    }
  });
  document.addEventListener('click', handleClick);
  document.addEventListener('input', event => {
    if (event.target.matches('[data-table-search]')) filterTable(event.target);
  });
  document.addEventListener('change', event => {
    if (event.target.matches('[data-status-filter]')) filterTable($('[data-table-search]') || { value: '' });
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !$('#modal-root').hidden) closeModal();
    if (event.key === 'Escape') $('#app-shell').classList.remove('menu-open');
  });
  $('#toggle-password').addEventListener('click', () => {
    const input = $('#login-password');
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  async function start() {
    $('#current-year').textContent = new Date().getFullYear();
    await Promise.all([checkDatabase(), loadLoginRoles()]);
    await loadDemoAccounts();
    if (!app.access) return showLogin();
    try {
      app.user = await api.get('auth/me/');
      app.permissions = app.user.permissions || [];
      showApplication();
    } catch (error) {
      console.error('La sesión anterior ya no está activa.', error);
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      app.access = null;
      app.refresh = null;
      showLogin();
    }
  }

  start();
})();
