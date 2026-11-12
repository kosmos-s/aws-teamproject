'use strict';
// Member management built for dozens–hundreds of accounts: summary, search, filters, paging.
const ROLE_LABEL = {admin:'관리자', member:'멤버', viewer:'게스트(조회)'};
const admin = { users: [], page: 0, perPage: 15 };

function summaryCard(label, value, hint) {
  const card = document.createElement('article');
  const p = document.createElement('p'); p.textContent = label;
  const s = document.createElement('strong'); s.textContent = String(value);
  const small = document.createElement('small'); small.textContent = hint || '';
  card.append(p, s, small); return card;
}

function renderSummary() {
  const u = admin.users, box = $('member-summary'); box.replaceChildren();
  const count = f => u.filter(f).length;
  box.append(
    summaryCard('전체 멤버', u.length, `관리자 ${count(x => x.role === 'admin')} · 멤버 ${count(x => x.role === 'member')} · 게스트 ${count(x => x.role === 'viewer')}`),
    summaryCard('지금 접속 중', count(x => x.sessions > 0 && x.active), '로그인이 유지된 계정'),
    summaryCard('접속 차단', count(x => !x.active), `첫 로그인 전 ${count(x => x.must_change)}명`),
  );
}

function filteredUsers() {
  const q = $('member-search').value.trim().toLowerCase(), role = $('member-role').value, status = $('member-status').value;
  return admin.users.filter(u => (!q || u.username.toLowerCase().includes(q)) && (!role || u.role === role) &&
    (!status || (status === 'online' && u.sessions > 0 && u.active) || (status === 'active' && u.active) || (status === 'blocked' && !u.active) || (status === 'pending' && u.must_change)));
}

