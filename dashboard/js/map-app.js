// ═══════════════════════════════════════════════════════════
// DATA
// ═══════════════════════════════════════════════════════════

// ATM_META загружается с /api/atms (единый источник правды — реестр + реальный
// баланс от atm_monitor, если он опрашивается для этого банкомата).
let ATM_META = [];

// ═══════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════

let atmState      = {};
let refreshTimer  = null;
let selectedId    = null;
let markers       = {};

// Global Search State
let currentSearchQuery = "";
let selectedRegionFromModal = null;
let selectedAtmIdsFromModal = null; // Set of IDs (null if no modal filter is active)

function hydrateIcons(root) {
  if (!window.lucide || typeof lucide.createIcons !== 'function') return;
  try {
    const opts = {
      attrs: { 'stroke-width': '2.4' },
      nameAttr: 'data-lucide',
    };
    if (root) opts.root = root;
    lucide.createIcons(opts);
  } catch (err) {
    console.warn('lucide.createIcons failed:', err);
  }
}

function appIcon(name, extra = '') {
  return `<i data-lucide="${name}" class="icon-inline ${extra}"></i>`;
}

// ═══════════════════════════════════════════════════════════
// REGION SEARCH & FILTER FUNCTIONS
// ═══════════════════════════════════════════════════════════

function getFilteredATMs() {
  return ATM_META.filter(atm => {
    // 1. Filter by region/ATMs selected in modal if active
    if (selectedAtmIdsFromModal) {
      if (!selectedAtmIdsFromModal.has(atm.id)) return false;
    }
    
    // 2. Filter by search input query if typed
    if (currentSearchQuery) {
      const q = currentSearchQuery.toLowerCase();
      const name = (atm.name || "").toLowerCase();
      const addr = (atm.address || "").toLowerCase();
      const reg = (atm.region || "").toLowerCase();
      const bank = (atm.bank || "").toLowerCase();
      
      return name.includes(q) || addr.includes(q) || reg.includes(q) || bank.includes(q);
    }
    
    return true;
  });
}

function updateMarkersHighlight(filtered) {
  if (!atmsVisible) {
    Object.values(markers).forEach(marker => {
      if (map.hasLayer(marker)) map.removeLayer(marker);
    });
    return;
  }

  const isFiltering = currentSearchQuery !== "" || selectedAtmIdsFromModal !== null;
  const filteredSet = new Set(filtered.map(a => a.id));
  
  Object.entries(markers).forEach(([id, marker]) => {
    const st = atmState[id] || { status: 'ok' };
    const isMatched = filteredSet.has(id);
    
    if (isFiltering) {
      if (isMatched) {
        setAtmMarkerIcon(marker, st.status, true);
        marker.setOpacity(1.0);
        if (!map.hasLayer(marker)) marker.addTo(map);
      } else {
        setAtmMarkerIcon(marker, st.status, false);
        marker.setOpacity(0.25);
        if (!map.hasLayer(marker)) marker.addTo(map);
      }
    } else {
      setAtmMarkerIcon(marker, st.status, false);
      marker.setOpacity(1.0);
      if (!map.hasLayer(marker)) marker.addTo(map);
    }
  });
}

function zoomToFiltered(filtered) {
  if (!filtered || filtered.length === 0) return;
  const points = [];
  filtered.forEach(atm => {
    const lat = parseFloat(atm.lat);
    const lon = parseFloat(atm.lon);
    if (!isNaN(lat) && !isNaN(lon) && lat !== 0 && lon !== 0) {
      points.push([lat, lon]);
    }
  });
  if (points.length > 0) {
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
  }
}

function onLeftSearchInput() {
  const input = document.getElementById('left-search-input');
  currentSearchQuery = input.value.trim();
  renderList();
  
  if (currentSearchQuery) {
    const filtered = getFilteredATMs();
    zoomToFiltered(filtered);
  }
}

function openRegionModal() {
  const modal = document.getElementById('region-modal');
  modal.style.display = 'flex';
  
  const select = document.getElementById('region-select');
  select.innerHTML = '<option value="">-- Все регионы --</option>';
  
  const regions = [...new Set(ATM_META.map(a => a.region).filter(Boolean))].sort();
  regions.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r;
    opt.textContent = r;
    select.appendChild(opt);
  });
  
  if (selectedRegionFromModal) {
    select.value = selectedRegionFromModal === "Все регионы" ? "" : selectedRegionFromModal;
  }
  
  onRegionChange();
  hydrateIcons();
}

function closeRegionModal() {
  document.getElementById('region-modal').style.display = 'none';
}

function onRegionChange() {
  const select = document.getElementById('region-select');
  const region = select.value;
  
  const container = document.getElementById('modal-atm-list');
  container.innerHTML = '';
  
  const atms = region 
    ? ATM_META.filter(a => a.region === region)
    : ATM_META;
    
  document.getElementById('modal-atm-count-val').textContent = `${atms.length} из ${atms.length}`;
  
  atms.forEach(atm => {
    const item = document.createElement('div');
    item.className = 'modal-atm-item';
    
    const isChecked = selectedAtmIdsFromModal 
      ? selectedAtmIdsFromModal.has(atm.id)
      : true;
      
    item.innerHTML = `
      <input type="checkbox" id="modal-atm-${atm.id}" value="${atm.id}" ${isChecked ? 'checked' : ''} onchange="updateModalAtmCount()">
      <div class="modal-atm-details">
        <span class="modal-atm-name">${atm.name} (${atm.bank})</span>
        <span class="modal-atm-address">${atm.address || 'Адрес не указан'}</span>
      </div>
    `;
    container.appendChild(item);
  });
}

function updateModalAtmCount() {
  const container = document.getElementById('modal-atm-list');
  const checkedCount = container.querySelectorAll('input[type="checkbox"]:checked').length;
  const totalCount = container.querySelectorAll('input[type="checkbox"]').length;
  document.getElementById('modal-atm-count-val').textContent = `${checkedCount} из ${totalCount}`;
}

function performRegionSearch() {
  const select = document.getElementById('region-select');
  const region = select.value;
  
  const container = document.getElementById('modal-atm-list');
  const checkedBoxes = container.querySelectorAll('input[type="checkbox"]:checked');
  
  if (checkedBoxes.length === 0) {
    alert('Пожалуйста, выберите хотя бы один банкомат или отмените поиск.');
    return;
  }
  
  selectedRegionFromModal = region || "Все регионы";
  selectedAtmIdsFromModal = new Set(Array.from(checkedBoxes).map(cb => cb.value));
  
  const banner = document.getElementById('filter-banner');
  const regionNameEl = document.getElementById('filter-region-name');
  const countEl = document.getElementById('filter-count');
  
  regionNameEl.textContent = selectedRegionFromModal;
  countEl.textContent = selectedAtmIdsFromModal.size;
  banner.style.display = 'flex';
  
  closeRegionModal();
  renderList();
  
  const filtered = getFilteredATMs();
  zoomToFiltered(filtered);
}

function clearRegionFilter() {
  selectedRegionFromModal = null;
  selectedAtmIdsFromModal = null;
  
  document.getElementById('filter-banner').style.display = 'none';
  document.getElementById('left-search-input').value = '';
  currentSearchQuery = '';
  
  renderList();
}

// ═══════════════════════════════════════════════════════════
// MAP INIT
// ═══════════════════════════════════════════════════════════

const map = L.map('map', { zoomControl: true }).setView([41.3510, 69.2900], 14);

L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '© OpenStreetMap © CARTO',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);

// Явно показываем, что проект ограничен только Юнусабадским районом.
// Приоритет: точная граница из GeoJSON, fallback: bbox.
const DISTRICT_COLORS = [
  '#3b82f6', // blue
  '#10b981', // green
  '#8b5cf6', // purple
  '#f59e0b', // amber
  '#ec4899', // pink
  '#14b8a6', // teal
  '#f43f5e', // rose
  '#06b6d4', // cyan
  '#6366f1', // indigo
  '#a855f7', // purple-500
  '#22c55e', // green-500
  '#eab308'  // yellow
];

function getDistrictColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % DISTRICT_COLORS.length;
  return DISTRICT_COLORS[index];
}

let countryBorderLayer = null;
let regionsLayer = null;
let districtsLayer = null;

// 1. Граница Узбекистана (жирный контур)
async function addUzbekistanBorder() {
  try {
    const res = await fetch('/uzbekistan.geojson');
    if (!res.ok) throw new Error('uzbekistan.geojson not found');
    const geo = await res.json();

    if (countryBorderLayer) map.removeLayer(countryBorderLayer);

    countryBorderLayer = L.geoJSON(geo, {
      style: {
        color: '#0f172a', // темно-грифельный
        weight: 5,       // жирная линия
        fillOpacity: 0,  // без заливки
      },
      interactive: false // клики проходят сквозь границу
    }).addTo(map);
    console.log('Uzbekistan outer border loaded');
  } catch (err) {
    console.warn('Failed to load Uzbekistan border:', err);
  }
}

