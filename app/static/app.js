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
    if (response.status === 401 && path !== '/api/login') { showLogin(); throw new Error('로그인이 필요하거나 만료되었습니다. 다시 로그인하세요.'); }
    throw new Error(ERRORS[detail] || STATUS_ERRORS[response.status] || `요청을 처리하지 못했습니다 (${response.status}).`);
  }
  if (data === null) throw new Error('서버 응답을 읽지 못했습니다. 잠시 후 다시 시도하세요.');
  return data;
}
const ERRORS = {
  'Invalid credentials': '아이디 또는 비밀번호가 올바르지 않습니다.',
  'Try again in five minutes': '로그인 실패가 많아 5분 동안 막혔습니다. 잠시 후 다시 시도하세요.',
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
  'User not found': '계정을 찾을 수 없습니다. 새로고침하세요.',
  'Project not found': '프로젝트를 찾을 수 없습니다. 새로고침하세요.',
  'File not found': '파일을 찾을 수 없습니다.',
  'Allowed: txt, png, jpg, pdf': 'TXT, PNG, JPG, PDF 파일만 올릴 수 있습니다.',
  'Maximum 1 MiB': '파일은 1MiB까지 올릴 수 있습니다.',
  'Request too large': '요청이 너무 큽니다.',
  'Invalid input': '입력값을 확인하세요. 빈 칸이나 허용되지 않은 문자가 있습니다.',
  'Storage unavailable': '파일 저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.',
  'Database unavailable': '데이터베이스에 연결하지 못했습니다. 잠시 후 다시 시도하세요.',
};
const STATUS_ERRORS = {400:'요청이 올바르지 않습니다.',403:'권한이 없습니다.',404:'대상을 찾을 수 없습니다.',409:'현재 상태에서는 할 수 없는 작업입니다.',413:'요청이 너무 큽니다.',422:'입력값을 확인하세요.',429:'요청이 너무 많습니다. 잠시 후 다시 시도하세요.',500:'서버 내부 오류가 발생했습니다.',502:'서버가 응답하지 않습니다. 운영 시간인지 확인하세요.',503:'서버를 잠시 사용할 수 없습니다.',504:'서버 응답 시간이 초과되었습니다.'};
function applySession(session) {
  currentUser = session; csrf = session.csrf; $('identity').textContent = session.username;
  for (const id of ['admin-tools','account-tools','operations-tools']) $(id).hidden = session.role !== 'admin';
  for (const id of ['project-form','note-form','upload-form']) $(id).hidden = session.role === 'viewer';
}
function showLogin() { currentUser = null; $('login').hidden = false; $('dashboard').hidden = true; csrf = ''; live.last = null; if (typeof chatReset === 'function') chatReset(); }
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
    const node = record(file.name, `${file.size} bytes`, '');
    const link = document.createElement('a'); link.href = `/api/attachments/${file.id}`;
    link.textContent = '다운로드'; node.append(link); $('files').append(node);
  }
}
async function refresh() {
  const [projects, notes, events, status] = await Promise.all(['/api/projects','/api/notes','/api/events','/api/status'].map(path => api(path)));
  $('project-count').textContent = projects.length;
  $('state').textContent = ({ok:'정상',failed:'점검 실패',unknown:'확인 전',stale:'점검 지연'})[status.state] || status.state;
  $('checked').textContent = status.created ? new Date(status.created).toLocaleString() : '아직 점검 기록이 없습니다.';
  $('projects').replaceChildren(); $('notes').replaceChildren(); $('events').replaceChildren();
  for (const id of ['project-select', 'upload-project']) {
    const selected = $(id).value; $(id).replaceChildren();
    for (const p of projects) { const option = document.createElement('option'); option.value = p.id; option.textContent = p.name; $(id).append(option); }
    if (projects.some(p => String(p.id) === selected)) $(id).value = selected;
  }
  for (const p of projects) {
    const node = record(p.name, p.description, new Date(p.created).toLocaleString());
    if (p.orca_available && currentUser?.role !== 'viewer') {
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
      const detail = document.createElement('p'); detail.textContent = '승인된 팀원과 서버의 파일·터미널을 공유합니다.'; node.append(detail);
      if (p.repository_url) {const link=document.createElement('a');link.href=p.repository_url;link.textContent='GitHub 저장소';link.target='_blank';link.rel='noopener noreferrer';node.append(link);}
    }
    $('projects').append(node);
  }
  for (const n of notes) $('notes').append(record(projects.find(p => p.id === n.project_id)?.name || '프로젝트', n.body, `${n.author} · ${new Date(n.created).toLocaleString()}`));
  for (const e of events) $('events').append(record(`${e.kind} · ${e.state}`, e.summary, new Date(e.created).toLocaleString()));
  if (!events.length) $('events').append(record('기록 없음', '정기 점검이 실행되면 이곳에 표시됩니다.', ''));
  $('events').dataset.count = String(events.length);
  $('events-count').textContent = events.length ? `조회된 최근 ${events.length}개 · 기본 화면에는 3개만 표시합니다.` : '아직 기록이 없습니다.';
  updateEventsView();
  await files();
  if (currentUser?.role === 'admin') await refreshAdmin();
}
function form(id, handler) {
  $(id).addEventListener('submit', async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true; message('');
    try { await handler(new FormData(event.target)); } catch (error) { message(error.message); } finally { button.disabled = false; }
  });
}
form('login-form', async data => {
  const result = await api('/api/login', {method:'POST', body:Object.fromEntries(data)}); csrf = result.csrf;
  const session = await api('/api/session'); applySession(session);
  $('login-form').reset(); $('login').hidden = true; $('dashboard').hidden = false; await refresh(); await chatStart();
});
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
api('/api/session').then(async session => { applySession(session); $('login').hidden = true; $('dashboard').hidden = false; await refresh(); await chatStart(); }).catch(() => showLogin());
// Live updates: poll a cheap fingerprint and redraw only the parts that changed.
// 3s while the tab is visible, 15s in the background; a full refresh still runs every 60s.
const live = { last: null, timer: null, failures: 0, lastFull: 0 };
async function livePoll() {
  if ($('dashboard').hidden) return;
  try {
    const now = await api('/api/changes');
    const prev = live.last; live.last = now; live.failures = 0;
    if (prev) {
      if (now.board !== prev.board || now.events !== prev.events || Date.now() - live.lastFull > 60000) { live.lastFull = Date.now(); await refresh(); }
      else if (now.users !== prev.users && currentUser?.role === 'admin') await refreshAdmin();
      if (now.chat !== prev.chat) await chatTick();
    } else live.lastFull = Date.now();
    if ($('message').dataset.offline) { message(''); delete $('message').dataset.offline; }
  } catch (error) {
    live.failures += 1;
    if (live.failures === 2) { message(error.message); $('message').dataset.offline = '1'; }
  }
}
function liveSchedule() {
  clearTimeout(live.timer);
  const delay = document.hidden ? 15000 : Math.min(3000 * Math.max(1, live.failures), 30000);
  live.timer = setTimeout(async () => { await livePoll(); liveSchedule(); }, delay);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) livePoll().finally(liveSchedule); });
liveSchedule();