function memberRow(user) {
  const row = document.createElement('div'); row.className = 'member-row' + (user.active ? '' : ' blocked');
  const who = document.createElement('div'); who.className = 'who';
  const name = document.createElement('strong'); name.textContent = user.username + (user.username === currentUser.username ? ' (나)' : '');
  const state = document.createElement('small');
  state.textContent = !user.active ? '차단됨' : user.sessions > 0 ? `● 접속 중 (${user.sessions})` : '○ 오프라인';
  const last = document.createElement('small');
  last.textContent = user.last_login ? `마지막 로그인 ${new Date(user.last_login).toLocaleString()}` : '로그인 기록 없음';
  who.append(name, state, last);
  if (user.must_change) { const w = document.createElement('small'); w.className = 'badge-warn'; w.textContent = '첫 로그인 전 (비밀번호 변경 대기)'; who.append(w); }
  if (user.totp) { const k = document.createElement('small'); k.className = 'ok-text'; k.textContent = '🔐 2단계 인증 사용 중'; who.append(k); }
  if (user.groups?.length) { const g = document.createElement('div'); for (const n of user.groups) { const c = document.createElement('span'); c.className = 'chip'; c.textContent = n; g.append(c); } who.append(g); }

  const role = document.createElement('select'); role.setAttribute('aria-label', user.username + ' 역할');
  for (const [value, label] of Object.entries(ROLE_LABEL)) { const o = document.createElement('option'); o.value = value; o.textContent = label; role.append(o); }
  role.value = user.role;
  const allow = document.createElement('label'); const active = document.createElement('input');
  active.type = 'checkbox'; active.checked = user.active; allow.append(active, document.createTextNode('접속 허용'));
  const apply = document.createElement('button'); apply.textContent = '적용'; apply.title = '역할·접속 허용을 적용하고 기존 접속을 끊습니다';
  const access = document.createElement('div'); access.className = 'access'; access.append(role, allow, apply);
  row.append(who, access);

  if (user.username === currentUser.username) {
    role.disabled = active.disabled = apply.disabled = true;
    const note = document.createElement('small'); note.className = 'self-note'; note.textContent = '자기 계정은 \'내 계정\' 메뉴에서 관리합니다.'; row.append(note);
    return row;
  }
  apply.addEventListener('click', async () => {
    apply.disabled = true;
    try { await api(`/api/admin/users/${user.id}`, {method:'PATCH', body:{active:active.checked, role:role.value}}); await refreshAdmin(); message(`${user.username}: 권한을 적용하고 기존 접속을 끊었습니다.`); }
    catch (error) { message(error.message); apply.disabled = false; }
  });
  const pw = document.createElement('input'); pw.type = 'password'; pw.placeholder = '새 비밀번호 (8자+)'; pw.autocomplete = 'new-password'; pw.maxLength = 256; pw.minLength = 8;
  pw.setAttribute('aria-label', user.username + ' 새 비밀번호');
  const reset = document.createElement('button'); reset.textContent = '재설정'; reset.className = 'secondary';
  reset.addEventListener('click', async () => {
    if (pw.value.length < 8) { message('새 비밀번호는 8자 이상이어야 합니다.'); pw.focus(); return; }
    reset.disabled = true;
    try { await api(`/api/admin/users/${user.id}/password`, {method:'PUT', body:{password:pw.value}}); pw.value = ''; message(`${user.username} 비밀번호를 바꾸고 기존 접속을 끊었습니다. 새 비밀번호는 안전한 경로로 전달하세요.`); }
    catch (error) { message(error.message); } finally { reset.disabled = false; }
  });
  const remove = document.createElement('button'); remove.textContent = '삭제'; remove.className = 'danger';
  remove.addEventListener('click', async () => {
    if (!window.confirm(`${user.username} 계정을 삭제할까요?\n되돌릴 수 없습니다. 1:1 대화는 지워지고, 메모와 전체 채팅 글은 이름으로 남습니다.`)) return;
    remove.disabled = true;
    try { await api(`/api/admin/users/${user.id}`, {method:'DELETE'}); await refreshAdmin(); message(`${user.username} 계정을 삭제했습니다.`); }
    catch (error) { message(error.message); remove.disabled = false; }
  });
  const secret = document.createElement('div'); secret.className = 'secret'; secret.append(pw, reset, remove);
  if (user.totp) {
    const otp = document.createElement('button'); otp.className = 'secondary'; otp.textContent = '2FA 초기화'; otp.title = '휴대폰을 잃어버린 멤버의 2단계 인증을 끕니다';
    otp.addEventListener('click', async () => { if (!window.confirm(`${user.username}의 2단계 인증을 초기화할까요?`)) return; try { await api(`/api/admin/users/${user.id}/totp`, {method:'DELETE'}); await refreshAdmin(); message(`${user.username}의 2단계 인증을 초기화했습니다.`); } catch (e) { message(e.message); } });
    secret.append(otp);
  }
  row.append(secret);
  return row;
}

function renderMembers() {
  const list = filteredUsers(), pages = Math.max(1, Math.ceil(list.length / admin.perPage));
  admin.page = Math.min(admin.page, pages - 1);
  const box = $('users'); box.replaceChildren();
  if (!list.length) { const p = document.createElement('p'); p.className = 'muted'; p.textContent = '조건에 맞는 멤버가 없습니다.'; box.append(p); }
  for (const u of list.slice(admin.page * admin.perPage, (admin.page + 1) * admin.perPage)) box.append(memberRow(u));
  const pager = $('member-pager'); pager.replaceChildren();
  const info = document.createElement('small'); info.textContent = `${list.length}명 중 ${list.length ? admin.page * admin.perPage + 1 : 0}–${Math.min(list.length, (admin.page + 1) * admin.perPage)}`;
  const prev = document.createElement('button'); prev.className = 'secondary'; prev.textContent = '이전'; prev.disabled = admin.page === 0;
  const next = document.createElement('button'); next.className = 'secondary'; next.textContent = '다음'; next.disabled = admin.page >= pages - 1;
  prev.addEventListener('click', () => { admin.page--; renderMembers(); });
  next.addEventListener('click', () => { admin.page++; renderMembers(); });
  pager.append(prev, info, next);
}