// 2. Границы областей Узбекистана
async function addRegionalBoundaries() {
  try {
    const res = await fetch('/uzbekistan_regional.geojson');
    if (!res.ok) throw new Error('uzbekistan_regional.geojson not found');
    const geo = await res.json();

    if (regionsLayer) map.removeLayer(regionsLayer);

    regionsLayer = L.geoJSON(geo, {
      style: function(feature) {
        const name = feature.properties.ADM1_RU || feature.properties.ADM1_EN || 'Область';
        const color = getDistrictColor(name);
        return {
          color: '#94a3b8',
          weight: 1.4,
          fillColor: '#fff',
          fillOpacity: 0,
        };
      },
      onEachFeature: function(feature, layer) {
        const p = feature.properties || {};
        const nameRu = p.ADM1_RU || 'Неизвестная область';
        const nameUz = p.ADM1_UZ || '';
        const nameEn = p.ADM1_EN || '';

        layer.bindPopup(`<div style="font-family:inherit;font-size:13px;">
          <b style="font-size:14px;color:#0f172a;">${nameRu}</b><br>
          <span style="color:#64748b;font-weight:500;">${nameUz || nameEn}</span>
        </div>`);

        layer.on({
          mouseover: function(e) {
            const l = e.target;
            l.setStyle({
              fillColor: '#64748b',
              fillOpacity: 0.08,
              weight: 2.2,
            });
          },
          mouseout: function(e) {
            const l = e.target;
            l.setStyle({
              fillColor: '#fff',
              fillOpacity: 0,
              weight: 1.4,
            });
          }
        });
      }
    }).addTo(map);
    console.log('Uzbekistan regional boundaries loaded');
  } catch (err) {
    console.warn('Failed to load regional boundaries:', err);
  }
}

// 3. Границы районов Ташкента (тонкий контур внутри Ташкента)
async function addDistrictBoundaries() {
  try {
    const res = await fetch('/tashkent_districts.geojson');
    if (!res.ok) throw new Error('tashkent_districts.geojson not found');
    const geo = await res.json();

    if (districtsLayer) map.removeLayer(districtsLayer);

    districtsLayer = L.geoJSON(geo, {
      style: {
        color: '#94a3b8',   // легкий светло-серый
        weight: 1.2,        // тонкий штрих
        fillOpacity: 0,     // прозрачный, чтобы не перекрывать заливку областей
        dashArray: '3 3',   // пунктир
      },
      onEachFeature: function(feature, layer) {
        const p = feature.properties || {};
        const nameRu = p.ADM2_RU || 'Район';
        const nameUz = p.ADM2_UZ || '';

        layer.bindPopup(`<div style="font-family:inherit;font-size:12px;">
          <b style="color:#334155;">Район: ${nameRu}</b><br>
          <span style="color:#94a3b8;">${nameUz}</span>
        </div>`);
      }
    }).addTo(map);
    console.log('Tashkent district boundaries loaded');
  } catch (err) {
    console.warn('Failed to load district boundaries:', err);
  }
}

// Инициализируем слои по порядку наложения
async function initMapLayers() {
  await addRegionalBoundaries();
  await addDistrictBoundaries();
  await addUzbekistanBorder();
}
initMapLayers();

function makeIcon(status, isHighlighted = false) {
  const colors = { ok:'#22c55e', warning:'#f59e0b', critical:'#ef4444' };
  const c = colors[status] || '#94a3b8';
  // Inline SVG — избегаем lucide.createIcons() здесь, чтобы смена иконки не мигала
  const glyph = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/></svg>`;

  if (isHighlighted) {
    return L.divIcon({
      className: 'atm-marker-icon',
      html: `<div class="marker-highlighted" style="
        width:34px;height:34px;border-radius:50%;
        background:${c};border:3.5px solid #facc15;
        box-shadow:0 0 15px #facc15, 0 0 6px ${c};
        display:flex;align-items:center;justify-content:center;
        color:#fff;
        animation: marker-pulse 1.2s infinite alternate;
      ">${glyph}</div>`,
      iconSize: [34,34], iconAnchor: [17,17],
    });
  }

  return L.divIcon({
    className: 'atm-marker-icon',
    html: `<div style="
      width:28px;height:28px;border-radius:50%;
      background:${c};border:3px solid #fff;
      box-shadow:0 0 12px ${c}99;
      display:flex;align-items:center;justify-content:center;
      color:#fff;
    ">${glyph}</div>`,
    iconSize: [28,28], iconAnchor: [14,14],
  });
}

function setAtmMarkerIcon(marker, status, isHighlighted = false) {
  if (!marker) return;
  const key = `${status}|${isHighlighted ? 1 : 0}`;
  if (marker._atmIconKey === key) return;
  marker._atmIconKey = key;
  marker.setIcon(makeIcon(status, isHighlighted));
}

let atmsVisible = true;

function clearAtmMarkers() {
  Object.values(markers).forEach((marker) => {
    try { map.removeLayer(marker); } catch (_) {}
  });
  markers = {};
}

function initMarkers(fit = true) {
  clearAtmMarkers();
  const points = [];
  ATM_META.forEach(atm => {
    const lat = parseFloat(atm.lat);
    const lon = parseFloat(atm.lon);
    if (!isNaN(lat) && !isNaN(lon) && lat !== 0 && lon !== 0) {
      const st = atmState[atm.id]?.status || 'ok';
      const m = L.marker([lat, lon], { icon: makeIcon(st) })
        .on('click', () => selectAtm(atm.id));
      m._atmIconKey = `${st}|0`;
      if (atmsVisible) m.addTo(map);
      markers[atm.id] = m;
      points.push([lat, lon]);
    }
  });
  console.log(`Placed ${points.length} markers on the map out of ${ATM_META.length} ATMs`);
  if (fit && points.length > 0) {
    map.fitBounds(L.latLngBounds(points), { padding: [50, 50] });
  }
  syncAtmsToggleBtn();
}

function syncAtmsToggleBtn() {
  const btn = document.getElementById('atms-toggle-btn');
  if (!btn) return;
  if (atmsVisible) {
    btn.style.background = '#2563eb';
    btn.style.color = '#fff';
    btn.style.borderColor = '#2563eb';
  } else {
    btn.style.background = '';
    btn.style.color = '';
    btn.style.borderColor = '';
  }
}

function toggleAtmsLayer() {
  atmsVisible = !atmsVisible;
  Object.values(markers).forEach((marker) => {
    if (atmsVisible) {
      if (!map.hasLayer(marker)) marker.addTo(map);
    } else if (map.hasLayer(marker)) {
      map.removeLayer(marker);
    }
  });
  if (atmsVisible) updateMarkersHighlight(getFilteredATMs());
  syncAtmsToggleBtn();
  hydrateIcons();
}

// ═══════════════════════════════════════════════════════════
// ФИЛИАЛЫ — отдельный слой на карте
// ═══════════════════════════════════════════════════════════

let branchesLayer   = null;
let branchesVisible = false;
let branchesLoaded  = false;
let branchesCache   = [];
let warehouseOnly   = false;

function fmtBranchMoney(v, digits = 0) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function getUsdAmount(cash) {
  if (!cash || !Array.isArray(cash.currencies)) return null;
  const usd = cash.currencies.find(c => String(c.iso) === '840' || c.code === 'USD');
  return usd && usd.amount != null ? Number(usd.amount) : null;
}

function closeBranchCashPanel() {
  const panel = document.getElementById('branch-cash-panel');
  if (panel) panel.classList.remove('open');
}

function openBranchCashPanelByCode(localCode) {
  const b = branchesCache.find(x => String(x.local_code) === String(localCode));
  if (b) openBranchCashPanel(b);
}

