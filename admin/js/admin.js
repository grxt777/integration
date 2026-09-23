const API = location.origin;

let PAGES = [];      // [{key, label}]
let ROLES = [];      // текущие роли (для селекта в форме пользователя)

function showMsg(text, kind) {
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = 'msg ' + (kind || 'ok');
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
}

async function api(path, opts) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || ('Ошибка ' + res.status));
  return data;
}

// ── Шапка / выход ────────────────────────────────────────────
async function loadMe() {
  try {
    const me = await api('/api/auth/me');
    document.getElementById('who').textContent = `${me.full_name || me.username} · ${me.role_label}`;
    if (!me.is_admin) {
      document.body.innerHTML = '<div style="padding:40px;text-align:center;color:#64748b">Нет доступа к админ-панели.</div>';
    }
  } catch (e) {
    location.href = '/dashboard/login.html?next=/admin/';
  }
}

document.getElementById('logout-link').addEventListener('click', async (e) => {
  e.preventDefault();
  await api('/api/auth/logout', { method: 'POST' });
  location.href = '/dashboard/login.html';
});

// ── Табы ─────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
  });
});

// ── Модалка ──────────────────────────────────────────────────
const overlay = document.getElementById('overlay');
const modalBody = document.getElementById('modal-body');
function openModal(html) { modalBody.innerHTML = html; overlay.classList.add('open'); }
function closeModal() { overlay.classList.remove('open'); modalBody.innerHTML = ''; }
overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

// ── Пользователи ─────────────────────────────────────────────
async function loadUsers() {
  const { users } = await api('/api/admin/users');
  const tbody = document.getElementById('users-body');
  tbody.innerHTML = users.map(u => `
    <tr>
      <td><b>${u.username}</b></td>
      <td>${u.full_name || '—'}</td>
      <td>${u.role_label}</td>
      <td><span class="pill ${u.is_active ? 'pill-ok' : 'pill-off'}">${u.is_active ? 'активен' : 'выключен'}</span></td>
      <td class="actions">
        <button class="btn btn-ghost btn-sm" onclick="editUser(${u.id})">Изменить</button>
        <button class="btn btn-danger btn-sm" onclick="removeUser(${u.id}, '${u.username}')">Удалить</button>
      </td>
    </tr>
  `).join('') || '<tr><td colspan="5" style="color:#94a3b8">Пользователей нет</td></tr>';
}

function roleOptions(selectedId) {
  return ROLES.map(r => `<option value="${r.id}" ${r.id === selectedId ? 'selected' : ''}>${r.label}</option>`).join('');
}

document.getElementById('btn-new-user').addEventListener('click', () => {
  openModal(`
    <h3>Новый пользователь</h3>
    <label>Логин</label>
    <input type="text" id="f-username" autocomplete="off" />
    <label>ФИО</label>
    <input type="text" id="f-full-name" />
    <label>Пароль</label>
    <input type="password" id="f-password" autocomplete="new-password" />
    <div class="hint">Не короче 6 символов</div>
    <label>Роль</label>
    <select id="f-role">${roleOptions(null)}</select>
    <div class="row-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" onclick="submitNewUser()">Создать</button>
    </div>
  `);
});

async function submitNewUser() {
  try {
    await api('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        username: document.getElementById('f-username').value.trim(),
        full_name: document.getElementById('f-full-name').value.trim() || null,
        password: document.getElementById('f-password').value,
        role_id: Number(document.getElementById('f-role').value),
      }),
    });
    closeModal();
    showMsg('Пользователь создан', 'ok');
    loadUsers();
  } catch (e) {
    showMsg(e.message, 'error');
  }
}

async function editUser(id) {
  const { users } = await api('/api/admin/users');
  const u = users.find(x => x.id === id);
  if (!u) return;
  openModal(`
    <h3>Пользователь: ${u.username}</h3>
    <label>ФИО</label>
    <input type="text" id="f-full-name" value="${u.full_name || ''}" />
    <label>Роль</label>
    <select id="f-role">${roleOptions(u.role_id)}</select>
    <label><input type="checkbox" id="f-active" ${u.is_active ? 'checked' : ''} style="width:auto;margin-right:6px" /> Активен</label>
    <label>Новый пароль (необязательно)</label>
    <input type="password" id="f-password" autocomplete="new-password" />
    <div class="hint">Оставьте пустым, чтобы не менять пароль</div>
    <div class="row-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" onclick="submitEditUser(${u.id})">Сохранить</button>
    </div>
  `);
}

