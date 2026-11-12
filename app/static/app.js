'use strict';
let csrf = '';
let currentUser = null;
const $ = id => document.getElementById(id);
const message = text => { $('message').textContent = text; };
async function api(path, options = {}) {
  options.headers = { ...options.headers, 'X-CSRF-Token': csrf };
  if (options.body && !(options.body instanceof FormData)) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('서버에 연결할 수 없습니다. 운영 시간이 끝났거나 네트워크 문제일 수 있습니다.'); }
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : '';
    if (response.status === 401 && path !== '/api/login') {
      const wasIn = !!currentUser;
      showLogin();
      const text = detail === 'Signed in elsewhere' ? '다른 곳에서 같은 아이디로 로그인해 이 화면의 접속이 끊겼습니다. 계속하려면 다시 로그인하세요.' : '로그인이 필요하거나 만료되었습니다. 다시 로그인하세요.';
      if (wasIn) message(text);  // background requests swallow errors, so show it here
      throw new Error(text);
    }
    throw new Error(ERRORS[detail] || STATUS_ERRORS[response.status] || `요청을 처리하지 못했습니다 (${response.status}).`);
  }
  if (data === null) throw new Error('서버 응답을 읽지 못했습니다. 잠시 후 다시 시도하세요.');
  return data;
}
const ERRORS = {
  'Invalid credentials': '아이디 또는 비밀번호가 올바르지 않습니다.',
  'Try again in five minutes': '로그인 실패가 많아 5분 동안 막혔습니다. 잠시 후 다시 시도하세요.',
  'Account temporarily locked': '이 계정은 로그인 실패가 많아 15분 동안 잠겼습니다. 관리자에게 문의하거나 잠시 후 다시 시도하세요.',
  'Read-only account': '조회 전용 계정은 저장할 수 없습니다.',
  'Administrator required': '관리자만 할 수 있습니다.',
  'CSRF rejected': '보안 확인에 실패했습니다. 새로고침 후 다시 시도하세요.',
  'Origin rejected': '허용되지 않은 주소에서 보낸 요청입니다. 포털 주소로 다시 접속하세요.',
  'Username already exists': '이미 있는 아이디입니다.',
  'Cannot lock current or last administrator': '자기 자신이나 마지막 관리자는 잠그거나 권한을 낮출 수 없습니다.',
  'Cannot delete current account': '지금 로그인한 자기 계정은 삭제할 수 없습니다.',
  'Cannot delete last administrator': '마지막 관리자는 삭제할 수 없습니다.',
  'Use your own password change': '자기 비밀번호는 \'내 비밀번호 변경\'에서 바꾸세요.',
  'Current password incorrect': '현재 비밀번호가 올바르지 않습니다.',
  'New password must differ': '새 비밀번호는 지금 비밀번호와 달라야 합니다.',
  'Password change required': '먼저 비밀번호를 바꿔야 합니다.',
  'Only the author or an administrator': '작성자나 관리자만 할 수 있습니다.',
  'Note not found': '메모를 찾을 수 없습니다. 새로고침하세요.',
  'Group already exists': '같은 이름의 그룹이 이미 있습니다.',
  'Group not found': '그룹을 찾을 수 없습니다.',
  'At most 200 accounts per batch': '한 번에 200명까지 초대할 수 있습니다.',
  'Project not archived': '보관된 프로젝트가 아닙니다.',
  'Invalid repository URL': 'GitHub 저장소 주소 형식이 올바르지 않습니다.',
  'Invalid folder name': '폴더 이름이 올바르지 않습니다.',
  'Project already linked to Orca': '이미 Orca에 연결된 프로젝트입니다.',
  'Link request already in progress': '같은 프로젝트나 폴더의 요청이 처리 중입니다.',
  'Orca link not found': 'Orca 연결을 찾을 수 없습니다.',
  'Recipient is blocked': '차단된 멤버에게는 보낼 수 없습니다.',
  'Only the uploader or an administrator': '올린 사람이나 관리자만 삭제할 수 있습니다.',
  'Only the sender': '보낸 사람만 할 수 있습니다.',
  'Message not found': '메시지를 찾을 수 없습니다.',
  'Message already deleted': '이미 삭제된 메시지입니다.',
  'Signed in elsewhere': '다른 곳에서 같은 아이디로 로그인해 접속이 끊겼습니다.',
  'Too many messages': '메시지를 너무 빨리 보내고 있습니다. 잠시 후 다시 보내세요.',
  'User not found': '계정을 찾을 수 없습니다. 새로고침하세요.',
  'Project not found': '프로젝트를 찾을 수 없습니다. 새로고침하세요.',
  'File not found': '파일을 찾을 수 없습니다.',
  'Allowed: txt, png, jpg, pdf': 'TXT, PNG, JPG, PDF 파일만 올릴 수 있습니다.',
  'Maximum 1 MiB': '파일은 1MiB까지 올릴 수 있습니다.',
  'Request too large': '요청이 너무 큽니다.',
  'Invalid input': '입력값을 확인하세요. 비밀번호는 8자 이상이며, 빈 칸이나 허용되지 않은 문자가 없어야 합니다.',
  'Storage unavailable': '파일 저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.',
  'Database unavailable': '데이터베이스에 연결하지 못했습니다. 잠시 후 다시 시도하세요.',
};
const STATUS_ERRORS = {400:'요청이 올바르지 않습니다.',403:'권한이 없습니다.',404:'대상을 찾을 수 없습니다.',409:'현재 상태에서는 할 수 없는 작업입니다.',413:'요청이 너무 큽니다.',422:'입력값을 확인하세요.',429:'요청이 너무 많습니다. 잠시 후 다시 시도하세요.',500:'서버 내부 오류가 발생했습니다.',502:'서버가 응답하지 않습니다. 운영 시간인지 확인하세요.',503:'서버를 잠시 사용할 수 없습니다.',504:'서버 응답 시간이 초과되었습니다.'};
const ROLE_NAME = {admin:'관리자', member:'멤버', viewer:'게스트(조회)'};
function applySession(session) {
  currentUser = session; csrf = session.csrf; $('identity').textContent = `${session.username} · ${ROLE_NAME[session.role] || session.role}`;
  const isAdmin = session.role === 'admin';
  for (const id of ['admin-tools','account-tools','operations-tools','orca-tools','group-tools','audit-tools']) $(id).hidden = !isAdmin;
  document.querySelectorAll('.admin-only').forEach(el => { el.hidden = !isAdmin; });
  for (const id of ['project-form','note-form','upload-form']) $(id).hidden = session.role === 'viewer';
  $('logout').hidden = false;
}
function showLogin() {
  currentUser = null; $('login').hidden = false; $('dashboard').hidden = true; $('force-password').hidden = true; $('logout').hidden = true;
  $('identity').textContent = '팀 개발환경 운영 포털'; csrf = ''; live.last = null; document.title = 'KOSMOS · 운영 포털';
  if (typeof chatReset === 'function') chatReset();
}
// Show either the forced password screen or the workspace once a session is known.
async function enter(session) {
  applySession(session); $('login').hidden = true;
  if (session.must_change) { $('dashboard').hidden = true; $('force-password').hidden = false; return; }
  $('force-password').hidden = true; $('dashboard').hidden = false;
  showView(location.hash.slice(1) || 'home', false);
  await refresh(); await chatStart();
  liveLoop();
}
const VIEWS = ['home','chat','projects','notes','files','history','account','guide','members','groups','orca','audit','operations','server'];
function showView(name, push = true) {
  if (!VIEWS.includes(name)) name = 'home';
  const adminView = ['members','groups','orca','audit','operations','server'].includes(name);
  if (adminView && currentUser?.role !== 'admin') name = 'home';
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.dataset.view === name));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  if (push && location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  if (name === 'audit' && typeof refreshAudit === 'function') refreshAudit().catch(e => message(e.message));
}
function record(title, body, meta) {
  const node = document.createElement('article'); node.className = 'record';
  for (const [tag, text] of [['strong', title], ['p', body], ['small', meta]]) {
    const child = document.createElement(tag); child.textContent = text || ''; node.append(child);
  }
  return node;
}
function updateEventsView() {
  const button = $('events-toggle');
  const expanded = button.getAttribute('aria-expanded') === 'true';
  const count = Number($('events').dataset.count || 0);
  $('event-history').classList.toggle('expanded', expanded);
  $('events').tabIndex = expanded ? 0 : -1;
  button.hidden = count === 0;
  button.textContent = expanded ? '이력 접기' : `이력 펼치기 (${count}개)`;
}
async function files() {
  const id = $('upload-project').value; $('files').replaceChildren();
  if (!id) return;
  for (const file of await api(`/api/projects/${id}/attachments`)) {
    const node = record(file.name, `${file.size} bytes`, file.uploaded_by ? `올린 사람 ${file.uploaded_by}` : '');
    const link = document.createElement('a'); link.href = `/api/attachments/${file.id}`;
    link.textContent = '다운로드'; node.append(link);
    if (currentUser && (currentUser.role === 'admin' || (file.uploaded_by && file.uploaded_by === currentUser.username))) {
      const del = document.createElement('button'); del.className = 'danger small'; del.textContent = '삭제';
      del.addEventListener('click', async () => {
        if (!window.confirm(`${file.name} 파일을 삭제할까요? 되돌릴 수 없습니다.`)) return;
        del.disabled = true;
        try { await api(`/api/attachments/${file.id}`, {method:'DELETE'}); await files(); message('파일을 삭제했습니다.'); }
        catch (error) { message(error.message); del.disabled = false; }
      });
      node.append(' ', del);
    }
    $('files').append(node);
  }
}
async function refresh() {
  if (live.editing) return;  // do not wipe a note being edited
  const [projects, notes, events, status] = await Promise.all(['/api/projects','/api/notes','/api/events','/api/status'].map(path => api(path)));
  const active = projects.filter(p => !p.archived), archived = projects.filter(p => p.archived);
  const isAdmin = currentUser?.role === 'admin';
  $('project-count').textContent = active.length;
  $('archived-count').textContent = `보관된 프로젝트 ${archived.length}개`;
  $('state').textContent = ({ok:'정상',failed:'점검 실패',unknown:'확인 전',stale:'점검 지연'})[status.state] || status.state;
  $('checked').textContent = status.created ? new Date(status.created).toLocaleString() : '아직 점검 기록이 없습니다.';
  for (const id of ['projects','archived-projects','notes','events','home-notes','home-orca']) $(id).replaceChildren();
  for (const id of ['project-select', 'upload-project']) {
    const selected = $(id).value; $(id).replaceChildren();
    for (const p of active) { const option = document.createElement('option'); option.value = p.id; option.textContent = p.name; $(id).append(option); }
    if (active.some(p => String(p.id) === selected)) $(id).value = selected;
  }
  const projectNode = (p) => {
    const node = record(p.name, p.description, new Date(p.created).toLocaleString());
    if (p.access_groups?.length) { const chips = document.createElement('div'); for (const g of p.access_groups) { const c = document.createElement('span'); c.className = 'chip lock'; c.textContent = '공개: ' + g; chips.append(c); } node.append(chips); }
    if (!p.archived && p.orca_available && currentUser?.role !== 'viewer') {
      const button = document.createElement('button'); button.textContent = 'Orca에서 개발환경 열기';
      button.addEventListener('click', async () => {
        const tab = window.open('about:blank', '_blank');
        if (tab) tab.opener = null;
        button.disabled = true;
        try {
          const result = await api(`/api/projects/${p.id}/orca`, {method:'POST'});
          if (tab) tab.location.replace(result.url); else window.location.assign(result.url);
        } catch (error) { if (tab) tab.close(); message(error.message); }
        finally { button.disabled = false; }
      });
      node.append(button);
      if (p.repository_url && p.repository_url.startsWith('https://')) {const link=document.createElement('a');link.href=p.repository_url;link.textContent=' GitHub 저장소';link.target='_blank';link.rel='noopener noreferrer';node.append(link);}
    }
    if (isAdmin) {
      const b = document.createElement('button'); b.className = 'secondary'; b.textContent = p.archived ? '복원' : '보관';
      b.addEventListener('click', async () => {
        if (!p.archived && !window.confirm(`${p.name} 프로젝트를 보관할까요? 목록에서 숨겨지고 메모·첨부는 남습니다.`)) return;
        b.disabled = true;
        try { await api(`/api/projects/${p.id}/archive`, {method: p.archived ? 'DELETE' : 'POST'}); await refresh(); message(p.archived ? '프로젝트를 복원했습니다.' : '프로젝트를 보관했습니다.'); }
        catch (error) { message(error.message); b.disabled = false; }
      });
      node.append(' ', b);
      if (!p.archived && typeof openAccessEditor === 'function') {
        const acc = document.createElement('button'); acc.className = 'secondary'; acc.textContent = '공개 범위';
        acc.addEventListener('click', () => openAccessEditor(node, p));
        node.append(' ', acc);
      }
    }
    return node;
  };
  for (const p of active) $('projects').append(projectNode(p));
  if (!active.length) $('projects').append(record('프로젝트 없음', '위에서 첫 프로젝트를 추가하세요.', ''));
  for (const p of archived) $('archived-projects').append(projectNode(p));
  $('archived-box').hidden = !archived.length; $('archived-summary').textContent = `보관된 프로젝트 (${archived.length})`;
  for (const p of active.filter(p => p.orca_available)) $('home-orca').append(record(p.name, '개발환경 연결됨', ''));
  if (!active.some(p => p.orca_available)) $('home-orca').append(record('연결된 개발환경 없음', isAdmin ? '관리자 > Orca 연결에서 프로젝트를 연결하세요.' : '관리자에게 연결을 요청하세요.', ''));
  const noteNode = (n, withActions) => {
    const meta = `${n.author} · ${new Date(n.created).toLocaleString()}${n.edited ? ' · 수정됨' : ''}`;
    const node = record(projects.find(p => p.id === n.project_id)?.name || '프로젝트', n.body, meta);
    if (withActions && (n.author === currentUser?.username || isAdmin) && currentUser?.role !== 'viewer') {
      const actions = document.createElement('div'); actions.className = 'note-actions';
      const edit = document.createElement('button'); edit.className = 'secondary'; edit.textContent = '수정';
      const del = document.createElement('button'); del.className = 'danger'; del.textContent = '삭제';
      edit.addEventListener('click', () => {
        const box = document.createElement('div'); box.className = 'note-edit';
        const area = document.createElement('textarea'); area.value = n.body; area.maxLength = 4000;
        const save = document.createElement('button'); save.textContent = '저장';
        const cancel = document.createElement('button'); cancel.className = 'secondary'; cancel.textContent = '취소';
        const row = document.createElement('div'); row.className = 'note-actions'; row.append(save, cancel);
        box.append(area, row); node.querySelector('p').replaceWith(box); actions.hidden = true; area.focus();
        live.editing = true;
        cancel.addEventListener('click', () => { live.editing = false; refresh().catch(e => message(e.message)); });
        save.addEventListener('click', async () => {
          if (!area.value.trim()) { message('메모 내용을 입력하세요.'); return; }
          save.disabled = true;
          try { await api(`/api/notes/${n.id}`, {method:'PATCH', body:{body:area.value}}); live.editing = false; await refresh(); message('메모를 수정했습니다.'); }
          catch (error) { message(error.message); save.disabled = false; }
        });
      });
      del.addEventListener('click', async () => {
        if (!window.confirm('이 메모를 삭제할까요? 되돌릴 수 없습니다.')) return;
        del.disabled = true;
        try { await api(`/api/notes/${n.id}`, {method:'DELETE'}); await refresh(); message('메모를 삭제했습니다.'); }
        catch (error) { message(error.message); del.disabled = false; }
      });
      actions.append(edit, del); node.append(actions);
    }
    return node;
  };
  for (const n of notes) $('notes').append(noteNode(n, true));
  for (const n of notes.slice(0, 5)) $('home-notes').append(noteNode(n, false));
  if (!notes.length) { $('notes').append(record('메모 없음', '첫 작업 메모를 남겨 보세요.', '')); $('home-notes').append(record('메모 없음', '', '')); }
  for (const e of events) $('events').append(record(`${e.kind} · ${e.state}`, e.summary, new Date(e.created).toLocaleString()));
  if (!events.length) $('events').append(record('기록 없음', '정기 점검이 실행되면 이곳에 표시됩니다.', ''));
  $('events').dataset.count = String(events.length);
  $('events-count').textContent = events.length ? `조회된 최근 ${events.length}개 · 기본 화면에는 3개만 표시합니다.` : '아직 기록이 없습니다.';
  updateEventsView();
  renderMyInfo();
  await files();
  if (isAdmin) await refreshAdmin();
}
function renderMyInfo() {
  const box = $('my-info'); if (!box || !currentUser) return; box.replaceChildren();
  const groups = (typeof chat !== 'undefined' && chat.groups) ? chat.groups.map(g => g.name).join(', ') : '';
  for (const [label, value] of [['아이디', currentUser.username], ['역할', ROLE_NAME[currentUser.role] || currentUser.role], ['소속 그룹', groups || '없음']]) {
    const d = document.createElement('div'); const sm = document.createElement('small'); sm.textContent = label; const st = document.createElement('strong'); st.textContent = value; d.append(sm, st); box.append(d);
  }
}
function form(id, handler) {
  $(id).addEventListener('submit', async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true; message('');
    try { await handler(new FormData(event.target)); } catch (error) { message(error.message); } finally { button.disabled = false; }
  });
}
form('login-form', async data => {
  const result = await api('/api/login', {method:'POST', body:Object.fromEntries(data)}); csrf = result.csrf;
  const session = await api('/api/session'); $('login-form').reset(); await enter(session);
});
form('force-password-form', async data => {
  if (String(data.get('new') || '').length < 8) throw new Error('새 비밀번호는 8자 이상이어야 합니다.');
  await api('/api/account/password', {method:'POST', body:{current:data.get('current'), new:data.get('new')}});
  $('force-password-form').reset(); const session = await api('/api/session'); await enter(session);
  message('비밀번호를 바꿨습니다. 환영합니다!');
});
document.querySelectorAll('.nav-item').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
document.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => showView(b.dataset.goto)));
window.addEventListener('hashchange', () => { if (!$('dashboard').hidden) showView(location.hash.slice(1), false); });
form('password-form', async data => {
  const result = await api('/api/account/password', {method:'POST', body:{current:data.get('current'), new:data.get('new')}});
  $('password-form').reset();
  message(`비밀번호를 바꿨습니다. 다른 로그인 ${result.other_sessions_revoked}개를 끊었습니다.`);
});
form('project-form', async data => { await api('/api/projects', {method:'POST',body:Object.fromEntries(data)}); $('project-form').reset(); await refresh(); });
form('note-form', async data => { if (!data.get('project_id')) throw new Error('먼저 프로젝트를 만들거나 선택하세요.'); if (!String(data.get('body')||'').trim()) throw new Error('메모 내용을 입력하세요.'); await api(`/api/projects/${data.get('project_id')}/notes`, {method:'POST',body:{body:data.get('body')}}); $('note-form').elements.body.value = ''; await refresh(); });
form('upload-form', async data => {
  const file = data.get('file');
  if (!data.get('project_id')) throw new Error('먼저 프로젝트를 만들거나 선택하세요.');
  if (!file || !file.name) throw new Error('올릴 파일을 선택하세요.');
  if (!/\.(txt|png|jpg|pdf)$/i.test(file.name)) throw new Error('TXT, PNG, JPG, PDF 파일만 올릴 수 있습니다.');
  if (file.size > 1024 * 1024) throw new Error('파일은 1MiB까지 올릴 수 있습니다.');
  const id = data.get('project_id'); data.delete('project_id'); await api(`/api/projects/${id}/attachments`, {method:'POST',body:data}); $('upload-form').elements.file.value = ''; await files(); });