function openBranchCashPanel(branch) {
  const panel = document.getElementById('branch-cash-panel');
  const body = document.getElementById('bcp-body');
  const title = document.getElementById('bcp-title');
  if (!panel || !body) return;

  // marshrut / analytics paneli bilan birga ochilmasin
  const routeSb = document.getElementById('route-sidebar');
  if (routeSb) routeSb.classList.remove('open');
  
  const cash = branch.cash || null;
  const isInc = !!branch.incassation;
  const code = branch.local_code || '—';
  if (title) title.textContent = `Касса · ${code}`;

  if (!cash) {
    body.innerHTML = `
      <div class="popup-row">Регион: <span>${branch.region || '—'}</span></div>
      <div class="popup-row">Адрес: <span>${branch.address || '—'}</span></div>
      <div style="margin-top:14px;padding:12px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0;color:#64748b;font-size:13px;line-height:1.45">
        Кассовый остаток для этого филиала не загружен.
        Импорт: <b>Импорт → Остатки филиалов</b>.
      </div>`;
    panel.classList.add('open');
    hydrateIcons();
    return;
  }

  const usdAmount = getUsdAmount(cash);
  const limitUsd = cash.limit_usd != null ? Number(cash.limit_usd) : null;
  let usdStatusHtml = '';
  if (usdAmount != null && limitUsd != null) {
    const below = usdAmount < limitUsd;
    usdStatusHtml = below
      ? `<div style="margin-top:8px;padding:8px 10px;border-radius:10px;background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;font-size:12px;font-weight:800">
           ⚠ Ниже минимума — нужно пополнить USD
         </div>`
      : `<div style="margin-top:8px;padding:8px 10px;border-radius:10px;background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d;font-size:12px;font-weight:800">
           ✓ В норме — USD не ниже минимума
         </div>`;
  }

  const usdCardBorder = (usdAmount != null && limitUsd != null && usdAmount < limitUsd)
    ? 'background:#fef2f2;border:1px solid #fecaca'
    : 'background:#eff6ff;border:1px solid #bfdbfe';
  const usdValueColor = (usdAmount != null && limitUsd != null && usdAmount < limitUsd)
    ? '#991b1b' : '#1e3a8a';

  const usage = cash.usage_pct != null
    ? `<div style="margin:10px 0 4px;height:6px;background:#e2e8f0;border-radius:99px;overflow:hidden">
         <div style="height:100%;width:${Math.min(100, cash.usage_pct)}%;background:${cash.usage_pct > 90 ? '#dc2626' : cash.usage_pct > 70 ? '#d97706' : '#16a34a'}"></div>
       </div>`
    : '';

  const fc = cash.forecast || null;
  let forecastHtml = '';
  if (fc) {
    const savingsPositive = fc.potential_savings_uzs != null && fc.potential_savings_uzs > 0;
    const trendUp = fc.trend_pct_per_month != null && fc.trend_pct_per_month > 0.5;
    const trendDown = fc.trend_pct_per_month != null && fc.trend_pct_per_month < -0.5;
    const trendLabel = trendUp ? `↑ +${fc.trend_pct_per_month}%` : trendDown ? `↓ ${fc.trend_pct_per_month}%` : '≈ стабильно';
    const trendColor = trendUp ? '#b45309' : trendDown ? '#15803d' : '#64748b';
    forecastHtml = `
      <div class="bcp-card" style="margin-top:8px;background:#faf5ff;border-color:#e9d5ff">
        <div class="bcp-label" style="color:#7c3aed">Прогноз на след. месяц</div>
        <div class="bcp-value" style="color:#581c87;font-size:15px">${fmtBranchMoney(fc.forecast_next_month_avg_uzs)} <span style="font-size:10px;font-weight:700">сўm · можно держать</span></div>
        <div class="bcp-hint">Диапазон: ${fmtBranchMoney(fc.forecast_next_month_min_uzs)} — ${fmtBranchMoney(fc.forecast_next_month_max_uzs)} · тренд <span style="color:${trendColor};font-weight:800">${trendLabel}</span></div>
        <div style="display:flex;justify-content:space-between;gap:10px;margin-top:10px;padding-top:8px;border-top:1px dashed #e9d5ff">
          <div>
            <div style="font-size:10px;color:#64748b;font-weight:700">Тек. лимит</div>
            <div style="font-size:13px;font-weight:850;color:#581c87">${fmtBranchMoney(fc.current_limit_uzs)}</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:10px;color:#64748b;font-weight:700">Рек. лимит</div>
            <div style="font-size:13px;font-weight:850;color:#581c87">${fmtBranchMoney(fc.recommended_limit_uzs)}</div>
          </div>
        </div>
        ${savingsPositive ? `
          <div style="margin-top:8px;padding:8px 10px;border-radius:10px;background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d;font-size:12px;font-weight:800">
            ✓ Лимит можно снизить на ≈ ${fmtBranchMoney(fc.potential_savings_uzs)} сўм
          </div>` : ''}
        <div class="bcp-hint" style="margin-top:6px;opacity:.7">На основе истории остатков (${fc.history_days} дн.)</div>
      </div>`;
  }

  const ccyRows = (cash.currencies || [])
    .filter(c => c.amount !== null && c.amount !== undefined)
    .map(c => {
      const isUsd = String(c.iso) === '840';
      const warn = isUsd && limitUsd != null && Number(c.amount) < limitUsd;
      return `
        <tr style="${warn ? 'background:#fef2f2' : ''}">
          <td>${c.name_ru || c.name}<br><span style="font-size:9px;color:#94a3b8">${c.code} · ${c.iso}</span></td>
          <td style="font-weight:700;${warn ? 'color:#b91c1c' : ''}">${fmtBranchMoney(c.amount, 2)}</td>
          <td style="color:#1d4ed8">${c.rate_uzs != null ? fmtBranchMoney(c.rate_uzs, 0) : '—'}</td>
          <td>${c.uzs_equivalent != null ? fmtBranchMoney(c.uzs_equivalent, 0) : '—'}</td>
        </tr>`;
    }).join('');

  body.innerHTML = `
    <div style="font-size:12px;font-weight:800;color:#0f172a;margin-bottom:4px">${cash.branch_name || branch.address || code}</div>
    <div class="popup-row">Код: <span>${code}${branch.number ? ' · №' + branch.number : ''}</span></div>
    <div class="popup-row">Регион: <span>${branch.region || '—'}</span></div>
    <div class="popup-row">Тип: <span style="color:${isInc ? '#7c3aed' : '#64748b'};font-weight:700">
      ${isInc ? 'Для выезда инкассаторов' : 'Обычный филиал'}
    </span></div>

    <div class="bcp-card" style="margin-top:12px;background:#f0fdf4;border-color:#bbf7d0">
      <div class="bcp-label" style="color:#15803d">Остаток (сўм)</div>
      <div class="bcp-value" style="color:#14532d">${fmtBranchMoney(cash.balance_uzs)}</div>
      <div class="bcp-hint">Сейчас в кассе</div>
    </div>

    <div class="bcp-card" style="margin-top:8px;background:#eff6ff;border-color:#bfdbfe">
      <div class="bcp-label" style="color:#1d4ed8">Лимит сўм (максимум)</div>
      <div class="bcp-value" style="color:#1e3a8a;font-size:14px">${fmtBranchMoney(cash.limit_uzs)} <span style="font-size:10px;font-weight:700">сўм</span></div>
      <div class="bcp-hint">Столько максимум можно держать в сўм</div>
    </div>
    ${usage}
    ${forecastHtml}

    <div class="bcp-card" style="margin-top:8px;${usdCardBorder}">
      <div class="bcp-label" style="color:${usdValueColor}">Лимит USD (минимум)</div>
      <div style="display:flex;justify-content:space-between;gap:10px;margin-top:6px;align-items:flex-end">
        <div>
          <div style="font-size:10px;color:#64748b;font-weight:700">Сейчас USD</div>
          <div style="font-size:15px;font-weight:850;color:${usdValueColor}">${fmtBranchMoney(usdAmount, 2)}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:10px;color:#64748b;font-weight:700">Мин. лимит</div>
          <div style="font-size:15px;font-weight:850;color:${usdValueColor}">${fmtBranchMoney(limitUsd, 2)}</div>
        </div>
      </div>
      <div class="bcp-hint">Если USD ниже минимума — касса в дефиците (красный)</div>
      ${usdStatusHtml}
    </div>

    <div style="font-size:10px;font-weight:800;color:#334155;margin:14px 0 6px;text-transform:uppercase;letter-spacing:.04em">Valyuta · SQB xarid</div>
    ${ccyRows ? `
      <table>
        <thead>
          <tr>
            <th>Valyuta</th>
            <th>Summa</th>
            <th>Xarid</th>
            <th>≈ sўm</th>
          </tr>
        </thead>
        <tbody>${ccyRows}</tbody>
      </table>
      ${cash.fx_uzs_equivalent != null ? `<div style="font-size:10px;color:#0f766e;margin-top:8px;font-weight:700">Valyuta jami ≈ ${fmtBranchMoney(cash.fx_uzs_equivalent, 0)} sўm</div>` : ''}
    ` : `<div style="font-size:12px;color:#94a3b8">Валютные остатки не указаны (− / пусто)</div>`}
  `;

  panel.classList.add('open');
  hydrateIcons();
  if (map && map.closePopup) map.closePopup();
}

