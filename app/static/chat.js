'use strict';
// Team chat: main room, group rooms ('g<id>') and 1:1 rooms ('u<id>'). Text is always set with textContent.
const chat = { room: 'main', lastId: 0, peers: [], groups: [], loading: false, started: false, lastTotal: 0, rooms: null };
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

function chatAppend(messages) {
  const log = $('chat-log');
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  if (chat.lastId === 0 && !messages.length && !log.querySelector('.chat-empty')) {
    const empty = document.createElement('p'); empty.className = 'chat-empty'; empty.textContent = '아직 메시지가 없습니다. 첫 메시지를 남겨 보세요.'; log.append(empty);
  }
  if (messages.length) log.querySelector('.chat-empty')?.remove();
  for (const m of messages) {
    if (m.id <= chat.lastId) continue;
    const row = document.createElement('div'); row.className = 'msg' + (m.mine ? ' mine' : '');
    const meta = document.createElement('small'); meta.textContent = `${m.mine ? '나' : m.sender} · ${chatTime(m.created)}${m.edited ? ' · 수정됨' : ''}`;
    const body = document.createElement('p'); body.textContent = m.deleted ? '삭제된 메시지입니다' : m.body;
    if (m.deleted) row.classList.add('deleted');
    row.append(meta, body);
    if (!m.deleted && (m.mine || currentUser?.role === 'admin')) row.append(messageTools(m, row));
    log.append(row); chat.lastId = m.id;
  }
  if (nearBottom || messages.some(m => m.mine)) log.scrollTop = log.scrollHeight;
}

function messageTools(m, row) {
  const tools = document.createElement('span'); tools.className = 'msg-tools';
  if (m.mine) {
    const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = '수정';
    edit.addEventListener('click', async () => {
      const text = window.prompt('메시지 수정', m.body);
      if (text === null) return;
      if (!text.trim()) { message('내용을 입력하세요.'); return; }
      try { await api(`/api/chat/messages/${m.id}`, {method:'PATCH', body:{body:text}}); await chatReload(); }
      catch (error) { message(error.message); }
    });
    tools.append(edit);
  }
  const del = document.createElement('button'); del.type = 'button'; del.textContent = '삭제';
  del.addEventListener('click', async () => {
    if (!window.confirm('이 메시지를 삭제할까요?')) return;
    try { await api(`/api/chat/messages/${m.id}`, {method:'DELETE'}); await chatReload(); }
    catch (error) { message(error.message); }
  });
  tools.append(del);
  return tools;
}
async function chatReload() {
  const log = $('chat-log'); const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80; const top = log.scrollTop;
  chat.lastId = 0; log.replaceChildren(); await chatLoad();
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
  } finally { chat.loading = false; }
}

function chatTitle() {
  if (chat.room === 'main') return '# 전체 채팅';
  if (chat.room.startsWith('g')) { const g = chat.groups.find(x => 'g' + x.id === chat.room); return `# ${g ? g.name : '그룹'} (그룹 채팅)`; }
  const p = chat.peers.find(x => 'u' + x.id === chat.room); return `${p ? p.username : '멤버'}님과 1:1 대화`;
}

async function chatOpen(key) {
  chat.room = key; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = chatTitle();
  try { await chatLoad(); await chatPeople(); $('chat-form').elements.body.focus(); }
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
async function chatStart() { chat.started = true; chat.room = 'main'; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = '# 전체 채팅'; await chatTick(); }
function chatReset() { chat.rooms = null; chat.started = false; chat.lastId = 0; chat.room = 'main'; chat.groups = []; $('chat-log')?.replaceChildren(); $('chat-rooms')?.replaceChildren(); showUnread(0); document.title = BASE_TITLE; }

window.addEventListener('DOMContentLoaded', () => {
  // Sends are queued in order; the box is cleared immediately so typing the next message is never lost.
  let sendQueue = Promise.resolve();
  $('chat-form').addEventListener('submit', event => {
    event.preventDefault();
    const input = event.target.elements.body; const text = input.value.trim();
    if (!text) return;
    const path = chatRoomPath();
    input.value = ''; input.focus();
    sendQueue = sendQueue.then(async () => {
      try { await api(path, {method:'POST', body:{body:text}}); await chatLoad(); }
      catch (error) {
        message(error.message);
        if (!input.value) input.value = text;  // give the unsent text back
      }
    });
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
