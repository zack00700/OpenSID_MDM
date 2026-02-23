/**
 * O.S MDM V2 — Application JavaScript
 * Modules : Auth, Dashboard, Import, Entités, Doublons, Golden Records,
 *            Connexions DB, Règles de fusion, Reporting BI, Export CSV
 */

const API = window.location.origin + '/api';
let TOKEN = localStorage.getItem('mdm_token') || '';
let currentUser = null, currentPage = 1;
let currentEntityId = null, currentDupId = null, currentDupData = null;
let currentConnId = null, currentRuleId = null;
let charts = {}, debounceTimer = null;

// ── UTILS ─────────────────────────────────────────────────────────────────
function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function fmtDate(d){if(!d)return'—';try{return new Date(d).toLocaleString('fr-FR',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});}catch{return d;}}
function toast(msg,type='success'){const t=document.createElement('div');const c={success:'#059669',error:'#dc2626',warning:'#d97706',info:'#1B5EA6'};t.style.cssText=`position:fixed;bottom:24px;right:24px;background:${c[type]||c.success};color:#fff;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,.18);transition:opacity .3s;max-width:360px;`;t.textContent=msg;document.body.appendChild(t);setTimeout(()=>{t.style.opacity='0';setTimeout(()=>t.remove(),300);},3500);}

async function api(path,opts={}){
  try{
    const res=await fetch(API+path,{headers:{'Content-Type':'application/json','Authorization':`Bearer ${TOKEN}`,...opts.headers},...opts});
    if(res.status===401){logout();return null;}
    const data=await res.json();
    if(!res.ok&&data.error){toast(data.error,'error');return null;}
    return data;
  }catch(e){toast('Erreur réseau — backend démarré ?','error');return null;}
}

// ── AUTH ──────────────────────────────────────────────────────────────────
window.onload=()=>{
  TOKEN?initApp():showLogin();
  // Wire form submit
  const form=document.getElementById('login-form');
  if(form) form.addEventListener('submit',e=>{e.preventDefault();login();});
};
function showLogin(){document.getElementById('login-page').style.display='flex';document.getElementById('app-page').style.display='none';}

async function login(){
  const email=document.getElementById('login-email').value.trim();
  const pw=document.getElementById('login-password').value;
  const btn=document.querySelector('#login-form button[type="submit"]');
  if(btn){btn.textContent='⏳';btn.disabled=true;}
  const res=await api('/auth/login',{method:'POST',body:JSON.stringify({email,password:pw})});
  if(btn){btn.textContent='Se connecter';btn.disabled=false;}
  if(!res?.token)return;
  TOKEN=res.token;localStorage.setItem('mdm_token',TOKEN);currentUser=res.user;initApp();
}
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&document.getElementById('login-page').style.display!=='none')login();});
function logout(){TOKEN='';localStorage.removeItem('mdm_token');document.getElementById('login-page').style.display='flex';document.getElementById('app-page').style.display='none';}

async function initApp(){
  const me=await api('/auth/me');if(!me)return;
  currentUser=me;
  document.getElementById('login-page').style.display='none';
  document.getElementById('app-page').style.display='flex';
  const unEl=document.getElementById('user-name');if(unEl)unEl.textContent=me.name||me.email;const ueEl=document.getElementById('user-email');if(ueEl)ueEl.textContent=me.email||'';
  showSection('dashboard');
}

// ── NAVIGATION ────────────────────────────────────────────────────────────
function showSection(name){
  document.querySelectorAll('.section').forEach(s=>s.style.display='none');
  document.querySelectorAll('.sidebar-link').forEach(l=>l.classList.remove('active'));
  const sec=document.getElementById('section-'+name);if(sec)sec.style.display='block';
  const link=document.querySelector(`.sidebar-link[data-section="${name}"]`);if(link)link.classList.add('active');
  switch(name){
    case 'dashboard':   loadDashboard();break;
    case 'connections': loadConnections();break;
    case 'import':      loadImportLogs();break;
    case 'entities':    loadEntities();break;
    case 'duplicates':  loadDuplicates();break;
    case 'golden':      loadGoldenRecords();break;
    case 'rules':       loadRules();break;
    case 'reporting':   loadReporting();break;
    case 'export':      break;
    case 'maritime-vessels': initMaritime().then(()=>{loadVessels();loadMaritimeKPIs();});break;
    case 'maritime-owners':  initMaritime().then(()=>loadOwners());break;
    case 'maritime-ports':   initMaritime().then(()=>loadPorts());break;
    case 'maritime-calls':   initMaritime().then(()=>loadCalls());break;
  }
}
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('.sidebar-link').forEach(link=>{link.addEventListener('click',()=>showSection(link.dataset.section));});
});