function makeBranchIcon(incassation) {
  const c = incassation ? '#7c3aed' : '#64748b';
  const glyph = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/></svg>`;
  return L.divIcon({
    className: 'branch-marker-icon',
    html: `<div style="
      width:26px;height:26px;border-radius:7px;
      background:${c};border:2.5px solid #fff;
      box-shadow:0 0 10px ${c}99;
      display:flex;align-items:center;justify-content:center;
      color:#fff;
    ">${glyph}</div>`,
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

async function loadBranches() {
  try {
    const res = await fetch(`${API_BASE}/api/branches?limit=5000`);
    if (!res.ok) throw new Error('Failed to fetch branches');
    const data = await res.json();
    const branches = data.branches || [];
    branchesCache = branches;

    if (branchesLayer) map.removeLayer(branchesLayer);
    branchesLayer = L.layerGroup();

    let withInc = 0, withoutInc = 0, plotted = 0, withCash = 0, skippedNoCash = 0;
    branches.forEach(b => {
      const lat = parseFloat(b.lat);
      const lon = parseFloat(b.lon);
      if (isNaN(lat) || isNaN(lon) || lat === 0 || lon === 0) return;

      const cash = b.cash || null;
      if (cash) withCash++;
      if (warehouseOnly && !cash) {
        skippedNoCash++;
        return;
      }

      const isInc = !!b.incassation;
      if (isInc) withInc++; else withoutInc++;
      plotted++;

      const marker = L.marker([lat, lon], { icon: makeBranchIcon(isInc) });
      marker.bindPopup(`
        <div class="popup-title">${appIcon('building-2')}${b.local_code || ''}${b.number ? ' · №' + b.number : ''}</div>
        <div class="popup-row">Регион: <span>${b.region || '—'}</span></div>
        <div class="popup-row" style="max-width:220px">Адрес: <span>${b.address || '—'}</span></div>
        <div class="popup-row">Тип: <span style="color:${isInc ? '#7c3aed' : '#64748b'};font-weight:700">
          ${isInc ? 'Для выезда инкассаторов' : 'Обычный филиал'}
        </span></div>
        <button onclick="openBranchCashPanelByCode('${String(b.local_code || '').replace(/'/g, "\\'")}')"
          style="margin-top:10px;width:100%;padding:8px 10px;border:0;border-radius:10px;background:#0d9488;color:#fff;font-weight:800;font-size:12px;cursor:pointer">
          ${cash ? 'Открыть кассу филиала →' : 'Касса не загружена'}
        </button>
      `, { maxWidth: 260 });
      marker.on('click', () => {
        if (cash) openBranchCashPanel(b);
      });
      branchesLayer.addLayer(marker);
    });

    const modeEl = document.getElementById('branches-legend-mode');
    if (modeEl) modeEl.style.display = warehouseOnly ? 'block' : 'none';

    document.getElementById('branches-legend-count').textContent = warehouseOnly
      ? `Со складом на карте: ${plotted} · в файле остатков: ${withCash} · скрыто без остатков: ${skippedNoCash}`
      : `На карте: ${plotted} · со складом: ${withCash} · инкассаторских: ${withInc} · всего: ${branches.length}`;

    branchesLoaded = true;
    console.log(`Loaded ${branches.length} branches, plotted ${plotted}, warehouseOnly=${warehouseOnly}`);

    if (!branches.length) {
      branchesLoaded = false;
      alert('В базе нет филиалов. Сначала загрузите реестр через «Импорт филиалов».');
      return false;
    }
    if (!plotted) {
      if (warehouseOnly) {
        alert(
          'Режим «только со складом»: нет филиалов с загруженными остатками.\n\n' +
          'Сначала Импорт → Остатки филиалов, затем снова включите слой.'
        );
        return false;
      }
      branchesLoaded = false;
      alert(
        `Филиалы в базе: ${branches.length}, но ни у одного нет координат (широта/долгота).\n\n` +
        'Поэтому на карте они не отображаются.\n\n' +
        'Загрузите XLSX заново через Импорт → Филиалы, с колонками Lat и Lon ' +
        '(или двумя колонками «Геолокация») и включите «Очистить таблицу перед импортом».'
      );
      return false;
    }
    return true;
  } catch (err) {
    console.warn('Failed to load branches:', err);
    alert('Не удалось загрузить филиалы: ' + (err.message || err));
    return false;
  }
}

function syncWarehouseToggleBtn() {
  const btn = document.getElementById('warehouse-toggle-btn');
  if (!btn) return;
  if (warehouseOnly) {
    btn.style.background = '#0d9488';
    btn.style.color = '#fff';
    btn.style.borderColor = '#0d9488';
  } else {
    btn.style.background = '';
    btn.style.color = '';
    btn.style.borderColor = '';
  }
}

async function toggleWarehouseOnly() {
  warehouseOnly = !warehouseOnly;
  syncWarehouseToggleBtn();
  if (!branchesLoaded) {
    const ok = await loadBranches();
    if (!ok) { warehouseOnly = !warehouseOnly; syncWarehouseToggleBtn(); return; }
  } else {
    const ok = await loadBranches();
    if (!ok && warehouseOnly) {
      // keep mode on but layer may be empty
    }
  }
  if (branchesVisible && branchesLayer) {
    if (!map.hasLayer(branchesLayer)) branchesLayer.addTo(map);
    document.getElementById('branches-legend').style.display = 'block';
  }
  hydrateIcons();
}

async function toggleBranchesLayer() {
  const btn = document.getElementById('branches-toggle-btn');
  const legend = document.getElementById('branches-legend');

  if (!branchesLoaded) {
    const ok = await loadBranches();
    if (!ok) return;
  }

  branchesVisible = !branchesVisible;

  if (branchesVisible) {
    if (branchesLayer) branchesLayer.addTo(map);
    legend.style.display = 'block';
    btn.style.background = '#7c3aed';
    btn.style.color = '#fff';
    btn.style.borderColor = '#7c3aed';
  } else {
    if (branchesLayer) map.removeLayer(branchesLayer);
    legend.style.display = 'none';
    btn.style.background = '';
    btn.style.color = '';
    btn.style.borderColor = '';
  }
  hydrateIcons();
}




// ═══════════════════════════════════════════════════════════
// LOAD CSV
// ═══════════════════════════════════════════════════════════

// Автоматически подхватываем хост — работает и на localhost и на любом сервере
const API_BASE = location.origin;

function hideLoader() {
  const loader = document.getElementById('loader');
  if (!loader) return;
  loader.style.display = 'none';
  loader.classList.add('is-hidden');
  loader.setAttribute('hidden', '');
  loader.style.pointerEvents = 'none';
}

async function loadAtmsFromDb() {
  try {
    const res = await fetch(`${API_BASE}/api/atms?limit=5000`);
    if (!res.ok) throw new Error('Failed to fetch ATMs from DB');
    const data = await res.json();
    if (data && data.atms) {
      ATM_META = data.atms.map(a => {
        const capacity = a.capacity || 400000000;
        const balance = a.balance != null ? Number(a.balance) : null;
        const pct = (balance != null && capacity) ? balance / capacity : null;
        let status = a.status || 'unknown';
        if (pct != null) {
          if (pct < 0.2) status = 'critical';
          else if (pct < 0.4) status = 'warning';
          else status = 'ok';
        }
        return {
          // Внутренний ключ карты/маршрутов/API остаётся terminal_id из реестра —
          // это то, по чему бэкенд ищет ATM (/api/atms/{terminal_id}/...), менять нельзя.
          id:              a.terminal_id,
          // А вот отображаемый номер — реальный id BTech (tid), если ATM у него есть
          // (даже когда найден только по координатам, а не по terminal_id).
          // Иначе — как раньше, локальный номер из реестра.
          name:            a.live_tid || a.atm_number || a.terminal_id,
          bank:            a.branch || 'SQB',
          address:         a.address || 'Адрес не указан',
          lat:             a.lat,
          lon:             a.lon,
          capacity,
          balance,
          status,
          region:          a.region,
          // Реальные данные от сборщика atm_monitor (если этот ATM им опрашивается).
          // live_match: 'terminal_id' — точное совпадение id; 'location' — id в реестре
          // не совпал с id BTech (разные сети), совпадение найдено по координатам.
          live:            !!a.live,
          liveMatch:       a.live_match || null,
          liveTid:         a.live_tid || null,
          agentStatus:     a.agent_status || null,
          forecastHours:   a.forecast_hours ?? null,
          balancePolledAt: a.balance_polled_at || null,
          lastIncassation: a.last_incassation || null,
          // Реальные кассеты (список, не словарь по номиналу — у части моделей
          // бывает несколько кассет одного номинала, терять их нельзя).
          cassettes:       Array.isArray(a.cassettes) && a.cassettes.length ? a.cassettes : null,
        };
      });
      console.log(`Loaded ${ATM_META.length} ATMs from DB (${ATM_META.filter(a => a.live).length} с живыми данными atm_monitor)`);
      return true;
    }
  } catch (err) {
    console.warn('Failed to load ATMs from DB:', err);
  }
  return false;
}

// Оценка разбивки остатка по 4 номиналам — та же формула, что и на бэкенде
// (api/main.py::get_atm_cassettes), пока для этого ATM нет реальных данных
// по кассетам от atm_monitor. Честно помечена как оценка.
// Максимум CASSETTE_MAX_COUNT купюр в одной кассете (физический потолок) —
// баланс кассеты не подгоняется под общий остаток, а честно считается
// как количество купюр × номинал после этого ограничения.
const CASSETTE_SHARE = { 10000: 0.10, 50000: 0.45, 100000: 0.30, 200000: 0.15 };
const CASSETTE_MAX_COUNT = 2000;

function estimateCassettes(balance, capacity) {
  if (balance == null || !capacity) return [];
  return Object.entries(CASSETTE_SHARE).map(([denomStr, share]) => {
    const denom = Number(denomStr);
    const count = Math.min(Math.floor((balance * share) / denom), CASSETTE_MAX_COUNT);
    return {
      denomination: denom,
      count,
      balance: count * denom,
      capacity: CASSETTE_MAX_COUNT,
      fill_pct: Math.round((count / CASSETTE_MAX_COUNT) * 100 * 10) / 10,
    };
  });
}

// Реальные статусы кассет от BTech (не только OK/LOW/MISSING).
const CASSETTE_STATUS_COLOR = {
  OK: '#22c55e', FULL: '#22c55e', HIGH: '#22c55e',
  LOW: '#f59e0b',
  EMPTY: '#ef4444', MISSING: '#ef4444',
  INOP: '#94a3b8', // кассета не в работе — не про уровень наличных, про исправность
};

// Плитки кассет для карточки списка. Реальные кассеты — список (не словарь по
// номиналу): у части моделей встречается несколько кассет одного номинала
// (например, две по 200 000 — их нельзя схлопывать в одну).
function cassetteTilesHtml(cassettes, source) {
  if (source === 'live') {
    return (cassettes || []).map(c => {
      const color = CASSETTE_STATUS_COLOR[c.status] || '#94a3b8';
      const denomTxt = c.nominal >= 1000 ? (c.nominal / 1000).toFixed(0) + 'к' : (c.nominal ?? '—');
      return `<div style="background:#f8fafc;border:1px solid #e5eaf3;border-radius:10px;padding:5px 7px">
        <div style="display:flex;justify-content:space-between;font-size:9px;color:#667085;margin-bottom:4px;font-weight:700">
          <span>${denomTxt} сум</span><span style="color:${color}">${c.status || '—'}</span>
        </div>
        <div style="font-size:9px;color:#667085">${c.balance != null ? (c.balance/1e6).toFixed(1) + ' млн' : '—'} · ${c.count ?? '—'} шт</div>
      </div>`;
    }).join('');
  }
  return (cassettes || []).map(c => {
    const fillColor = c.fill_pct > 60 ? '#22c55e' : c.fill_pct > 25 ? '#f59e0b' : '#ef4444';
    const denom = c.denomination >= 1000 ? (c.denomination/1000).toFixed(0)+'к' : c.denomination;
    return `<div style="background:#f8fafc;border:1px solid #e5eaf3;border-radius:10px;padding:5px 7px">
      <div style="display:flex;justify-content:space-between;font-size:9px;color:#667085;margin-bottom:4px;font-weight:700">
        <span>${denom} сум</span><span style="color:${fillColor}">${c.fill_pct}%</span>
      </div>
      <div style="height:5px;background:#e5eaf3;border-radius:999px;overflow:hidden">
        <div style="height:4px;background:${fillColor};border-radius:2px;width:${Math.min(c.fill_pct,100)}%"></div>
      </div>
      <div style="font-size:9px;color:#667085;margin-top:3px">${(c.balance/1e6).toFixed(0)} млн · ${c.count}/${c.capacity}</div>
    </div>`;
  }).join('');
}

// Обновлённая метка "Обновлено:" в шапке — самый свежий реальный опрос среди
// загруженных ATM (раньше здесь была фейковая крутящаяся "Симуляция").
function updateFreshnessLabel() {
  const el = document.getElementById('sim-time');
  if (!el) return;
  let latest = null;
  ATM_META.forEach(atm => {
    if (atm.balancePolledAt && (!latest || atm.balancePolledAt > latest)) latest = atm.balancePolledAt;
  });
  const d = latest ? new Date(latest) : new Date();
  el.textContent = d.toLocaleString('ru-RU', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) + (latest ? '' : ' (реестр)');
}

// Строит atmState напрямую из реальных данных ATM_META (без фейкового тика)
// и обновляет KPI/маркеры/список.
function syncAtmStateFromMeta() {
  let nCrit = 0, nWarn = 0, nOk = 0;

  ATM_META.forEach(atm => {
    const pct = (atm.balance != null && atm.capacity) ? atm.balance / atm.capacity : null;
    if (atm.status === 'critical') nCrit++;
    else if (atm.status === 'warning') nWarn++;
    else if (atm.status === 'ok') nOk++;

    atmState[atm.id] = {
      balance:       atm.balance,
      pct:           pct,
      status:        atm.status,
      lastInc:       atm.lastIncassation ? new Date(atm.lastIncassation).toLocaleString('ru-RU') : 'нет данных',
      isIncNow:      false,
      capacity:      atm.capacity,
      live:          atm.live,
      liveMatch:     atm.liveMatch,
      agentStatus:   atm.agentStatus,
      forecastHours: atm.forecastHours,
      // Реальные кассеты от atm_monitor, если есть; иначе — честно помеченная
      // оценка от общего остатка (см. estimateCassettes).
      cassettes:       atm.cassettes || estimateCassettes(atm.balance, atm.capacity),
      cassettesSource: atm.cassettes ? 'live' : 'estimated',
      cassetteToFill:  Math.max(0, (atm.capacity || 0) - (atm.balance || 0)) > (atm.capacity || 0) * 0.2 ? 1 : 0,
    };

    if (markers[atm.id]) {
      const isHighlighted = selectedAtmIdsFromModal && selectedAtmIdsFromModal.has(atm.id);
      setAtmMarkerIcon(markers[atm.id], atm.status, isHighlighted);
    }
  });

  renderKpisAndMarkers(nCrit, nWarn, nOk, 0);
  updateFreshnessLabel();
}

function renderKpisAndMarkers(nCrit, nWarn, nOk, nInc) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('s-total', ATM_META.length);
  set('s-critical', nCrit);
  set('s-warning', nWarn);
  set('s-ok', nOk);
  set('s-inc', nInc);
}

