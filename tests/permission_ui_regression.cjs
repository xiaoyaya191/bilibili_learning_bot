const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {};
const nodes = new Map();
class Element {
  constructor() { this.checked=false; this.value=''; this.disabled=false; this.children=[]; this.dataset={}; this.events={}; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children=[]; }
  closest() { return {hidden:false}; }
  addEventListener(name, handler) { this.events[name]=handler; }
  matches() { return this === nodes.get('permission-master'); }
}
const byId = id => { if (!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id); };
byId('platform-operation').value='create';
byId('permission-score').value='7';
const document = {
  getElementById: byId,
  createElement: () => new Element(),
  addEventListener(name, fn) { (listeners[name] ||= []).push(fn); },
  querySelectorAll(selector) {
    const walk = node => node.children.flatMap(child => [child,...walk(child)]);
    const inputs = walk(byId('permission-actions')).filter(node => node.dataset.permission);
    return selector === '[data-permission]' ? inputs : [...inputs, byId('permission-master')];
  }
};
let stored = {enabled:false,actions:{follow_up:false},definitions:{follow_up:{label:'关注',scope:'platform'}}};
let defer=false;
let pending=[];
let revertAfterSave=false;
const payload = url => url === '/api/ai-permissions' ? {ok:true,...structuredClone(stored)} : url === '/api/collection-settings' ? {ok:true,settings:{destination:'local',folder_name:'默认',min_score:7,auto_collect_enabled:false,require_interest_match:false}} : {ok:true,switches:{subtitles_enabled:true}};
const response = body => ({ok:true,json:async()=>body});
async function fetch(url, options={}) {
  if (options.method === 'POST') {
    if (url === '/api/ai-permissions') Object.assign(stored,JSON.parse(options.body));
    if (url === '/api/collection-settings' && revertAfterSave) stored.enabled=false;
    return response({ok:true});
  }
  const snapshot=payload(url);
  if (defer) return new Promise(resolve=>pending.push(()=>resolve(response(snapshot))));
  return response(snapshot);
}
const tick = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const window={};
  vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{document,window,fetch,panelConfirm:async()=>true});
  listeners.DOMContentLoaded[0](); await tick();
  defer=true;
  const stale=window.rf_ai_permissions();
  byId('permission-master').checked=true;
  (listeners.change || []).forEach(fn=>fn({target:byId('permission-master')}));
  pending.splice(0).forEach(resolve=>resolve()); await stale;
  assert.equal(byId('permission-master').checked,true,'delayed GET must not erase edits');
  defer=false;
  document.querySelectorAll('[data-permission]')[0].checked=true;
  await byId('permission-save').events.click(); await tick();
  assert.equal(stored.enabled,true);
  assert.equal(stored.actions.follow_up,true);
  assert.match(byId('permission-status').textContent,/已保存并核验/);
  revertAfterSave=true;
  await byId('permission-save').events.click(); await tick();
  assert.match(byId('permission-status').textContent,/核验不一致/,'must not claim success if persistence reverts');
  assert.equal(byId('permission-save').disabled,false);
  console.log('Permission UI race and persistence verification passed');
})().catch(error=>{console.error(error);process.exitCode=1});