async function submitEditUser(id) {
  try {
    const password = document.getElementById('f-password').value;
    await api(`/api/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        full_name: document.getElementById('f-full-name').value.trim() || null,
        role_id: Number(document.getElementById('f-role').value),
        is_active: document.getElementById('f-active').checked,
        new_password: password || null,
      }),
    });
    closeModal();
    showMsg('Сохранено', 'ok');
    loadUsers();
  } catch (e) {
    showMsg(e.message, 'error');
  }
}

async function removeUser(id, username) {
  if (!confirm(`Удалить пользователя ${username}?`)) return;
  try {
    await api(`/api/admin/users/${id}`, { method: 'DELETE' });
    showMsg('Пользователь удалён', 'ok');
    loadUsers();
  } catch (e) {
    showMsg(e.message, 'error');
  }
}

// ── Роли ─────────────────────────────────────────────────────
async function loadRoles() {
  const { roles } = await api('/api/admin/roles');
  ROLES = roles;
  const tbody = document.getElementById('roles-body');
  tbody.innerHTML = roles.map(r => `
    <tr>
      <td><b>${r.name}</b></td>
      <td>${r.label}</td>
      <td>${r.is_admin
        ? '<span class="page-chip">Полный доступ</span>'
        : `<div class="pages-list">${(r.pages.map(k => `<span class="page-chip">${pageLabel(k)}</span>`).join('') || '<span style="color:#94a3b8">нет прав</span>')}</div>`
      }</td>
      <td class="actions">
        ${r.is_admin ? '' : `
          <button class="btn btn-ghost btn-sm" onclick="editRole(${r.id})">Изменить</button>
          <button class="btn btn-danger btn-sm" onclick="removeRole(${r.id}, '${r.name}')">Удалить</button>
        `}
      </td>
    </tr>
  `).join('');
}

function pageLabel(key) {
  const p = PAGES.find(x => x.key === key);
  return p ? p.label : key;
}

function pageChecks(selected) {
  selected = selected || [];
  return PAGES.map(p => `
    <label><input type="checkbox" value="${p.key}" ${selected.includes(p.key) ? 'checked' : ''} /> ${p.label}</label>
  `).join('');
}

document.getElementById('btn-new-role').addEventListener('click', () => {
  openModal(`
    <h3>Новая роль</h3>
    <label>Имя (латиницей, без пробелов)</label>
    <input type="text" id="f-name" autocomplete="off" />
    <label>Название</label>
    <input type="text" id="f-label" />
    <label>Доступные страницы</label>
    <div class="checks">${pageChecks([])}</div>
    <div class="row-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" onclick="submitNewRole()">Создать</button>
    </div>
  `);
});

function collectCheckedPages() {
  return Array.from(document.querySelectorAll('#modal-body .checks input:checked')).map(i => i.value);
}

async function submitNewRole() {
  try {
    await api('/api/admin/roles', {
      method: 'POST',
      body: JSON.stringify({
        name: document.getElementById('f-name').value.trim(),
        label: document.getElementById('f-label').value.trim(),
        pages: collectCheckedPages(),
      }),
    });
    closeModal();
    showMsg('Роль создана', 'ok');
    loadRoles();
  } catch (e) {
    showMsg(e.message, 'error');
  }
}

async function editRole(id) {
  const r = ROLES.find(x => x.id === id);
  if (!r) return;
  openModal(`
    <h3>Роль: ${r.name}</h3>
    <label>Название</label>
    <input type="text" id="f-label" value="${r.label}" />
    <label>Доступные страницы</label>
    <div class="checks">${pageChecks(r.pages)}</div>
    <div class="row-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Отмена</button>
      <button class="btn btn-primary" onclick="submitEditRole(${r.id})">Сохранить</button>
    </div>
  `);
}

async function submitEditRole(id) {
  try {
    await api(`/api/admin/roles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        label: document.getElementById('f-label').value.trim(),
        pages: collectCheckedPages(),
      }),
    });
    closeModal();
    showMsg('Сохранено', 'ok');
    loadRoles();
  } catch (e) {
    showMsg(e.message, 'error');
  }
}

async function removeRole(id, name) {
  if (!confirm(`Удалить роль ${name}?`)) return;
  try {
    await api(`/api/admin/roles/${id}`, { method: 'DELETE' });
    showMsg('Роль удалена', 'ok');
    loadRoles();
  } catch (e) {
    showMsg(e.message, 'error');
  }
}

// window-scope для onclick="..." в динамически вставленной разметке
window.editUser = editUser;
window.removeUser = removeUser;
window.submitNewUser = submitNewUser;
window.submitEditUser = submitEditUser;
window.editRole = editRole;
window.removeRole = removeRole;
window.submitNewRole = submitNewRole;
window.submitEditRole = submitEditRole;
window.closeModal = closeModal;

// ── Boot ─────────────────────────────────────────────────────
(async function boot() {
  await loadMe();
  const { pages } = await api('/api/admin/pages');
  PAGES = pages;
  await loadRoles();
  await loadUsers();
})();