// Первичная загрузка: реестр + реальные данные, один раз строим маркеры.
async function initAtms() {
  const loaderP = document.querySelector('#loader p');
  if (loaderP) loaderP.textContent = 'Загрузка банкоматов...';
  await loadAtmsFromDb();
  syncAtmStateFromMeta();
  initMarkers(true);
  renderList();
  hideLoader();
  await showTripFromQuery();
  startAutoRefresh();
}

// Периодическое реальное обновление вместо фейкового тика — источник данных
// (atm_monitor) сам опрашивается раз в час, чаще дёргать бэкенд смысла нет.
function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(async () => {
    const ok = await loadAtmsFromDb();
    if (!ok) return;
    syncAtmStateFromMeta();
    renderList();
    updateMarkersHighlight(getFilteredATMs());
  }, 5 * 60 * 1000);
}

// ═══════════════════════════════════════════════════════════
// RENDER LIST
// ═══════════════════════════════════════════════════════════

function renderList() {
  const container = document.getElementById('atm-list');
  const filtered = getFilteredATMs();
  
  // sort: critical first, then warning, then ok
  const order = { critical: 0, warning: 1, ok: 2 };
  const sorted = [...filtered].sort((a,b) => {
    const sa = atmState[a.id]?.status || 'ok';
    const sb = atmState[b.id]?.status || 'ok';
    return (order[sa]||0) - (order[sb]||0);
  });

  container.innerHTML = '';
  sorted.forEach(atm => {
    const st = atmState[atm.id] || { balance: 0, pct: 0, status: 'ok', lastInc: '—' };
    const pctDisp = Math.round(st.pct * 100);
    const balDisp = (st.balance / 1_000_000).toFixed(1);
    const capDisp = (atm.capacity / 1_000_000).toFixed(0);

    // Реальный прогноз площадки (BTech), не ML — своя ML-модель ещё не построена,
    // накопленная история (/api/atms/{id}/history) — задел под неё.
    const forecastTxt = st.forecastHours != null
      ? `~${st.forecastHours < 24 ? Math.round(st.forecastHours) + ' ч' : Math.round(st.forecastHours / 24) + ' д'}`
      : null;

    const card = document.createElement('div');
    card.className = `atm-card ${st.status} ${selectedId === atm.id ? 'selected' : ''}`;
    card.innerHTML = `
      <div class="atm-card-top">
        <div>
          <div class="atm-card-name">${atm.name}</div>
          <div class="atm-card-bank">${atm.bank}</div>
        </div>
        <div class="status-dot dot-${st.status}"></div>
      </div>
      <div class="atm-card-bar-wrap">
        <div class="bar-labels">
          <span>Сейчас</span>
          <span class="val">${balDisp} / ${capDisp} млн (${pctDisp}%)</span>
        </div>
        <div class="bar-bg">
          <div class="bar-fill fill-${st.status}" style="width:${pctDisp}%"></div>
        </div>
      </div>
      ${forecastTxt ? `
      <div style="margin-top:5px;display:flex;align-items:center;justify-content:space-between;font-size:11px">
        <span style="color:#667085">${appIcon('activity')}Прогноз площадки:</span>
        <span style="color:#4f46e5;font-weight:700">${forecastTxt} до cash-out</span>
      </div>` : ''}
      <div class="atm-card-footer" style="margin-top:6px">
        <span>${pctDisp}% заполнен</span>
        ${st.isIncNow ? '<span class="highlight">&#x21BB; Инкассация сейчас</span>' : '<span>Посл. инк.: ' + st.lastInc + '</span>'}
      </div>

      <!-- Кассеты: реальные (atm_monitor, список — без группировки по номиналу,
           у части моделей бывает несколько кассет одного номинала) или оценка -->
      <div style="margin-top:7px">
        <div style="font-size:10px;color:#667085;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px;font-weight:800">${st.cassettesSource === 'live' ? 'Кассеты (реальные, atm_monitor)' : 'Кассеты (оценка от остатка)'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px">
          ${cassetteTilesHtml(st.cassettes, st.cassettesSource)}
        </div>
        ${st.cassetteToFill > 0 ? `<div style="margin-top:3px;font-size:10px;color:#f59e0b">
          ${appIcon('arrow-up-circle')}Нужно довезти: ${(st.cassetteToFill/1e6).toFixed(0)} млн
        </div>` : `<div style="margin-top:3px;font-size:10px;color:#16a34a">${appIcon('check-circle-2')}Кассеты заполнены</div>`}
      </div>
    `;
    card.onclick = () => selectAtm(atm.id);
    container.appendChild(card);
  });

  document.getElementById('list-count').textContent = filtered.length + ' ATM';
  updateMarkersHighlight(filtered);
  hydrateIcons();
}

// ═══════════════════════════════════════════════════════════
// SELECT ATM
// ═══════════════════════════════════════════════════════════

