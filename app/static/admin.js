'use strict';
async function refreshAdmin() {
  const [users, ops] = await Promise.all([api('/api/admin/users'), api('/api/admin/operations')]);
  $('users').replaceChildren();
  for (const user of users) {
    const node = record(user.username, user.active ? '접속 허용' : '접속 차단', '');
    const role = document.createElement('select'); role.setAttribute('aria-label', user.username + ' 역할');
    for (const [value,label] of [['member','팀원'],['viewer','조회 전용'],['admin','관리자']]) {
      const option = document.createElement('option'); option.value=value; option.textContent=label; role.append(option);
    }
    role.value=user.role;
    const label=document.createElement('label'); const active=document.createElement('input');
    active.type='checkbox'; active.checked=user.active; label.append(active,document.createTextNode('접속 허용'));
    const button=document.createElement('button'); button.textContent='적용 · 기존 접속 회수';
    if (user.username === currentUser.username) {role.disabled=true;active.disabled=true;button.disabled=true;}
    button.addEventListener('click', async () => {
      button.disabled=true;
      try {await api(`/api/admin/users/${user.id}`,{method:'PATCH',body:{active:active.checked,role:role.value}});await refreshAdmin();message('접근 권한을 적용하고 기존 세션을 회수했습니다.');}
      catch(error){message(error.message);button.disabled=false;}
    });
    node.append(role,label,button); $('users').append(node);
  }
  $('operations').replaceChildren();
  const state={unknown:'확인 기록 없음',stale:'오래된 확인 기록',current:'최근 운영자 확인'}[ops.state] || ops.state;
  $('operations').append(record(state,ops.detail || ('마지막 확인: '+new Date(ops.captured_at).toLocaleString()),'실시간 조회 아님'));
  if (ops.resources) {
    $('operations').append(record('승인 종료 시각',ops.stop_at ? new Date(ops.stop_at).toLocaleString() : '미설정','백업 보관 '+ops.backup_retention_days+'일'));
    $('operations').append(record('월 환산 견적','$'+ops.monthly_estimate_usd.toFixed(2),ops.estimate_date+' 단가 · S3/트래픽 별도 · 실제 청구 아님'));
    for (const resource of ops.resources) $('operations').append(record(resource.kind+' · '+resource.label,resource.state,'정리 상태: '+resource.cleanup));
  }
}
window.addEventListener('DOMContentLoaded', () => {
  form('user-form', async data => {
    await api('/api/admin/users',{method:'POST',body:Object.fromEntries(data)});
    $('user-form').reset(); await refreshAdmin();
    message('새 팀 계정을 만들었습니다. 비밀번호는 별도 안전한 경로로 전달하세요.');
  });
});