async function refreshAdmin() {
  const [users, ops] = await Promise.all([api('/api/admin/users'), api('/api/admin/operations')]);
  // Do not wipe a password someone is typing during a background refresh.
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest('#users')) { admin.users = users; renderSummary(); return; }
  admin.users = users; renderSummary(); renderMembers();
  refreshOrca().catch(error => message(error.message));
  refreshGroups().catch(error => message(error.message));
  $('operations').replaceChildren();
  const state = {unknown:'확인 기록 없음', stale:'오래된 확인 기록', current:'최근 운영자 확인'}[ops.state] || ops.state;
  $('operations').append(record(state, ops.detail || ('마지막 확인: ' + new Date(ops.captured_at).toLocaleString()), '실시간 조회 아님'));
  if (ops.resources) {
    $('operations').append(record('승인 종료 시각', ops.stop_at ? new Date(ops.stop_at).toLocaleString() : '미설정', '백업 보관 ' + ops.backup_retention_days + '일'));
    $('operations').append(record('월 환산 견적', '$' + ops.monthly_estimate_usd.toFixed(2), ops.estimate_date + ' 단가 · S3/트래픽 별도 · 실제 청구 아님'));
    for (const resource of ops.resources) $('operations').append(record(resource.kind + ' · ' + resource.label, resource.state, '정리 상태: ' + resource.cleanup));
  }
}

window.addEventListener('DOMContentLoaded', () => {
  form('user-form', async data => {
    const name = String(data.get('username') || '').trim();
    if (!/^[a-zA-Z0-9_.-]+$/.test(name)) throw new Error('아이디는 영문, 숫자, _ . - 만 쓸 수 있습니다.');
    await api('/api/admin/users', {method:'POST', body:{username:name, password:data.get('password'), role:data.get('role')}});
    $('user-form').reset(); await refreshAdmin();
    message(`${name} 계정을 만들었습니다. 비밀번호는 안전한 경로로 전달하세요.`);
  });
  for (const id of ['member-search', 'member-role', 'member-status']) $(id).addEventListener('input', () => { admin.page = 0; renderMembers(); });
});