function selectAtm(id) {
  selectedId = id;
  const atm = ATM_META.find(a => a.id === id);
  const st  = atmState[id] || {};
  const pct = Math.round((st.pct || 0) * 100);

  map.setView([atm.lat, atm.lon], 16, { animate: true });

  const stPop = atmState[id] || {};

  // Строки для попапа (та же логика реальных/оценочных кассет, что и в
  // cassetteTilesHtml для карточек списка, просто в виде списка, а не плиток).
  function cassettesHtml(cassettes, source) {
    const label = source === 'live' ? 'Кассеты (реальные, atm_monitor)' : 'Кассеты (оценка от остатка)';
    let rows;
    if (source === 'live') {
      // Реальные кассеты — список, не словарь по номиналу: у части моделей
      // бывает несколько кассет одного номинала, их нельзя схлопывать в одну.
      // "% заполнения" не показываем — реальной ёмкости кассеты BTech не отдаёт,
      // вместо этого настоящий статус самой площадки (OK/LOW/EMPTY/INOP/...).
      rows = (cassettes || []).map(c => {
        const color = CASSETTE_STATUS_COLOR[c.status] || '#94a3b8';
        return `<div style="display:flex;align-items:center;justify-content:space-between;gap:5px;margin-bottom:3px;font-size:10px">
          <span style="color:#667085">${c.nominal ? Number(c.nominal).toLocaleString('ru-RU') : '—'} сум</span>
          <span style="color:#475569">${c.count ?? '—'} шт · ${c.balance != null ? (c.balance/1e6).toFixed(1) + ' млн' : '—'}</span>
          <span style="color:${color};font-weight:700">${c.status || '—'}</span>
        </div>`;
      }).join('');
    } else {
      rows = (cassettes || []).map(c => {
        const fillColor = c.fill_pct > 60 ? '#22c55e' : c.fill_pct > 25 ? '#f59e0b' : '#ef4444';
        const denom = c.denomination >= 1000 ? (c.denomination / 1000).toFixed(0) + 'к' : c.denomination;
        return `<div style="display:flex;align-items:center;gap:5px;margin-bottom:3px;font-size:10px">
          <span style="color:#667085;width:40px">${denom} сум</span>
          <div style="flex:1;height:6px;background:#e5eaf3;border-radius:999px;overflow:hidden">
            <div style="height:6px;background:${fillColor};border-radius:3px;width:${Math.min(c.fill_pct || 0, 100)}%"></div>
          </div>
          <span style="color:${fillColor};width:32px;text-align:right">${c.fill_pct != null ? c.fill_pct + '%' : '—'}</span>
          <span style="color:#475569;font-size:9px">${c.balance != null ? (c.balance / 1e6).toFixed(0) + ' млн' : ''}</span>
        </div>`;
      }).join('');
    }
    return `<div style="font-size:10px;color:#667085;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px;font-weight:800">${label}</div>${rows}`;
  }

  const forecastTxt = stPop.forecastHours != null
    ? `~${stPop.forecastHours < 24 ? Math.round(stPop.forecastHours) + ' ч' : Math.round(stPop.forecastHours / 24) + ' д'}`
    : '—';

  const popupHtml = (cassettes, source) => `
    <div class="popup-title">${atm.name}</div>
    <div class="popup-row">Адрес: <span>${atm.address}</span></div>
    <hr style="border-color:#e5eaf3;margin:8px 0">

    <div class="popup-row">Остаток: <span>${((stPop.balance||0)/1_000_000).toFixed(1)} млн сум (${pct}%)</span></div>
    <div class="popup-row">Статус: <span style="color:${
      stPop.status==='ok'?'#16a34a':stPop.status==='warning'?'#d97706':'#dc2626'
    }">${stPop.status==='ok'?'Норма':stPop.status==='warning'?'Предупреждение':'Критично'}</span></div>
    ${stPop.agentStatus ? `<div class="popup-row">Агент: <span style="color:${stPop.agentStatus === 'online' ? '#16a34a' : '#dc2626'}">${stPop.agentStatus}</span></div>` : ''}
    ${stPop.live && stPop.liveMatch === 'location' ? `<div class="popup-row" style="font-size:10px;color:#94a3b8">${appIcon('map-pin')}Найден по координатам (id в реестре не совпал с BTech)</div>` : ''}

    <hr style="border-color:#e5eaf3;margin:8px 0">
    ${cassettesHtml(cassettes, source)}

    <hr style="border-color:#e5eaf3;margin:8px 0">
    <div class="popup-row">Прогноз площадки до cash-out: <span style="color:#4f46e5">${forecastTxt}</span></div>
    <div class="popup-row">Посл. инкассация: <span>${stPop.lastInc}</span></div>
  `;

  // Реальные кассеты уже приходят вместе со списком ATM (bulk-запрос в
  // /api/atms), отдельный запрос по клику больше не нужен.
  markers[id].bindPopup(popupHtml(stPop.cassettes, stPop.cassettesSource)).openPopup();
  hydrateIcons();
  renderList();
}

// ═══════════════════════════════════════════════════════════
// ROUTING
// ═══════════════════════════════════════════════════════════

// Депо инкассаторов — центральный офис в Юнусабаде
const DEPOT = { lat: 41.3510, lon: 69.2830, name: 'Депо (Amir Temur 107)' };

// Цвета для разных машин
const CAR_COLORS  = ['#f59e0b', '#3b82f6', '#a855f7', '#10b981', '#ef4444', '#06b6d4', '#84cc16', '#f97316', '#6366f1', '#14b8a6', '#e11d48', '#0ea5e9'];
const CAR_LABELS  = ['Машина A', 'Машина B', 'Машина C', 'Машина D'];

let routeControls = [];   // Leaflet Routing Machine контролы (локальный режим)
let routingLayers = [];   // обычные полилинии (WebSocket-режим)
let depotMarker   = null;
let _routeDrawGen = 0;

async function buildRegionalRoute(status) {
  clearRoute();
  if (status === 'all' && !confirm('В маршрут попадут и банкоматы в норме. Продолжить только для нуждающихся (критичные + предупреждения)?\n\nOK — только нуждающиеся\nОтмена — прервать')) {
    return;
  }
  if (status === 'all') status = 'warning';

  const speedKmh = parseInt(document.getElementById('speed-kmh')?.value, 10) || 30;
  const maxStops = parseInt(document.getElementById('max-stops')?.value, 10) || 12;

  const infoEl = document.getElementById('route-info');
  if (infoEl) setRouteInfo('Строим маршруты по дорогам только для ATM ниже нормы…');

  try {
    // Баланс уже реальный на бэкенде (atm_monitor), клиенту ничего подмешивать не нужно.
    const data = await fetch(
      `${API_BASE}/api/routes/incassation?status=${status}&speed_kmh=${speedKmh}&max_stops=${maxStops}&snap_roads=true`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persist: true }),
      }
    ).then(r => r.json());
    if (!data.cars || !data.cars.length) {
      const d = data.diagnostics || {};
      alert(
        `Нет банкоматов, которые нужно заправлять.\n\n` +
        `В норме (пропущены): ${d.skipped_ok ?? '—'}\n` +
        `Нуждаются (critical/warning): ${d.target_atms || 0}\n\n` +
        `ATM в норме в маршрут не включаются.`
      );
      return;
    }
    data.cars.forEach((car, i) => {
      car.color = CAR_COLORS[i % CAR_COLORS.length];
      car.label = car.label || `${car.region} · ${car.departure_branch?.name || ''}`;
      car.total_dist_km = car.total_dist_km ?? car.distance_km ?? 0;
      car.est_time_min = car.est_time_min || 0;
      car.refill_total = car.refill_total || 0;
      (car.stops || []).forEach(s => {
        s.atm_id = s.atm_id || s.terminal_id;
        s.name = s.name || s.address || s.terminal_id;
        s.bank = s.bank || '';
        s.balance = s.balance || 0;
        s.balance_pct = Number(s.balance_pct || 0);
        s.refill_amount = s.refill_amount || 0;
      });
    });
    renderRegionalRoutes(data);
    if (infoEl) {
      const roads = (data.cars || []).filter(c => c.routing_provider === 'osrm').length;
      setRouteInfo(
        infoEl.innerHTML +
        `<br><a href="/dashboard/incassation.html" style="color:#7c3aed;font-weight:800">Открыть в календаре →</a>` +
        (data.saved_to_calendar ? ` · сохранено рейсов: ${data.saved_to_calendar}` : '') +
        (roads ? ` · дороги OSRM: ${roads}` : '')
      );
    }
  } catch (e) {
    alert('Ошибка построения регионального маршрута: ' + e.message);
  }
}

async function buildRoute(filterStatus) {
  return buildRegionalRoute(filterStatus);
}

