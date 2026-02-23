/**
 * O.S MDM V2 — Module Maritime
 * Navires · Armateurs · Ports · Escales
 */

const MAPI = window.location.origin + '/api/maritime';
let vesselPage = 1, ownerPage = 1, portPage = 1, callPage = 1;
let currentVesselId = null, currentOwnerId = null, currentPortId = null, currentCallId = null;
let vesselTimer = null, ownerTimer = null, portTimer = null, callTimer = null;
let maritimeRefs = { flags: [], vesselTypes: [], callStatuses: [] };

// ── INIT MARITIME ─────────────────────────────────────────────────────────
async function initMaritime() {
  // Charger les référentiels
  const [flags, types, statuses] = await Promise.all([
    api('/maritime/referentials/flags'),
    api('/maritime/referentials/vessel-types'),
    api('/maritime/referentials/call-statuses'),
  ]);
  if (flags)    maritimeRefs.flags = flags;
  if (types)    maritimeRefs.vesselTypes = types;
  if (statuses) maritimeRefs.callStatuses = statuses;

  // Remplir les selects des filtres
  const flagFilter = document.getElementById('vessel-flag');
  if (flagFilter) flags?.forEach(f => {
    const o = document.createElement('option'); o.value=f.code; o.textContent=`${f.code} — ${f.name}`;
    flagFilter.appendChild(o);
  });
  const typeFilter = document.getElementById('vessel-type-filter');
  if (typeFilter) types?.forEach(t => {
    const o = document.createElement('option'); o.value=t; o.textContent=t;
    typeFilter.appendChild(o);
  });

  // Selects dans les modals
  ['v-flag','o-country','p-country'].forEach(id => {
    const sel = document.getElementById(id);
    if (sel) {
      flags?.forEach(f => {
        const o = document.createElement('option'); o.value=f.code; o.textContent=`${f.code} — ${f.name}`;
        sel.appendChild(o);
      });
    }
  });
  const vtSel = document.getElementById('v-type');
  if (vtSel) types?.forEach(t => {
    const o = document.createElement('option'); o.value=t; o.textContent=t;
    vtSel.appendChild(o);
  });
}

// ── MARITIME KPIs ─────────────────────────────────────────────────────────
async function loadMaritimeKPIs() {
  const stats = await api('/maritime/stats');
  if (!stats) return;
  const el = document.getElementById('maritime-kpis');
  if (!el) return;
  const items = [
    { label: 'Navires', value: stats.total_vessels,    color: '#1B5EA6', icon: '🚢' },
    { label: 'Armateurs', value: stats.total_owners,   color: '#7c3aed', icon: '🏢' },
    { label: 'Ports', value: stats.total_ports,        color: '#059669', icon: '⚓' },
    { label: 'Escales actives', value: stats.active_calls, color: '#d97706', icon: '📍' },
  ];
  el.innerHTML = items.map(i => `
    <div class="kpi-card" style="border-left:3px solid ${i.color};">
      <p style="font-size:11px;color:#6b7280;font-weight:600;margin:0 0 4px;">${i.icon} ${i.label}</p>
      <p style="font-size:28px;font-weight:800;color:${i.color};margin:0;">${i.value}</p>
    </div>`).join('');

  // Alertes qualité
  if (stats.validation_errors > 0 || stats.low_confidence > 0) {
    const alertDiv = document.createElement('div');
    alertDiv.style.cssText = 'grid-column:span 4;';
    alertDiv.innerHTML = `<div style="background:#fef3c7;border-radius:10px;padding:10px 14px;font-size:12px;color:#92400e;display:flex;gap:16px;">
      ${stats.validation_errors > 0 ? `<span>⚠️ <b>${stats.validation_errors}</b> navire(s) avec erreurs de validation</span>` : ''}
      ${stats.low_confidence > 0 ? `<span>🔶 <b>${stats.low_confidence}</b> navire(s) avec score de confiance faible</span>` : ''}
    </div>`;
    el.appendChild(alertDiv);
  }
}

