'use strict';
let csrf = '';
const $ = id => document.getElementById(id);
const message = text => { $('message').textContent = text; };
async function api(path, options = {}) {
  options.headers = { ...options.headers, 'X-CSRF-Token': csrf };
  if (options.body && !(options.body instanceof FormData)) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(`요청 실패 (${response.status}). 로그인 상태와 입력을 확인하세요.`);
  }
  return response.json();
}
function showLogin() { $('login').hidden = false; $('dashboard').hidden = true; csrf = ''; }
function record(title, body, meta) {
  const node = document.createElement('article'); node.className = 'record';
  for (const [tag, text] of [['strong', title], ['p', body], ['small', meta]]) {
    const child = document.createElement(tag); child.textContent = text || ''; node.append(child);
  }
  return node;
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
    if (p.orca_available) {
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
  await files();
}
function form(id, handler) {
  $(id).addEventListener('submit', async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true; message('');
    try { await handler(new FormData(event.target)); } catch (error) { message(error.message); } finally { button.disabled = false; }
  });
}
form('login-form', async data => {
  const result = await api('/api/login', {method:'POST', body:Object.fromEntries(data)}); csrf = result.csrf;
  const session = await api('/api/session'); $('admin-tools').hidden = session.role !== 'admin'; $('identity').textContent = session.username;
  $('login-form').reset(); $('login').hidden = true; $('dashboard').hidden = false; await refresh();
});
form('project-form', async data => { await api('/api/projects', {method:'POST',body:Object.fromEntries(data)}); $('project-form').reset(); await refresh(); });
form('note-form', async data => { await api(`/api/projects/${data.get('project_id')}/notes`, {method:'POST',body:{body:data.get('body')}}); $('note-form').elements.body.value = ''; await refresh(); });
form('upload-form', async data => { const id = data.get('project_id'); data.delete('project_id'); await api(`/api/projects/${id}/attachments`, {method:'POST',body:data}); $('upload-form').elements.file.value = ''; await files(); });
$('upload-project').addEventListener('change', () => files().catch(error => message(error.message)));
$('logout').addEventListener('click', async () => { try { await api('/api/logout',{method:'POST'}); showLogin(); } catch(error) { message(error.message); } });
api('/api/session').then(async session => { csrf = session.csrf; $('identity').textContent = session.username; $('admin-tools').hidden = session.role !== 'admin'; $('login').hidden = true; $('dashboard').hidden = false; await refresh(); }).catch(() => showLogin());
setInterval(() => { if (!$('dashboard').hidden) refresh().catch(error => message(error.message)); }, 60000);
