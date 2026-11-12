'use strict';
let noticeNewest=0, noticeBefore=0;
async function refreshNotices(more=false) {
  if(!currentUser)return;
  const data=await api(`/api/notices?limit=20${more?`&before=${noticeBefore}`:''}`);
  const list=$('team-notices');
  if(!more) { list.replaceChildren(); noticeNewest=data.items[0]?.id || 0; }
  for(const n of data.items) {
    const item=record(n.project_name ? `${n.project_name} · ${n.title}` : n.title,n.body,`${n.actor} · ${new Date(n.created).toLocaleString()}`);
    if(n.project_id) {
      const open=document.createElement('button');open.type='button';open.className='secondary';open.textContent='프로젝트 보기';
      open.addEventListener('click',()=> { showView('projects'); document.querySelector(`[data-project-id="${n.project_id}"]`)?.scrollIntoView({block:'center'}); });
      item.append(open);
    }
    item.classList.toggle('notice-unread',n.unread);
    if(n.unread) { const badge=document.createElement('small');badge.textContent='미확인';badge.className='notice-badge';item.prepend(badge); }
    list.append(item);
  }
  if(!list.children.length)list.textContent='아직 등록된 변경사항이 없습니다.';
  noticeBefore=data.next_before;
  $('notice-unread').textContent=`미확인 ${data.unread}개`;
  $('notices-more').hidden=!data.has_more;
  $('notices-read').disabled=!data.unread;
  $('notice-publish').hidden=currentUser.role!=='admin';
}
document.addEventListener('DOMContentLoaded',()=> {
  $('notices-refresh').addEventListener('click',()=>refreshNotices().catch(e=>message(e.message)));
  $('notices-more').addEventListener('click',()=>refreshNotices(true).catch(e=>message(e.message)));
  $('notices-read').addEventListener('click',async()=> {
    try { await api('/api/notices/read',{method:'POST',body:{last_id:noticeNewest}});await refreshNotices(); }
    catch(e){message(e.message);}
  });
  $('notice-form').addEventListener('submit',async event=> {
    event.preventDefault();const f=event.currentTarget,button=f.querySelector('button');button.disabled=true;
    try {await api('/api/admin/notices',{method:'POST',body:{title:f.elements.title.value,body:f.elements.body.value}});f.reset();await refreshNotices();message('전체 공지를 등록했습니다.');}
    catch(e){message(e.message);}finally{button.disabled=false;}
  });
});
