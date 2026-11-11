'use strict';
// Team chat: one main room for everyone plus 1:1 rooms. Text is always set with textContent.
const chat = { room: 'main', lastId: 0, peers: [], loading: false, started: false };

function chatRoomPath() { return chat.room === 'main' ? '/api/chat/main' : `/api/chat/dm/${chat.room}`; }
function chatTime(iso) { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }

function chatRoomButton(label, key, unread, extra) {
  const b = document.createElement('button'); b.type = 'button';
  b.className = 'room' + (String(chat.room) === String(key) ? ' active' : '');
  const name = document.createElement('span'); name.textContent = label; b.append(name);
  if (extra) { const s = document.createElement('small'); s.textContent = extra; b.append(s); }
  if (unread > 0) { const badge = document.createElement('em'); badge.textContent = unread > 99 ? '99+' : String(unread); b.append(badge); }
  b.addEventListener('click', () => chatOpen(key));
  return b;
}

async function chatPeople() {
  const data = await api('/api/chat/people');
  chat.peers = data.people;
  const nav = $('chat-rooms'); nav.replaceChildren();
  nav.append(chatRoomButton('# 전체 채팅', 'main', chat.room === 'main' ? 0 : data.main_unread, '모든 멤버'));
  const head = document.createElement('p'); head.className = 'rooms-label'; head.textContent = `1:1 대화 · ${data.people.length}명`; nav.append(head);
  const filter = ($('chat-people-search')?.value || '').trim().toLowerCase();
  const sorted = [...data.people].sort((a, b) => (b.unread - a.unread) || (b.online - a.online) || a.username.localeCompare(b.username));
  for (const p of sorted) {
    if (filter && !p.username.toLowerCase().includes(filter)) continue;
    nav.append(chatRoomButton((p.online ? '● ' : '○ ') + p.username, p.id, String(chat.room) === String(p.id) ? 0 : p.unread, p.online ? '접속 중' : ''));
  }
  const total = data.main_unread + data.people.reduce((n, p) => n + p.unread, 0);
  $('chat-status').textContent = total ? `읽지 않은 메시지 ${total}개` : '새 메시지 없음';
}

function chatAppend(messages) {
  const log = $('chat-log');
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  if (chat.lastId === 0 && !messages.length) {
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

async function chatOpen(key) {
  chat.room = key; chat.lastId = 0; $('chat-log').replaceChildren();
  const peer = chat.peers.find(p => String(p.id) === String(key));
  $('chat-title').textContent = key === 'main' ? '# 전체 채팅' : `${peer ? peer.username : '멤버'}님과 1:1 대화`;
  try { await chatLoad(); await chatPeople(); $('chat-form').elements.body.focus(); }
  catch (error) { message(error.message); }
}

async function chatTick() { if (!chat.started) return; await chatLoad(); await chatPeople(); }
async function chatStart() { chat.started = true; chat.room = 'main'; chat.lastId = 0; $('chat-log').replaceChildren(); $('chat-title').textContent = '# 전체 채팅'; await chatTick(); }
function chatReset() { chat.started = false; chat.lastId = 0; chat.room = 'main'; $('chat-log')?.replaceChildren(); $('chat-rooms')?.replaceChildren(); }

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
