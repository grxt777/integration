    const base = location.origin;
    let charts = [], modalChart = null, catsExpandChart = null, catsExpandCurrentView = 'both', globalTopByPosition = {}, globalCategories = [], currentCatsView = 'chart';
    const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

    // Initialize filter parameters from URL query string or sessionStorage
    const initParams = new URLSearchParams(window.location.search);
    let currentPage = parseInt(initParams.get('page') || sessionStorage.getItem('sqb_page') || '1');
    let pageSize = parseInt(initParams.get('pageSize') || sessionStorage.getItem('sqb_pageSize') || '25');
    let selectedRole = initParams.get('role') || sessionStorage.getItem('sqb_role') || '';
    let selectedStatus = initParams.get('status') || sessionStorage.getItem('sqb_status') || '';
    let searchQuery = initParams.get('search') || sessionStorage.getItem('sqb_search') || '';
    let selectedPosition = initParams.get('position') || sessionStorage.getItem('sqb_position') || '';
    let selectedBranch = initParams.get('branch') || sessionStorage.getItem('sqb_branch') || '';
    let searchTimeout = null;

    function saveStateToSession() {
      sessionStorage.setItem('sqb_page', currentPage);
      sessionStorage.setItem('sqb_pageSize', pageSize);
      sessionStorage.setItem('sqb_role', selectedRole);
      sessionStorage.setItem('sqb_status', selectedStatus);
      sessionStorage.setItem('sqb_search', searchQuery);
      sessionStorage.setItem('sqb_position', selectedPosition);
      sessionStorage.setItem('sqb_branch', selectedBranch);

      const params = new URLSearchParams();
      if (currentPage > 1) params.set('page', currentPage);
      if (pageSize !== 25) params.set('pageSize', pageSize);
      if (selectedRole) params.set('role', selectedRole);
      if (selectedStatus) params.set('status', selectedStatus);
      if (searchQuery) params.set('search', searchQuery);
      if (selectedPosition) params.set('position', selectedPosition);
      if (selectedBranch) params.set('branch', selectedBranch);

      const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
      window.history.replaceState({}, '', newUrl);
    }

    function resetAllFilters() {
      selectedRole = '';
      selectedStatus = '';
      selectedPosition = '';
      selectedBranch = '';
      searchQuery = '';
      currentPage = 1;

      document.getElementById('search-input').value = '';
      document.getElementById('clear-search-btn').style.display = 'none';
      if (document.getElementById('position-select')) document.getElementById('position-select').value = '';
      if (document.getElementById('branch-select')) document.getElementById('branch-select').value = '';

      document.querySelectorAll('.pill-btn.role').forEach(b => {
        b.classList.toggle('active', (b.dataset.role || '') === '');
      });
      document.querySelectorAll('.st-pill').forEach(b => {
        b.classList.toggle('active', (b.dataset.status || '') === '');
      });

      load();
    }

    function clearSearch() {
      document.getElementById('search-input').value = '';
      document.getElementById('clear-search-btn').style.display = 'none';
      executeSearch();
    }

    function executeSearch() {
      clearTimeout(searchTimeout);
      searchQuery = document.getElementById('search-input').value.trim();
      currentPage = 1;
      load();
    }

    function onSearchInput() {
      const val = document.getElementById('search-input').value;
      document.getElementById('clear-search-btn').style.display = val ? 'block' : 'none';
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        executeSearch();
      }, 300);
    }

    function onPositionSelect() {
      selectedPosition = document.getElementById('position-select').value;
      currentPage = 1;
      load();
    }

    function onBranchSelect() {
      selectedBranch = document.getElementById('branch-select').value;
      currentPage = 1;
      load();
    }

    function updateBranchSelectOptions(branches) {
      const sel = document.getElementById('branch-select');
      if (!sel || sel.options.length > 1) return;
      (branches || []).forEach(br => {
        const opt = document.createElement('option');
        opt.value = br;
        opt.textContent = `🏛️ ${br}`;
        sel.appendChild(opt);
      });
    }

    function drawTop(labels, data) {
      const ctx = document.getElementById('top');
      if (!ctx) return;
      const topChart = charts.find(c => c && c.canvas && c.canvas.id === 'top');
      if (topChart) {
        try { topChart.destroy(); } catch(e) {}
      }
      charts = charts.filter(c => c && c.canvas && c.canvas.id !== 'top');
      charts.push(new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: 'Операций',
            data: data,
            backgroundColor: '#2563eb',
            borderRadius: 8
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } }
        }
      }));
    }

    function drawCats(categories) {
      const ctx = document.getElementById('cats');
      if (!ctx) return;
      const catChart = charts.find(c => c && c.canvas && c.canvas.id === 'cats');
      if (catChart) {
        try { catChart.destroy(); } catch(e) {}
      }
      charts = charts.filter(c => c && c.canvas && c.canvas.id !== 'cats');
      const labels = categories.map(x => `${x.name} (${x.pct}%)`);
      const data = categories.map(x => x.count);
      const colors = ['#2563eb','#3b82f6','#10b981','#f59e0b','#8b5cf6','#f43f5e','#06b6d4','#64748b'];
      charts.push(new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: data,
            backgroundColor: colors.slice(0, categories.length)
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: true, position: 'right', labels: { font: { size: 11, family: 'Inter' } } },
            tooltip: {
              callbacks: {
                label: function(item) {
                  const cat = categories[item.dataIndex];
                  return ` ${cat.name}: ${nf.format(cat.count)} опер. (${cat.pct}%)`;
                }
              }
            }
          }
        }
      }));
    }

    function setCatsView(view) {
      currentCatsView = view;
      const chartView = document.getElementById('cats-chart-view');
      const tableView = document.getElementById('cats-table-view');
      const btnChart = document.getElementById('btn-cats-chart');
      const btnTable = document.getElementById('btn-cats-table');
      if (!chartView || !tableView) return;

      if (view === 'table') {
        chartView.style.display = 'none';
        tableView.style.display = 'block';
        if (btnChart) btnChart.classList.remove('active');
        if (btnTable) btnTable.classList.add('active');
        renderCatsTable(globalCategories);
      } else {
        chartView.style.display = 'block';
        tableView.style.display = 'none';
        if (btnChart) btnChart.classList.add('active');
        if (btnTable) btnTable.classList.remove('active');
      }
    }

    function renderCatsTable(categories) {
      const tbody = document.getElementById('cats-table-body');
      if (!tbody) return;
      if (!categories || !categories.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#94a3b8">Операции не найдены</td></tr>';
        return;
      }
      const colors = ['#2563eb','#3b82f6','#10b981','#f59e0b','#8b5cf6','#f43f5e','#06b6d4','#64748b'];

      tbody.innerHTML = categories.map((cat, idx) => {
        const dotColor = colors[idx % colors.length];
        const mins = Math.round(cat.minutes || 0);
        const hoursVal = Math.floor(mins / 60);
        const minsRem = mins % 60;
        const hoursStr = mins >= 60 ? `${nf.format(hoursVal)}ч ${minsRem}м` : `${mins}м`;
        const pctVal = cat.pct || 0;

        return `
          <tr style="border-bottom:1px solid #f1f5f9; transition:background 0.15s ease;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
            <td style="padding:10px 4px; font-weight:600; color:#64748b; font-size:11px; vertical-align:top; padding-top:12px;">${idx + 1}</td>
            <td style="padding:10px 8px 10px 6px; font-weight:600; color:#1e293b; font-size:12px; vertical-align:top; min-width:0; overflow:hidden;">
              <div style="display:flex; align-items:flex-start; gap:8px; line-height:1.4; min-width:0; overflow:hidden;">
                <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${dotColor}; margin-top:5px; flex-shrink:0;"></span>
                <span style="word-break:break-word; overflow-wrap:anywhere; min-width:0; flex:1;">${escapeHtml(cat.name)}</span>
              </div>
            </td>
            <td style="padding:10px 6px; text-align:right; font-weight:700; color:#0f172a; font-size:12px; vertical-align:top; padding-top:12px; white-space:nowrap;">${nf.format(cat.count || 0)}</td>
            <td style="padding:10px 6px; text-align:right; vertical-align:top; padding-top:10px; white-space:nowrap;">
              <div style="font-weight:700; color:#334155; font-size:12px;">${hoursStr}</div>
              <div style="font-size:10px; color:#94a3b8; font-weight:500;">${nf.format(mins)} мин</div>
            </td>
            <td style="padding:10px 6px; text-align:right; font-weight:700; color:#2563eb; vertical-align:top; padding-top:12px; white-space:nowrap;">
              <div style="display:flex; align-items:center; justify-content:flex-end; gap:6px;">
                <span style="min-width:32px; text-align:right; font-size:12px;">${pctVal}%</span>
                <div style="width:28px; height:6px; background:#e2e8f0; border-radius:3px; overflow:hidden; flex-shrink:0;">
                  <div style="width:${Math.min(100, pctVal)}%; height:100%; background:${dotColor}; border-radius:3px;"></div>
                </div>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    }

    function openCatsExpandModal() {
      const modal = document.getElementById('cats-expand-modal');
      if (!modal) return;
      modal.classList.add('active');

      const filterLabel = selectedRole === 'back' ? ' (💼 БЭК)' : selectedRole === 'front' ? ' (💳 ФРОНТ)' : '';
      const titleEl = document.getElementById('cats-expand-title');
      if (titleEl) titleEl.textContent = `📊 Структура выполненных операций (%) ${filterLabel}`;

      setCatsExpandView(catsExpandCurrentView || 'both');
    }

    function closeCatsExpandModal() {
      const modal = document.getElementById('cats-expand-modal');
      if (!modal) return;
      modal.classList.remove('active');
      if (catsExpandChart) {
        try { catsExpandChart.destroy(); } catch(e) {}
        catsExpandChart = null;
      }
    }

    function closeCatsExpandModalOnOverlay(e) {
      if (e.target && e.target.id === 'cats-expand-modal') {
        closeCatsExpandModal();
      }
    }

    function setCatsExpandView(mode) {
      catsExpandCurrentView = mode;
      const chartBox = document.getElementById('cats-expand-chart-box');
      const tableBox = document.getElementById('cats-expand-table-box');
      const layoutGrid = document.getElementById('cats-expand-layout-grid');
      const btnChart = document.getElementById('btn-cats-expand-chart');
      const btnTable = document.getElementById('btn-cats-expand-table');
      const btnBoth = document.getElementById('btn-cats-expand-both');

      if (!chartBox || !tableBox || !layoutGrid) return;

      if (btnChart) btnChart.classList.toggle('active', mode === 'chart');
      if (btnTable) btnTable.classList.toggle('active', mode === 'table');
      if (btnBoth) btnBoth.classList.toggle('active', mode === 'both');

      if (mode === 'chart') {
        layoutGrid.style.gridTemplateColumns = '1fr';
        chartBox.style.display = 'block';
        tableBox.style.display = 'none';
        chartBox.style.height = '480px';
      } else if (mode === 'table') {
        layoutGrid.style.gridTemplateColumns = '1fr';
        chartBox.style.display = 'none';
        tableBox.style.display = 'block';
      } else { // 'both'
        layoutGrid.style.gridTemplateColumns = '0.9fr 1.3fr';
        chartBox.style.display = 'block';
        tableBox.style.display = 'block';
        chartBox.style.height = '440px';
      }

      if (mode === 'chart' || mode === 'both') {
        renderCatsExpandChart(globalCategories || []);
      }
      if (mode === 'table' || mode === 'both') {
        renderCatsExpandTable(globalCategories || []);
      }
    }

    function renderCatsExpandChart(categories) {
      const ctx = document.getElementById('cats-expand-canvas');
      if (!ctx) return;
      if (catsExpandChart) {
        try { catsExpandChart.destroy(); } catch(e) {}
        catsExpandChart = null;
      }
      if (!categories || !categories.length) return;

      const labels = categories.map(x => `${x.name} (${x.pct}%)`);
      const data = categories.map(x => x.count);
      const colors = ['#2563eb','#3b82f6','#10b981','#f59e0b','#8b5cf6','#f43f5e','#06b6d4','#64748b','#ec4899','#84cc16','#f97316','#14b8a6'];

      catsExpandChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: data,
            backgroundColor: colors.slice(0, categories.length)
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true,
              position: 'right',
              labels: { font: { size: 12, family: 'Inter', weight: '600' }, padding: 12 }
            },
            tooltip: {
              callbacks: {
                label: function(item) {
                  const cat = categories[item.dataIndex];
                  const mins = Math.round(cat.minutes || 0);
                  const hrs = Math.floor(mins / 60);
                  return ` ${cat.name}: ${nf.format(cat.count)} опер. (${cat.pct}%) · ${hrs}ч ${mins % 60}м`;
                }
              }
            }
          }
        }
      });
    }

    function renderCatsExpandTable(categories) {
      const tbody = document.getElementById('cats-expand-table-body');
      if (!tbody) return;
      if (!categories || !categories.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#94a3b8">Операции не найдены</td></tr>';
        return;
      }
      const colors = ['#2563eb','#3b82f6','#10b981','#f59e0b','#8b5cf6','#f43f5e','#06b6d4','#64748b','#ec4899','#84cc16','#f97316','#14b8a6'];

      tbody.innerHTML = categories.map((cat, idx) => {
        const dotColor = colors[idx % colors.length];
        const mins = Math.round(cat.minutes || 0);
        const hoursVal = Math.floor(mins / 60);
        const minsRem = mins % 60;
        const hoursStr = mins >= 60 ? `${nf.format(hoursVal)}ч ${minsRem}м` : `${mins}м`;
        const pctVal = cat.pct || 0;

        return `
          <tr style="border-bottom:1px solid #f1f5f9; transition:background 0.15s ease;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
            <td style="padding:10px 4px; font-weight:600; color:#64748b; font-size:12px; vertical-align:top; padding-top:12px;">${idx + 1}</td>
            <td style="padding:10px 8px 10px 6px; font-weight:600; color:#1e293b; font-size:12.5px; vertical-align:top; min-width:0; overflow:hidden;">
              <div style="display:flex; align-items:flex-start; gap:8px; line-height:1.4; min-width:0; overflow:hidden;">
                <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${dotColor}; margin-top:5px; flex-shrink:0;"></span>
                <span style="word-break:break-word; overflow-wrap:anywhere; min-width:0; flex:1; display:block;">${escapeHtml(cat.name)}</span>
              </div>
            </td>
            <td style="padding:10px 6px; text-align:right; font-weight:700; color:#0f172a; font-size:12.5px; vertical-align:top; padding-top:12px; white-space:nowrap;">${nf.format(cat.count || 0)}</td>
            <td style="padding:10px 6px; text-align:right; vertical-align:top; padding-top:10px; white-space:nowrap;">
              <div style="font-weight:700; color:#334155; font-size:12.5px;">${hoursStr}</div>
              <div style="font-size:10px; color:#94a3b8; font-weight:500;">${nf.format(mins)} мин</div>
            </td>
            <td style="padding:10px 6px; text-align:right; font-weight:700; color:#2563eb; vertical-align:top; padding-top:12px; white-space:nowrap;">
              <div style="display:flex; align-items:center; justify-content:flex-end; gap:6px;">
                <span style="min-width:32px; text-align:right; font-size:12px;">${pctVal}%</span>
                <div style="width:28px; height:6px; background:#e2e8f0; border-radius:3px; overflow:hidden; flex-shrink:0;">
                  <div style="width:${Math.min(100, pctVal)}%; height:100%; background:${dotColor}; border-radius:3px;"></div>
                </div>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    }

    function topMetric(x) {
      if (selectedRole === 'back') return Number(x.bek_count || 0);
      if (selectedRole === 'front') return Number(x.front_count || 0);
      return Number(x.operations_count || 0);
    }

    function drawTopFromList(list) {
      const top10 = (list || []).filter(x => topMetric(x) > 0).slice(0, 10);
      drawTop(
        top10.map(x => (x.full_name || '').split(' ').slice(0, 2).join(' ')),
        top10.map(x => topMetric(x))
      );
    }

    function renderPosTopTabs(topByPosition) {
      globalTopByPosition = topByPosition || {};
      const container = document.getElementById('pos-top-tabs');
      if (!container) return;
      
      const positions = Object.keys(globalTopByPosition);
      if (!positions.length) { container.innerHTML = ''; return; }

      let html = `<button class="pill-btn active" style="padding:4px 10px;font-size:11px" onclick="switchPosTop('')">Все</button>`;
      positions.slice(0, 4).forEach(pos => {
        html += `<button class="pill-btn" style="padding:4px 10px;font-size:11px" onclick="switchPosTop('${pos.replace(/'/g, "\\'")}')">${pos}</button>`;
      });
      container.innerHTML = html;
    }

    function switchPosTop(posName) {
      const container = document.getElementById('pos-top-tabs');
      if (container) {
        container.querySelectorAll('button').forEach(b => {
          if ((b.textContent === 'Все' && !posName) || b.textContent === posName) {
            b.classList.add('active');
          } else {
            b.classList.remove('active');
          }
        });
      }

      if (!posName) {
        drawTopFromList(window.globalTopCashiers || []);
      } else {
        drawTopFromList(globalTopByPosition[posName] || []);
      }
    }

    function updatePositionSelectOptions(positions) {
      const sel = document.getElementById('position-select');
      if (!sel || sel.options.length > 1) return;
      positions.forEach(pos => {
        const opt = document.createElement('option');
        opt.value = pos;
        opt.textContent = pos;
        sel.appendChild(opt);
      });
    }

    async function load() {
      try {
        saveStateToSession();

        const searchInp = document.getElementById('search-input');
        if (searchInp && searchInp.value !== searchQuery) searchInp.value = searchQuery;
        const clearBtn = document.getElementById('clear-search-btn');
        if (clearBtn) clearBtn.style.display = searchQuery ? 'block' : 'none';
        const posSel = document.getElementById('position-select');
        if (posSel && selectedPosition) posSel.value = selectedPosition;
        const brSel = document.getElementById('branch-select');
        if (brSel && selectedBranch) brSel.value = selectedBranch;

        document.querySelectorAll('.st-pill').forEach(b => {
          b.classList.toggle('active', (b.dataset.status || '') === (selectedStatus || ''));
        });
        document.querySelectorAll('.pill-btn.role').forEach(b => {
          b.classList.toggle('active', (b.dataset.role || '') === (selectedRole || ''));
        });

        let url = base + `/api/cashiers/analytics?page=${currentPage}&page_size=${pageSize}`;
        if (selectedRole) url += `&role=${encodeURIComponent(selectedRole)}`;
        if (selectedStatus) url += `&status=${encodeURIComponent(selectedStatus)}`;
        if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;
        if (selectedPosition) url += `&position=${encodeURIComponent(selectedPosition)}`;
        if (selectedBranch) url += `&branch=${encodeURIComponent(selectedBranch)}`;

        let r = await fetch(url);
        let d = await r.json(), s = d.summary || {};
        if (!d.import) {
          document.getElementById('notice-text').textContent = 'Нет загруженных отчётов кассиров. Загрузите Excel-файл выше.';
          return;
        }

        if (d.positions) updatePositionSelectOptions(d.positions);
        if (d.branches) updateBranchSelectOptions(d.branches);
        renderPosTopTabs(d.top_by_position);

        window.globalTopCashiers = d.top_cashiers || [];
        window.currentCashiersList = d.cashiers;

        const filterLabel = selectedRole === 'back' ? ' (БЭК)' : selectedRole === 'front' ? ' (ФРОНТ)' : selectedRole === 'universal' ? ' (Универсальные)' : '';
        const stLabel = selectedStatus ? ` · Status: ${selectedStatus}` : '';
        const posLabel = selectedPosition ? ` · ${selectedPosition}` : '';
        const brLabel = selectedBranch ? ` · BXM: ${selectedBranch}` : '';
        document.getElementById('notice-text').textContent = `Отчёт: ${d.import.filename} · импортирован ${new Date(d.import.imported_at).toLocaleString('ru-RU')}${filterLabel}${stLabel}${posLabel}${brLabel}`;
        
        document.getElementById('lbl-cash').textContent = selectedRole ? `Кассиров${filterLabel}` : 'Всего кассиров';
        document.getElementById('k-cash').textContent = s.cashiers || 0;
        document.getElementById('k-bek-front').textContent = `${s.bek_pct || 0}% / ${s.front_pct || 0}%`;
        const bekFrontSub = document.getElementById('k-bek-front-sub');
        if (bekFrontSub) {
          bekFrontSub.textContent = `${nf.format(s.bek_operations || 0)} БЭК · ${nf.format(s.front_operations || 0)} ФРОНТ`;
        }
        document.getElementById('k-status-stat').textContent = `${s.active_cashiers || 0} / ${s.maternity_cashiers || 0}`;
        document.getElementById('k-noreplace').textContent = (s.no_replacement_cashiers || 0) + ' чел.';
        document.getElementById('k-disciplined').textContent = (s.disciplined_cashiers || 0) + ' чел.';
        document.getElementById('k-load').textContent = (s.avg_load_percent || 0) + ' %';
        document.getElementById('k-ops-summary').textContent = nf.format(s.operations || 0);
        document.getElementById('k-hours-sub').textContent = `${s.hours || 0} ч. работы`;

        const topMetricLabel = selectedRole === 'back' ? ' по БЭК' : selectedRole === 'front' ? ' по ФРОНТ' : '';
        document.getElementById('chart-top-title').textContent = `Топ 10 кассиров${topMetricLabel}${posLabel}${brLabel}`;
        document.getElementById('chart-cats-title').textContent = `Структура операций (%) ${filterLabel}`;

        try {
          drawTopFromList(window.globalTopCashiers);
        } catch(e) { console.warn('Top chart render error:', e); }

        try {
          globalCategories = d.categories || [];
          let c = globalCategories.slice(0, 8);
          drawCats(c);
          renderCatsTable(globalCategories);
          setCatsView(currentCatsView);
        } catch(e) { console.warn('Cats chart render error:', e); }

        currentPage = d.page || 1;
        totalPages = d.total_pages || 1;
        renderPaginationControls(currentPage, totalPages, d.total || 0, pageSize);

        if (!d.cashiers || d.cashiers.length === 0) {
          document.getElementById('rows').innerHTML = `
            <tr>
              <td colspan="6" style="text-align:center;padding:36px;color:#64748b">
                <b style="font-size:15px;color:#1e293b">Записи не найдены по выбранным фильтрам</b><br>
                <span style="font-size:13px;margin-top:6px;display:inline-block">Нажмите <a href="javascript:void(0)" onclick="resetAllFilters()" style="color:#2563eb;font-weight:bold;text-decoration:underline">«Сбросить фильтры»</a> для отображения всех сотрудников.</span>
              </td>
            </tr>
          `;
          return;
        }

        document.getElementById('rows').innerHTML = d.cashiers.map(x => {
          const loadColor = (x.load_percent > 100) ? '#dc2626' : (x.load_percent >= 70) ? '#059669' : '#d97706';
          
          let statusBadgeHTML = '';
          if (x.hr_status_code === 'maternity') {
            if (x.has_replacement) {
              statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff">🟣 В декрете</div>`;
            } else {
              statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#fee2e2;color:#991b1b;border:1px solid #fca5a5">🔴 Без замены (Декрет)</div>`;
            }
          } else if (x.hr_status_code === 'vacation') {
            statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#e0f2fe;color:#075985;border:1px solid #bae6fd">🔵 В отпуске</div>`;
          } else if (x.hr_status_code === 'temporary') {
            statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#fef3c7;color:#92400e;border:1px solid #fde68a">🟡 Вр. замещение</div>`;
          } else if (x.hr_status_code === 'sick') {
            statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#fee2e2;color:#991b1b;border:1px solid #fca5a5">🔴 Болен</div>`;
          } else if (x.hr_status_code === 'vacant') {
            statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#f1f5f9;color:#475569;border:1px solid #cbd5e1">⚪ Вакансия</div>`;
          } else {
            statusBadgeHTML = `<div style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;display:inline-block;background:#dcfce7;color:#166534;border:1px solid #bbf7d0">🟢 Работает</div>`;
          }

          let roleBadgeHTML = '';
          if (x.cashier_type === 'front') {
            roleBadgeHTML = `<span class="badge-role badge-front" style="font-size:10px;padding:2px 6px">💳 ФРОНТ</span>`;
          } else if (x.cashier_type === 'back') {
            roleBadgeHTML = `<span class="badge-role badge-back" style="font-size:10px;padding:2px 6px">💼 БЭК</span>`;
          }

          const initials = (x.full_name || '').split(' ').slice(0, 2).map(n => n[0] || '').join('').toUpperCase() || 'K';

          // Discipline status tag
          let discTagHTML = '';
          if (x.has_discipline) {
            discTagHTML = `<div style="font-size:10px;font-weight:800;padding:2px 7px;border-radius:6px;display:inline-block;background:#fff1f2;color:#be123c;border:1px solid #fecdd3;margin-top:4px" title="Сотрудник имеет дисциплинарное взыскание (Нажмите для просмотра)">⚠️ Взыскание</div>`;
          }

          const currentNavParams = new URLSearchParams(window.location.search).toString();

          return `
          <tr onclick="window.location.href='/dashboard/cashier-detail.html?id=${x.id}&${currentNavParams}'" style="cursor:pointer">
            <td>
              <div class="cashier-info-box">
                <div class="avatar-circle" style="${x.has_discipline ? 'border:2px solid #f43f5e' : ''}">${initials}</div>
                <div>
                  <div class="cashier-name">${escapeHtml(x.full_name)} ${x.has_discipline ? '<span style="color:#e11d48" title="Взыскание">⚠️</span>' : ''}</div>
                  <div style="margin-top:2px">${roleBadgeHTML} <small class="muted" style="margin-left:4px">№ ${escapeHtml(x.employee_number || '—')}</small></div>
                </div>
              </div>
            </td>
            <td>
              ${statusBadgeHTML}
              ${discTagHTML ? `<br>${discTagHTML}` : ''}
            </td>
            <td>
              <b>${escapeHtml(x.position || '—')}</b>
              <br><span style="font-size:11px;font-weight:700;color:#047857;background:#ecfdf5;border:1px solid #a7f3d0;padding:2px 7px;border-radius:6px;display:inline-block;margin-top:3px">🏛️ ${escapeHtml(cleanBranchName(x.branch_name))}</span>
            </td>
            <td><b>${nf.format(x.days_worked)} дн.</b> <small class="muted">(${x.days_worked_pct}%)</small></td>
            <td>
              <div style="font-weight:850;font-size:14px;color:#0f172a">${nf.format(x.operations_count)} опер.</div>
              <small style="color:#64748b;font-size:11px">${nf.format(x.operations_per_day)} опер./день</small>
            </td>
            <td>
              <div style="font-weight:850;color:${loadColor}">${x.load_percent}%</div>
              <div style="height:5px;background:#e2e8f0;border-radius:3px;margin-top:3px;width:60px;overflow:hidden">
                <div style="height:100%;background:${loadColor};width:${Math.min(x.load_percent, 100)}%"></div>
              </div>
              ${x.load_percent > 100 ? `<div style="margin-top:3px"><span style="font-size:10px;font-weight:800;background:#fef2f2;color:#dc2626;border:1px solid #fca5a5;padding:2px 6px;border-radius:6px;display:inline-block">🔥 +${(x.load_percent - 100).toFixed(1)}% превышение</span></div>` : ''}
            </td>
          </tr>
        `;
        }).join('');
      } catch(e) {
        document.getElementById('notice-text').textContent = 'Не удалось получить данные: ' + e.message;
      }
    }

    async function openCashierModal(reportId) {
      try {
        const r = await fetch(base + '/api/cashiers/' + reportId);
        if (!r.ok) throw new Error('Не удалось загрузить данные кассира');
        const x = await r.json();

        // --- Header Info ---
        document.getElementById('m-name').textContent = x.full_name;
        document.getElementById('m-pos').textContent = x.position || 'Должность не указана';
        document.getElementById('m-branch-str').textContent = '🏛️ Филиал / БХМ: ' + cleanBranchName(x.branch_name);
        document.getElementById('m-meta').textContent = `Табель №: ${x.tab_number || '—'} · Сотрудник №: ${x.employee_number || '—'}`;

        // --- Role Badge ---
        const badge = document.getElementById('m-role-badge');
        const bekCnt = x.bek_count || 0;
        const frontCnt = x.front_count || 0;
        if (x.cashier_type === 'front') {
          badge.className = 'badge-role badge-front';
          badge.textContent = '💳 ФРОНТ-кассир';
        } else if (x.cashier_type === 'back') {
          badge.className = 'badge-role badge-back';
          badge.textContent = '💼 БЭК-кассир';
        } else {
          badge.className = 'badge-role badge-universal';
          badge.textContent = 'Нет операций';
        }

        // --- HR Status Badge ---
        const hrBadge = document.getElementById('m-hr-status-badge');
        const hrBanner = document.getElementById('m-hr-banner');
        const statusStyles = {
          maternity: x.has_replacement
            ? 'background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff'
            : 'background:#fee2e2;color:#991b1b;border:1px solid #fca5a5',
          vacation: x.has_replacement
            ? 'background:#e0f2fe;color:#075985;border:1px solid #bae6fd'
            : 'background:#fee2e2;color:#991b1b;border:1px solid #fca5a5',
          temporary: 'background:#fef3c7;color:#92400e;border:1px solid #fde68a',
          vacant: 'background:#f1f5f9;color:#475569;border:1px solid #cbd5e1',
          active: 'background:#dcfce7;color:#166534;border:1px solid #bbf7d0'
        };
        const baseHrStyle = 'font-size:12px;font-weight:800;padding:4px 12px;border-radius:99px;';
        const sc = x.hr_status_code || 'active';
        hrBadge.style.cssText = baseHrStyle + (statusStyles[sc] || statusStyles.active);
        hrBadge.textContent = x.hr_status_label || '🟢 Работает';

        // --- HR Banner (replacement info) ---
        if (x.replacing_full_name) {
          hrBanner.style.cssText = 'display:block;margin-top:14px;padding:12px 16px;border-radius:12px;font-size:13px;line-height:1.5;background:#fef3c7;color:#92400e;border:1px solid #fde68a';
          hrBanner.innerHTML = `<b>🟡 Вақтинча ўринбосар ходим</b><br>Асосий штат бирлигини алмаштираяпти: <b>${escapeHtml(x.replacing_full_name)}</b>`;
        } else if (x.replaced_by_full_name) {
          hrBanner.style.cssText = 'display:block;margin-top:14px;padding:12px 16px;border-radius:12px;font-size:13px;line-height:1.5;background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff';
          hrBanner.innerHTML = `<b>🟣 Декрет/Та'тилда (Ўринбосар бор)</b><br>Ўрнида вақтинча ишлаяпти: <b>${escapeHtml(x.replaced_by_full_name)}</b>`;
        } else if (sc !== 'active' && sc !== 'vacant' && !x.has_replacement) {
          hrBanner.style.cssText = 'display:block;margin-top:14px;padding:12px 16px;border-radius:12px;font-size:13px;line-height:1.5;background:#fee2e2;color:#991b1b;border:1px solid #fca5a5';
          hrBanner.innerHTML = `<b>🔴 ⚠️ Диqqat: Ўринбосар йўq!</b><br>Ходим декрет/та'тилда, аммо филиалда <b>ўринбосар тайинланмаган</b>.`;
        } else {
          hrBanner.style.display = 'none';
        }

        // --- KPI metrics ---
        const mBekFrontVal = document.getElementById('m-bek-front-val');
        const mBekFrontGrade = document.getElementById('m-bek-front-grade');
        if (mBekFrontVal) mBekFrontVal.textContent = `${x.bek_pct || 0}% / ${x.front_pct || 0}%`;
        if (mBekFrontGrade) mBekFrontGrade.textContent = `${nf.format(bekCnt)} БЭК · ${nf.format(frontCnt)} ФРОНТ`;
        document.getElementById('m-ops-val').textContent = nf.format(x.operations_count);
        document.getElementById('m-ops-daily').textContent = `${nf.format(x.operations_per_day)} опер./день`;
        document.getElementById('m-hours-val').textContent = x.hours_str;
        document.getElementById('m-days-val').textContent = `${x.days_worked} дн. (${x.days_worked_pct}%)`;

        const loadValEl = document.getElementById('m-load-val');
        loadValEl.innerHTML = x.load_percent > 100
          ? `${x.load_percent}%<br><span style="font-size:11px;font-weight:800;background:#fee2e2;color:#dc2626;border:1px solid #fca5a5;padding:2px 7px;border-radius:6px;display:inline-block;margin-top:4px">🔥 +${(x.load_percent - 100).toFixed(1)}% ortiqcha yuklama</span>`
          : `${x.load_percent}%`;
        document.getElementById('m-speed-val').textContent = `${x.avg_seconds_per_operation}с на опер.`;

        // --- БЭК / ФРОНТ split progress bar ---
        const bekPctSplit = Number(x.bek_pct || 0);
        document.getElementById('m-bek-lbl').textContent = `💼 БЭК: ${bekPctSplit}%`;
        document.getElementById('m-front-lbl').textContent = `💳 ФРОНТ: ${Number(x.front_pct || 0)}%`;
        document.getElementById('m-bek-bar').style.width = bekPctSplit + '%';
        document.getElementById('m-bek-cnt').textContent = `${nf.format(bekCnt)} БЭК операция`;
        document.getElementById('m-front-cnt').textContent = `${nf.format(frontCnt)} ФРОНТ операция`;

        // --- Operations detail table (only rows with count > 0) ---
        const topMetrics = (x.metrics || []).slice(0, 8);
        const tbody = document.getElementById('m-table-body');
        tbody.innerHTML = (x.metrics || []).filter(m => m.count > 0).map(m => {
          const isFront = m.section.includes('ФРОНТ');
          return `<tr style="background:${isFront ? '#eff6ff' : '#f5f3ff'}">
            <td><b>${escapeHtml(m.name)}</b></td>
            <td><span class="badge-role ${isFront ? 'badge-front' : 'badge-back'}" style="font-size:10px;padding:2px 7px">${m.section}</span></td>
            <td><b>${nf.format(m.count)}</b></td>
            <td><b>${m.pct}%</b></td>
            <td>${nf.format(m.minutes)} мин</td>
          </tr>`;
        }).join('') || '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:20px">Операциялар маълумоти йўқ</td></tr>';

        // --- Chart ---
        const ctx = document.getElementById('modal-chart');
        if (modalChart) { try { modalChart.destroy(); } catch(e) {} }
        modalChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: topMetrics.map(m => m.name),
            datasets: [{
              label: 'Доля (%)',
              data: topMetrics.map(m => m.pct),
              backgroundColor: topMetrics.map(m => m.section.includes('ФРОНТ') ? '#3b82f6' : '#7c3aed'),
              borderRadius: 6
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: (ctx) => ` ${ctx.parsed.x}% (${nf.format(topMetrics[ctx.dataIndex].count)} опер.)`
                }
              }
            },
            scales: { x: { max: 100, ticks: { callback: v => v + '%' } } }
          }
        });

        document.getElementById('detail-modal').classList.add('active');
      } catch(e) {
        alert(e.message);
      }
    }

    function closeModal() {
      document.getElementById('detail-modal').classList.remove('active');
    }

    function closeModalOnOverlay(e) {
      if (e.target.id === 'detail-modal') closeModal();
    }

    function setRole(role) {
      selectedRole = role || '';
      if (role === '') {
        selectedStatus = '';
        document.querySelectorAll('.st-pill').forEach(b => {
          b.classList.toggle('active', (b.dataset.status || '') === '');
        });
      }
      currentPage = 1;
      document.querySelectorAll('.pill-btn.role').forEach(b => {
        b.classList.toggle('active', (b.dataset.role || '') === (role || ''));
      });
      load();
    }

    function setStatus(st) {
      selectedStatus = st || '';
      currentPage = 1;
      document.querySelectorAll('.st-pill').forEach(b => {
        b.classList.toggle('active', (b.dataset.status || '') === (st || ''));
      });
      load();
    }

    function setPageSize(sz) {
      pageSize = parseInt(sz) || 25;
      currentPage = 1;
      load();
    }

    function goToPage(p) {
      p = parseInt(p);
      if (isNaN(p)) return;
      if (p < 1) p = 1;
      if (p > totalPages) p = totalPages;
      if (p !== currentPage) {
        currentPage = p;
        load();
        const tableEl = document.getElementById('rows');
        if (tableEl) tableEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }

    function renderPaginationControls(page, totalPages, total, size) {
      const container = document.getElementById('pagination-buttons');
      const infoEl = document.getElementById('pagination-info-text');
      if (!container) return;

      const startIdx = total > 0 ? (page - 1) * size + 1 : 0;
      const endIdx = Math.min(page * size, total);
      if (infoEl) {
        infoEl.textContent = total > 0 ? `Показано ${startIdx}–${endIdx} из ${total} кассиров` : 'Кассиры не найдены';
      }

      let html = '';
      html += `<button class="page-btn" onclick="goToPage(1)" ${page <= 1 ? 'disabled' : ''} title="Первая страница">«</button>`;
      html += `<button class="page-btn" onclick="goToPage(${page - 1})" ${page <= 1 ? 'disabled' : ''} title="Предыдущая">‹</button>`;

      let pages = [];
      const delta = 2;
      for (let i = Math.max(2, page - delta); i <= Math.min(totalPages - 1, page + delta); i++) {
        pages.push(i);
      }

      if (page - delta > 2) {
        pages.unshift('...');
      }
      pages.unshift(1);

      if (page + delta < totalPages - 1) {
        pages.push('...');
      }
      if (totalPages > 1) {
        pages.push(totalPages);
      }

      pages.forEach(p => {
        if (p === '...') {
          html += `<span class="page-dots">...</span>`;
        } else {
          const activeClass = p === page ? 'active' : '';
          html += `<button class="page-btn ${activeClass}" onclick="goToPage(${p})">${p}</button>`;
        }
      });

      html += `<button class="page-btn" onclick="goToPage(${page + 1})" ${page >= totalPages ? 'disabled' : ''} title="Следующая">›</button>`;
      html += `<button class="page-btn" onclick="goToPage(${totalPages})" ${page >= totalPages ? 'disabled' : ''} title="Последняя страница">»</button>`;

      container.innerHTML = html;

      const jumpInput = document.getElementById('page-jump-input');
      if (jumpInput) {
        jumpInput.value = page;
        jumpInput.max = totalPages;
      }
    }

    function go(delta) {
      goToPage(currentPage + delta);
    }

    lucide.createIcons();
    load();