function greedyRouteFromDepot(atms) {
  if (atms.length === 0) return [];
  const visited = new Set();
  const result  = [];
  let   current = DEPOT;

  while (result.length < atms.length) {
    let nearest = null, minDist = Infinity;
    atms.forEach(a => {
      if (visited.has(a.id)) return;
      // приоритет: критичные ближе, warning — средне, ok — дальше
      const priority = atmState[a.id]?.status === 'critical' ? 0.6
                     : atmState[a.id]?.status === 'warning'  ? 0.8 : 1.0;
      const d = haversineKm(current.lat, current.lon, a.lat, a.lon) * priority;
      if (d < minDist) { minDist = d; nearest = a; }
    });
    if (!nearest) break;
    result.push(nearest);
    visited.add(nearest.id);
    current = nearest;
  }
  return result;
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2)**2
          + Math.cos(lat1*Math.PI/180) * Math.cos(lat2*Math.PI/180) * Math.sin(dLon/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function renderRouteSidebar(carRoutes, totalStops, totalDistKm, totalTimeMin) {
  document.getElementById('rs-cars-count').textContent  = carRoutes.length;
  document.getElementById('rs-stops-count').textContent = totalStops;
  document.getElementById('rs-distance').textContent    = totalDistKm.toFixed(1) + ' км';
  document.getElementById('rs-time').textContent        = totalTimeMin + ' мин';

  const container = document.getElementById('rs-cars-list');
  container.innerHTML = '';

  carRoutes.forEach(({ ordered, color, label }, gi) => {
    const div = document.createElement('div');
    div.className = 'rs-car';

    const distCar = (() => {
      let d = 0, pts = [DEPOT, ...ordered, DEPOT];
      for (let k = 0; k < pts.length-1; k++)
        d += haversineKm(pts[k].lat, pts[k].lon, pts[k+1].lat, pts[k+1].lon);
      return (d * 1.35).toFixed(1);
    })();

    div.innerHTML = `
      <div class="rs-car-header" style="background:${color}22;border:1px solid ${color}44;border-bottom:none;">
        <div class="rs-car-dot" style="background:${color}"></div>
        <span style="color:${color}">${label}</span>
        <span style="margin-left:auto;color:#667085;font-weight:600">${ordered.length} остановок · ${distCar} км</span>
      </div>
      <div class="rs-stops">
        <div class="rs-depot">
          <span class="rs-depot-icon"><i data-lucide="warehouse"></i></span>
          <span>Старт: ${DEPOT.name}</span>
        </div>
        ${ordered.map((atm, si) => {
          const st = atmState[atm.id] || {};
          const pct = Math.round((st.pct||0)*100);
          const balCls = st.status==='critical'?'bal-crit':st.status==='warning'?'bal-warn':'bal-ok';
          const balStr = ((st.balance||0)/1e6).toFixed(1) + ' млн';
          return `
            <div class="rs-stop" onclick="selectAtm('${atm.id}')" style="cursor:pointer">
              <div class="rs-stop-num" style="background:${color}">${si+1}</div>
              <div class="rs-stop-name">${atm.name}<br><span style="color:#667085">${atm.bank}</span></div>
              <div class="rs-stop-bal ${balCls}">${balStr}<br><span style="font-weight:500;color:#667085">${pct}%</span></div>
            </div>`;
        }).join('')}
        <div class="rs-depot">
          <span class="rs-depot-icon"><i data-lucide="flag"></i></span>
          <span>Возврат в депо</span>
        </div>
      </div>
    `;
    container.appendChild(div);
  });
  hydrateIcons();
}

function setRouteInfo(html) {
  const infoEl = document.getElementById('route-info');
  if (!infoEl) return;
  if (html) {
    infoEl.innerHTML = html;
    infoEl.style.display = '';
  } else {
    infoEl.innerHTML = '';
    infoEl.style.display = 'none';
  }
}

function moneyMln(v, digits) {
  const n = Number(v) || 0;
  const d = digits == null ? (Math.abs(n) >= 1e9 ? 0 : 1) : digits;
  return (n / 1e6).toFixed(d) + ' млн';
}

function stopRefill(s) {
  if (s && s.refill_amount != null && Number(s.refill_amount) > 0) return Number(s.refill_amount);
  const cap = Number((s && s.capacity) || 400_000_000);
  const bal = Number((s && s.balance) || 0);
  return Math.max(0, Math.round(cap * 0.8 - bal));
}

function validLatLng(p) {
  if (!p) return null;
  const lat = Number(p.lat ?? p.latitude);
  const lon = Number(p.lon ?? p.lng ?? p.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) < 0.01 && Math.abs(lon) < 0.01) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return L.latLng(lat, lon);
}

function isRoadGeometry(pts, waypoints) {
  return pts.length >= Math.max(8, (waypoints.length || 2) * 4);
}

function drawRoadLine(pts, color) {
  if (!pts || pts.length < 2) return;
  routingLayers.push(L.polyline(pts, {
    color: '#000', weight: 8, opacity: 0.18, lineJoin: 'round', lineCap: 'round'
  }).addTo(map));
  routingLayers.push(L.polyline(pts, {
    color, weight: 5, opacity: 0.95, lineJoin: 'round', lineCap: 'round'
  }).addTo(map));
}

