// Общий скрипт для всех страниц dashboard/*.html (кроме login.html):
// - подтверждает сессию (реальная защита — на сервере, в api/main.py::auth_gate;
//   это только для UX — не дожидаться перехода и 403, а сразу спрятать лишнее);
// - прячет пункты навигации, к которым у роли нет доступа;
// - показывает, кто вошёл, и даёт выйти.
(function () {
  const PAGE_DEFINITIONS = [
    { key: 'atm_map', html: ['/dashboard/map.html', '/dashboard/incassation.html', '/dashboard/import-atms.html', '/dashboard/import-branches.html'] },
    { key: 'atm_analytics', html: ['/dashboard/analytics.html'] },
    { key: 'treasury', html: ['/dashboard/branch-cash.html', '/dashboard/import-branch-balances.html', '/dashboard/import-sqb-rates.html'] },
    { key: 'hr_cashiers', html: ['/dashboard/cashiers.html', '/dashboard/cashier-detail.html', '/dashboard/import-cashiers.html'] },
  ];
  const FREE_PATHS = new Set(['/', '/dashboard/index.html', '/dashboard/import.html', '/dashboard/login.html']);

  function pageKeyForPath(path) {
    for (const p of PAGE_DEFINITIONS) if (p.html.includes(path)) return p.key;
    return null;
  }

  function hideRestrictedLinks(me) {
    if (me.is_admin) return;
    const allowed = new Set(me.pages || []);
    document.querySelectorAll('a[href^="/dashboard/"]').forEach((a) => {
      let path;
      try {
        path = new URL(a.getAttribute('href'), location.origin).pathname;
      } catch (e) {
        return;
      }
      if (FREE_PATHS.has(path)) return;
      const key = pageKeyForPath(path);
      if (key && !allowed.has(key)) a.style.display = 'none';
    });
  }

  function renderUserBadge(me) {
    const bar = document.createElement('div');
    bar.style.cssText =
      'position:fixed;bottom:12px;right:12px;z-index:9999;background:#fff;border:1px solid #e2e8f0;' +
      'border-radius:999px;padding:6px 14px;font:600 12px -apple-system,BlinkMacSystemFont,sans-serif;' +
      'color:#475569;box-shadow:0 6px 20px rgba(15,23,42,.12);display:flex;align-items:center;gap:10px';
    const adminLink = me.is_admin
      ? `<a href="/admin/" style="color:#2563eb;text-decoration:none;font-weight:800">Админка</a>`
      : '';
    bar.innerHTML =
      `<span>${escapeHtml(me.full_name || me.username)} · ${escapeHtml(me.role_label)}</span>` +
      adminLink +
      `<a href="#" id="auth-nav-logout" style="color:#2563eb;text-decoration:none;font-weight:800">Выйти</a>`;
    document.body.appendChild(bar);
    document.getElementById('auth-nav-logout').addEventListener('click', async (e) => {
      e.preventDefault();
      try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (err) {}
      location.href = '/dashboard/login.html';
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  async function init() {
    let me;
    try {
      const res = await fetch('/api/auth/me');
      if (!res.ok) {
        location.href = '/dashboard/login.html?next=' + encodeURIComponent(location.pathname);
        return;
      }
      me = await res.json();
    } catch (err) {
      return; // сервер недоступен — не мешаем странице, серверный гейт всё равно защищает API
    }
    hideRestrictedLinks(me);
    renderUserBadge(me);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
