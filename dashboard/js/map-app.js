// ═══════════════════════════════════════════════════════════
// DATA
// ═══════════════════════════════════════════════════════════

// ATM_META Р·Р°РіСЂСѓР¶Р°РµС‚СЃСЏ СЃ API (РµРґРёРЅС‹Р№ РёСЃС‚РѕС‡РЅРёРє РїСЂР°РІРґС‹)
let ATM_META = [];

// ═══════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════

let allData       = {};
let atmState      = {};
let mlPredictions = {};
let timeIndex     = 0;
let timeSteps     = [];
let simTimer      = null;
let selectedId    = null;
let markers       = {};

// Global Search State
let currentSearchQuery = "";
let selectedRegionFromModal = null;
let selectedAtmIdsFromModal = null; // Set of IDs (null if no modal filter is active)

function hydrateIcons() {
  if (window.lucide) lucide.createIcons();
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
        marker.setIcon(makeIcon(st.status, true));
        marker.setOpacity(1.0);
        if (!map.hasLayer(marker)) marker.addTo(map);
      } else {
        marker.setIcon(makeIcon(st.status, false));
        marker.setOpacity(0.25);
        if (!map.hasLayer(marker)) marker.addTo(map);
      }
    } else {
      // Normal state (no filter)
      marker.setIcon(makeIcon(st.status, false));
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
          color: '#475569', // спокойный серый цвет для границ областей
          weight: 2.2,
          fillColor: color,
          fillOpacity: 0.03,
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
              fillOpacity: 0.12,
              weight: 3
            });
          },
          mouseout: function(e) {
            const l = e.target;
            l.setStyle({
              fillOpacity: 0.03,
              weight: 2.2
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
  
  if (isHighlighted) {
    return L.divIcon({
      className: '',
      html: `<div class="marker-highlighted" style="
        width:34px;height:34px;border-radius:50%;
        background:${c};border:3.5px solid #facc15;
        box-shadow:0 0 15px #facc15, 0 0 6px ${c};
        display:flex;align-items:center;justify-content:center;
        color:#fff;
        animation: marker-pulse 1.2s infinite alternate;
      ">${appIcon('credit-card')}</div>`,
      iconSize: [34,34], iconAnchor: [17,17],
    });
  }
  
  return L.divIcon({
    className: '',
    html: `<div style="
      width:28px;height:28px;border-radius:50%;
      background:${c};border:3px solid #fff;
      box-shadow:0 0 12px ${c}99;
      display:flex;align-items:center;justify-content:center;
      color:#fff;
    ">${appIcon('credit-card')}</div>`,
    iconSize: [28,28], iconAnchor: [14,14],
  });
}

let atmsVisible = true;

function initMarkers() {
  const points = [];
  ATM_META.forEach(atm => {
    const lat = parseFloat(atm.lat);
    const lon = parseFloat(atm.lon);
    if (!isNaN(lat) && !isNaN(lon) && lat !== 0 && lon !== 0) {
      const m = L.marker([lat, lon], { icon: makeIcon('ok') })
        .on('click', () => selectAtm(atm.id));
      if (atmsVisible) m.addTo(map);
      markers[atm.id] = m;
      points.push([lat, lon]);
    }
  });
  console.log(`Placed ${points.length} markers on the map out of ${ATM_META.length} ATMs`);
  if (points.length > 0) {
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, { padding: [50, 50] });
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
  Object.values(markers).forEach(marker => {
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
  return L.divIcon({
    className: '',
    html: `<div style="
      width:26px;height:26px;border-radius:7px;
      background:${c};border:2.5px solid #fff;
      box-shadow:0 0 10px ${c}99;
      display:flex;align-items:center;justify-content:center;
      color:#fff;
    ">${appIcon('building-2')}</div>`,
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

// ═══════════════════════════════════════════════════════════
// WEBSOCKET — получаем данные с FastAPI сервера
// ═══════════════════════════════════════════════════════════

// Автоматически подхватываем хост — работает и на localhost и на любом сервере
const API_BASE = location.origin;
const WS_URL   = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`;
let   ws       = null;
let   wsMode   = false;   // true = WebSocket активен

// ── Baseline vs ML ───────────────────────────────────────────
let _lastMlSavingsUpdate = 0;
async function updateMlSavings() {
  const now = Date.now();
  if (now - _lastMlSavingsUpdate < 30_000) return;  // не чаще раз в 30с
  _lastMlSavingsUpdate = now;
  try {
    const data = await fetch(`${API_BASE}/api/baseline`).then(r => r.json());
    const saved = data.summary?.ml_cash_saved || 0;
    const el = document.getElementById('s-ml-save');
    if (el) el.textContent = saved > 0 ? `${(saved/1e6).toFixed(0)} млн` : '0 млн';
    window._baselineData = data;
  } catch(e) {}
}

async function showBaselinePanel() {
  const panel = document.getElementById('baseline-panel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display === 'none') return;

  try {
    const data = window._baselineData || await fetch(`${API_BASE}/api/baseline`).then(r => r.json());
    window._baselineData = data;
    const s = data.summary;
    const topRisk = (data.atms || []).slice(0, 5);

    document.getElementById('baseline-content').innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
        <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:16px;padding:12px">
          <div style="color:#9a3412;font-size:10px;margin-bottom:4px;font-weight:800;letter-spacing:.5px">МЕТОД БАНКА</div>
          <div style="color:#dc2626;font-size:20px;font-weight:800">${(s.bank_planned_refill/1e6).toFixed(0)} млн</div>
          <div style="color:#667085;font-size:10px">план на 24ч по прошлым транзакциям</div>
          <div style="margin-top:6px;color:#d97706;font-size:11px;font-weight:700"><i data-lucide="lock-keyhole" class="icon-inline"></i>заморожено у банка: ${(s.bank_frozen_cash/1e6).toFixed(0)} млн</div>
          <div style="margin-top:6px;color:#d97706;font-size:11px;font-weight:700"><i data-lucide="history" class="icon-inline"></i>среднее снятие прошлой недели</div>
          <div style="color:#667085;font-size:10px">${s.bank_cashout_risk} ATM могут уйти в риск</div>
        </div>
        <div style="background:#ecfdf5;border:1px solid #bbf7d0;border-radius:16px;padding:12px">
          <div style="color:#166534;font-size:10px;margin-bottom:4px;font-weight:800;letter-spacing:.5px">ML ПРОГНОЗ (XGBoost)</div>
          <div style="color:#16a34a;font-size:20px;font-weight:800">${(s.ml_recommended_refill/1e6).toFixed(0)} млн</div>
          <div style="color:#667085;font-size:10px">рекомендовано по прогнозу +24ч</div>
          <div style="margin-top:6px;color:#059669;font-size:11px;font-weight:700"><i data-lucide="trending-up" class="icon-inline"></i>Разница: ${(s.ml_cash_saved/1e6).toFixed(0)} млн</div>
          <div style="color:#667085;font-size:10px">эффективность ML экономит: ${s.efficiency_gain_pct}%</div>
        </div>
      </div>
      <div style="color:#667085;font-size:11px;margin-bottom:6px;font-weight:800">Топ-5 по риску cash-out:</div>
      ${topRisk.map(atm => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #eef2f7;font-size:11px">
          <span style="color:#111827;font-weight:700">${atm.name}</span>
          <span style="color:${atm.ml_risk==='HIGH'?'#ef4444':atm.ml_risk==='MEDIUM'?'#f59e0b':'#4ade80'};font-weight:700">${atm.ml_risk}</span>
          <span style="color:#667085">${(atm.ml_cashout_prob*100).toFixed(0)}% риск</span>
        </div>
      `).join('')}
    `;
    hydrateIcons();
  } catch(e) {
    document.getElementById('baseline-content').innerHTML = '<span style="color:#ef4444">Ошибка загрузки</span>';
  }
}

function connectWebSocket() {
  const loaderP = document.querySelector('#loader p');
  if (loaderP) loaderP.textContent = 'Подключение к API...';

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log('WebSocket connected');
    wsMode = true;
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleServerMessage(msg);
  };

  ws.onerror = () => {
    console.warn('WebSocket недоступен — fallback на JSON-файлы');
    ws = null;
    wsMode = false;
    loadFromJSON();
  };

  ws.onclose = () => {
    if (wsMode) {
      console.warn('WebSocket закрыт, переподключение через 3с...');
      setTimeout(connectWebSocket, 3000);
    }
  };
}

function handleServerMessage(msg) {
  if (msg.type === 'snapshot' || msg.type === 'tick') {
    // Обновляем мета-данные ATM из сервера
    if (msg.meta) {
      Object.entries(msg.meta).forEach(([id, m]) => {
        const atmEntry = ATM_META.find(a => a.id === id);
        if (atmEntry) {
          // Обновляем уже существующие записи, чтобы в UI ушли реальные названия/адреса.
          atmEntry.name = m.name;
          atmEntry.bank = m.bank;
          atmEntry.address = m.address;
          atmEntry.lat = m.lat;
          atmEntry.lon = m.lon;
          atmEntry.capacity = m.capacity;
          atmEntry.region = m.region; // сохранить регион
        } else {
          ATM_META.push({
            id: id, name: m.name, bank: m.bank,
            address: m.address, lat: m.lat, lon: m.lon, capacity: m.capacity,
            region: m.region, // сохранить регион
          });
        }
      });
    }

    // Обновляем ML-прогнозы
    if (msg.predictions) {
      Object.entries(msg.predictions).forEach(([id, p]) => {
        mlPredictions[id] = p;
      });
    }

    // Обновляем текущее состояние каждого ATM
    if (msg.states) {
      Object.entries(msg.states).forEach(([id, st]) => {
        const atm = ATM_META.find(a => a.id === id);
        if (!atm) return;

        const pct = st.balance / atm.capacity;
        let status = 'ok';
        if (pct < 0.20) status = 'critical';
        else if (pct < 0.40) status = 'warning';

        atmState[id] = {
          balance:          st.balance,
          pct:              pct,
          status:           status,
          lastInc:          st.last_incassation || 'нет данных',
          isIncNow:         !!st.is_incassation,
          isBreakdown:      !!st.is_breakdown,
          capacity:         atm.capacity,
          hoursToEmpty:     st.hours_to_empty,
          emptyAt:          st.empty_at || null,
          isSalaryDay:      !!st.is_salary_day,
          isNearSalary:     !!st.is_near_salary,
          // 4 реальные кассеты с номиналами
          cassettes:        st.cassettes || [],
          cassetteFillPct:  st.cassettes_total_fill_pct ?? 0,
          cassetteToFill:   st.cassettes_value_to_fill ?? 0,
          cashOk12h:        !!st.cash_ok_12h,
        };

        if (markers[id]) {
          const isHighlighted = selectedAtmIdsFromModal && selectedAtmIdsFromModal.has(id);
          markers[id].setIcon(makeIcon(status, isHighlighted));
        }
      });

      // Статистика
      const states = Object.values(atmState);
      document.getElementById('s-total').textContent    = states.length;
      document.getElementById('s-critical').textContent = states.filter(s => s.status === 'critical').length;
      document.getElementById('s-warning').textContent  = states.filter(s => s.status === 'warning').length;
      document.getElementById('s-ok').textContent       = states.filter(s => s.status === 'ok').length;
      document.getElementById('s-inc').textContent      = states.filter(s => s.isIncNow).length;

      const mlVals = Object.values(mlPredictions);
      if (mlVals.length > 0) {
        document.getElementById('s-ml-high').textContent = mlVals.filter(m => m.risk_label === 'HIGH').length;
        document.getElementById('s-ml-med').textContent  = mlVals.filter(m => m.risk_label === 'MEDIUM').length;
      }

      // Зарплатный день
      const salaryCount = states.filter(s => s.isSalaryDay).length;
      const salaryEl = document.getElementById('s-salary');
      const salaryBox = document.getElementById('salary-box');
      if (salaryCount > 0) {
        salaryEl.textContent = 'Сегодня!';
        salaryBox.style.background = '#3b0764';
        salaryBox.style.animation = 'pulse-salary 1.5s infinite';
      } else {
        const nearCount = states.filter(s => s.isNearSalary).length;
        salaryEl.textContent = nearCount > 0 ? 'Скоро ±1 день' : 'Нет';
        salaryBox.style.background = '';
        salaryBox.style.animation = '';
      }

      // Кассеты: сколько ATM нуждаются в пополнении
      const cassetteNeed = states.filter(s => (s.cassetteToFill || 0) > 0).length;
      document.getElementById('s-cassette').textContent = cassetteNeed + ' ATM';

      // ML экономия (периодически обновляем)
      updateMlSavings();
    }

    // Время симуляции
    if (msg.sim) {
      const ts = msg.sim.current_timestamp;
      document.getElementById('sim-time').textContent =
        new Date(ts).toLocaleString('ru-RU', {
          day: '2-digit', month: 'short', year: 'numeric',
          hour: '2-digit', minute: '2-digit'
        });
    }

    // Первый снапшот — убираем лоадер и инициализируем карту
    if (msg.type === 'snapshot') {
      // Строим ATM_META из данных снапшота (единый источник правды)
      if (ATM_META.length === 0 && msg.atms) {
        ATM_META = msg.atms.map(a => ({
          id:       a.atm_id,
          name:     a.name,
          bank:     a.bank || 'Банк',
          address:  a.address || a.name,
          lat:      a.lat,
          lon:      a.lon,
          capacity: a.capacity || 50_000_000,
          profile:  a.profile || 'residential',
          region:   a.region, // сохранить регион
        }));
      }
      document.getElementById('loader').style.display = 'none';
      if (Object.keys(markers).length === 0) initMarkers();
      hydrateIcons();
    }

    renderList();
    hydrateIcons();
  }

  if (msg.type === 'route') {
    renderWSRoute(msg.data);
  }

}

async function loadAtmsFromDb() {
  try {
    const res = await fetch(`${API_BASE}/api/atms?limit=5000`);
    if (!res.ok) throw new Error('Failed to fetch ATMs from DB');
    const data = await res.json();
    if (data && data.atms) {
      ATM_META = data.atms.map(a => ({
        id:       a.terminal_id,
        name:     a.atm_number || a.terminal_id,
        bank:     a.branch || 'SQB',
        address:  a.address || 'Адрес не указан',
        lat:      a.lat,
        lon:      a.lon,
        capacity: a.capacity || 400000000,
        region:   a.region, // сохранить регион
      }));
      console.log(`Loaded ${ATM_META.length} ATMs from SQLite DB`);
      return true;
    }
  } catch (err) {
    console.warn('Failed to load ATMs from DB:', err);
  }
  return false;
}

// Fallback — JSON-файлы если API недоступен
async function loadFromJSON() {
  const loaderP = document.querySelector('#loader p');
  try {
    if (loaderP) loaderP.textContent = 'Загрузка банкоматов из БД...';
    
    // Сначала пробуем загрузить реальные банкоматы из базы
    const dbSuccess = await loadAtmsFromDb();
    
    // Optional local JSON (only if present — avoid console 404 noise)
    let tsData = {};
    if (!dbSuccess) {
      if (loaderP) loaderP.textContent = 'Загрузка истории транзакций...';
      try {
        const tsRes = await fetch('data/timeseries.json');
        if (tsRes.ok) tsData = await tsRes.json();
      } catch (_) {}
      try {
        const predRes = await fetch('data/predictions.json');
        if (predRes.ok) mlPredictions = await predRes.json();
      } catch (_) {}
    }

    // Определяем временные шаги симуляции
    const times = new Set();
    Object.keys(tsData).forEach(id => {
      tsData[id].forEach(r => times.add(r.transactionTime));
    });

    if (times.size > 0) {
      timeSteps = [...times].sort();
      allData = tsData;
    } else {
      // Нет timeseries — симуляция 30 дней с шагом 2 часа
      const start = new Date('2024-10-01');
      for (let i = 0; i < 24 * 30; i++) {
        times.add(new Date(start.getTime() + i * 2 * 3600_000).toISOString());
      }
      timeSteps = [...times];
    }

    // Для каждого банкомата без истории — синтетические балансы
    ATM_META.forEach(atm => {
      if (!allData[atm.id] || allData[atm.id].length === 0) {
        let bal = atm.capacity * (0.3 + Math.random() * 0.6);
        allData[atm.id] = timeSteps.map(t => {
          const outcome = Math.floor(Math.random() * atm.capacity * 0.04);
          bal = Math.max(0, bal - outcome);
          let is_inc = 0;
          if (bal < atm.capacity * 0.20) {
            bal = atm.capacity * (0.8 + Math.random() * 0.15);
            is_inc = 1;
          }
          return {
            transactionTime: t,
            totalBalance: bal,
            atm_capacity: atm.capacity,
            is_incassation: is_inc,
            low_cash_alert: bal < atm.capacity * 0.20 ? 1 : 0
          };
        });
      }
    });

    document.getElementById('loader').style.display = 'none';
    startSimulation();
  } catch (err) {
    console.warn('Ошибка при загрузке:', err);
    document.getElementById('loader').style.display = 'none';
  }
}

function generateSyntheticData() {
  const start = new Date('2024-10-01');
  const times = [];
  for (let i = 0; i < 24 * 30; i++) {
    times.push(new Date(start.getTime() + i * 2 * 3600_000).toISOString());
  }
  timeSteps = times;
  ATM_META.forEach(atm => {
    let bal = atm.capacity * 0.8;
    allData[atm.id] = times.map(t => {
      const outcome = Math.floor(Math.random() * atm.capacity * 0.03);
      bal = Math.max(0, bal - outcome);
      if (bal < atm.capacity * 0.2) bal = atm.capacity * 0.85;
      return { transactionTime: t, totalBalance: bal, atm_capacity: atm.capacity,
               is_incassation: 0, low_cash_alert: bal < atm.capacity * 0.2 ? 1 : 0 };
    });
  });
}

// ═══════════════════════════════════════════════════════════
// SIMULATION TICK
// ═══════════════════════════════════════════════════════════

function tick() {
  if (timeIndex >= timeSteps.length) { timeIndex = 0; }
  const ts = timeSteps[timeIndex];

  document.getElementById('sim-time').textContent =
    new Date(ts).toLocaleString('ru-RU', {
      day:'2-digit', month:'short', year:'numeric',
      hour:'2-digit', minute:'2-digit'
    });

  let nCrit = 0, nWarn = 0, nOk = 0, nInc = 0;

  ATM_META.forEach(atm => {
    const rows = allData[atm.id] || [];
    const row  = rows[Math.min(timeIndex, rows.length - 1)];
    if (!row) return;

    const pct = row.totalBalance / atm.capacity;
    let status = 'ok';
    if (pct < 0.2) { status = 'critical'; nCrit++; }
    else if (pct < 0.4) { status = 'warning'; nWarn++; }
    else { nOk++; }

    if (row.is_incassation) nInc++;

    const lastIncRow = rows.slice(0, timeIndex + 1).reverse().find(r => r.is_incassation);
    const lastInc = lastIncRow
      ? new Date(lastIncRow.transactionTime).toLocaleDateString('ru-RU')
      : 'нет данных';

    atmState[atm.id] = {
      balance: row.totalBalance,
      pct: pct,
      status,
      lastInc,
      isIncNow: !!row.is_incassation,
      capacity: atm.capacity,
    };

    // обновляем маркер
    if (markers[atm.id]) {
      const isHighlighted = selectedAtmIdsFromModal && selectedAtmIdsFromModal.has(atm.id);
      markers[atm.id].setIcon(makeIcon(status, isHighlighted));
    }
  });

  document.getElementById('s-total').textContent    = ATM_META.length;
  document.getElementById('s-critical').textContent = nCrit;
  document.getElementById('s-warning').textContent  = nWarn;
  document.getElementById('s-ok').textContent       = nOk;
  document.getElementById('s-inc').textContent      = nInc;

  // ML риски
  const mlVals = Object.values(mlPredictions);
  if (mlVals.length > 0) {
    document.getElementById('s-ml-high').textContent = mlVals.filter(m => m.risk_label === 'HIGH').length;
    document.getElementById('s-ml-med').textContent  = mlVals.filter(m => m.risk_label === 'MEDIUM').length;
  }

  renderList();

  timeIndex++;
}

function startSimulation() {
  initMarkers();
  renderList();
  tick();
  simTimer = setInterval(tick, 1200);
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

    const ml  = mlPredictions[atm.id] || {};
    const mlBal  = ml.pred_balance_24h  ? (ml.pred_balance_24h  / 1_000_000).toFixed(1) : null;
    const mlPct  = ml.pred_balance_pct_24h ?? ml.pred_balance_pct ?? null;
    const mlProbRaw = ml.pred_cashout_prob ?? ml.cashout_prob;
    const mlProb = mlProbRaw != null ? (mlProbRaw * 100).toFixed(0) : null;
    const mlRisk = ml.risk_label || null;
    const mlRiskColor = mlRisk ? getRiskColor(mlRisk) : '#64748b';
    const mlRiskIcon  = mlRisk ? getRiskIcon(mlRisk)  : '';

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
      ${mlBal ? `
      <div class="atm-card-bar-wrap" style="margin-top:6px">
        <div class="bar-labels">
          <span style="color:#4f46e5;font-weight:700">${appIcon('brain-circuit')}Прогноз +24ч</span>
          <span class="val" style="color:#4f46e5">${mlBal} млн (${mlPct}%)</span>
        </div>
        <div class="bar-bg">
          <div class="bar-fill" style="width:${Math.min(mlPct,100)}%;background:linear-gradient(90deg,#6366f1,#818cf8)"></div>
        </div>
      </div>
      <div style="margin-top:5px;display:flex;align-items:center;justify-content:space-between;font-size:11px">
        <span style="color:#667085">Риск cash-out:</span>
        <span style="color:${mlRiskColor};font-weight:700">${mlRiskIcon} ${mlRisk} · ${mlProb}%</span>
      </div>` : ''}
      <div class="atm-card-footer" style="margin-top:6px">
        <span>${pctDisp}% заполнен</span>
        ${st.isIncNow ? '<span class="highlight">&#x21BB; Инкассация сейчас</span>' : '<span>Посл. инк.: ' + st.lastInc + '</span>'}
      </div>

      <!-- 4 Кассеты с реальными номиналами -->
      <div style="margin-top:7px">
        <div style="font-size:10px;color:#667085;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px;font-weight:800">Кассеты</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px">
          ${(st.cassettes || []).map(c => {
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
          }).join('')}
        </div>
        ${st.cassetteToFill > 0 ? `<div style="margin-top:3px;font-size:10px;color:#f59e0b">
          ${appIcon('arrow-up-circle')}Нужно довезти: ${(st.cassetteToFill/1e6).toFixed(0)} млн
        </div>` : `<div style="margin-top:3px;font-size:10px;color:#16a34a">${appIcon('check-circle-2')}Кассеты заполнены</div>`}
      </div>

      <!-- Время опустошения + зарплатный день -->
      <div style="margin-top:5px;display:flex;gap:8px;font-size:11px;flex-wrap:wrap">
        ${st.emptyAt ? `<span style="color:${st.status==='critical'?'#dc2626':st.status==='warning'?'#d97706':'#667085'}">
          ${appIcon('timer')}Опустеет: <b>${st.emptyAt}</b>
        </span>` : ''}
        ${st.isSalaryDay ? `<span style="color:#7c3aed;font-weight:700">${appIcon('calendar-days')}Зарплатный день</span>` : ''}
        ${!st.isSalaryDay && st.isNearSalary ? `<span style="color:#7c3aed">${appIcon('calendar-clock')}Скоро зарплата</span>` : ''}
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

  const ml2  = mlPredictions[id] || {};
  const mlB2 = ml2.pred_balance_24h ? (ml2.pred_balance_24h / 1_000_000).toFixed(1) : '—';
  const mlP2 = ml2.pred_balance_pct_24h ?? ml2.pred_balance_pct ?? '—';
  const mlR2 = ml2.risk_label || '—';
  const mlPrRaw2 = ml2.pred_cashout_prob ?? ml2.cashout_prob;
  const mlPr2 = mlPrRaw2 != null ? (mlPrRaw2 * 100).toFixed(0) + '%' : '—';
  const mlRC2 = getRiskColor(mlR2);

  const stPop = atmState[id] || {};
  const salaryBadge = stPop.isSalaryDay
    ? `<span style="background:#ede9fe;color:#6d28d9;padding:3px 7px;border-radius:999px;font-size:10px;margin-left:6px;font-weight:800">${appIcon('calendar-days')}Зарплатный день</span>`
    : stPop.isNearSalary
      ? `<span style="background:#f5f3ff;color:#7c3aed;padding:3px 7px;border-radius:999px;font-size:10px;margin-left:6px;font-weight:800">${appIcon('calendar-clock')}Скоро зарплата</span>`
      : '';

  const cassIcons = Array.from({length: stPop.cassetteCap || 4}, (_, i) =>
    `<span style="display:inline-block;width:14px;height:20px;border-radius:2px;border:1px solid #475569;
      background:${i < (stPop.cassetteLoaded || 0) ? '#16a34a' : '#e5eaf3'};
      font-size:8px;line-height:20px;text-align:center">${i < (stPop.cassetteLoaded||0)?'▮':''}</span>`
  ).join('');

  markers[id].bindPopup(`
    <div class="popup-title">${atm.name}${salaryBadge}</div>
    <div class="popup-row">Адрес: <span>${atm.address}</span></div>
    <hr style="border-color:#e5eaf3;margin:8px 0">

    <div class="popup-row">Остаток: <span>${((stPop.balance||0)/1_000_000).toFixed(1)} млн сум (${pct}%)</span></div>
    <div class="popup-row">Статус: <span style="color:${
      stPop.status==='ok'?'#16a34a':stPop.status==='warning'?'#d97706':'#dc2626'
    }">${stPop.status==='ok'?'Норма':stPop.status==='warning'?'Предупреждение':'Критично'}</span></div>
    ${stPop.emptyAt ? `<div class="popup-row">${appIcon('timer')}Опустеет: <span style="color:#dc2626;font-weight:800">${stPop.emptyAt}</span></div>` : ''}

    <hr style="border-color:#e5eaf3;margin:8px 0">
    <div style="font-size:10px;color:#667085;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px;font-weight:800">4 Кассеты</div>
    ${(stPop.cassettes || []).map(c => {
      const fillColor = c.fill_pct > 60 ? '#22c55e' : c.fill_pct > 25 ? '#f59e0b' : '#ef4444';
      const denom = c.denomination >= 1000 ? (c.denomination/1000).toFixed(0)+'к' : c.denomination;
      return `<div style="display:flex;align-items:center;gap:5px;margin-bottom:3px;font-size:10px">
        <span style="color:#667085;width:40px">${denom} сум</span>
        <div style="flex:1;height:6px;background:#e5eaf3;border-radius:999px;overflow:hidden">
          <div style="height:6px;background:${fillColor};border-radius:3px;width:${Math.min(c.fill_pct,100)}%"></div>
        </div>
        <span style="color:${fillColor};width:32px;text-align:right">${c.fill_pct}%</span>
        <span style="color:#475569;font-size:9px">${(c.balance/1e6).toFixed(0)} млн</span>
      </div>`;
    }).join('')}
    ${stPop.cassetteToFill > 0 ? `<div style="margin-top:2px;font-size:10px;color:#f59e0b">${appIcon('arrow-up-circle')}Нужно: ${(stPop.cassetteToFill/1e6).toFixed(0)} млн</div>` : `<div style="font-size:10px;color:#16a34a">${appIcon('check-circle-2')}Все кассеты заполнены</div>`}

    <hr style="border-color:#e5eaf3;margin:8px 0">
    <div style="font-size:11px;color:#4f46e5;font-weight:800;margin-bottom:3px">${appIcon('brain-circuit')}ML Прогноз +24ч</div>
    <div class="popup-row">Баланс через 24ч: <span style="color:#4f46e5">${mlB2} млн (${mlP2}%)</span></div>
    <div class="popup-row">Риск cash-out: <span style="color:${mlRC2};font-weight:700">${getRiskIcon(mlR2)} ${mlR2} · ${mlPr2}</span></div>
    <div class="popup-row">Посл. инкассация: <span>${stPop.lastInc}</span></div>
  `).openPopup();
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

async function buildRegionalRoute(status) {
  clearRoute();
  if (status === 'all' && !confirm('В маршрут попадут и банкоматы в норме. Продолжить только для нуждающихся (критичные + предупреждения)?\n\nOK — только нуждающиеся\nОтмена — прервать')) {
    return;
  }
  if (status === 'all') status = 'warning';

  const speedKmh = parseInt(document.getElementById('speed-kmh')?.value, 10) || 30;
  const maxStops = parseInt(document.getElementById('max-stops')?.value, 10) || 12;
  const states = ATM_META.map(atm => {
    const st = atmState[atm.id];
    if (!st) return null;
    return { terminal_id: atm.id, balance: Math.round(st.balance || 0), status: st.status };
  }).filter(Boolean);

  const infoEl = document.getElementById('route-info');
  if (infoEl) infoEl.innerHTML = 'Строим маршруты по дорогам только для ATM ниже нормы…';

  try {
    const data = await fetch(
      `${API_BASE}/api/routes/incassation?status=${status}&speed_kmh=${speedKmh}&max_stops=${maxStops}&snap_roads=true`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ states, persist: true }),
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
      infoEl.innerHTML +=
        `<br><a href="/dashboard/incassation.html" style="color:#7c3aed;font-weight:800">Открыть в календаре →</a>` +
        (data.saved_to_calendar ? ` · сохранено рейсов: ${data.saved_to_calendar}` : '') +
        (roads ? ` · дороги OSRM: ${roads}` : '');
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

function renderRegionalRoutes(data) {
  routingLayers.forEach(l => map.removeLayer(l));
  routingLayers = [];
  if (depotMarker) { map.removeLayer(depotMarker); depotMarker = null; }

  const allPts = [];
  data.cars.forEach((car, gi) => {
    const color = car.color || CAR_COLORS[gi % CAR_COLORS.length];
    const dep = car.departure_branch || {};
    const routePts = (car.geometry || []).map(p => L.latLng(p.lat, p.lon));
    const wps = [];
    if (dep.lat != null && dep.lon != null) wps.push(L.latLng(dep.lat, dep.lon));
    (car.stops || []).forEach(s => wps.push(L.latLng(s.lat, s.lon)));
    if (dep.lat != null && dep.lon != null) wps.push(L.latLng(dep.lat, dep.lon));
    allPts.push(...(routePts.length ? routePts : wps));

    const roadLike = routePts.length > wps.length + 4;
    if (roadLike) {
      routingLayers.push(L.polyline(routePts, {
        color: '#000', weight: 8, opacity: 0.16, lineJoin: 'round', lineCap: 'round'
      }).addTo(map));
      routingLayers.push(L.polyline(routePts, {
        color, weight: 5, opacity: 0.92, lineJoin: 'round', lineCap: 'round'
      }).addTo(map));
    } else if (wps.length >= 2 && L.Routing) {
      const ctrl = L.Routing.control({
        waypoints: wps,
        router: L.Routing.osrmv1({ serviceUrl: 'https://router.project-osrm.org/route/v1' }),
        addWaypoints: false,
        draggableWaypoints: false,
        fitSelectedRoutes: false,
        show: false,
        routeWhileDragging: false,
        lineOptions: {
          styles: [
            { color: '#000', weight: 8, opacity: 0.16 },
            { color, weight: 5, opacity: 0.92 },
          ],
        },
        createMarker: () => null,
      }).addTo(map);
      routeControls.push(ctrl);
    } else if (wps.length >= 2) {
      routingLayers.push(L.polyline(wps, { color, weight: 5, opacity: 0.9 }).addTo(map));
    }
    if (dep.lat != null && dep.lon != null) {
      const depotPin = L.marker([dep.lat, dep.lon], {
        icon: L.divIcon({
          className: '',
          html: `<div style="width:34px;height:34px;border-radius:9px;background:${color};border:2.5px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 0 10px ${color}99">${appIcon('building-2')}</div>`,
          iconSize: [34, 34], iconAnchor: [17, 17]
        })
      }).addTo(map).bindPopup(`<b>${dep.name || 'Филиал'}</b><br>${car.region || ''}<br>${dep.address || ''}`);
      routingLayers.push(depotPin);
    }

    (car.stops || []).forEach((stop, si) => {
      const stColor = stop.status === 'critical' ? '#ef4444' : stop.status === 'warning' ? '#f59e0b' : '#22c55e';
      const pin = L.marker([stop.lat, stop.lon], {
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
        <div class="popup-row">Статус: <span style="color:${stColor}">${stop.status || '—'}</span></div>
      `);
      routingLayers.push(pin);
    });
  });

  if (allPts.length) map.fitBounds(L.latLngBounds(allPts), { padding: [45, 45] });

  const warnings = (data.unserved_regions || []).map(x => `${x.region}: ${x.reason}`).join('<br>');
  document.getElementById('route-info').innerHTML =
    `<b>${data.cars.length} маршрутов по вилоятам</b><br>` +
    `Старт/финиш: свой филиал с Инкассация = 1<br>` +
    `Остановок: ${data.total_stops} · ${data.total_dist_km} км · ~${data.est_time_min} мин` +
    (data.fallback_unknown_balances ? '<br><span style="color:#d97706">Нет актуальных балансов: предварительный маршрут по ATM без статуса.</span>' : '') +
    (warnings ? `<br><span style="color:#dc2626">${warnings}</span>` : '');

  const sb = document.getElementById('route-sidebar');
  if (!sb) return;
  openRouteSidebar();
  document.getElementById('rs-cars-count').textContent = data.cars.length;
  document.getElementById('rs-stops-count').textContent = data.total_stops;
  document.getElementById('rs-distance').textContent = Number(data.total_dist_km || 0).toFixed(1) + ' км';
  document.getElementById('rs-time').textContent = (data.est_time_min || 0) + ' мин';

  const container = document.getElementById('rs-cars-list');
  if (!container) return;
  container.innerHTML = data.cars.map(car => {
    const color = car.color;
    const stops = (car.stops || []).map((s, si) => {
      const pct = Number(s.balance_pct || 0).toFixed(0);
      const balStr = ((s.balance || 0) / 1e6).toFixed(1) + ' млн';
      const balCls = s.status === 'critical' ? 'bal-crit' : s.status === 'warning' ? 'bal-warn' : 'bal-ok';
      return `
        <div class="rs-stop" onclick="typeof selectAtm==='function' && selectAtm('${s.atm_id || s.terminal_id || ''}')" style="cursor:pointer">
          <div class="rs-stop-num" style="background:${color}">${si + 1}</div>
          <div class="rs-stop-name">${s.name || s.terminal_id}<br>
            <span style="color:#667085;font-size:10px">${s.bank || s.address || ''}</span>
          </div>
          <div class="rs-stop-bal ${balCls}">${balStr}<br>
            <span style="font-weight:500;color:#667085">${pct}%</span>
          </div>
        </div>`;
    }).join('');
    return `
      <div class="rs-car">
        <div class="rs-car-header" style="background:${color}22;border:1px solid ${color}55;border-bottom:none;">
          <div class="rs-car-dot" style="background:${color}"></div>
          <span style="color:${color};font-weight:700">${car.label}</span>
          <span style="margin-left:auto;color:#667085;font-size:11px;font-weight:600">
            ${car.stops.length} ост. · ${Number(car.total_dist_km || 0).toFixed(1)} км · ${car.est_time_min || 0} мин
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
  routeControls.forEach(rc => map.removeControl(rc));
  routeControls = [];
  routingLayers.forEach(l => map.removeLayer(l));
  routingLayers = [];
  if (depotMarker) { map.removeLayer(depotMarker); depotMarker = null; }
  document.getElementById('route-sidebar').classList.remove('open');
}

// ═══════════════════════════════════════════════════════════
// ML PREDICTIONS
// ═══════════════════════════════════════════════════════════

// loadPredictions() теперь интегрирована в WebSocket snapshot

function getRiskColor(label) {
  if (label === 'HIGH')   return '#ef4444';
  if (label === 'MEDIUM') return '#f59e0b';
  return '#22c55e';
}

function getRiskIcon(label) {
  if (label === 'HIGH')   return appIcon('octagon-alert');
  if (label === 'MEDIUM') return appIcon('circle-alert');
  return appIcon('shield-check');
}

// Рендер маршрута полученного по WebSocket (данные от FastAPI)
function renderWSRoute(routeData) {
  if (!routeData || !routeData.cars) return;

  // Очищаем старые слои
  routingLayers.forEach(l => map.removeLayer(l));
  routingLayers = [];
  if (depotMarker) { map.removeLayer(depotMarker); depotMarker = null; }

  // Маркер депо
  depotMarker = L.marker([DEPOT.lat, DEPOT.lon], {
    icon: L.divIcon({
      className: '',
      html: `<div style="
        width:38px;height:38px;border-radius:10px;
        background:#ffffff;border:2px solid #2563eb;
        display:flex;align-items:center;justify-content:center;
        font-size:20px;box-shadow:0 12px 28px rgba(37,99,235,.22);
      ">${appIcon('warehouse')}</div>`,
      iconSize: [38,38], iconAnchor: [19,19]
    })
  }).addTo(map).bindPopup(`<b>Депо инкассаторов</b><br>${DEPOT.name}`);
  routingLayers.push(depotMarker);

  // Рисуем маршруты
  const allPts = [];
  routeData.cars.forEach((car, gi) => {
    const fallbackPts = [
      L.latLng(DEPOT.lat, DEPOT.lon),
      ...car.stops.map(s => L.latLng(s.lat, s.lon)),
      L.latLng(DEPOT.lat, DEPOT.lon),
    ];
    const routePts = (car.geometry && car.geometry.length > 1)
      ? car.geometry.map(p => L.latLng(p.lat, p.lon))
      : fallbackPts;
    allPts.push(...routePts, ...fallbackPts);

    // Тень линии (чуть толще, тёмная) для глубины
    const shadow = L.polyline(routePts, {
      color: '#000', weight: 8, opacity: 0.18, lineJoin: 'round', lineCap: 'round'
    }).addTo(map);
    routingLayers.push(shadow);

    // Основная линия
    const poly = L.polyline(routePts, {
      color: car.color,
      weight: 5,
      opacity: 0.92,
      lineJoin: 'round',
      lineCap: 'round',
    }).addTo(map);
    routingLayers.push(poly);

    // Пунктирная обводка поверх — эффект "движения"
    const dash = L.polyline(routePts, {
      color: '#ffffff',
      weight: 1.5,
      opacity: 0.35,
      dashArray: '6 10',
      lineJoin: 'round',
    }).addTo(map);
    routingLayers.push(dash);

    // Маркеры остановок
    car.stops.forEach((stop, si) => {
      const pct   = stop.balance_pct;
      const color = stop.status === 'critical' ? '#ef4444'
                  : stop.status === 'warning'  ? '#f59e0b' : '#22c55e';

      const stopMarker = L.marker([stop.lat, stop.lon], {
        icon: L.divIcon({
          className: '',
          html: `
            <div style="
              width:32px;height:32px;border-radius:50%;
              background:${car.color};border:3px solid #fff;
              display:flex;align-items:center;justify-content:center;
              font-size:12px;font-weight:800;color:#fff;
              box-shadow:0 0 10px ${car.color}cc, 0 2px 6px #0008;
            ">${si+1}</div>
            <div style="
              position:absolute;bottom:-5px;left:50%;transform:translateX(-50%);
              width:8px;height:8px;border-radius:50%;
              background:${color};border:2px solid #fff;
              box-shadow:0 0 6px ${color};
            "></div>`,
          iconSize: [32,32], iconAnchor: [16,16]
        })
      }).addTo(map).bindPopup(`
        <div class="popup-title">${gi+1}${String.fromCharCode(64+si+1)}. ${stop.name}</div>
        <div class="popup-row">Банк: <span>${stop.bank}</span></div>
        <div class="popup-row">Остаток: <span>${(stop.balance/1e6).toFixed(1)} млн · ${pct.toFixed(0)}%</span></div>
        <div class="popup-row">Довезти: <span>${((stop.refill_amount || 0)/1e6).toFixed(0)} млн</span></div>
        <div class="popup-row">Статус: <span style="color:${color}">${
          stop.status==='critical'?'Критично':stop.status==='warning'?'Предупреждение':'Норма'
        }</span></div>
        ${stop.cashout_prob!=null ? `<div class="popup-row">ML риск: <span>${(stop.cashout_prob*100).toFixed(0)}%</span></div>` : ''}
        ${stop.empty_at ? `<div class="popup-row">Опустеет: <span>${stop.empty_at}</span></div>` : ''}
        ${stop.priority_score!=null ? `<div class="popup-row">Приоритет: <span>${stop.priority_score}</span></div>` : ''}
        <div class="popup-row">Маршрут: <span>${car.label}</span></div>
      `);
      routingLayers.push(stopMarker);
    });
  });

  // Подгоняем карту под маршруты
  if (allPts.length > 0) map.fitBounds(L.latLngBounds(allPts), { padding: [40, 40] });

  // ── Sidebar ──────────────────────────────────────────────
  const sb = document.getElementById('route-sidebar');
  if (!sb) return;
  openRouteSidebar();

  document.getElementById('rs-cars-count').textContent  = routeData.cars.length;
  document.getElementById('rs-stops-count').textContent = routeData.total_stops;
  document.getElementById('rs-distance').textContent    = routeData.total_dist_km.toFixed(1) + ' км';
  document.getElementById('rs-time').textContent        = routeData.est_time_min + ' мин';

  const q = routeData.route_quality;
  const providers = [...new Set(routeData.cars.map(c => c.routing_provider || 'fallback'))].join(', ');
  if (q && q.saved_km > 0) {
    document.getElementById('route-info').innerHTML =
      `Дороги: ${providers}<br>Оптимизация: −${q.saved_km.toFixed(1)} км (${q.saved_pct}%) vs старый round-robin`;
  } else {
    document.getElementById('route-info').innerHTML =
      `Дороги: ${providers}<br>Алгоритм: ML-приоритет + геокластеры + 2-opt`;
  }

  const container = document.getElementById('rs-cars-list');
  container.innerHTML = routeData.cars.map(car => {
    const stops = car.stops.map((s, si) => {
      const pct    = s.balance_pct.toFixed(0);
      const balStr = (s.balance / 1e6).toFixed(1) + ' млн';
      const refill = ((s.refill_amount || 0) / 1e6).toFixed(0) + ' млн';
      const balCls = s.status === 'critical' ? 'bal-crit'
                   : s.status === 'warning'  ? 'bal-warn' : 'bal-ok';
      const prob   = s.cashout_prob != null
                   ? `<span style="color:#7c3aed;font-size:10px;"> · ML риск ${(s.cashout_prob*100).toFixed(0)}%</span>` : '';
      return `
        <div class="rs-stop" onclick="selectAtm('${s.atm_id}')" style="cursor:pointer">
          <div class="rs-stop-num" style="background:${car.color}">${si+1}</div>
          <div class="rs-stop-name">
            ${s.name}<br>
            <span style="color:#667085;font-size:10px">${s.bank}</span>
          </div>
          <div class="rs-stop-bal ${balCls}">${balStr}<br>
            <span style="font-weight:500;color:#667085">${pct}% · +${refill}${prob}</span>
          </div>
        </div>`;
    }).join('');

    return `
      <div class="rs-car">
        <div class="rs-car-header" style="background:${car.color}22;border:1px solid ${car.color}55;border-bottom:none;">
          <div class="rs-car-dot" style="background:${car.color}"></div>
          <span style="color:${car.color};font-weight:700">${car.label}</span>
          <span style="margin-left:auto;color:#667085;font-size:11px;font-weight:600">
            ${car.stops.length} ост. · ${car.total_dist_km.toFixed(1)} км · ${car.est_time_min} мин · ${(car.refill_total/1e6).toFixed(0)} млн
          </span>
        </div>
        <div class="rs-stops">${stops}</div>
      </div>`;
  }).join('');
  hydrateIcons();
}

// ═══════════════════════════════════════════════════════════
// BOOT — пробуем WebSocket, fallback на JSON-файлы
// ═══════════════════════════════════════════════════════════
hydrateIcons();
connectWebSocket();