async function fetchOsrmOnce(wps) {
  const coords = wps.map((p) => `${p.lng.toFixed(6)},${p.lat.toFixed(6)}`).join(';');
  const publicUrl = `https://router.project-osrm.org/route/v1/driving/${coords}?overview=full&geometries=geojson&steps=false`;
  try {
    const res = await fetch(publicUrl);
    if (res.ok) {
      const data = await res.json();
      if (data.code === 'Ok' && data.routes && data.routes[0]) {
        return (data.routes[0].geometry.coordinates || []).map(([lon, lat]) => L.latLng(lat, lon));
      }
    }
  } catch (err) {
    console.warn('Public OSRM failed:', err);
  }
  const points = wps.map((p) => ({ lat: p.lat, lon: p.lng }));
  const res = await fetch(`${API_BASE}/api/osrm/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ points }),
  });
  if (!res.ok) throw new Error('OSRM HTTP ' + res.status);
  const data = await res.json();
  const g = (data.geometry || []).map(validLatLng).filter(Boolean);
  if (g.length < 2) throw new Error('OSRM empty geometry');
  return g;
}

async function fetchOsrmRoadLine(wps) {
  if (!wps || wps.length < 2) return [];
  const CHUNK = 20;
  if (wps.length <= CHUNK) return fetchOsrmOnce(wps);
  const out = [];
  for (let i = 0; i < wps.length - 1; i += CHUNK - 1) {
    const chunk = wps.slice(i, Math.min(i + CHUNK, wps.length));
    if (chunk.length < 2) break;
    const part = await fetchOsrmOnce(chunk);
    if (!part.length) continue;
    if (out.length) out.push(...part.slice(1));
    else out.push(...part);
  }
  return out;
}

async function snapAndDrawCar(car, color, gen) {
  const dep = car.departure_branch || {};
  const saved = (car.geometry || []).map(validLatLng).filter(Boolean);
  const stopPts = (car.stops || []).map(validLatLng).filter(Boolean);
  const depPt = validLatLng(dep);
  const wps = [];
  if (depPt) wps.push(depPt);
  wps.push(...stopPts);
  if (depPt) wps.push(depPt);

  let linePts = saved;
  if (!isRoadGeometry(saved, wps) && wps.length >= 2) {
    try {
      linePts = await fetchOsrmRoadLine(wps);
    } catch (err) {
      console.warn('OSRM road snap failed, using waypoints:', err);
      linePts = [];
    }
  }
  if (gen != null && gen !== _routeDrawGen) return [];
  if (linePts.length < 2) linePts = wps;
  drawRoadLine(linePts, color);
  return linePts;
}

function renderRegionalRoutes(data) {
  const gen = ++_routeDrawGen;
  routingLayers.forEach(l => map.removeLayer(l));
  routingLayers = [];
  routeControls.forEach(rc => { try { map.removeControl(rc); } catch (_) {} });
  routeControls = [];
  if (depotMarker) { map.removeLayer(depotMarker); depotMarker = null; }

  const allPts = [];
  const cars = data.cars || [];
  cars.forEach((car, gi) => {
    const color = car.color || CAR_COLORS[gi % CAR_COLORS.length];
    const dep = car.departure_branch || {};
    const depPt = validLatLng(dep);

    if (depPt) {
      const depotPin = L.marker(depPt, {
        icon: L.divIcon({
          className: '',
          html: `<div style="width:34px;height:34px;border-radius:9px;background:${color};border:2.5px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 0 10px ${color}99">${appIcon('building-2')}</div>`,
          iconSize: [34, 34], iconAnchor: [17, 17]
        })
      }).addTo(map).bindPopup(`<b>${dep.name || 'Филиал'}</b><br>${car.region || ''}<br>${dep.address || ''}`);
      routingLayers.push(depotPin);
      allPts.push(depPt);
    }

    (car.stops || []).forEach((stop, si) => {
      const pt = validLatLng(stop);
      if (!pt) return;
      const stColor = stop.status === 'critical' ? '#ef4444' : stop.status === 'warning' ? '#f59e0b' : '#22c55e';
      const pin = L.marker(pt, {
        icon: L.divIcon({
          className: '',
          html: `<div style="width:28px;height:28px;border-radius:50%;background:${color};border:3px solid #fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#fff;box-shadow:0 2px 6px #0005">${si + 1}</div>`,
          iconSize: [28, 28], iconAnchor: [14, 14]
        })
      }).addTo(map).bindPopup(`
        <div class="popup-title">${si + 1}. ${stop.name || stop.terminal_id}</div>
        <div class="popup-row">Вилоят: <span>${car.region || '—'}</span></div>
        <div class="popup-row">Филиал: <span>${dep.name || dep.local_code || '—'}</span></div>
        <div class="popup-row">Адрес: <span>${stop.address || '—'}</span></div>
        <div class="popup-row">Остаток: <span>${moneyMln(stop.balance)} · ${Number(stop.balance_pct || 0).toFixed(0)}%</span></div>
        <div class="popup-row">Довезти: <span style="color:#d97706">${moneyMln(stopRefill(stop), 0)}</span></div>
        <div class="popup-row">Статус: <span style="color:${stColor}">${stop.status || '—'}</span></div>
      `);
      routingLayers.push(pin);
      allPts.push(pt);
    });
  });

  const fit = () => {
    if (gen !== _routeDrawGen) return;
    try { map.invalidateSize(); } catch (_) {}
    if (allPts.length) {
      map.fitBounds(L.latLngBounds(allPts), { padding: [60, 60], maxZoom: 14 });
    }
  };
  hideLoader();
  setTimeout(fit, 80);

  (async () => {
    let i = 0;
    const workers = Array.from({ length: Math.min(3, cars.length) }, async () => {
      while (i < cars.length) {
        const idx = i++;
        const car = cars[idx];
        const color = car.color || CAR_COLORS[idx % CAR_COLORS.length];
        const pts = await snapAndDrawCar(car, color, gen);
        allPts.push(...pts);
      }
    });
    await Promise.all(workers);
    fit();
  })();

  const infoEl = document.getElementById('route-info');
  if (infoEl) {
    const warnings = (data.unserved_regions || []).map(x => `${x.region}: ${x.reason}`).join('<br>');
    setRouteInfo(
      `<b>${(data.cars || []).length} маршрутов</b><br>` +
      `Остановок: ${data.total_stops} · ${data.total_dist_km} км · ~${data.est_time_min} мин` +
      (warnings ? `<br><span style="color:#dc2626">${warnings}</span>` : '')
    );
  }

  const sb = document.getElementById('route-sidebar');
  if (!sb) return;
  openRouteSidebar();
  const carsCount = document.getElementById('rs-cars-count');
  const stopsCount = document.getElementById('rs-stops-count');
  const distEl = document.getElementById('rs-distance');
  const timeEl = document.getElementById('rs-time');
  if (carsCount) carsCount.textContent = (data.cars || []).length;
  if (stopsCount) stopsCount.textContent = data.total_stops;
  if (distEl) distEl.textContent = Number(data.total_dist_km || 0).toFixed(1) + ' км';
  if (timeEl) timeEl.textContent = (data.est_time_min || 0) + ' мин';

  const container = document.getElementById('rs-cars-list');
  if (!container) return;
  container.innerHTML = (data.cars || []).map(car => {
    const color = car.color;
    const refillTotal = Number(car.refill_total) || (car.stops || []).reduce((s, x) => s + stopRefill(x), 0);
    const stops = (car.stops || []).map((s, si) => {
      const pct = Number(s.balance_pct || 0).toFixed(0);
      const balStr = moneyMln(s.balance);
      const refillStr = moneyMln(stopRefill(s), 0);
      const balCls = s.status === 'critical' ? 'bal-crit' : s.status === 'warning' ? 'bal-warn' : 'bal-ok';
      return `
        <div class="rs-stop" onclick="typeof selectAtm==='function' && selectAtm('${s.atm_id || s.terminal_id || ''}')" style="cursor:pointer">
          <div class="rs-stop-num" style="background:${color}">${si + 1}</div>
          <div class="rs-stop-name">${s.name || s.terminal_id}<br>
            <span style="color:#667085;font-size:10px">${s.bank || s.address || ''}</span>
            <span style="display:block;color:#667085;font-size:10px;margin-top:2px">остаток ${balStr} (${pct}%)</span>
          </div>
          <div class="rs-stop-bal ${balCls}">
            +${refillStr}
            <br><span style="font-weight:600;color:#d97706;font-size:10px">довезти</span>
          </div>
        </div>`;
    }).join('');
    return `
      <div class="rs-car">
        <div class="rs-car-header" style="background:${color}22;border:1px solid ${color}55;border-bottom:none;">
          <div class="rs-car-dot" style="background:${color}"></div>
          <span style="color:${color};font-weight:700">${car.label}</span>
          <span style="margin-left:auto;color:#667085;font-size:11px;font-weight:600">
            ${(car.stops || []).length} ост. · ${Number(car.total_dist_km || car.distance_km || 0).toFixed(1)} км · ${car.est_time_min || 0} мин · ${moneyMln(refillTotal, 0)}
          </span>
        </div>
        <div class="rs-stops">${stops}</div>
      </div>`;
  }).join('');
  hydrateIcons();
}

function closeSidebar() {
  document.getElementById('route-sidebar').classList.remove('open');
}

function openRouteSidebar() {
  closeBranchCashPanel();
    document.getElementById('route-sidebar').classList.add('open');
}

function clearRoute() {
  _routeDrawGen++;
  routeControls.forEach(rc => map.removeControl(rc));
  routeControls = [];
  routingLayers.forEach(l => map.removeLayer(l));
  routingLayers = [];
  if (depotMarker) { map.removeLayer(depotMarker); depotMarker = null; }
  document.getElementById('route-sidebar').classList.remove('open');
  setRouteInfo('');
}

function tripRecordToCar(t) {
  const dep = t.departure_branch || {};
  return {
    region: t.region,
    label: t.label || t.region,
    priority: t.priority,
    color: '#7c3aed',
    departure_branch: {
      local_code: t.branch_local_code || dep.local_code,
      address: t.branch_address || dep.address,
      name: (t.branch_local_code || dep.local_code)
        ? `Филиал ${t.branch_local_code || dep.local_code}`
        : (dep.name || 'Филиал'),
      lat: t.branch_lat ?? dep.lat,
      lon: t.branch_lon ?? dep.lon,
    },
    stops: t.stops || [],
    geometry: t.geometry || [],
    distance_km: t.distance_km || 0,
    total_dist_km: t.distance_km || t.total_dist_km || 0,
    est_time_min: t.est_time_min || 0,
    refill_total: t.refill_total || 0,
  };
}

let _shownTripId = null;
async function showTripFromQuery() {
  const tripId = new URLSearchParams(location.search).get('trip');
  if (!tripId || tripId === 'undefined' || tripId === 'null') return false;
  if (_shownTripId === String(tripId) && routingLayers.length) return true;
  try {
    let t = null;
    const one = await fetch(`${API_BASE}/api/incassation/trips/${encodeURIComponent(tripId)}`);
    if (one.ok) t = await one.json();
    if (!t) {
      const cal = await fetch(`${API_BASE}/api/incassation/calendar`).then((r) => r.json());
      t = (cal.trips || cal.events || []).find((x) => String(x.id) === String(tripId));
    }
    if (!t) {
      console.warn('Рейс не найден:', tripId);
      return false;
    }
    _shownTripId = String(tripId);
    const car = tripRecordToCar(t);
    (car.stops || []).forEach((s) => {
      s.atm_id = s.atm_id || s.terminal_id;
    });
    renderRegionalRoutes({
      cars: [car],
      total_stops: (car.stops || []).length,
      total_dist_km: car.distance_km || 0,
      est_time_min: car.est_time_min || 0,
      unserved_regions: [],
    });
    const infoEl = document.getElementById('route-info');
    if (infoEl) {
      setRouteInfo(
        `<b>${car.label}</b><br>` +
        `Дата: ${t.planned_date || '—'} · приоритет: ${t.priority || '—'}<br>` +
        `Остановок: ${(car.stops || []).length} · ${Number(car.distance_km || 0).toFixed(1)} км · ~${car.est_time_min || 0} мин<br>` +
        `Довезти: ${moneyMln(car.refill_total || (car.stops || []).reduce((s, x) => s + stopRefill(x), 0), 0)}`
      );
    }
    return true;
  } catch (err) {
    console.warn('Не удалось открыть рейс на карте:', err);
    return false;
  }
}

// ═══════════════════════════════════════════════════════════
// ML PREDICTIONS — задел: реальная история теперь копится в atm_monitor
// (GET /api/atms/{id}/history), но собственной ML-модели пока нет.
// ═══════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════
// BOOT — реестр + реальные данные atm_monitor, без симуляции
// ═══════════════════════════════════════════════════════════
hydrateIcons();
initAtms().catch(err => {
  console.warn('Ошибка инициализации карты:', err);
  hideLoader();
});
setTimeout(hideLoader, 8000);

// onclick="..." handlers — explicit globals
window.toggleAtmsLayer = toggleAtmsLayer;
window.toggleBranchesLayer = toggleBranchesLayer;
window.toggleWarehouseOnly = toggleWarehouseOnly;
window.openRegionModal = openRegionModal;
window.closeRegionModal = closeRegionModal;
window.performRegionSearch = performRegionSearch;
window.clearRegionFilter = clearRegionFilter;
window.onRegionChange = onRegionChange;
window.updateModalAtmCount = updateModalAtmCount;
window.onLeftSearchInput = onLeftSearchInput;
window.buildRoute = buildRoute;
window.buildRegionalRoute = buildRegionalRoute;
window.clearRoute = clearRoute;
window.closeSidebar = closeSidebar;
window.closeBranchCashPanel = closeBranchCashPanel;
window.openBranchCashPanelByCode = openBranchCashPanelByCode;
window.selectAtm = selectAtm;
