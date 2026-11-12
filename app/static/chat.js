'use strict';
// Team chat: main room, group rooms ('g<id>') and 1:1 rooms ('u<id>'). Text is always set with textContent.
const chat = { room: 'main', lastId: 0, peers: [], groups: [], loading: false, started: false, lastTotal: 0, rooms: null, replyTo: null, lastDay: '', lastSender: null, lastAt: 0, initial: true };
const REACTIONS = ['👍','❤️','😂','😮','😢','🙏'];
let profiles = {};  // username -> {display_name, team, photo, v}
const BASE_TITLE = 'KOSMOS · 운영 포털';

function chatRoomPath() {
  if (chat.room === 'main') return '/api/chat/main';
  if (chat.room.startsWith('g')) return `/api/chat/group/${chat.room.slice(1)}`;
  return `/api/chat/dm/${chat.room.slice(1)}`;
}
function chatTime(iso) { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }

function chatRoomButton(label, key, unread, extra, cls = '') {
  const b = document.createElement('button'); b.type = 'button';
  b.className = 'room ' + cls + (chat.room === key ? ' active' : '');
  const name = document.createElement('span'); name.textContent = label; b.append(name);
  if (extra) { const s = document.createElement('small'); s.textContent = extra; b.append(s); }
  if (unread > 0) { const badge = document.createElement('em'); badge.textContent = unread > 99 ? '99+' : String(unread); b.append(badge); }
  b.addEventListener('click', () => chatOpen(key));
  return b;
}
function roomsLabel(text) { const p = document.createElement('p'); p.className = 'rooms-label'; p.textContent = text; return p; }

// ---- chat alarm: popup + sound for rooms you are not looking at ----
function alarmSetting(name, fallback) { try { const v = localStorage.getItem('kosmos-alarm-' + name); return v === null ? fallback : v === 'on'; } catch { return fallback; } }
function setAlarmSetting(name, on) { try { localStorage.setItem('kosmos-alarm-' + name, on ? 'on' : 'off'); } catch {} }
let audioCtx = null;
function beep() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = 'sine'; o.frequency.value = 880; g.gain.setValueAtTime(0.0001, audioCtx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.15, audioCtx.currentTime + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.35);
    o.connect(g); g.connect(audioCtx.destination); o.start(); o.stop(audioCtx.currentTime + 0.4);
  } catch { /* sound is optional */ }
}
function toast(title, body, key) {
  const box = $('toasts'); if (!box) return;
  const t = document.createElement('button'); t.type = 'button'; t.className = 'toast';
  const s = document.createElement('strong'); s.textContent = title; const p = document.createElement('span'); p.textContent = body;
  t.append(s, p); box.append(t);
  const close = () => t.remove();
  t.addEventListener('click', () => { close(); showView('chat'); chatOpen(key); });
  setTimeout(close, 6000);
  while (box.children.length > 3) box.firstChild.remove();
}
function chatAlarm(rooms) {
  // rooms: key -> {label, unread}. Compare with the previous snapshot; the first load never alarms.
  const prev = chat.rooms; chat.rooms = rooms;
  if (!prev) return;
  const viewingChat = document.querySelector('.view.active')?.dataset.view === 'chat' && !document.hidden;
  let fired = false;
  for (const [key, r] of Object.entries(rooms)) {
    const before = prev[key]?.unread || 0;
    if (r.unread > before && !(viewingChat && chat.room === key)) {
      if (alarmSetting('popup', true)) toast(r.label, `새 메시지 ${r.unread - before}개`, key);
      fired = true;
    }
  }
  if (fired && alarmSetting('sound', true)) beep();
}
function notifyNew(total) {
  try {
    if (total > chat.lastTotal && document.hidden && 'Notification' in window && Notification.permission === 'granted' && localStorage.getItem('kosmos-notify') === 'on')
      new Notification('KOSMOS 새 메시지', { body: `읽지 않은 메시지 ${total}개`, tag: 'kosmos-chat' });
  } catch { /* notifications are optional */ }
  chat.lastTotal = total;
}
function showUnread(total) {
  notifyNew(total);
  document.title = total ? `(${total > 99 ? '99+' : total}) ${BASE_TITLE}` : BASE_TITLE;
  const badge = $('nav-chat-badge'); if (badge) { badge.hidden = !total; badge.textContent = total > 99 ? '99+' : String(total); }
  const metric = $('unread-count'); if (metric) metric.textContent = String(total);
  $('chat-status').textContent = total ? `읽지 않은 메시지 ${total}개` : '새 메시지 없음';
}

