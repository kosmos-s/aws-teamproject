'use strict';
// Owner settings operate through authenticated APIs; no command or private key is returned to the browser.
const REPO_STATE={none:'GitHub 주소 없음',pending:'연결 대기',linked:'Orca 연결 완료',waiting_key:'키 등록 후 연결 필요',failed:'연결 실패',restore_required:'복구 후 다시 연결 필요'};
const KEY_STATE={pending:'키 준비 대기',awaiting_registration:'GitHub 등록 대기',read_verified:'읽기 연결 확인됨',removed:'서버 키 제거됨',failed:'키 준비 실패',needs_registration:'복구 후 새 키 필요'};
const JOB_STATE={pending:'대기',running:'진행 중',done:'완료',failed:'실패',cancelled:'취소',waiting_key:'키 등록 대기'};
const JOB_KIND={link:'저장소 연결',key_create:'키 준비',key_verify:'읽기 연결 확인',key_remove:'서버 키 제거'};
function closeProjectEditors() { if(window.kosmosProjectEditorCleanup)window.kosmosProjectEditorCleanup();window.kosmosProjectEditorCleanup=null; }
function projectLabel(text,input) { const label=document.createElement('label');label.append(document.createTextNode(text),input);return label; }
function projectInput(name,value,max=255) { const el=document.createElement('input');el.name=name;el.value=value || '';el.maxLength=max;return el; }
function projectButton(text,action,cls='secondary') {
  const button=document.createElement('button');button.type='button';button.textContent=text;button.className=cls;
  button.addEventListener('click',async()=> {button.disabled=true;try{await action();}catch(e){message(e.message);}finally{if(button.isConnected)button.disabled=false;}});return button;
}
async function openProjectManager(node,project) {
  if(node.querySelector('.project-manager'))return;
  if(live.editing){message('열려 있는 편집을 먼저 닫아 주세요.');return;}
  live.editing=true;
  const box=document.createElement('section');box.className='project-manager';node.append(box);
  let timer=null,closed=false;
  window.kosmosProjectEditorCleanup=()=> {closed=true;clearTimeout(timer);live.editing=false;box.remove();};
  const close=()=> {if(closed)return;closeProjectEditors();if(currentUser)refresh().catch(e=>message(e.message));};
  const title=document.createElement('h3');title.textContent='프로젝트 관리';box.append(title,projectButton('설정 닫기',close));
  const form=document.createElement('form');form.className='owner-form';
  const name=projectInput('name',project.name,120);name.required=true;
  const description=document.createElement('textarea');description.name='description';description.value=project.description || '';description.maxLength=2000;description.rows=2;
  const save=document.createElement('button');save.textContent='이름·설명 저장';
  form.append(projectLabel('이름',name),projectLabel('설명',description),save);
  form.addEventListener('submit',async e=> {e.preventDefault();save.disabled=true;try {await api(`/api/projects/${project.id}`,{method:'PATCH',body:{name:name.value,description:description.value}});message('프로젝트를 수정했습니다.');close();}catch(err){message(err.message);save.disabled=false;}});box.append(form);
  const owners=document.createElement('div');owners.className='owner-form';
  const select=document.createElement('select');select.setAttribute('aria-label','새 소유자');
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='소유자 선택';select.append(placeholder);
  try {for(const person of await api(`/api/projects/${project.id}/management-candidates`)){const option=document.createElement('option');option.value=person.id;option.textContent=person.username;option.selected=person.username===project.owner;select.append(option);}}
  catch(e){message(e.message);close();return;}
  owners.append(projectLabel(`현재 소유자: ${project.owner || '미지정'}`,select),projectButton('소유자 지정·이전',async()=> {
    if(!select.value){message('새 소유자를 선택하세요.');return;}
    if(!window.confirm('소유자를 바꾸면 기존 소유자의 관리 권한이 즉시 변경됩니다. 계속할까요?'))return;
    await api(`/api/projects/${project.id}/owner`,{method:'PUT',body:{user_id:Number(select.value)}});message('소유자를 변경했습니다.');close();
  }));box.append(owners);
  const repoTitle=document.createElement('h3');repoTitle.textContent='GitHub · Deploy key';box.append(repoTitle);
  const warning=document.createElement('p');warning.className='muted';warning.textContent='신뢰하는 팀원이 함께 쓰는 Orca 환경입니다. 같은 서버 계정의 팀원은 다른 프로젝트 키에도 접근할 수 있습니다. 개인 토큰은 서버에 저장하지 않습니다.';box.append(warning);
  const urlForm=document.createElement('form');urlForm.className='owner-form';
  const url=projectInput('repository_url','');url.type='url';url.placeholder='https://github.com/소유자/저장소';url.required=true;
  const connect=document.createElement('button');connect.textContent='GitHub 연결 요청';urlForm.append(projectLabel('GitHub 주소',url),connect);box.append(urlForm);
  const status=document.createElement('div');status.className='repository-status';status.setAttribute('aria-live','polite');box.append(status);
  urlForm.addEventListener('submit',async e=> {e.preventDefault();connect.disabled=true;try {await api(`/api/projects/${project.id}/repository`,{method:'PUT',body:{repository_url:url.value}});await load();}catch(err){message(err.message);}finally{connect.disabled=false;}});
  async function operation(action) {await api(`/api/projects/${project.id}/deploy-key/${action}`,{method:'POST'});await load();}
  async function load() {
    clearTimeout(timer);if(closed)return;
    const data=await api(`/api/projects/${project.id}/repository`);if(closed)return;
    url.value=data.repository_url;url.disabled=!!data.repository_url;connect.hidden=!!data.repository_url;
    status.replaceChildren();const state=document.createElement('p');state.textContent=REPO_STATE[data.state] || '상태 확인 필요';status.append(state);
    const busy=data.jobs.some(j=>['pending','running'].includes(j.state));
    if(data.repository_url) {
      const link=document.createElement('a');link.href=data.repository_url+'/settings/keys';link.textContent='GitHub에서 Deploy keys 열기';link.target='_blank';link.rel='noopener noreferrer';status.append(link);
      const guide=document.createElement('p');guide.textContent='1. 서버 키 준비 → 2. GitHub에 공개키 등록(Allow write access 선택) → 3. 읽기 연결 확인. 비공개 저장소는 키 등록 후 받을 수 있습니다.';status.append(guide);
      const actions=document.createElement('div');actions.className='note-actions';
      if(!data.key || ['removed','failed','needs_registration'].includes(data.key.state))actions.append(projectButton('서버 키 준비',()=>operation('create')));
      if(data.key) {
        const keyState=document.createElement('p');keyState.textContent=`${KEY_STATE[data.key.state] || '키 확인 필요'} · 쓰기 권한은 실제 push로 별도 확인하세요.`;status.append(keyState);
        if(data.key.public_key) {
          const pub=document.createElement('textarea');pub.readOnly=true;pub.value=data.key.public_key;pub.rows=3;pub.setAttribute('aria-label','GitHub에 등록할 공개키');
          const fingerprint=document.createElement('small');fingerprint.textContent=data.key.fingerprint;
          status.append(pub,fingerprint,projectButton('공개키 복사',async()=> {await navigator.clipboard.writeText(data.key.public_key);message('공개키를 복사했습니다.');}));
          actions.append(projectButton('등록 후 읽기 연결 확인',()=>operation('verify')));
        }
        if(data.key.state!=='removed')actions.append(projectButton('서버 키 제거',async()=> {if(!window.confirm('서버 키를 제거하면 이 연결로 push할 수 없습니다. GitHub에 등록한 키는 GitHub에서도 별도로 삭제해야 합니다. 계속할까요?'))return;await operation('remove');}));
      }
      actions.append(projectButton('연결 다시 시도',async()=> {await api(`/api/projects/${project.id}/repository/retry`,{method:'POST'});await load();}));
      actions.append(projectButton('연결 해제',async()=> {if(!window.confirm('Orca 작업 폴더는 보존하고 포털 연결과 서버 키를 해제할까요? GitHub 등록 키도 별도로 삭제해 주세요.'))return;await api(`/api/projects/${project.id}/repository`,{method:'DELETE'});await load();}));
      for(const button of actions.querySelectorAll('button'))button.disabled=busy;status.append(actions);
    }
    status.append(projectButton('작업 상태 새로고침',load));
    for(const job of data.jobs)status.append(record(JOB_KIND[job.kind] || '저장소 작업',JOB_STATE[job.state] || '상태 확인 필요',job.detail));
    if(busy)timer=setTimeout(()=>load().catch(e=>message(e.message)),5000);
  }
  try {await load();}catch(e){message(e.message);}
  if(currentUser.role==='admin')box.append(projectButton('포털 자료 완전 삭제',async()=> {
    const confirmation=window.prompt(`프로젝트 이름을 정확히 입력하세요: ${project.name}\n포털 자료·첨부는 삭제하고 Orca 작업 폴더와 GitHub 저장소는 보존합니다.`);
    if(confirmation===null)return;
    await api(`/api/projects/${project.id}`,{method:'DELETE',body:{confirmation}});message('포털 자료를 삭제했습니다. GitHub 키 등록은 별도로 확인하세요.');close();
  },'danger'));
}