// ── DASHBOARD ─────────────────────────────────────────────────────────────
async function loadDashboard(){
  const data=await api('/dashboard/stats');if(!data)return;
  // Update individual KPI values
  const kmap={
    'd-entities':data.total_entities,'d-dups':data.total_duplicates,
    'd-golden':data.total_golden,'d-imports':data.total_imports,
    'd-conns':data.total_connections,'d-rules':data.total_rules
  };
  Object.entries(kmap).forEach(([id,val])=>{const el=document.getElementById(id);if(el)el.textContent=val??'—';});
  const rEl=document.getElementById('recent-entities');
  if(rEl&&data.recent_entities){rEl.innerHTML=data.recent_entities.length?`<table style="width:100%;border-collapse:collapse;">${data.recent_entities.map(e=>{let d={};try{d=typeof e.data==='string'?JSON.parse(e.data):e.data;}catch{}const name=d.nom||d.name||d.company||Object.values(d)[0]||'—';return`<tr><td class="table-td"><span style="font-family:monospace;font-size:10px;color:#1B5EA6;">${e.mdm_id||''}</span></td><td class="table-td" style="font-weight:600;">${esc(name)}</td><td class="table-td"><span class="badge" style="background:#e8f0fb;color:#1B5EA6;">${esc(e.source||'')}</span></td><td class="table-td" style="font-size:11px;color:#9ca3af;">${fmtDate(e.created_at)}</td></tr>`;}).join('')}</table>`:'<p style="color:#9ca3af;font-size:13px;">Aucune entité.</p>';}
  const sEl=document.getElementById('source-breakdown');
  if(sEl&&data.sources_breakdown?.length){const max=data.sources_breakdown[0]?.cnt||1;sEl.innerHTML=data.sources_breakdown.map(s=>`<div style="margin-bottom:10px;"><div style="display:flex;justify-content:space-between;margin-bottom:3px;"><span style="font-size:12px;color:#374151;font-weight:600;">${esc(s.source||'—')}</span><span style="font-size:12px;color:#6b7280;">${s.cnt}</span></div><div style="background:#f3f4f6;border-radius:99px;height:6px;"><div style="background:#1B5EA6;border-radius:99px;height:6px;width:${Math.round(s.cnt/max*100)}%;"></div></div></div>`).join('');}
}