// Orca connections: requests are processed by a fixed server job; poll while any is open.
const ORCA_STATE = {pending:'대기', running:'처리 중', done:'완료', failed:'실패'};
const ORCA_SOURCE = u => u === '(new)' ? '새 빈 프로젝트' : u === '(existing)' ? '기존 서버 폴더' : (u || '로컬 폴더');
function orcaModeView() {
  const mode = $('orca-mode').value, url = $('orca-url'), folder = $('orca-folder');
  url.hidden = mode !== 'github'; url.required = mode === 'github';
  folder.required = mode !== 'github';
  folder.placeholder = mode === 'github' ? '서버 폴더 이름 (비우면 저장소 이름)' : mode === 'new' ? '새 폴더 이름 (영문·숫자·_ . -)' : '서버 폴더 고르기 (목록에서 선택)';
}
let orcaTimer = null;
async function refreshOrca() {
  const data = await api('/api/admin/orca');
  const sel = $('orca-project'), keep = sel.value; sel.replaceChildren();
  const free = data.projects.filter(p => !p.linked);
  if (!free.length) { const o = document.createElement('option'); o.value = ''; o.textContent = '연결 안 된 프로젝트가 없습니다 (먼저 프로젝트 추가)'; sel.append(o); }
  for (const p of free) { const o = document.createElement('option'); o.value = p.id; o.textContent = p.name; sel.append(o); }
  if (free.some(p => String(p.id) === keep)) sel.value = keep;
  const maps = $('orca-mappings'); maps.replaceChildren();
  if (!data.mappings.length) maps.append(record('연결 없음', '아직 Orca에 연결된 프로젝트가 없습니다.', ''));
  for (const m of data.mappings) {
    const node = record(m.project, ORCA_SOURCE(m.repository_url), `서버 폴더: /home/orca/projects/${m.label}`);
    const b = document.createElement('button'); b.className = 'secondary'; b.textContent = '연결 해제';
    b.addEventListener('click', async () => {
      if (!window.confirm(`${m.project}의 Orca 연결을 해제할까요? 서버의 파일은 지워지지 않습니다.`)) return;
      b.disabled = true;
      try { await api(`/api/admin/orca-projects/${m.project_id}`, {method:'DELETE'}); await refreshOrca(); await refresh(); message('Orca 연결을 해제했습니다.'); }
      catch (error) { message(error.message); b.disabled = false; }
    });
    node.append(b); maps.append(node);
  }
  const reqs = $('orca-requests'); reqs.replaceChildren();
  if (!data.requests.length) reqs.append(record('요청 없음', '', ''));
  for (const r of data.requests) {
    const node = record(`${r.project} ← ${ORCA_SOURCE(r.repository_url)} (${r.folder})`, r.detail, `${r.requested_by} · ${new Date(r.created).toLocaleString()}`);
    const st = document.createElement('span'); st.className = 'state-' + r.state; st.textContent = ORCA_STATE[r.state] || r.state;
    node.querySelector('strong').append(' · ', st); reqs.append(node);
  }
  const list = $('orca-folder-list'); list.replaceChildren();
  for (const f of (data.server_folders?.folders || [])) { const o = document.createElement('option'); o.value = f.name; o.label = f.git ? 'git 저장소' : '폴더'; list.append(o); }
  const open = data.requests.some(r => r.state === 'pending' || r.state === 'running');
  clearTimeout(orcaTimer);
  if (open) orcaTimer = setTimeout(() => refreshOrca().then(() => refresh()).catch(() => {}), 3000);
}
window.addEventListener('DOMContentLoaded', () => {
  form('orca-form', async data => {
    if (!data.get('project_id')) throw new Error('연결할 프로젝트를 고르세요.');
    const mode = data.get('mode'), url = String(data.get('repository_url') || '').trim(), folder = String(data.get('folder') || '').trim();
    if (mode === 'github' && !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+?(\.git)?\/?$/.test(url)) throw new Error('https://github.com/소유자/저장소 형식의 공개 저장소 주소를 넣으세요.');
    if (mode !== 'github' && !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/.test(folder)) throw new Error('폴더 이름은 영문·숫자로 시작하고 영문·숫자·_ . - 만 쓸 수 있습니다.');
    const r = await api('/api/admin/orca-links', {method:'POST', body:{project_id:Number(data.get('project_id')), mode, repository_url: mode === 'github' ? url : '', folder}});
    $('orca-form').reset(); orcaModeView(); message(`연결을 요청했습니다 (${r.folder}). 20초 안에 처리됩니다.`); await refreshOrca();
  });
  $('orca-mode').addEventListener('change', orcaModeView); orcaModeView();
});


