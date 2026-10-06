(() => {
  const byId = id => document.getElementById(id);
  let definitions = {};
  let busy = false;
  function status(text) { byId('permission-status').textContent = text; }
  async function call(url, payload) {
    const response = await fetch(url, payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const body = await response.json();
    if (!response.ok || !body.ok) throw new Error(body.message || '操作失败');
    return body;
  }
  async function load() {
    try {
      const [permissions, favorites, switches] = await Promise.all([call('/api/ai-permissions'), call('/api/collection-settings'), call('/api/interaction-switches')]);
      definitions = permissions.definitions;
      byId('permission-master').checked = permissions.enabled;
      const grid = byId('permission-actions'); grid.replaceChildren();
      const groups = {};
      for (const scope of ['local', 'platform']) {
        const section = document.createElement('section'); section.className = 'permission-scope';
        const heading = document.createElement('h4'); heading.textContent = scope === 'local' ? '本地能力' : '平台写操作';
        const intro = document.createElement('p'); intro.textContent = scope === 'local' ? '只影响当前项目，学习与整理默认可用。' : '需同时开启总授权，并遵守人工审核。请只选择必要操作。';
        const cards = document.createElement('div'); cards.className = 'permission-scope-grid';
        section.append(heading, intro, cards); grid.append(section); groups[scope] = cards;
      }
      for (const [key, definition] of Object.entries(definitions).sort((left, right) => left[1].scope.localeCompare(right[1].scope))) {
        const label = document.createElement('label'); label.className = 'permission-card';
        const input = document.createElement('input'); input.type = 'checkbox'; input.dataset.permission = key; input.checked = permissions.actions[key];
        const text = document.createElement('span'); text.textContent = definition.label;
        const hint = document.createElement('small'); hint.textContent = definition.scope === 'local' ? '本地能力 · 不受平台总开关影响' : '平台写操作 · 需要总授权';
        label.append(input, text, hint); (groups[definition.scope] || groups.platform).append(label);
      }
      const settings = favorites.settings;
      byId('permission-destination').value = settings.destination;
      byId('permission-folder').value = settings.folder_name;
      byId('permission-score').value = settings.min_score;
      byId('permission-collect').checked = settings.auto_collect_enabled;
      byId('permission-interest').checked = settings.require_interest_match;
      if (byId('subtitle-master')) byId('subtitle-master').checked = switches.switches.subtitles_enabled;
      status('已读取当前账号权限。平台总开关：' + (permissions.enabled ? '已授权' : '关闭'));
    } catch (error) { status(error.message); }
  }
  async function save(lock = false) {
    if (busy) return;
    busy = true; byId('permission-save').disabled = true;
    try {
      const actions = {};
      for (const input of document.querySelectorAll('[data-permission]')) {
        const key = input.dataset.permission;
        actions[key] = lock && definitions[key].scope === 'platform' ? false : input.checked;
      }
      const enabled = !lock && byId('permission-master').checked;
      if (enabled && !await panelConfirm('授权平台操作', '仅授权已勾选的操作。B 站可能风控；投币与删除等操作存在风险。', '确认授权')) return;
      await call('/api/ai-permissions', {enabled, actions});
      if (!lock) await call('/api/collection-settings', {destination: byId('permission-destination').value, folder_name: byId('permission-folder').value, min_score: Number(byId('permission-score').value), auto_collect_enabled: byId('permission-collect').checked, require_interest_match: byId('permission-interest').checked});
      await load(); status(lock ? '平台总授权及所有平台权限已关闭。' : '当前账号设置已保存。');
    } catch (error) { status(error.message); }
    finally { busy = false; byId('permission-save').disabled = false; }
  }
  async function platformRead(content) {
    const result = byId('platform-result'); result.textContent = '正在读取…';
    try {
      let url = '/api/platform-favorites';
      if (content) {
        const folder = Number(byId('platform-folder').value);
        if (!Number.isInteger(folder) || folder <= 0) throw new Error('请输入收藏夹 ID');
        url += '?media_id=' + folder;
      }
      const body = await call(url); result.textContent = JSON.stringify(body.data, null, 2);
    } catch (error) { result.textContent = error.message; }
  }
  async function platformSubmit() {
    const operation = byId('platform-operation').value;
    const payload = {};
    if (operation !== 'create') payload.media_id = Number(byId('platform-folder').value);
    if (['add', 'remove'].includes(operation)) payload.bvid = byId('platform-bvid').value.trim();
    if (['create', 'edit'].includes(operation)) { payload.title = byId('platform-title').value.trim(); payload.introduction = byId('platform-intro').value.trim(); payload.private = byId('platform-private').checked; }
    if (['copy', 'move'].includes(operation)) { payload.target_id = Number(byId('platform-target').value); payload.aids = byId('platform-aids').value.split(',').map(value => Number(value.trim())); }
    const button = byId('platform-submit'); button.disabled = true;
    try {
      if (!await panelConfirm('提交平台收藏夹操作', '只提交人工审核，不立即执行。请核对具体收藏夹和视频。', '提交审核')) return;
      const body = await call('/api/platform-favorites', {operation, payload});
      byId('platform-result').textContent = body.message + (body.review_id ? '\n审核编号：' + body.review_id : '');
    } catch (error) { byId('platform-result').textContent = error.message; }
    finally { button.disabled = false; }
  }
  function operationFields() {
    const operation = byId('platform-operation').value;
    const relevant = {'platform-folder': operation !== 'create', 'platform-target': ['copy', 'move'].includes(operation), 'platform-bvid': ['add', 'remove'].includes(operation), 'platform-aids': ['copy', 'move'].includes(operation), 'platform-title': ['create', 'edit'].includes(operation), 'platform-intro': ['create', 'edit'].includes(operation)};
    for (const [id, visible] of Object.entries(relevant)) byId(id).closest('.fg').hidden = !visible;
    byId('platform-private').closest('label').hidden = !['create', 'edit'].includes(operation);
  }
  document.addEventListener('DOMContentLoaded', () => {
    window.rf_ai_permissions = load;
    byId('platform-operation').addEventListener('change', operationFields);
    operationFields();
    byId('permission-save').addEventListener('click', () => save());
    byId('permission-lock').addEventListener('click', () => save(true));
    byId('permission-reload').addEventListener('click', load);
    byId('platform-list').addEventListener('click', () => platformRead(false));
    byId('platform-content').addEventListener('click', () => platformRead(true));
    byId('platform-submit').addEventListener('click', platformSubmit);
    byId('subtitle-master').addEventListener('change', async event => {
      try { await call('/api/interaction-switches', {subtitles_enabled: event.target.checked}); }
      catch (error) { event.target.checked = !event.target.checked; status(error.message); }
    });
    document.addEventListener('click', event => { if (event.target.closest('[data-pg="ai-permissions"], [data-pg="asr"]')) load(); });
    load();
  });
})();