// ── VESSELS ───────────────────────────────────────────────────────────────
async function loadVessels() {
  const search = document.getElementById('vessel-search')?.value.trim() || '';
  const flag   = document.getElementById('vessel-flag')?.value || '';
  const vtype  = document.getElementById('vessel-type-filter')?.value || '';
  const params = new URLSearchParams({ page: vesselPage, per_page: 20 });
  if (search) params.set('search', search);
  if (flag)   params.set('flag', flag);
  if (vtype)  params.set('vessel_type', vtype);
  const data = await api(`/maritime/vessels?${params}`);
  if (!data) return;

  const container = document.getElementById('vessels-table');
  if (!data.vessels.length) {
    container.innerHTML = '<p style="color:#9ca3af;font-size:13px;text-align:center;padding:24px;">Aucun navire.</p>';
    return;
  }

  const confBadge = score => {
    if (score >= 0.9) return '<span class="badge" style="background:#d1fae5;color:#065f46;">✅ Élevé</span>';
    if (score >= 0.7) return '<span class="badge" style="background:#fef3c7;color:#92400e;">⚠️ Moyen</span>';
    return '<span class="badge" style="background:#fee2e2;color:#991b1b;">❌ Faible</span>';
  };
  const statusBadge = status => {
    if (!status || status === 'active') return '';
    return `<span class="badge" style="background:#f3f4f6;color:#6b7280;">${status}</span>`;
  };

  container.innerHTML = `<table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th class="table-th">MDM ID</th>
      <th class="table-th">Navire</th>
      <th class="table-th">IMO</th>
      <th class="table-th">MMSI</th>
      <th class="table-th">Type</th>
      <th class="table-th">Pavillon</th>
      <th class="table-th">GT</th>
      <th class="table-th">Confiance</th>
      <th class="table-th">Actions</th>
    </tr></thead>
    <tbody>${data.vessels.map(v => `<tr>
      <td class="table-td"><span style="font-family:monospace;font-size:10px;color:#1B5EA6;">${v.mdm_id}</span></td>
      <td class="table-td"><span style="font-weight:600;color:#111827;">${esc(v.vessel_name)}</span></td>
      <td class="table-td"><span style="font-family:monospace;font-size:11px;color:#059669;">${esc(v.imo_number||'—')}</span></td>
      <td class="table-td" style="font-family:monospace;font-size:11px;color:#6b7280;">${esc(v.mmsi||'—')}</td>
      <td class="table-td"><span class="badge" style="background:#e8f0fb;color:#1B5EA6;">${esc(v.vessel_type||'—')}</span></td>
      <td class="table-td">${v.flag_code ? `<span title="${esc(v.flag_name||'')}"><b>${esc(v.flag_code)}</b></span>` : '—'}</td>
      <td class="table-td" style="color:#6b7280;">${v.gross_tonnage ? Number(v.gross_tonnage).toLocaleString() : '—'}</td>
      <td class="table-td">${confBadge(v.confidence_score||1)}</td>
      <td class="table-td">
        <div style="display:flex;gap:4px;">
          <button class="btn btn-secondary" style="padding:3px 8px;font-size:11px;" onclick="editVessel('${v.id}')">✏️</button>
          <button class="btn btn-danger" style="padding:3px 8px;font-size:11px;" onclick="deleteVessel('${v.id}')">🗑️</button>
        </div>
      </td>
    </tr>`).join('')}</tbody>
  </table>`;

  document.getElementById('vessel-count').textContent = `${data.total} navire(s)`;
  document.getElementById('vessel-page-info').textContent = `Page ${vesselPage}`;
  document.getElementById('vessel-prev').disabled = vesselPage <= 1;
  document.getElementById('vessel-next').disabled = (vesselPage * 20) >= data.total;
}

function debounceVessels() { clearTimeout(vesselTimer); vesselPage=1; vesselTimer=setTimeout(loadVessels, 400); }
function vesselPrevPage() { if(vesselPage>1){vesselPage--;loadVessels();} }
function vesselNextPage() { vesselPage++;loadVessels(); }

