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
    summaryCard('접속 차단', count(x => !x.active), '로그인할 수 없는 계정'),
  );
}

function filteredUsers() {
  const q = $('member-search').value.trim().toLowerCase(), role = $('member-role').value, status = $('member-status').value;
  return admin.users.filter(u => (!q || u.username.toLowerCase().includes(q)) && (!role || u.role === role) &&
    (!status || (status === 'online' && u.sessions > 0 && u.active) || (status === 'active' && u.active) || (status === 'blocked' && !u.active)));
}

function memberRow(user) {
  const row = document.createElement('div'); row.className = 'member-row' + (user.active ? '' : ' blocked');
  const who = document.createElement('div'); who.className = 'who';
  const name = document.createElement('strong'); name.textContent = user.username + (user.username === currentUser.username ? ' (나)' : '');
  const state = document.createElement('small');
  state.textContent = !user.active ? '차단됨' : user.sessions > 0 ? `● 접속 중 (${user.sessions})` : '○ 오프라인';
  who.append(name, state);

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
    const note = document.createElement('small'); note.className = 'self-note'; note.textContent = '자기 계정은 위 \'내 비밀번호 변경\'에서 관리합니다.'; row.append(note);
    return row;
  }
  apply.addEventListener('click', async () => {
    apply.disabled = true;
    try { await api(`/api/admin/users/${user.id}`, {method:'PATCH', body:{active:active.checked, role:role.value}}); await refreshAdmin(); message(`${user.username}: 권한을 적용하고 기존 접속을 끊었습니다.`); }
    catch (error) { message(error.message); apply.disabled = false; }
  });
  const pw = document.createElement('input'); pw.type = 'password'; pw.placeholder = '새 비밀번호'; pw.autocomplete = 'new-password'; pw.maxLength = 256;
  pw.setAttribute('aria-label', user.username + ' 새 비밀번호');
  const reset = document.createElement('button'); reset.textContent = '재설정'; reset.className = 'secondary';
  reset.addEventListener('click', async () => {
    if (!pw.value) { message('새 비밀번호를 입력하세요.'); pw.focus(); return; }
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