// Groups: team / department / cohort. Each group gets a chat room for its members.
let groupEditing = null;
async function refreshGroups() {
  if (groupEditing !== null) return;  // keep an open member editor intact
  const groups = await api('/api/admin/groups');
  const box = $('groups'); box.replaceChildren();
  if (!groups.length) box.append(record('그룹 없음', '위에서 첫 그룹을 만드세요. 여러 명 초대에서 그룹 이름을 적어도 자동으로 만들어집니다.', ''));
  const names = Object.fromEntries(admin.users.map(u => [u.id, u.username]));
  for (const g of groups) {
    const card = document.createElement('div'); card.className = 'group-card';
    const head = document.createElement('div'); head.className = 'head';
    const title = document.createElement('div'); const t = document.createElement('strong'); t.textContent = `${g.name} · ${g.user_ids.length}명`; title.append(t);
    const actions = document.createElement('div');
    const edit = document.createElement('button'); edit.className = 'secondary'; edit.textContent = '멤버 편집';
    const del = document.createElement('button'); del.className = 'danger'; del.textContent = '삭제';
    actions.append(edit, del); head.append(title, actions); card.append(head);
    if (g.description) { const d = document.createElement('p'); d.className = 'muted'; d.textContent = g.description; card.append(d); }
    const chips = document.createElement('div');
    for (const id of g.user_ids) { const c = document.createElement('span'); c.className = 'chip'; c.textContent = names[id] || `#${id}`; chips.append(c); }
    card.append(chips);
    edit.addEventListener('click', () => openGroupEditor(card, g));
    del.addEventListener('click', async () => {
      if (!window.confirm(`${g.name} 그룹을 삭제할까요?\n그룹 채팅 기록도 함께 지워집니다. 계정은 그대로 남습니다.`)) return;
      del.disabled = true;
      try { await api(`/api/admin/groups/${g.id}`, {method:'DELETE'}); await refreshGroups(); await chatTick(); message(`${g.name} 그룹을 삭제했습니다.`); }
      catch (error) { message(error.message); del.disabled = false; }
    });
    box.append(card);
  }
}
function openGroupEditor(card, g) {
  if (card.querySelector('.group-editor')) return;
  groupEditing = g.id;
  const ed = document.createElement('div'); ed.className = 'group-editor';
  const search = document.createElement('input'); search.type = 'search'; search.placeholder = '멤버 찾기'; search.setAttribute('aria-label', '그룹 멤버 찾기');
  const picks = document.createElement('div'); picks.className = 'picks';
  const chosen = new Set(g.user_ids);
  const draw = () => {
    picks.replaceChildren(); const q = search.value.trim().toLowerCase();
    for (const u of admin.users) {
      if (q && !u.username.toLowerCase().includes(q)) continue;
      const l = document.createElement('label'); const c = document.createElement('input'); c.type = 'checkbox'; c.checked = chosen.has(u.id);
      c.addEventListener('change', () => { if (c.checked) chosen.add(u.id); else chosen.delete(u.id); count.textContent = `${chosen.size}명 선택`; });
      l.append(c, document.createTextNode(u.username)); picks.append(l);
    }
  };
  const row = document.createElement('div'); row.className = 'note-actions';
  const count = document.createElement('small'); count.textContent = `${chosen.size}명 선택`;
  const save = document.createElement('button'); save.textContent = '저장';
  const cancel = document.createElement('button'); cancel.className = 'secondary'; cancel.textContent = '취소';
  row.append(save, cancel, count); ed.append(search, picks, row); card.append(ed); draw();
  search.addEventListener('input', draw);
  cancel.addEventListener('click', () => { groupEditing = null; refreshGroups().catch(e => message(e.message)); });
  save.addEventListener('click', async () => {
    save.disabled = true;
    try { await api(`/api/admin/groups/${g.id}/members`, {method:'PUT', body:{user_ids:[...chosen]}}); groupEditing = null; await refreshAdmin(); await chatTick(); message(`${g.name}: 멤버 ${chosen.size}명을 저장했습니다.`); }
    catch (error) { message(error.message); save.disabled = false; }
  });
}

window.addEventListener('DOMContentLoaded', () => {
  form('group-form', async data => {
    const name = String(data.get('name') || '').trim(); if (!name) throw new Error('그룹 이름을 입력하세요.');
    await api('/api/admin/groups', {method:'POST', body:{name, description:String(data.get('description') || '')}});
    $('group-form').reset(); await refreshGroups(); message(`${name} 그룹을 만들었습니다. '멤버 편집'으로 사람을 추가하세요.`);
  });
  form('bulk-form', async data => {
    const text = String(data.get('text') || '').trim(); if (!text) throw new Error('초대할 아이디를 한 줄에 한 명씩 입력하세요.');
    const r = await api('/api/admin/users/bulk', {method:'POST', body:{text}});
    const box = $('bulk-result'); box.replaceChildren();
    const table = document.createElement('table'); table.className = 'bulk-table';
    const head = document.createElement('tr'); for (const h of ['아이디', '역할', '그룹', '임시 비밀번호 / 결과']) { const th = document.createElement('th'); th.textContent = h; head.append(th); } table.append(head);
    const lines = [];
    for (const x of r.results) {
      const tr = document.createElement('tr');
      for (const v of [x.username, x.role || '', x.group || '']) { const td = document.createElement('td'); td.textContent = v; tr.append(td); }
      const td = document.createElement('td');
      if (x.password) { const c = document.createElement('code'); c.textContent = x.password; td.append(c); lines.push(`${x.username},${x.password}`); }
      else { td.textContent = x.error; td.className = 'badge-warn'; }
      tr.append(td); table.append(tr);
    }
    box.append(table);
    if (lines.length) {
      const copy = document.createElement('button'); copy.className = 'secondary'; copy.textContent = '아이디,비밀번호 목록 복사';
      copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(lines.join('\n')); message('복사했습니다. 안전한 경로로 전달한 뒤 지우세요.'); } catch { message('복사하지 못했습니다. 표에서 직접 복사하세요.'); } });
      box.append(copy);
    }
    $('bulk-form').reset(); await refreshAdmin();
    message(`${r.created}명을 만들었습니다. 임시 비밀번호는 지금만 보이며, 첫 로그인 때 본인이 바꿉니다.`);
  });
});