// ── CONNECTIONS ────────────────────────────────────────────────────────────
async function loadConnections(){
  const conns=await api('/connections');const container=document.getElementById('connections-list');
  if(!conns?.length){container.innerHTML='<div class="card" style="text-align:center;color:#9ca3af;padding:40px;"><p style="font-size:32px;">🔌</p><p>Aucune connexion. Cliquez "+ Nouvelle connexion".</p></div>';return;}
  const icons={postgresql:'🐘',mysql:'🐬',mariadb:'🐬',mssql:'🪟',oracle:'🔶',sqlite:'💾'};
  const ss=s=>s==='ok'?'background:#d1fae5;color:#065f46;':s==='error'?'background:#fee2e2;color:#991b1b;':'background:#f3f4f6;color:#6b7280;';
  const sl=s=>s==='ok'?'✅ Connecté':s==='error'?'❌ Erreur':'⏳ Non testé';
  container.innerHTML=`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;">${conns.map(c=>`<div class="card" style="padding:16px;"><div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;"><span style="font-size:28px;">${icons[c.db_type]||'🗄️'}</span><div><p style="font-size:14px;font-weight:700;margin:0;">${esc(c.name)}</p><p style="font-size:11px;color:#9ca3af;margin:0;">${c.db_type?.toUpperCase()} · ${esc(c.host||'—')}:${c.port||''}</p></div><span class="badge" style="margin-left:auto;${ss(c.status)}">${sl(c.status)}</span></div><p style="font-size:12px;color:#6b7280;margin:0 0 10px;">Base : <b>${esc(c.database_name||'—')}</b> · User : ${esc(c.username||'—')}</p><div style="display:flex;gap:6px;flex-wrap:wrap;"><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick="testConn('${c.id}')">🔌 Tester</button><button class="btn btn-primary" style="font-size:11px;padding:4px 10px;" onclick="openDBImport('${c.id}','${esc(c.name)}')">📥 Importer</button><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick='editConn(${JSON.stringify(c).replace(/"/g,"&quot;")})'>✏️</button><button class="btn btn-danger" style="font-size:11px;padding:4px 10px;" onclick="deleteConn('${c.id}')">🗑️</button></div></div>`).join('')}</div>`;
}
function openConnModal(conn=null){currentConnId=conn?.id||null;document.getElementById('conn-modal-title').textContent=conn?'Modifier connexion':'Nouvelle connexion';['name','db_type','host','port','database_name','username'].forEach((f,i)=>{const ids=['c-name','c-type','c-host','c-port','c-db','c-user'];const el=document.getElementById(ids[i]);if(el)el.value=conn?.[f]||'';});document.getElementById('c-pass').value='';document.getElementById('conn-modal').style.display='flex';}
function editConn(conn){openConnModal(conn);}
function closeConnModal(){document.getElementById('conn-modal').style.display='none';currentConnId=null;}
async function saveConn(){const body={name:document.getElementById('c-name').value.trim(),db_type:document.getElementById('c-type').value,host:document.getElementById('c-host').value.trim(),port:parseInt(document.getElementById('c-port').value)||null,database_name:document.getElementById('c-db').value.trim(),username:document.getElementById('c-user').value.trim(),password:document.getElementById('c-pass').value};if(!body.name){toast('Nom requis','error');return;}if(currentConnId)await api(`/connections/${currentConnId}`,{method:'PUT',body:JSON.stringify(body)});else await api('/connections',{method:'POST',body:JSON.stringify(body)});toast(currentConnId?'Mise à jour':'Connexion créée');closeConnModal();loadConnections();}
async function testCurrentConn(){await saveConn();if(currentConnId)await testConn(currentConnId);}
async function testConn(id){toast('Test…','info');const res=await api(`/connections/${id}/test`,{method:'POST'});if(res)toast(res.status==='ok'?'✅ Connexion réussie !':'❌ '+(res.message||'Échec'),res.status==='ok'?'success':'error');loadConnections();}
async function deleteConn(id){if(!confirm('Supprimer ?'))return;await api(`/connections/${id}`,{method:'DELETE'});toast('Supprimée','warning');loadConnections();}
async function openDBImport(connId,connName){const panel=document.getElementById('db-import-panel');if(!panel)return;panel.style.display='block';panel.dataset.connId=connId;document.getElementById('db-import-table').innerHTML='<option>Chargement…</option>';document.getElementById('db-preview').innerHTML='';const res=await api(`/connections/${connId}/tables`);const sel=document.getElementById('db-import-table');if(res?.tables?.length)sel.innerHTML=res.tables.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join('');else sel.innerHTML='<option value="">— Aucune table —</option>';}
async function previewTable(){const connId=document.getElementById('db-import-panel').dataset.connId;const table=document.getElementById('db-import-table').value;const sql=document.getElementById('db-import-sql').value.trim();const res=await api(`/connections/${connId}/preview`,{method:'POST',body:JSON.stringify({table,sql:sql||null})});if(!res?.rows?.length){document.getElementById('db-preview').innerHTML='<p style="color:#9ca3af;font-size:12px;">Aucun résultat.</p>';return;}const cols=res.columns||Object.keys(res.rows[0]);document.getElementById('db-preview').innerHTML=`<div style="overflow-x:auto;margin-top:10px;max-height:200px;"><table style="width:100%;border-collapse:collapse;font-size:11px;"><thead><tr>${cols.map(c=>`<th class="table-th">${esc(c)}</th>`).join('')}</tr></thead><tbody>${res.rows.map(r=>`<tr>${cols.map(c=>`<td class="table-td">${esc(String(r[c]??''))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
async function importFromDB(){const connId=document.getElementById('db-import-panel').dataset.connId;const table=document.getElementById('db-import-table').value;const source=document.getElementById('db-import-label').value.trim()||table;const sql=document.getElementById('db-import-sql').value.trim();toast('Import…','info');const res=await api(`/connections/${connId}/import`,{method:'POST',body:JSON.stringify({table,source_label:source,sql:sql||null})});if(res){toast(`✅ ${res.imported} lignes importées`);document.getElementById('db-import-panel').style.display='none';}}

// ── IMPORT ─────────────────────────────────────────────────────────────────
let dragFile=null;
function setupDropzone(){const dz=document.getElementById('drop-zone');if(!dz||dz._ready)return;dz._ready=true;dz.addEventListener('dragover',e=>{e.preventDefault();dz.style.borderColor='#1B5EA6';});dz.addEventListener('dragleave',()=>dz.style.borderColor='#e5e7eb');dz.addEventListener('drop',e=>{e.preventDefault();dz.style.borderColor='#e5e7eb';handleFile(e.dataTransfer.files[0]);});document.getElementById('file-input').addEventListener('change',e=>handleFile(e.target.files[0]));}
function handleFile(file){if(!file)return;dragFile=file;document.getElementById('selected-filename').textContent=`📄 ${file.name} (${(file.size/1024).toFixed(1)} KB)`;document.getElementById('file-preview').style.display='block';document.getElementById('drop-zone').style.display='none';}
function clearFile(){dragFile=null;document.getElementById('drop-zone').style.display='block';document.getElementById('file-preview').style.display='none';document.getElementById('file-input').value='';}
async function uploadFile(){if(!dragFile){toast('Choisissez un fichier','error');return;}const source=document.getElementById('import-source-label').value.trim()||dragFile.name;const fd=new FormData();fd.append('file',dragFile);fd.append('source_label',source);const btn=document.getElementById('upload-btn');btn.textContent='⏳ Import…';btn.disabled=true;try{const res=await fetch(`${API}/import/csv`,{method:'POST',headers:{'Authorization':`Bearer ${TOKEN}`},body:fd});const data=await res.json();btn.textContent='📤 Importer';btn.disabled=false;if(data.imported!==undefined){toast(`✅ ${data.imported} lignes importées`);clearFile();loadImportLogs();loadDashboard();}else toast(data.error||'Erreur','error');}catch{btn.textContent='📤 Importer';btn.disabled=false;toast('Erreur upload','error');}}
async function loadImportLogs(){setupDropzone();const logs=await api('/import/logs');const el=document.getElementById('import-logs-list');if(!el)return;if(!logs?.length){el.innerHTML='<p style="color:#9ca3af;font-size:13px;">Aucun import.</p>';return;}el.innerHTML=`<table style="width:100%;border-collapse:collapse;"><thead><tr><th class="table-th">Fichier</th><th class="table-th">Source</th><th class="table-th">Total</th><th class="table-th">Importés</th><th class="table-th">Erreurs</th><th class="table-th">Statut</th><th class="table-th">Date</th></tr></thead><tbody>${logs.map(l=>{const sc=l.status==='done'?'background:#d1fae5;color:#065f46;':l.status==='error'?'background:#fee2e2;color:#991b1b;':'background:#fef3c7;color:#92400e;';return`<tr><td class="table-td" style="font-weight:600;">${esc(l.filename)}</td><td class="table-td"><span class="badge" style="background:#e8f0fb;color:#1B5EA6;">${esc(l.source_label||'—')}</span></td><td class="table-td">${l.total_rows||0}</td><td class="table-td" style="color:#059669;font-weight:600;">${l.imported||0}</td><td class="table-td" style="color:#dc2626;">${l.errors||0}</td><td class="table-td"><span class="badge" style="${sc}">${l.status}</span></td><td class="table-td" style="font-size:11px;color:#9ca3af;">${fmtDate(l.created_at)}</td></tr>`;}).join('')}</tbody></table>`;}

// ── ENTITIES ───────────────────────────────────────────────────────────────
async function loadEntities(){
  const srch=document.getElementById('entity-search')?.value.trim()||'';const src=document.getElementById('entity-source-filter')?.value.trim()||'';
  const params=new URLSearchParams({page:currentPage,per_page:20});if(srch)params.set('search',srch);if(src)params.set('source',src);
  const data=await api(`/entities?${params}`);if(!data)return;
  const container=document.getElementById('entities-table');
  if(!data.entities.length){container.innerHTML='<p style="color:#9ca3af;text-align:center;padding:24px;font-size:13px;">Aucune entité.</p>';return;}
  const allKeys=[...new Set(data.entities.flatMap(e=>Object.keys(e.data||{})))].slice(0,5);
  container.innerHTML=`<table style="width:100%;border-collapse:collapse;"><thead><tr><th class="table-th">MDM ID</th>${allKeys.map(k=>`<th class="table-th">${esc(k)}</th>`).join('')}<th class="table-th">Source</th><th class="table-th">Créé</th><th class="table-th">Actions</th></tr></thead><tbody>${data.entities.map(e=>`<tr><td class="table-td"><span style="font-family:monospace;font-size:10px;color:#1B5EA6;">${e.mdm_id}</span></td>${allKeys.map(k=>`<td class="table-td" style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(String(e.data?.[k]??'—'))}</td>`).join('')}<td class="table-td"><span class="badge" style="background:#e8f0fb;color:#1B5EA6;">${esc(e.source||'—')}</span></td><td class="table-td" style="font-size:11px;color:#9ca3af;">${fmtDate(e.created_at)}</td><td class="table-td"><div style="display:flex;gap:4px;"><button class="btn btn-secondary" style="padding:3px 8px;font-size:11px;" onclick="editEntity('${e.id}')">✏️</button><button class="btn btn-danger" style="padding:3px 8px;font-size:11px;" onclick="deleteEntity('${e.id}')">🗑️</button></div></td></tr>`).join('')}</tbody></table>`;
  document.getElementById('entity-count').textContent=`${data.total} entité(s)`;
  document.getElementById('page-info').textContent=`Page ${currentPage}`;
  document.getElementById('prev-btn').disabled=currentPage<=1;
  document.getElementById('next-btn').disabled=(currentPage*20)>=data.total;
}
function debounceSearch(){clearTimeout(debounceTimer);currentPage=1;debounceTimer=setTimeout(loadEntities,400);}
function prevPage(){if(currentPage>1){currentPage--;loadEntities();}}
function nextPage(){currentPage++;loadEntities();}
function openCreateEntity(){openEntityModal(null);}
async function editEntity(id){const e=await api(`/entities/${id}`);if(e)openEntityModal(e);}
function openEntityModal(entity=null){currentEntityId=entity?.id||null;document.getElementById('entity-modal-title').textContent=entity?'Modifier entité':'Nouvelle entité';const container=document.getElementById('entity-fields-container');container.innerHTML='';const data=entity?.data||{};const fields=Object.keys(data).length?Object.entries(data):[['','']];fields.forEach(([k,v])=>addEntityField(k,v));document.getElementById('entity-modal').style.display='flex';}
function addEntityField(key='',value=''){const div=document.createElement('div');div.style.cssText='display:flex;gap:8px;margin-bottom:8px;align-items:center;';div.innerHTML=`<input class="input" placeholder="Champ" value="${esc(key)}" style="flex:1;"/><input class="input" placeholder="Valeur" value="${esc(String(value))}" style="flex:2;"/><button onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:#dc2626;font-size:16px;padding:4px;">✕</button>`;document.getElementById('entity-fields-container').appendChild(div);}
function closeEntityModal(){document.getElementById('entity-modal').style.display='none';currentEntityId=null;}
async function saveEntity(){const data={};document.querySelectorAll('#entity-fields-container > div').forEach(d=>{const [k,v]=d.querySelectorAll('input');if(k.value.trim())data[k.value.trim()]=v.value;});if(currentEntityId)await api(`/entities/${currentEntityId}`,{method:'PUT',body:JSON.stringify({data})});else await api('/entities',{method:'POST',body:JSON.stringify({data})});toast(currentEntityId?'Mis à jour':'Créé');closeEntityModal();loadEntities();}
async function deleteEntity(id){if(!confirm('Supprimer ?'))return;await api(`/entities/${id}`,{method:'DELETE'});toast('Supprimée','warning');loadEntities();}

// ── DUPLICATES ─────────────────────────────────────────────────────────────
function toggleFuzzy(){document.getElementById('fuzzy-threshold-wrap').style.display=document.getElementById('dup-method').value==='fuzzy'?'block':'none';}
async function detectDuplicates(){const method=document.getElementById('dup-method').value;const fields=document.getElementById('dup-fields').value.split(',').map(s=>s.trim()).filter(Boolean);const threshold=parseInt(document.getElementById('dup-threshold')?.value)||80;const btn=document.getElementById('detect-btn');btn.textContent='⏳…';btn.disabled=true;const res=await api('/duplicates/detect',{method:'POST',body:JSON.stringify({method,fields,threshold})});btn.textContent='🔍 Détecter';btn.disabled=false;if(!res)return;toast(`${res.found} doublon(s)`,res.found>0?'warning':'success');loadDuplicates();}
async function loadDuplicates(){
  const dups=await api('/duplicates?status=pending');const badge=document.getElementById('dup-badge');
  if(dups?.length){badge.textContent=dups.length;badge.style.display='inline';}else badge.style.display='none';
  const container=document.getElementById('duplicates-list');
  if(!dups?.length){container.innerHTML='<div class="card" style="text-align:center;color:#9ca3af;padding:40px;">✅ Aucun doublon en attente.</div>';return;}
  const keys=[...new Set(dups.flatMap(d=>[...Object.keys(d.entity1?.data||{}),...Object.keys(d.entity2?.data||{})]))].slice(0,5);
  container.innerHTML=dups.map(d=>{const sc=d.score>=.9?'#dc2626':d.score>=.7?'#d97706':'#6b7280';const safeD=JSON.stringify(d).replace(/</g,'\\u003c').replace(/>/g,'\\u003e').replace(/'/g,"\\u0027");return`<div class="card" style="margin-bottom:14px;"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;"><div style="display:flex;gap:8px;"><span class="badge" style="background:#fee2e2;color:${sc};">Score ${Math.round(d.score*100)}%</span><span class="badge" style="background:#f3f4f6;color:#6b7280;">${d.method}</span></div><div style="display:flex;gap:6px;"><button class="btn btn-success" style="font-size:12px;" onclick='openMerge(${safeD})'>⚡ Fusionner</button><button class="btn btn-secondary" style="font-size:12px;" onclick="ignoredup('${d.id}')">Ignorer</button></div></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">${[d.entity1,d.entity2].map((e,i)=>`<div style="background:#f9fafb;border-radius:10px;padding:14px;"><p style="font-size:11px;font-weight:700;color:#1B5EA6;margin:0 0 8px;">Entité ${i+1} — <span style="font-family:monospace;">${e?.mdm_id||'?'}</span></p>${keys.map(k=>`<div style="display:flex;gap:8px;margin-bottom:4px;"><span style="font-size:11px;color:#9ca3af;min-width:70px;">${esc(k)}</span><span style="font-size:12px;color:#374151;font-weight:500;">${esc(String(e?.data?.[k]??'—'))}</span></div>`).join('')}</div>`).join('')}</div></div>`;}).join('');
}
async function ignoredup(id){await api('/duplicates/ignore',{method:'POST',body:JSON.stringify({duplicate_id:id})});toast('Ignoré','info');loadDuplicates();}

// ── MERGE MODAL ────────────────────────────────────────────────────────────
function openMerge(dup){currentDupId=dup.id;currentDupData=dup;const e1=dup.entity1?.data||{};const e2=dup.entity2?.data||{};const allKeys=[...new Set([...Object.keys(e1),...Object.keys(e2)])];document.getElementById('merge-fields').innerHTML=allKeys.map(k=>{const v1=e1[k]??'';const v2=e2[k]??'';return`<div style="border:1px solid #f3f4f6;border-radius:10px;padding:12px;"><p style="font-size:12px;font-weight:700;color:#374151;margin:0 0 8px;">${esc(k)}</p><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;"><label style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px;cursor:pointer;"><input type="radio" name="f_${esc(k)}" value="${esc(String(v1))}" class="merge-radio" data-field="${esc(k)}" checked/><span style="font-size:12px;">${esc(String(v1))||'&lt;vide&gt;'}</span></label><label style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px;cursor:pointer;"><input type="radio" name="f_${esc(k)}" value="${esc(String(v2))}" class="merge-radio" data-field="${esc(k)}"/><span style="font-size:12px;">${esc(String(v2))||'&lt;vide&gt;'}</span></label></div></div>`;}).join('');document.getElementById('merge-modal').style.display='flex';}
function closeMergeModal(){document.getElementById('merge-modal').style.display='none';currentDupId=null;currentDupData=null;}
async function applyRulesPreview(){if(!currentDupData)return;const e1={...(currentDupData.entity1?.data||{}),_source:currentDupData.entity1?.source};const e2={...(currentDupData.entity2?.data||{}),_source:currentDupData.entity2?.source};const res=await api('/fusion-rules/preview',{method:'POST',body:JSON.stringify({entity1:e1,entity2:e2})});if(!res?.applied)return;res.applied.forEach(a=>{document.querySelectorAll(`.merge-radio[data-field="${a.field}"]`).forEach(r=>{r.checked=(r.value===String(a.chosen??''));});});toast(`Règles appliquées (${res.applied.length} champs)`,'info');}
async function confirmMerge(){const mergedData={};document.querySelectorAll('.merge-radio:checked').forEach(r=>{mergedData[r.dataset.field]=r.value;});const res=await api('/golden-records/merge',{method:'POST',body:JSON.stringify({entity_ids:[currentDupData.entity1.id,currentDupData.entity2.id],merged_data:mergedData,duplicate_id:currentDupId})});if(!res)return;toast(`Golden Record créé : ${res.mdm_id}`,'success');closeMergeModal();loadDuplicates();loadDashboard();}

// ── GOLDEN RECORDS ─────────────────────────────────────────────────────────
async function loadGoldenRecords(){const records=await api('/golden-records');const container=document.getElementById('golden-list');if(!records?.length){container.innerHTML='<p style="color:#9ca3af;font-size:13px;">Aucun Golden Record.</p>';return;}const allKeys=[...new Set(records.flatMap(r=>Object.keys(r.data||{})))].slice(0,6);container.innerHTML=`<table style="width:100%;border-collapse:collapse;"><thead><tr><th class="table-th">MDM ID</th>${allKeys.map(k=>`<th class="table-th">${esc(k)}</th>`).join('')}<th class="table-th">Sources</th><th class="table-th">Créé</th></tr></thead><tbody>${records.map(r=>`<tr><td class="table-td"><span style="font-family:monospace;font-size:11px;color:#059669;font-weight:700;">${r.mdm_id}</span></td>${allKeys.map(k=>`<td class="table-td" style="max-width:140px;overflow:hidden;text-overflow:ellipsis;">${esc(String(r.data?.[k]??'—'))}</td>`).join('')}<td class="table-td" style="color:#9ca3af;">${Array.isArray(r.source_ids)?r.source_ids.length+' entités':'—'}</td><td class="table-td" style="color:#9ca3af;font-size:11px;">${fmtDate(r.created_at)}</td></tr>`).join('')}</tbody></table>`;}

// ── FUSION RULES ───────────────────────────────────────────────────────────
async function loadRules(){const rules=await api('/fusion-rules');const container=document.getElementById('rules-list');if(!rules?.length){container.innerHTML='<div class="card" style="text-align:center;color:#9ca3af;padding:40px;">Aucune règle de fusion.</div>';return;}const sl={'most_complete':'Plus complet','non_empty':'Non vide','longest':'Plus long','source_priority':'Priorité source','always_entity1':'Toujours E1','always_entity2':'Toujours E2'};container.innerHTML=`<div style="display:flex;flex-direction:column;gap:10px;">${rules.map(r=>{let prio=[];try{prio=JSON.parse(r.source_priority||'[]');}catch{}const safe=JSON.stringify(r).replace(/</g,'\\u003c').replace(/>/g,'\\u003e').replace(/'/g,"\\u0027");return`<div class="card" style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;"><div style="display:flex;align-items:center;gap:14px;flex:1;"><div style="width:36px;height:36px;border-radius:8px;background:${r.active?'#e8f0fb':'#f3f4f6'};display:flex;align-items:center;justify-content:center;font-size:16px;">${r.active?'⚡':'💤'}</div><div><p style="font-size:14px;font-weight:700;color:#111827;margin:0;">${esc(r.name)}</p><p style="font-size:12px;color:#9ca3af;margin:2px 0 0;">Champ: <b>${esc(r.field)}</b> · <span class="rule-strategy-tag">${sl[r.strategy]||r.strategy}</span>${prio.length?' · Priorité: '+prio.join(' > '):''}</p></div></div><div style="display:flex;gap:6px;"><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px;" onclick='editRule(${safe})'>✏️</button><button class="btn btn-danger" style="font-size:11px;padding:4px 10px;" onclick="deleteRule('${r.id}')">🗑️</button></div></div>`;}).join('')}</div>`;}
function openRuleModal(rule=null){currentRuleId=rule?.id||null;document.getElementById('rule-modal-title').textContent=rule?'Modifier règle':'Nouvelle règle';document.getElementById('r-name').value=rule?.name||'';document.getElementById('r-field').value=rule?.field||'';document.getElementById('r-strategy').value=rule?.strategy||'most_complete';let prio=[];try{prio=JSON.parse(rule?.source_priority||'[]');}catch{}document.getElementById('r-priority').value=prio.join(', ');document.getElementById('r-active').value=rule?.active!==undefined?String(rule.active):'1';toggleSourcePriority();document.getElementById('rule-modal').style.display='flex';}
function editRule(rule){openRuleModal(rule);}
function closeRuleModal(){document.getElementById('rule-modal').style.display='none';currentRuleId=null;}
function toggleSourcePriority(){document.getElementById('source-priority-wrap').style.display=document.getElementById('r-strategy').value==='source_priority'?'block':'none';}
async function saveRule(){const prio=document.getElementById('r-priority').value.split(',').map(s=>s.trim()).filter(Boolean);const body={name:document.getElementById('r-name').value.trim(),field:document.getElementById('r-field').value.trim(),strategy:document.getElementById('r-strategy').value,source_priority:prio,active:parseInt(document.getElementById('r-active').value)};if(!body.name||!body.field){toast('Nom et champ requis','error');return;}if(currentRuleId)await api(`/fusion-rules/${currentRuleId}`,{method:'PUT',body:JSON.stringify(body)});else await api('/fusion-rules',{method:'POST',body:JSON.stringify(body)});toast(currentRuleId?'Mise à jour':'Règle créée');closeRuleModal();loadRules();}
async function deleteRule(id){if(!confirm('Supprimer ?'))return;await api(`/fusion-rules/${id}`,{method:'DELETE'});toast('Supprimée','warning');loadRules();}

// ── REPORTING ──────────────────────────────────────────────────────────────
let reportData=null;
async function loadReporting(){reportData=await api('/reporting/overview');if(!reportData)return;renderBIKPIs(reportData.kpis);renderCharts(reportData);const fields=await api('/reporting/fields');if(fields?.fields){['pivot-row','pivot-col','pivot-value'].forEach(id=>{const sel=document.getElementById(id);if(!sel)return;const hasNone=id!=='pivot-row';sel.innerHTML=hasNone?'<option value="">— Aucun —</option>':'';fields.fields.forEach(f=>{const o=document.createElement('option');o.value=f;o.textContent=f;sel.appendChild(o);});});}}
function renderBIKPIs(kpis){const el=document.getElementById('bi-kpis');if(!el)return;const items=[{label:'Entités actives',value:kpis.total_entities,color:'#1B5EA6'},{label:'Lignes importées',value:(kpis.total_rows_imported||0).toLocaleString(),color:'#374151'},{label:'Taux doublons',value:kpis.duplicate_rate+'%',color:'#dc2626'},{label:'Golden Records',value:kpis.total_golden_records,color:'#059669'},{label:'Couverture GR',value:kpis.golden_coverage+'%',color:'#7c3aed'},{label:'Doublons résolus',value:kpis.total_duplicates_resolved,color:'#d97706'},{label:'Ignorés',value:kpis.total_duplicates_ignored,color:'#6b7280'},{label:'Imports',value:kpis.total_imports,color:'#1B5EA6'}];el.innerHTML=items.map(i=>`<div class="kpi-card" style="border-left:3px solid ${i.color};"><p style="font-size:11px;color:#6b7280;font-weight:600;margin:0 0 4px;">${i.label}</p><p style="font-size:24px;font-weight:800;color:${i.color};margin:0;">${i.value}</p></div>`).join('');}
function renderCharts(data){const blue='#1B5EA6',green='#059669',red='#ef4444';const mk=(id,type,labels,datasets)=>{if(charts[id])charts[id].destroy();const ctx=document.getElementById(id);if(!ctx)return;charts[id]=new Chart(ctx,{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:type==='doughnut',position:'bottom',labels:{boxWidth:10,font:{size:11}}}},scales:type!=='doughnut'?{x:{ticks:{font:{size:10}}},y:{ticks:{font:{size:10}},beginAtZero:true}}:{}}});};mk('chart-imports','bar',data.import_trend.map(r=>r.day),[{label:'Lignes',data:data.import_trend.map(r=>r.rows),backgroundColor:blue+'33',borderColor:blue,borderWidth:2,borderRadius:4}]);mk('chart-sources','doughnut',data.by_source.slice(0,8).map(s=>s.source||'—'),[{data:data.by_source.slice(0,8).map(s=>s.count),backgroundColor:['#1B5EA6','#3b82f6','#60a5fa','#93c5fd','#059669','#34d399','#f59e0b','#ef4444'],borderWidth:2}]);mk('chart-dups','line',data.dup_trend.map(r=>r.day),[{label:'Doublons',data:data.dup_trend.map(r=>r.found),borderColor:red,backgroundColor:red+'22',fill:true,tension:.4,pointRadius:3}]);mk('chart-gr','line',data.gr_trend.map(r=>r.day),[{label:'GR créés',data:data.gr_trend.map(r=>r.created),borderColor:green,backgroundColor:green+'22',fill:true,tension:.4,pointRadius:3}]);}
function switchReportTab(tab,btn){document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');['overview','pivot','pdf'].forEach(t=>{const el=document.getElementById(`report-${t}`);if(el)el.style.display=t===tab?'block':'none';});if(tab==='overview'&&reportData)renderCharts(reportData);}
async function runPivot(){const row_field=document.getElementById('pivot-row').value;const col_field=document.getElementById('pivot-col').value||null;const aggregation=document.getElementById('pivot-agg').value;const value_field=document.getElementById('pivot-value').value||null;if(!row_field){toast('Champ ligne requis','error');return;}const res=await api('/reporting/pivot',{method:'POST',body:JSON.stringify({row_field,col_field,aggregation,value_field})});const container=document.getElementById('pivot-result');if(res?.error){container.innerHTML=`<p style="color:#dc2626;font-size:13px;">❌ ${res.error}</p>`;return;}if(!res?.pivot?.length){container.innerHTML='<p style="color:#9ca3af;">Aucun résultat.</p>';return;}const cols=res.columns;container.innerHTML=`<p style="font-size:12px;color:#9ca3af;margin:0 0 10px;">${res.pivot.length} ligne(s)</p><div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;"><thead><tr>${cols.map(c=>`<th class="table-th">${esc(String(c))}</th>`).join('')}</tr></thead><tbody>${res.pivot.map(row=>`<tr>${cols.map(c=>`<td class="table-td">${esc(String(row[c]??''))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
async function exportPDF(){const data=await api('/reporting/export-pdf-data');if(!data)return;const html=`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>O.S MDM Rapport</title><style>body{font-family:system-ui;padding:30px;color:#111;max-width:900px;margin:0 auto;}h1{color:#1B5EA6;}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px;}.kpi{background:#f9fafb;border-radius:8px;padding:14px;border-left:3px solid #1B5EA6;}.kpi .val{font-size:24px;font-weight:800;color:#1B5EA6;margin:0;}.kpi .lbl{font-size:11px;color:#9ca3af;margin:0 0 4px;}table{width:100%;border-collapse:collapse;font-size:13px;margin-top:14px;}th{background:#f3f4f6;padding:8px 12px;text-align:left;font-size:11px;font-weight:700;color:#6b7280;}td{padding:8px 12px;border-top:1px solid #f3f4f6;}.print-btn{background:#1B5EA6;color:#fff;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:14px;margin-top:20px;}@media print{.print-btn{display:none;}}</style></head><body><h1>O.S MDM V2 — Rapport analytique</h1><p style="color:#9ca3af;">${data.generated_at}</p><div class="grid"><div class="kpi"><p class="lbl">Entités actives</p><p class="val">${data.kpis.total_entities}</p></div><div class="kpi"><p class="lbl">Golden Records</p><p class="val">${data.kpis.total_golden}</p></div><div class="kpi"><p class="lbl">Doublons</p><p class="val">${data.kpis.total_duplicates}</p></div><div class="kpi"><p class="lbl">Imports</p><p class="val">${data.kpis.total_imports}</p></div></div><h2>Répartition par source</h2><table><thead><tr><th>Source</th><th>Entités</th></tr></thead><tbody>${(data.by_source||[]).map(s=>`<tr><td>${esc(s.source||'—')}</td><td>${s.count}</td></tr>`).join('')}</tbody></table><h2>Imports 30j</h2><table><thead><tr><th>Date</th><th>Lignes</th></tr></thead><tbody>${(data.import_trend||[]).map(r=>`<tr><td>${r.day}</td><td>${r.rows}</td></tr>`).join('')}</tbody></table><button class="print-btn" onclick="window.print()">🖨️ Imprimer / PDF</button></body></html>`;const win=window.open('','_blank');win.document.write(html);win.document.close();setTimeout(()=>win.print(),600);toast('Rapport ouvert');}

// ── EXPORT ─────────────────────────────────────────────────────────────────
async function exportEntities(){const source=document.getElementById('export-source')?.value||'';const merged=document.getElementById('export-merged')?.checked||false;const params=new URLSearchParams();if(source)params.set('source',source);if(merged)params.set('include_merged','true');const res=await fetch(`${API}/export/csv?${params}`,{headers:{'Authorization':`Bearer ${TOKEN}`}});if(!res.ok){toast('Aucune entité','error');return;}await dlBlob(res);toast('Export téléchargé ✅');}
async function exportGolden(){const res=await fetch(`${API}/export/golden-records/csv`,{headers:{'Authorization':`Bearer ${TOKEN}`}});if(!res.ok){toast('Aucun Golden Record','error');return;}await dlBlob(res);toast('Golden Records exportés ✅');}
async function dlBlob(res){const blob=await res.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');const cd=res.headers.get('Content-Disposition')||'';const m=cd.match(/filename=(.+)/);a.href=url;a.download=m?m[1]:'export.csv';a.click();URL.revokeObjectURL(url);}