// Validation en temps réel
async function liveValidateIMO() {
  const val = document.getElementById('v-imo').value.trim();
  const el  = document.getElementById('imo-check');
  if (!val) { el.textContent=''; return; }
  const res = await api('/maritime/vessels/validate-imo', {method:'POST', body:JSON.stringify({imo:val})});
  el.textContent = res?.valid ? '✅' : '❌';
  el.title = res?.error || '';
}

async function liveValidateMMSI() {
  const val = document.getElementById('v-mmsi').value.trim();
  const el  = document.getElementById('mmsi-check');
  if (!val) { el.textContent=''; return; }
  const res = await api('/maritime/vessels/validate-mmsi', {method:'POST', body:JSON.stringify({mmsi:val})});
  el.textContent = res?.valid ? '✅' : (res?.error ? '❌' : '');
  el.title = res?.error || '';
}

async function liveValidateLOCODE() {
  const val = document.getElementById('p-locode')?.value.trim();
  const el  = document.getElementById('locode-check');
  if (!el) return;
  if (!val || val.length < 4) { el.textContent=''; return; }
  // Validation client-side simple
  const clean = val.replace(' ','');
  el.textContent = (clean.length===5 && /^[A-Z]{2}[A-Z0-9]{3}$/i.test(clean)) ? '✅' : '❌';
}

function openVesselModal(vessel=null) {
  currentVesselId = vessel?.id || null;
  document.getElementById('vessel-modal-title').textContent = vessel ? `Modifier — ${vessel.vessel_name}` : 'Nouveau navire';
  document.getElementById('v-name').value    = vessel?.vessel_name || '';
  document.getElementById('v-imo').value     = vessel?.imo_number || '';
  document.getElementById('v-mmsi').value    = vessel?.mmsi || '';
  document.getElementById('v-type').value    = vessel?.vessel_type || '';
  document.getElementById('v-flag').value    = vessel?.flag_code || '';
  document.getElementById('v-gt').value      = vessel?.gross_tonnage || '';
  document.getElementById('v-dwt').value     = vessel?.deadweight || '';
  document.getElementById('v-year').value    = vessel?.year_built || '';
  document.getElementById('v-class').value   = vessel?.class_society || '';
  document.getElementById('v-operator').value= vessel?.operator || '';
  document.getElementById('v-source').value  = vessel?.source || '';
  document.getElementById('imo-check').textContent = '';
  document.getElementById('mmsi-check').textContent = '';
  document.getElementById('vessel-modal-errors').style.display = 'none';
  document.getElementById('vessel-modal').style.display = 'flex';
}

async function editVessel(id) {
  const v = await api(`/maritime/vessels/${id}`);
  if (v) openVesselModal(v);
}

function closeVesselModal() {
  document.getElementById('vessel-modal').style.display = 'none'; currentVesselId = null;
}

async function saveVessel() {
  const body = {
    vessel_name:   document.getElementById('v-name').value.trim(),
    imo_number:    document.getElementById('v-imo').value.trim(),
    mmsi:          document.getElementById('v-mmsi').value.trim(),
    vessel_type:   document.getElementById('v-type').value,
    flag_code:     document.getElementById('v-flag').value,
    gross_tonnage: parseFloat(document.getElementById('v-gt').value) || null,
    deadweight:    parseFloat(document.getElementById('v-dwt').value) || null,
    year_built:    parseInt(document.getElementById('v-year').value) || null,
    class_society: document.getElementById('v-class').value.trim(),
    operator:      document.getElementById('v-operator').value.trim(),
    source:        document.getElementById('v-source').value.trim() || 'manuel',
  };
  if (!body.vessel_name) { toast('Nom du navire requis', 'error'); return; }

  const errEl = document.getElementById('vessel-modal-errors');
  let res;
  if (currentVesselId) {
    res = await api(`/maritime/vessels/${currentVesselId}`, { method:'PUT', body:JSON.stringify(body) });
  } else {
    res = await api('/maritime/vessels', { method:'POST', body:JSON.stringify(body) });
  }
  if (!res) return;

  // Afficher avertissements
  if (res.validation_errors?.length) {
    errEl.innerHTML = '⚠️ ' + res.validation_errors.join('<br>⚠️ ');
    errEl.style.display = 'block';
  }
  if (res.potential_duplicates?.length) {
    toast(`⚠️ ${res.potential_duplicates.length} doublon(s) potentiel(s) détecté(s)`, 'warning');
  }
  if (res.error) {
    errEl.textContent = '❌ ' + res.error; errEl.style.display = 'block';
    if (res.existing_id) errEl.innerHTML += ` — <a href="#" onclick="editVessel('${res.existing_id}')">Voir navire existant</a>`;
    return;
  }

  toast(currentVesselId ? 'Navire mis à jour' : 'Navire créé ✅');
  if (!res.validation_errors?.length) closeVesselModal();
  loadVessels(); loadMaritimeKPIs();
}