// Project visibility: no groups = all members; otherwise only those groups (and admins).
async function openAccessEditor(node, project) {
  if (node.querySelector('.group-editor')) return;
  live.editing = true;
  let groups, current;
  try { [groups, current] = await Promise.all([api('/api/admin/groups'), api(`/api/admin/projects/${project.id}/access`)]); }
  catch (error) { live.editing = false; message(error.message); return; }
  const ed = document.createElement('div'); ed.className = 'group-editor';
  const help = document.createElement('small'); help.textContent = groups.length ? '아무 그룹도 고르지 않으면 모든 멤버에게 보입니다. 관리자는 항상 볼 수 있습니다.' : '그룹이 없습니다. 그룹 관리에서 먼저 만드세요.';
  const picks = document.createElement('div'); picks.className = 'picks';
  const chosen = new Set(current.group_ids);
  for (const g of groups) {
    const l = document.createElement('label'); const c = document.createElement('input'); c.type = 'checkbox'; c.checked = chosen.has(g.id);
    c.addEventListener('change', () => { if (c.checked) chosen.add(g.id); else chosen.delete(g.id); });
    l.append(c, document.createTextNode(`${g.name} (${g.user_ids.length}명)`)); picks.append(l);
  }
  const row = document.createElement('div'); row.className = 'note-actions';
  const save = document.createElement('button'); save.textContent = '저장';
  const cancel = document.createElement('button'); cancel.className = 'secondary'; cancel.textContent = '취소';
  row.append(save, cancel); ed.append(help, picks, row); node.append(ed);
  cancel.addEventListener('click', () => { live.editing = false; refresh().catch(e => message(e.message)); });
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api(`/api/admin/projects/${project.id}/access`, {method:'PUT', body:{group_ids:[...chosen]}});
      live.editing = false; await refresh();
      message(chosen.size ? `${project.name}: 선택한 그룹과 관리자만 볼 수 있습니다.` : `${project.name}: 모든 멤버가 볼 수 있습니다.`);
    } catch (error) { message(error.message); save.disabled = false; }
  });
}

// Activity log (admin)
const AUDIT_KIND = {'account-access':'계정·권한', content:'콘텐츠', 'orca-link':'Orca 연결', 'orca-access':'Orca 접속', security:'보안'};
async function refreshAudit() {
  const q = encodeURIComponent($('audit-search').value.trim()), kind = encodeURIComponent($('audit-kind').value);
  const rows = await api(`/api/admin/audit?kind=${kind}&q=${q}&limit=200`);
  const box = $('audit-list'); box.replaceChildren();
  if (!rows.length) box.append(record('기록 없음', '조건에 맞는 활동 기록이 없습니다.', ''));
  for (const r of rows) box.append(record(`${AUDIT_KIND[r.kind] || r.kind} · ${r.state}`, r.summary, new Date(r.created).toLocaleString()));
}
window.addEventListener('DOMContentLoaded', () => {
  let t = null;
  $('audit-search').addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => refreshAudit().catch(e => message(e.message)), 300); });
  $('audit-kind').addEventListener('change', () => refreshAudit().catch(e => message(e.message)));
  $('audit-refresh').addEventListener('click', () => refreshAudit().catch(e => message(e.message)));
});
