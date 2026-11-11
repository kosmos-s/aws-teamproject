'use strict';
// Team chat: main room, group rooms ('g<id>') and 1:1 rooms ('u<id>'). Text is always set with textContent.
const chat = { room: 'main', lastId: 0, peers: [], groups: [], loading: false, started: false };
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

function showUnread(total) {
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
    const meta = document.createElement('small'); meta.textContent = `${m.mine ? '나' : m.sender} · ${chatTime(m.created)}`;
    const body = document.createElement('p'); body.textContent = m.body;
    row.append(meta, body); log.append(row); chat.lastId = m.id;
  }
  if (nearBottom || messages.some(m => m.mine)) log.scrollTop = log.scrollHeight;
}

async function chatLoad() {
  if (chat.loading) return; chat.loading = true;
  try { chatAppend(await api(`${chatRoomPath()}?after=${chat.lastId}`)); }
  finally { chat.loading = false; }
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

async function chatTick() {
  if (!chat.started) return;
  try { await chatLoad(); }
  catch (error) { if (chat.room !== 'main') { chat.room = 'main'; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = chatTitle(); } else throw error; }
  await chatPeople();
}
async function chatStart() { chat.started = true; chat.room = 'main'; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = '# 전체 채팅'; await chatTick(); }
function chatReset() { chat.started = false; chat.lastId = 0; chat.room = 'main'; chat.groups = []; $('chat-log')?.replaceChildren(); $('chat-rooms')?.replaceChildren(); showUnread(0); document.title = BASE_TITLE; }

window.addEventListener('DOMContentLoaded', () => {
  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    const input = event.target.elements.body; const text = input.value.trim();
    if (!text) return;
    const button = event.target.querySelector('button'); button.disabled = true;
    try { chatAppend([await api(chatRoomPath(), {method:'POST', body:{body:text}})]); input.value = ''; }
    catch (error) { message(error.message); }
    finally { button.disabled = false; input.focus(); }
  });
  $('chat-people-search').addEventListener('input', () => chatPeople().catch(() => {}));
});