async function chatPeople() {
  const data = await api('/api/chat/people');
  chat.peers = data.people; chat.groups = data.groups || [];
  const nav = $('chat-rooms'); nav.replaceChildren();
  nav.append(chatRoomButton('# 전체 채팅', 'main', chat.room === 'main' ? 0 : data.main_unread, '모든 멤버'));
  if (chat.groups.length) {
    nav.append(roomsLabel(`그룹 · ${chat.groups.length}개`));
    for (const g of chat.groups) nav.append(chatRoomButton('# ' + g.name, 'g' + g.id, chat.room === 'g' + g.id ? 0 : g.unread, `${g.members}명`, 'group-room'));
  }
  nav.append(roomsLabel(`1:1 대화 · ${data.people.length}명`));
  const filter = ($('chat-people-search')?.value || '').trim().toLowerCase();
  const sorted = [...data.people].sort((a, b) => (b.unread - a.unread) || (b.online - a.online) || a.username.localeCompare(b.username));
  for (const p of sorted) {
    if (filter && !p.username.toLowerCase().includes(filter)) continue;
    nav.append(chatRoomButton((p.online ? '● ' : '○ ') + p.username, 'u' + p.id, chat.room === 'u' + p.id ? 0 : p.unread, p.online ? '접속 중' : ''));
  }
  const rooms = { main: { label: '# 전체 채팅', unread: data.main_unread } };
  for (const g of chat.groups) rooms['g' + g.id] = { label: '# ' + g.name, unread: g.unread };
  for (const p of data.people) rooms['u' + p.id] = { label: `${p.username}님의 1:1 메시지`, unread: p.unread };
  chatAlarm(rooms);
  const total = (chat.room === 'main' ? 0 : data.main_unread) + chat.groups.reduce((n, g) => n + (chat.room === 'g' + g.id ? 0 : g.unread), 0)
    + data.people.reduce((n, p) => n + (chat.room === 'u' + p.id ? 0 : p.unread), 0);
  showUnread(total);
  if (typeof renderMyInfo === 'function') renderMyInfo();
}

