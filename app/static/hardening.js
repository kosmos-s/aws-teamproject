'use strict';
let notificationPrefs = {notify:'all',sound:true};
let lastHeartbeat = 0;
async function activityHeartbeat() {
  if (!currentUser || document.hidden || Date.now()-lastHeartbeat < 30000) return;
  lastHeartbeat = Date.now();
  try { await api('/api/activity',{method:'POST'}); } catch {}
}
function askPassword() {
  const dialog=$('reauth-dialog'), input=$('reauth-password');
  return new Promise(resolve => {
    let settled=false;
    const finish=value=> { if(settled)return; settled=true; input.value=''; dialog.close(); $('reauth-form').onsubmit=null; dialog.oncancel=null; dialog.onclose=null; resolve(value); };
    $('reauth-form').onsubmit=event=> { event.preventDefault(); finish(input.value); };
    $('reauth-cancel').onclick=()=>finish(null); dialog.oncancel=()=>finish(null); dialog.onclose=()=>finish(null);
    dialog.showModal(); input.focus();
  });
}
async function refreshPreferences() {
  if(!currentUser)return;
  notificationPrefs=await api('/api/account/preferences');
  $('notification-mode').value=notificationPrefs.notify; $('alarm-sound').checked=notificationPrefs.sound;
  const usage=await api('/api/account/storage');
  $('storage-usage').textContent=`내 저장 용량: ${(usage.used_bytes/1048576).toFixed(1)} / ${(usage.limit_bytes/1048576).toFixed(0)} MiB`;
}
document.addEventListener('DOMContentLoaded',()=> {
  $('save-preferences').addEventListener('click',async()=> {
    try { notificationPrefs=await api('/api/account/preferences',{method:'PUT',body:{notify:$('notification-mode').value,sound:$('alarm-sound').checked}}); message('알림 설정을 저장했습니다.'); }
    catch(e){ message(e.message); }
  });
  $('download-diagnostics').addEventListener('click',async()=> {
    try {
      const data=await api('/api/admin/diagnostics');
      const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
      const a=document.createElement('a'); a.href=url; a.download='kosmos-diagnostics.json'; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(e){message(e.message);}
  });
  // Refresh when account view opens; no session-extending background requests.
  document.addEventListener('click',e=> { if(e.target.closest('.nav-item[data-view="account"]')) refreshPreferences().catch(()=>{}); });
});