async function deleteVessel(id) {
  if (!confirm('Supprimer ce navire ?')) return;
  await api(`/maritime/vessels/${id}`, { method:'DELETE' });
  toast('Navire supprimé', 'warning'); loadVessels(); loadMaritimeKPIs();
}

// ── OWNERS ────────────────────────────────────────────────────────────────
async function loadOwners() {
  const search  = document.getElementById('owner-search')?.value.trim() || '';
  const country = document.getElementById('owner-country')?.value || '';
  const params  = new URLSearchParams({ page: ownerPage, per_page: 20 });
  if (search)  params.set('search', search);
  if (country) params.set('country', country);
  const data = await api(`/maritime/owners?${params}`);
  if (!data) return;
  const container = document.getElementById('owners-table');
  if (!data.owners.length) { container.innerHTML = '<p style="color:#9ca3af;font-size:13px;text-align:center;padding:24px;">Aucun armateur.</p>'; return; }
  container.innerHTML = `<table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th class="table-th">MDM ID</th><th class="table-th">Armateur</th>
      <th class="table-th">Type</th><th class="table-th">Pays</th>
      <th class="table-th">Ville</th><th class="table-th">Actions</th>
    </tr></thead>
    <tbody>${data.owners.map(o => `<tr>
      <td class="table-td"><span style="font-family:monospace;font-size:10px;color:#7c3aed;">${o.mdm_id}</span></td>
      <td class="table-td"><span style="font-weight:600;">${esc(o.owner_name)}</span></td>
      <td class="table-td"><span class="badge" style="background:#ede9fe;color:#7c3aed;">${esc(o.owner_type||'—')}</span></td>
      <td class="table-td">${o.country_code ? `<b>${esc(o.country_code)}</b> ${esc(o.country_name||'')}` : '—'}</td>
      <td class="table-td" style="color:#6b7280;">${esc(o.city||'—')}</td>
      <td class="table-td"><div style="display:flex;gap:4px;">
        <button class="btn btn-secondary" style="padding:3px 8px;font-size:11px;" onclick="editOwner('${o.id}')">✏️</button>
        <button class="btn btn-danger" style="padding:3px 8px;font-size:11px;" onclick="deleteOwner('${o.id}')">🗑️</button>
      </div></td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function debounceOwners() { clearTimeout(ownerTimer); ownerPage=1; ownerTimer=setTimeout(loadOwners,400); }
function openOwnerModal(owner=null) {
  currentOwnerId = owner?.id || null;
  document.getElementById('owner-modal-title').textContent = owner ? 'Modifier armateur' : 'Nouvel armateur';
  document.getElementById('o-name').value    = owner?.owner_name || '';
  document.getElementById('o-type').value    = owner?.owner_type || 'Shipowner';
  document.getElementById('o-country').value = owner?.country_code || '';
  document.getElementById('o-city').value    = owner?.city || '';
  document.getElementById('o-email').value   = owner?.contact_email || '';
  document.getElementById('o-address').value = owner?.address || '';
  document.getElementById('owner-modal').style.display = 'flex';
}
async function editOwner(id) { const o=await api(`/maritime/owners/${id}`); if(o)openOwnerModal(o); }
function closeOwnerModal() { document.getElementById('owner-modal').style.display='none'; currentOwnerId=null; }
async function saveOwner() {
  const body = { owner_name:document.getElementById('o-name').value.trim(), owner_type:document.getElementById('o-type').value, country_code:document.getElementById('o-country').value, city:document.getElementById('o-city').value.trim(), contact_email:document.getElementById('o-email').value.trim(), address:document.getElementById('o-address').value.trim() };
  if(!body.owner_name){toast('Nom requis','error');return;}
  if(currentOwnerId) await api(`/maritime/owners/${currentOwnerId}`,{method:'PUT',body:JSON.stringify(body)});
  else await api('/maritime/owners',{method:'POST',body:JSON.stringify(body)});
  toast(currentOwnerId?'Armateur mis à jour':'Armateur créé ✅');
  closeOwnerModal(); loadOwners(); loadMaritimeKPIs();
}
async function deleteOwner(id) { if(!confirm('Supprimer ?'))return; await api(`/maritime/owners/${id}`,{method:'DELETE'}); toast('Supprimé','warning'); loadOwners(); }

// ── PORTS ─────────────────────────────────────────────────────────────────
async function loadPorts() {
  const search  = document.getElementById('port-search')?.value.trim() || '';
  const country = document.getElementById('port-country')?.value || '';
  const params  = new URLSearchParams({ page: portPage, per_page: 20 });
  if (search)  params.set('search', search);
  if (country) params.set('country', country);
  const data = await api(`/maritime/ports?${params}`);
  if (!data) return;
  const container = document.getElementById('ports-table');
  if (!data.ports.length) { container.innerHTML = '<p style="color:#9ca3af;font-size:13px;text-align:center;padding:24px;">Aucun port.</p>'; return; }
  container.innerHTML = `<table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th class="table-th">MDM ID</th><th class="table-th">Port</th>
      <th class="table-th">UN/LOCODE</th><th class="table-th">Pays</th>
      <th class="table-th">Tirant max</th><th class="table-th">Marées</th><th class="table-th">Actions</th>
    </tr></thead>
    <tbody>${data.ports.map(p => `<tr>
      <td class="table-td"><span style="font-family:monospace;font-size:10px;color:#059669;">${p.mdm_id}</span></td>
      <td class="table-td"><span style="font-weight:600;">${esc(p.port_name)}</span></td>
      <td class="table-td"><span style="font-family:monospace;font-size:12px;color:#059669;font-weight:700;">${esc(p.un_locode||'—')}</span></td>
      <td class="table-td">${p.country_code?`<b>${esc(p.country_code)}</b>`:''} ${esc(p.country_name||'')}</td>
      <td class="table-td" style="color:#6b7280;">${p.max_draft ? p.max_draft+'m' : '—'}</td>
      <td class="table-td">${p.tide_dependent ? '<span class="badge" style="background:#fef3c7;color:#92400e;">⚓ Oui</span>' : '<span style="color:#9ca3af;font-size:12px;">Non</span>'}</td>
      <td class="table-td"><div style="display:flex;gap:4px;">
        <button class="btn btn-secondary" style="padding:3px 8px;font-size:11px;" onclick="editPort('${p.id}')">✏️</button>
        <button class="btn btn-danger" style="padding:3px 8px;font-size:11px;" onclick="deletePort('${p.id}')">🗑️</button>
      </div></td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function debouncePorts() { clearTimeout(portTimer); portPage=1; portTimer=setTimeout(loadPorts,400); }
function openPortModal(port=null) {
  currentPortId = port?.id || null;
  document.getElementById('port-modal-title').textContent = port ? 'Modifier port' : 'Nouveau port';
  document.getElementById('p-name').value   = port?.port_name || '';
  document.getElementById('p-locode').value = port?.un_locode || '';
  document.getElementById('p-country').value= port?.country_code || '';
  document.getElementById('p-lat').value    = port?.latitude || '';
  document.getElementById('p-lon').value    = port?.longitude || '';
  document.getElementById('p-draft').value  = port?.max_draft || '';
  document.getElementById('p-maxsize').value= port?.max_vessel_size || '';
  document.getElementById('p-tide').checked = !!port?.tide_dependent;
  document.getElementById('p-pilot').checked= port?.pilotage_required !== 0;
  document.getElementById('locode-check').textContent = '';
  document.getElementById('port-modal').style.display = 'flex';
}
async function editPort(id) { const p=await api(`/maritime/ports/${id}`); if(p)openPortModal(p); }
function closePortModal() { document.getElementById('port-modal').style.display='none'; currentPortId=null; }
async function savePort() {
  const body = { port_name:document.getElementById('p-name').value.trim(), un_locode:document.getElementById('p-locode').value.trim().toUpperCase(), country_code:document.getElementById('p-country').value, latitude:parseFloat(document.getElementById('p-lat').value)||null, longitude:parseFloat(document.getElementById('p-lon').value)||null, max_draft:parseFloat(document.getElementById('p-draft').value)||null, max_vessel_size:document.getElementById('p-maxsize').value.trim(), tide_dependent:document.getElementById('p-tide').checked, pilotage_required:document.getElementById('p-pilot').checked };
  if(!body.port_name){toast('Nom requis','error');return;}
  let res;
  if(currentPortId) res=await api(`/maritime/ports/${currentPortId}`,{method:'PUT',body:JSON.stringify(body)});
  else res=await api('/maritime/ports',{method:'POST',body:JSON.stringify(body)});
  if(res?.error){toast('❌ '+res.error,'error');return;}
  toast(currentPortId?'Port mis à jour':'Port créé ✅');
  closePortModal(); loadPorts(); loadMaritimeKPIs();
}
async function deletePort(id) { if(!confirm('Supprimer ce port ?'))return; await api(`/maritime/ports/${id}`,{method:'DELETE'}); toast('Port supprimé','warning'); loadPorts(); }

// ── PORT CALLS ────────────────────────────────────────────────────────────
async function loadCalls() {
  const search  = document.getElementById('call-search')?.value.trim() || '';
  const status  = document.getElementById('call-status-filter')?.value || '';
  const params  = new URLSearchParams({ page: callPage, per_page: 20 });
  if (search) params.set('search', search);
  if (status) params.set('status', status);
  const data = await api(`/maritime/port-calls?${params}`);
  if (!data) return;
  const container = document.getElementById('calls-table');
  if (!data.port_calls.length) { container.innerHTML = '<p style="color:#9ca3af;font-size:13px;text-align:center;padding:24px;">Aucune escale.</p>'; return; }

  const statusColor = s => ({ 'Planned':'#1B5EA6,#e8f0fb', 'In Transit':'#d97706,#fef3c7', 'At Anchor':'#7c3aed,#ede9fe', 'Berthed':'#059669,#d1fae5', 'Departed':'#6b7280,#f3f4f6', 'Cancelled':'#dc2626,#fee2e2' }[s] || '#6b7280,#f3f4f6');

  container.innerHTML = `<table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th class="table-th">MDM ID</th><th class="table-th">Navire</th><th class="table-th">IMO</th>
      <th class="table-th">Port</th><th class="table-th">LOCODE</th>
      <th class="table-th">ETA</th><th class="table-th">ETD</th>
      <th class="table-th">Statut</th><th class="table-th">Cargaison</th><th class="table-th">Actions</th>
    </tr></thead>
    <tbody>${data.port_calls.map(c => {
      const [fg,bg] = statusColor(c.call_status).split(',');
      return `<tr>
        <td class="table-td"><span style="font-family:monospace;font-size:10px;color:#d97706;">${c.mdm_id}</span></td>
        <td class="table-td"><span style="font-weight:600;">${esc(c.vessel_name||'—')}</span></td>
        <td class="table-td"><span style="font-family:monospace;font-size:11px;color:#059669;">${esc(c.imo_number||'—')}</span></td>
        <td class="table-td">${esc(c.port_name||'—')}</td>
        <td class="table-td"><span style="font-family:monospace;font-size:11px;font-weight:700;color:#059669;">${esc(c.un_locode||'—')}</span></td>
        <td class="table-td" style="font-size:11px;color:#6b7280;white-space:nowrap;">${c.eta ? new Date(c.eta).toLocaleString('fr-FR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '—'}</td>
        <td class="table-td" style="font-size:11px;color:#6b7280;white-space:nowrap;">${c.etd ? new Date(c.etd).toLocaleString('fr-FR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '—'}</td>
        <td class="table-td"><span class="badge" style="color:${fg};background:${bg};">${c.call_status}</span></td>
        <td class="table-td" style="color:#6b7280;font-size:12px;">${esc(c.cargo_type||'—')} ${c.cargo_quantity?`(${Number(c.cargo_quantity).toLocaleString()} ${c.cargo_unit||'MT'})`:''}  </td>
        <td class="table-td"><div style="display:flex;gap:4px;">
          <button class="btn btn-secondary" style="padding:3px 8px;font-size:11px;" onclick="editCall('${c.id}')">✏️</button>
          <button class="btn btn-danger" style="padding:3px 8px;font-size:11px;" onclick="deleteCall('${c.id}')">🗑️</button>
        </div></td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

function debounceCalls() { clearTimeout(callTimer); callPage=1; callTimer=setTimeout(loadCalls,400); }
function openCallModal(call=null) {
  currentCallId = call?.id || null;
  document.getElementById('call-modal-title').textContent = call ? 'Modifier escale' : 'Nouvelle escale';
  document.getElementById('c-vessel').value  = call?.vessel_name || call?.imo_number || '';
  document.getElementById('c-port').value    = call?.port_name || call?.un_locode || '';
  document.getElementById('c-eta').value     = call?.eta ? call.eta.slice(0,16) : '';
  document.getElementById('c-etd').value     = call?.etd ? call.etd.slice(0,16) : '';
  document.getElementById('c-status').value  = call?.call_status || 'Planned';
  document.getElementById('c-cargo').value   = call?.cargo_type || '';
  document.getElementById('c-qty').value     = call?.cargo_quantity || '';
  document.getElementById('c-voyage').value  = call?.voyage_number || '';
  document.getElementById('c-terminal').value= call?.terminal || '';
  document.getElementById('c-agent').value   = call?.agent_name || '';
  document.getElementById('call-modal').style.display = 'flex';
}
async function editCall(id) { const c=await api(`/maritime/port-calls/${id}`); if(c)openCallModal(c); }
function closeCallModal() { document.getElementById('call-modal').style.display='none'; currentCallId=null; }
async function saveCall() {
  const vesselRaw = document.getElementById('c-vessel').value.trim();
  const portRaw   = document.getElementById('c-port').value.trim();
  const body = {
    vessel_name: vesselRaw.startsWith('IMO') ? undefined : vesselRaw,
    imo_number:  vesselRaw.startsWith('IMO') ? vesselRaw : undefined,
    port_name:   portRaw.length===5||portRaw.includes(' ') ? undefined : portRaw,
    un_locode:   (portRaw.length===5||portRaw.includes(' ')) ? portRaw.replace(' ','').replace(/(.{2})/,'$1 ').trim().toUpperCase() : undefined,
    eta:         document.getElementById('c-eta').value || undefined,
    etd:         document.getElementById('c-etd').value || undefined,
    call_status: document.getElementById('c-status').value,
    cargo_type:  document.getElementById('c-cargo').value,
    cargo_quantity:parseFloat(document.getElementById('c-qty').value)||null,
    voyage_number:document.getElementById('c-voyage').value.trim(),
    terminal:    document.getElementById('c-terminal').value.trim(),
    agent_name:  document.getElementById('c-agent').value.trim(),
  };
  let res;
  if(currentCallId) res=await api(`/maritime/port-calls/${currentCallId}`,{method:'PUT',body:JSON.stringify(body)});
  else res=await api('/maritime/port-calls',{method:'POST',body:JSON.stringify(body)});
  if(res?.error){toast('❌ '+res.error,'error');return;}
  if(res?.validation_errors?.length) toast('⚠️ '+res.validation_errors[0],'warning');
  else toast(currentCallId?'Escale mise à jour':'Escale créée ✅');
  closeCallModal(); loadCalls(); loadMaritimeKPIs();
}
async function deleteCall(id) { if(!confirm('Supprimer cette escale ?'))return; await api(`/maritime/port-calls/${id}`,{method:'DELETE'}); toast('Escale supprimée','warning'); loadCalls(); }