function displayName(username) { const p = profiles[username]; return (p && p.display_name) ? `${p.display_name} (${username})` : username; }
function avatar(username) {
  const a = document.createElement('span'); a.className = 'avatar';
  const p = profiles[username];
  if (p && p.photo) { const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy'; img.src = `/api/profiles/${encodeURIComponent(username)}/photo?v=${encodeURIComponent(p.v || '')}`; a.append(img); }
  else a.textContent = ((p && p.display_name) || username || '?').slice(0, 1).toUpperCase();
  return a;
}
function dayLabel(iso) { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString('ko-KR', {year:'numeric', month:'long', day:'numeric', weekday:'long'}); }
// Text with @mentions highlighted; never uses innerHTML.
function richText(text) {
  const frag = document.createDocumentFragment(); const re = /@([A-Za-z0-9_.-]{1,80})/g; let last = 0, mm;
  while ((mm = re.exec(text))) {
    if (mm.index > last) frag.append(document.createTextNode(text.slice(last, mm.index)));
    const span = document.createElement('span'); span.className = 'mention' + (mm[1] === currentUser?.username ? ' me' : ''); span.textContent = mm[0]; frag.append(span);
    last = re.lastIndex;
  }
  if (last < text.length) frag.append(document.createTextNode(text.slice(last)));
  return frag;
}
function mentionsMe(text) { return !!currentUser && new RegExp(`(^|\\s)@${currentUser.username.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![A-Za-z0-9_.-])`).test(text || ''); }

function chatAppend(messages) {
  const log = $('chat-log');
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  if (chat.lastId === 0 && !messages.length && !log.querySelector('.chat-empty')) {
    const empty = document.createElement('p'); empty.className = 'chat-empty'; empty.textContent = '아직 메시지가 없습니다. 첫 메시지를 남겨 보세요.'; log.append(empty);
  }
  if (messages.length) log.querySelector('.chat-empty')?.remove();
  const place = node => { const pendingAt = log.querySelector('.msg.local'); if (pendingAt) log.insertBefore(node, pendingAt); else log.append(node); };
  for (const m of messages) {
    if (m.id <= chat.lastId) continue;
    const day = dayLabel(m.created);
    if (day && day !== chat.lastDay) { const d = document.createElement('div'); d.className = 'day-divider'; d.textContent = day; place(d); chat.lastDay = day; chat.lastSender = null; }
    const at = new Date(m.created).getTime();
    const cont = chat.lastSender === m.sender && at - chat.lastAt < 5 * 60 * 1000;
    chat.lastSender = m.sender; chat.lastAt = at;
    const row = document.createElement('div'); row.className = 'msg' + (m.mine ? ' mine' : '') + (cont ? ' cont' : ''); row.dataset.id = m.id;
    if (!m.mine && !cont) row.append(avatar(m.sender));
    const meta = document.createElement('small'); meta.textContent = `${m.mine ? '나' : displayName(m.sender)} · ${chatTime(m.created)}${m.edited ? ' · 수정됨' : ''}`;
    row.append(meta);
    if (m.reply_to && !m.deleted) {
      const q = document.createElement('div'); q.className = 'quote'; q.textContent = `↪ ${displayName(m.reply_to.sender)}: ${m.reply_to.body || '(삭제된 메시지 또는 파일)'}`;
      q.addEventListener('click', () => log.querySelector(`.msg[data-id="${m.reply_to.id}"]`)?.scrollIntoView({block:'center', behavior:'smooth'}));
      row.append(q);
    }
    if (m.file && !m.deleted) {
      if (m.file.image) { const a = document.createElement('a'); a.href = `/api/chat/files/${m.id}`; a.target = '_blank'; a.rel = 'noopener'; const img = document.createElement('img'); img.className = 'chat-image'; img.loading = 'lazy'; img.alt = m.file.name; img.src = `/api/chat/files/${m.id}`; a.append(img); row.append(a); }
      else { const a = document.createElement('a'); a.className = 'chat-file'; a.href = `/api/chat/files/${m.id}?download=1`; a.textContent = `📎 ${m.file.name} (${Math.max(1, Math.round(m.file.size / 1024))} KB)`; row.append(a); }
    }
    if (m.deleted || m.body) { const body = document.createElement('p'); if (m.deleted) body.textContent = '삭제된 메시지입니다'; else body.append(richText(m.body)); row.append(body); }
    if (m.deleted) row.classList.add('deleted');
    if (!m.deleted && !m.mine && mentionsMe(m.body)) row.classList.add('mention-me');
    if (m.reactions?.length && !m.deleted) {
      const box = document.createElement('div'); box.className = 'reactions';
      for (const r of m.reactions) { const b = document.createElement('button'); b.type = 'button'; b.className = 'reaction' + (r.mine ? ' mine' : ''); b.textContent = `${r.emoji} ${r.count}`; b.addEventListener('click', () => react(m.id, r.emoji)); box.append(b); }
      row.append(box);
    }
    if (m.unread_by > 0 && !m.deleted) { const n = document.createElement('em'); n.className = 'unread-by'; n.title = '아직 읽지 않은 사람 수'; n.textContent = String(m.unread_by); row.append(n); }
    if (!m.deleted) row.append(messageTools(m, row));
    place(row);
    // @mention alarm (not on first load, not for my own messages, not while looking at this room)
    if (!chat.initial && !m.mine && mentionsMe(m.body)) {
      const viewing = document.querySelector('.view.active')?.dataset.view === 'chat' && !document.hidden;
      if (!viewing) { if (alarmSetting('popup', true)) toast(`@멘션 · ${displayName(m.sender)}`, (m.body || '').slice(0, 60), chat.room); if (alarmSetting('sound', true)) beep(); }
    }
    chat.lastId = m.id;
  }
  if (nearBottom || messages.some(m => m.mine)) log.scrollTop = log.scrollHeight;
}

async function react(id, emoji) {
  try { await api(`/api/chat/messages/${id}/react`, {method:'POST', body:{emoji}}); await chatReload(); }
  catch (error) { message(error.message); }
}
function setReply(m) {
  chat.replyTo = m ? { id: m.id, sender: m.sender, body: m.body || (m.file ? m.file.name : '') } : null;
  const bar = $('reply-bar'); bar.hidden = !chat.replyTo;
  if (chat.replyTo) { $('reply-text').textContent = `↪ ${displayName(m.sender)}에게 답장: ${chat.replyTo.body.slice(0, 80)}`; $('chat-form').elements.body.focus(); }
}

function messageTools(m, row) {
  const tools = document.createElement('span'); tools.className = 'msg-tools';
  const add = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.addEventListener('click', fn); tools.append(b); return b; };
  add('답장', () => setReply(m));
  add('공감', () => {
    if (row.querySelector('.react-picker')) return row.querySelector('.react-picker').remove();
    const pick = document.createElement('span'); pick.className = 'react-picker';
    for (const e of REACTIONS) { const b = document.createElement('button'); b.type = 'button'; b.textContent = e; b.addEventListener('click', () => react(m.id, e)); pick.append(b); }
    row.append(pick);
  });
  const canPin = chat.room !== 'main' || currentUser?.role === 'admin';
  if (canPin) add('공지', async () => { try { await api('/api/chat/pin', {method:'POST', body:{message_id:m.id}}); await loadPin(); message('공지로 고정했습니다.'); } catch (error) { message(error.message); } });
  if (m.mine && m.body) add('수정', async () => {
    const text = window.prompt('메시지 수정', m.body);
    if (text === null) return;
    if (!text.trim()) { message('내용을 입력하세요.'); return; }
    try { await api(`/api/chat/messages/${m.id}`, {method:'PATCH', body:{body:text}}); await chatReload(); }
    catch (error) { message(error.message); }
  });
  if (m.mine || currentUser?.role === 'admin') add('삭제', async () => {
    if (!window.confirm('이 메시지를 삭제할까요?')) return;
    try { await api(`/api/chat/messages/${m.id}`, {method:'DELETE'}); await chatReload(); }
    catch (error) { message(error.message); }
  });
  return tools;
}
async function loadPin() {
  const bar = $('pin-bar'); if (!bar) return;
  try {
    const { pin } = await api(`/api/chat/pin?room=${encodeURIComponent(chat.room)}`);
    bar.hidden = !pin; if (!pin) return;
    $('pin-text').textContent = `📌 ${displayName(pin.sender)}: ${pin.body || '(파일)'}`;
    $('pin-text').onclick = () => $('chat-log').querySelector(`.msg[data-id="${pin.message_id}"]`)?.scrollIntoView({block:'center', behavior:'smooth'});
    $('pin-clear').hidden = chat.room === 'main' && currentUser?.role !== 'admin';
    $('pin-clear').onclick = async () => { try { await api(`/api/chat/pin/${pin.message_id}`, {method:'DELETE'}); await loadPin(); } catch (error) { message(error.message); } };
  } catch { bar.hidden = true; }
}
async function loadProfiles() { try { profiles = await api('/api/profiles'); } catch { /* optional */ } }
async function chatReload() {
  const log = $('chat-log'); const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80; const top = log.scrollTop;
  const locals = [...log.querySelectorAll('.msg.local')];
  chat.lastId = 0; chat.lastDay = ''; chat.lastSender = null; log.replaceChildren(); await chatLoad();
  for (const node of locals) if (node.dataset.room === chat.room) log.append(node);
  await loadPin();
  log.scrollTop = atBottom ? log.scrollHeight : top;
}
// Always fetch in server order from the last id we have. If another change arrives while a
// fetch is running, remember it and fetch again, so simultaneous messages are never skipped.
async function chatLoad() {
  if (chat.loading) { chat.again = true; return; }
  chat.loading = true;
  try {
    do {
      chat.again = false;
      const room = chat.room;
      const rows = await api(`${chatRoomPath()}?after=${chat.lastId}`);
      if (room === chat.room) chatAppend(rows);
    } while (chat.again);
  } finally { chat.loading = false; chat.initial = false; }
}