$('upload-project').addEventListener('change', () => files().catch(error => message(error.message)));
$('events-toggle').addEventListener('click', () => {
  const button = $('events-toggle');
  button.setAttribute('aria-expanded', String(button.getAttribute('aria-expanded') !== 'true'));
  updateEventsView();
});
$('logout').addEventListener('click', async () => { try { await api('/api/logout',{method:'POST'}); showLogin(); } catch(error) { message(error.message); } });
api('/api/session').then(enter).catch(() => showLogin());
// Live updates: poll a cheap fingerprint and redraw only the parts that changed.
// 3s while the tab is visible, 15s in the background; a full refresh still runs every 60s.
const live = { last: null, timer: null, failures: 0, lastFull: 0, editing: false, busy: false, looping: false, v: -1 };
async function livePoll() {
  if ($('dashboard').hidden || !currentUser || live.busy) return;
  live.busy = true;
  try {
    const now = await api('/api/changes');
    const prev = live.last; live.last = now; live.failures = 0;
    if (prev) {
      if (now.board !== prev.board || now.events !== prev.events || Date.now() - live.lastFull > 60000) { live.lastFull = Date.now(); await refresh(); }
      else if (now.users !== prev.users && currentUser?.role === 'admin') await refreshAdmin();
      if (now.access !== prev.access && now.board === prev.board) { live.lastFull = Date.now(); await refresh(); }
      if (now.chat !== prev.chat || now.access !== prev.access) await chatTick(now.chat.split('-')[2] !== prev.chat.split('-')[2]);
    } else live.lastFull = Date.now();
    if ($('message').dataset.offline) { message(''); delete $('message').dataset.offline; }
  } catch (error) {
    live.failures += 1;
    if (live.failures === 2) { message(error.message); $('message').dataset.offline = '1'; }
  } finally { live.busy = false; }
}
// Long-poll: the server answers /api/wait the moment anyone writes something, so chat shows up at once.
async function liveLoop() {
  if (live.looping) return; live.looping = true; live.v = -1;
  while (currentUser && !$('dashboard').hidden) {
    try {
      const r = await api(`/api/wait?v=${live.v}`);
      const changed = live.v !== -1 && r.v !== live.v; live.v = r.v;
      if (changed) await livePoll();
    } catch { await new Promise(res => setTimeout(res, 3000)); }
  }
  live.looping = false;
}
function liveSchedule() {
  clearTimeout(live.timer);
  const delay = document.hidden ? 30000 : Math.min(15000 * Math.max(1, live.failures), 60000);
  live.timer = setTimeout(async () => { await livePoll(); liveSchedule(); }, delay);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) livePoll().finally(liveSchedule); });
liveSchedule();
