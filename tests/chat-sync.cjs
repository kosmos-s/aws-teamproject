// Exercise the real client synchronization functions with a deterministic server and DOM boundary.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/chat.js', 'utf8').replace(/\r\n/g, '\n');
function declaration(name) {
  const start = source.indexOf(`async function ${name}(`);
  assert(start >= 0);
  return source.slice(start, source.indexOf('\n}\n', start) + 3);
}
const delivered = new Set([1]);
const messages = Array.from({length: 203}, (_, i) => ({id: i + 1, body: String(i + 1)}));
const log = {scrollHeight: 0, scrollTop: 0, clientHeight: 0, querySelectorAll: () => [], replaceChildren() {}, append() {}};
const context = vm.createContext({
  chat: {loading: false, again: false, lastId: 1, room: 'main', initial: false},
  document: {hidden: false, querySelector: () => ({dataset: {view: 'chat'}})},
  $: () => log, chatRoomPath: () => '/api/chat/main', loadPin: () => {},
  chatAppend: rows => {for (const m of rows) {delivered.add(m.id); context.chat.lastId = m.id;}},
  api: async path => {
    const url = new URL(path, 'http://local.test');
    const after = Number(url.searchParams.get('after') || 0);
    const before = Number(url.searchParams.get('before') || 0);
    const rows = messages.filter(m => m.id > after && (!before || m.id < before));
    return after && !before ? rows.slice(0, 200) : rows.slice(-200);
  }
});
vm.runInContext(declaration('chatLoad') + '\n' + declaration('chatReload'), context);
(async () => {
  await context.chatReload();
  assert(delivered.has(2), 'metadata refresh skipped the first unseen message');
  assert(delivered.has(203), 'catch-up failed to drain the second page');
  assert.equal(context.chat.lastId, 203);
  console.log('chat backlog + metadata refresh: passed');
  const appSource = fs.readFileSync('app/static/app.js', 'utf8').replace(/\r\n/g, '\n');
  const start = appSource.indexOf('function showLogin()');
  const nodes = new Map();
  const node = id => {if(!nodes.has(id))nodes.set(id,{textContent:'old-sensitive-value',value:'old-sensitive-value',hidden:false,reset(){this.resetCalled=true;},replaceChildren(){this.textContent='';}});return nodes.get(id);};
  const logoutContext = vm.createContext({$:node,currentUser:{username:'first'},csrf:'old',live:{last:{}},document:{title:'old'}});
  vm.runInContext(appSource.slice(start,appSource.indexOf('\n}\n',start)+3),logoutContext);
  logoutContext.showLogin();
  assert.equal(node('totp-secret').textContent,'');
  assert.equal(node('totp-setup').hidden,true);
  assert.equal(node('recovery-codes').textContent,'');
  assert.equal(node('reauth-password').value,'');
  assert.equal(node('projects').textContent,'');
  console.log('logout clears factor material: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