function chatTitle() {
  if (chat.room === 'main') return '# 전체 채팅';
  if (chat.room.startsWith('g')) { const g = chat.groups.find(x => 'g' + x.id === chat.room); return `# ${g ? g.name : '그룹'} (그룹 채팅)`; }
  const p = chat.peers.find(x => 'u' + x.id === chat.room); return `${p ? p.username : '멤버'}님과 1:1 대화`;
}

async function chatOpen(key) {
  chat.room = key; chat.lastId = 0; chat.lastDay = ''; chat.lastSender = null; chat.initial = true; setReply(null); $('chat-log').replaceChildren(); $('chat-title').textContent = chatTitle();
  try { await chatLoad(); await chatPeople(); await loadPin(); $('chat-form').elements.body.focus(); }
  catch (error) {
    message(error.message);
    if (key !== 'main') { chat.room = 'main'; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = chatTitle(); }
  }
}

async function chatTick(reload = false) {
  if (!chat.started) return;
  try { if (reload) await chatReload(); else await chatLoad(); }
  catch (error) { if (chat.room !== 'main') { chat.room = 'main'; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = chatTitle(); } else throw error; }
  await chatPeople();
}
async function chatStart() { chat.started = true; chat.room = 'main'; chat.lastId = 0; chat.lastDay = ''; chat.lastSender = null; chat.initial = true; $('chat-log').replaceChildren(); $('chat-title').textContent = '# 전체 채팅'; await loadProfiles(); await chatTick(); await loadPin(); }
function chatReset() { chat.rooms = null; chat.started = false; chat.lastId = 0; chat.room = 'main'; chat.groups = []; $('chat-log')?.replaceChildren(); $('chat-rooms')?.replaceChildren(); showUnread(0); document.title = BASE_TITLE; }

window.addEventListener('DOMContentLoaded', () => {
  // KakaoTalk-style sending: a local bubble appears at once ("전송 중"), is replaced by the server copy
  // on success, or turns into "전송 실패" with 재전송/삭제. Sends stay in order; the box clears immediately.
  let sendQueue = Promise.resolve();
  function sendLocal(node) {
    const { path, text, reply } = node.dataset;
    node.classList.remove('failed'); node.classList.add('sending');
    node.querySelector('small').textContent = '나 · 전송 중…';
    node.querySelector('.local-actions')?.remove();
    sendQueue = sendQueue.then(async () => {
      try {
        if (node._file) { const fd = new FormData(); fd.append('file', node._file); if (text) fd.append('body', text); await api(path, {method:'POST', body:fd}); }
        else await api(path, {method:'POST', body: reply ? {body:text, reply_to:Number(reply)} : {body:text}});
        node.remove(); await chatLoad();
      } catch (error) {
        node.classList.remove('sending'); node.classList.add('failed');
        node.querySelector('small').textContent = '나 · 전송 실패';
        const actions = document.createElement('span'); actions.className = 'local-actions';
        const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '재전송';
        const drop = document.createElement('button'); drop.type = 'button'; drop.textContent = '삭제';
        retry.addEventListener('click', () => sendLocal(node));
        drop.addEventListener('click', () => node.remove());
        actions.append(retry, drop); node.append(actions);
        message(error.message);
      }
    });
  }
  $('chat-form').addEventListener('submit', event => {
    event.preventDefault();
    const input = event.target.elements.body; const text = input.value.trim();
    if (!text) return;
    input.value = ''; input.focus();
    queueLocal(text, null);
  });
  function fileEndpoint() {
    if (chat.room === 'main') return '/api/chat/main/0/files';
    if (chat.room.startsWith('g')) return `/api/chat/group/${chat.room.slice(1)}/files`;
    return `/api/chat/dm/${chat.room.slice(1)}/files`;
  }
  function queueLocal(text, file) {
    const node = document.createElement('div'); node.className = 'msg mine local sending';
    node.dataset.path = file ? fileEndpoint() : chatRoomPath(); node.dataset.text = text; node.dataset.room = chat.room;
    if (chat.replyTo && !file) node.dataset.reply = String(chat.replyTo.id);
    node._file = file;
    const meta = document.createElement('small'); meta.textContent = '나 · 전송 중…';
    const body = document.createElement('p'); body.textContent = file ? `📎 ${file.name}${text ? ' · ' + text : ''}` : text;
    node.append(meta, body);
    const log = $('chat-log'); log.querySelector('.chat-empty')?.remove(); log.append(node); log.scrollTop = log.scrollHeight;
    setReply(null);
    sendLocal(node);
  }
  $('chat-attach').addEventListener('click', () => $('chat-file').click());
  $('chat-file').addEventListener('change', () => {
    const f = $('chat-file').files[0]; $('chat-file').value = '';
    if (!f) return;
    if (!/\.(png|jpe?g|gif|pdf|txt)$/i.test(f.name)) { message('PNG, JPG, GIF, PDF, TXT 파일만 보낼 수 있습니다.'); return; }
    if (f.size > 1536 * 1024) { message('파일은 1.5MiB까지 보낼 수 있습니다.'); return; }
    const input = $('chat-form').elements.body; const caption = input.value.trim(); input.value = '';
    queueLocal(caption, f);
  });
  $('reply-cancel').addEventListener('click', () => setReply(null));
  // chat search
  let searchTimer = null;
  $('chat-search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    const q = $('chat-search').value.trim(); const box = $('chat-search-results');
    if (!q) { box.hidden = true; box.replaceChildren(); return; }
    searchTimer = setTimeout(async () => {
      try {
        const rows = await api(`/api/chat/search?q=${encodeURIComponent(q)}`);
        box.replaceChildren(); box.hidden = false;
        if (!rows.length) { const p = document.createElement('p'); p.className = 'muted'; p.textContent = '검색 결과가 없습니다.'; box.append(p); return; }
        for (const r of rows) {
          const b = document.createElement('button'); b.type = 'button'; b.className = 'search-hit';
          const t = document.createElement('strong'); t.textContent = `${r.room_label} · ${displayName(r.sender)}`;
          const p = document.createElement('span'); p.textContent = r.body; const sm = document.createElement('small'); sm.textContent = new Date(r.created).toLocaleString();
          b.append(t, p, sm);
          b.addEventListener('click', async () => { box.hidden = true; $('chat-search').value = ''; await chatOpen(r.room); const el = $('chat-log').querySelector(`.msg[data-id="${r.id}"]`); if (el) { el.scrollIntoView({block:'center'}); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1600); } });
          box.append(b);
        }
      } catch (error) { message(error.message); }
    }, 250);
  });
  $('chat-people-search').addEventListener('input', () => chatPeople().catch(() => {}));
  const toggle = $('notify-toggle'), state = $('notify-state');
  const draw = () => {
    let on = false; try { on = localStorage.getItem('kosmos-notify') === 'on'; } catch {}
    const perm = 'Notification' in window ? Notification.permission : 'unsupported';
    toggle.textContent = on && perm === 'granted' ? '알림 끄기' : '알림 켜기';
    state.textContent = perm === 'unsupported' ? '이 브라우저는 알림을 지원하지 않습니다.' : perm === 'denied' ? '브라우저 설정에서 이 사이트 알림이 차단되어 있습니다.' : on && perm === 'granted' ? '켜짐' : '꺼짐';
  };
  toggle.addEventListener('click', async () => {
    if (!('Notification' in window)) return draw();
    let on = false; try { on = localStorage.getItem('kosmos-notify') === 'on'; } catch {}
    if (on) { try { localStorage.setItem('kosmos-notify', 'off'); } catch {} return draw(); }
    const perm = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
    if (perm === 'granted') { try { localStorage.setItem('kosmos-notify', 'on'); } catch {} }
    draw();
  });
  draw();
  for (const [id, name] of [['alarm-popup', 'popup'], ['alarm-sound', 'sound']]) {
    const box = $(id); box.checked = alarmSetting(name, true);
    box.addEventListener('change', () => { setAlarmSetting(name, box.checked); if (name === 'sound' && box.checked) beep(); });
  }
});
