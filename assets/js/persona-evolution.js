(function () {
  'use strict';
  var state = null, busy = false, loading = false, signature = '', goalDraft = '';
  function safe(value) { return esc(String(value == null ? '' : value)); }
  function selected() { return _personaCreating ? '' : (_selectedPersona || _activePersona || ''); }
  function timeLabel(value) { return new Date(Number(value) * 1000).toLocaleString(); }
  async function call(path, data) {
    var result = await api('POST', '/api/persona-evolution/' + path, data || {});
    if (!result.ok) throw new Error(result.message || '操作失败');
    return result;
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      var result = await api('GET', '/api/persona-evolution');
      if (!result.ok) throw new Error(result.message || '加载失败');
      state = result;
      render();
    } catch (error) {
      var box = document.getElementById('personaEvolutionBox');
      if (box && !state) box.innerHTML = '<p class="pe-note">人格进化加载失败：' + safe(error.message) + '</p>';
    } finally { loading = false; }
  }
  function render() {
    var box = document.getElementById('personaEvolutionBox');
    if (!box || !state) return;
    var key = selected(), nextSignature = JSON.stringify([state, key, busy]);
    if (signature === nextSignature && box.children.length) return;
    var goal = box.querySelector('[data-pe-goal]');
    if (goal) goalDraft = goal.value;
    signature = nextSignature;
    var overlay = state.overlays.find(function (item) { return item.persona_key === key; });
    var backups = state.backups.filter(function (item) { return item.persona_key === key; });
    var proposals = state.proposals.filter(function (item) { return item.persona_key === key; }).slice(0, 5);
    var disabled = busy ? ' disabled' : '';
    var html = '<header class="pe-heading"><div><span class="pe-beta">EXPERIMENT · 测试功能</span><h2>人格进化</h2><p>保留原本的你，只试着让表达更合适。</p></div><button type="button" class="pe-switch" role="switch" aria-label="人格进化测试开关" aria-checked="' + state.enabled + '" data-pe-toggle' + disabled + '><span></span></button></header>';
    html += '<div class="pe-safety"><strong>' + (state.enabled ? '已开启 · 人工审核模式' : '默认关闭 · 不会自动生成或改写人格') + '</strong><p>开启前须阅读10秒风险提示，服务器确认后保存原始提示词。进化只添加经过审核的表达风格，不改变身份、主人关系、硬性规则或安全边界。</p></div>';
    html += '<div class="pe-target"><strong>当前选择：' + safe(key || '请先保存人格') + '</strong><span>' + (overlay ? (overlay.effective ? '表达附加层已生效' : '附加层已停用（开关关闭或基础人格已改动）') : '使用基础人格') + '</span></div>';
    if (state.enabled && key) {
      html += '<label class="pe-goal-label">希望如何优化表达？<textarea data-pe-goal maxlength="1000" rows="3" placeholder="例如：讨论技术时先给结论，日常聊天温和自然。">' + safe(goalDraft) + '</textarea></label><div class="pe-actions"><button type="button" class="btn btn-pr" data-pe-generate' + disabled + '>' + (busy ? '处理中…' : '生成风格建议') + '</button><small>手动触发 · 每60秒最多一次 · 可能消耗AI额度</small></div>';
    }
    if (overlay) html += '<div class="pe-current"><strong>已保存的表达附加层</strong><ul>' + styleList(overlay.styles) + '</ul><button type="button" class="btn btn-out btn-sm" data-pe-restore' + disabled + '>恢复基础人格效果</button></div>';
    html += '<div class="pe-columns"><div><h3>原始人格备份 <span>' + backups.length + '</span></h3><p class="pe-note">按内容版本保存在本账号本地；关闭、恢复附加层不删除备份。</p>';
    html += backups.length ? backups.slice(0, 5).map(function (item) { return '<button type="button" class="pe-backup" data-pe-backup="' + Number(item.id) + '"><span>查看原始提示词</span><small>' + safe(timeLabel(item.created)) + '</small></button>'; }).join('') : '<p class="pe-empty">尚未开启，没有实验备份。原人格仍保持不变。</p>';
    html += '</div><div><h3>待审核与最近建议</h3>';
    html += proposals.length ? proposals.map(function (item) {
      var labels = {pending: '待审核', applied: '已应用', restored: '已恢复'};
      return '<article class="pe-proposal"><div class="pe-proposal-meta"><span>' + safe(item.stale ? '已失效，需重新生成' : labels[item.status] || item.status) + '</span><small>' + safe(timeLabel(item.created)) + '</small></div><ul>' + styleList(item.styles) + '</ul><p>' + safe(item.rationale) + '</p>' + (state.enabled && item.status === 'pending' && !item.stale ? '<button type="button" class="btn btn-out btn-sm" data-pe-apply="' + safe(item.id) + '"' + disabled + '>审核并应用</button>' : '') + '</article>';
    }).join('') : '<p class="pe-empty">尚无建议。开启后手动生成，不会后台自动进化。</p>';
    box.innerHTML = html + '</div></div>';
    box.querySelector('[data-pe-toggle]').addEventListener('click', toggle);
    var input = box.querySelector('[data-pe-goal]');
    if (input) input.addEventListener('input', function () { goalDraft = input.value; });
    var generateButton = box.querySelector('[data-pe-generate]');
    if (generateButton) generateButton.addEventListener('click', generate);
    var restoreButton = box.querySelector('[data-pe-restore]');
    if (restoreButton) restoreButton.addEventListener('click', restore);
    box.querySelectorAll('[data-pe-backup]').forEach(function (button) { button.addEventListener('click', function () { showBackup(button.dataset.peBackup); }); });
    box.querySelectorAll('[data-pe-apply]').forEach(function (button) { button.addEventListener('click', function () { apply(button.dataset.peApply); }); });
  }
  function styleList(styles) {
    return Object.keys(styles).map(function (field) { return '<li>' + safe((state.choices[field] || {})[styles[field]] || styles[field]) + '</li>'; }).join('');
  }
  async function perform(action) {
    if (busy) return;
    busy = true; render();
    try { var result = await action(); if (result.message) toast(result.message, 'ok'); }
    catch (error) { toast(error.message || '操作失败', 'err'); }
    finally { busy = false; await refresh(); render(); }
  }
  async function toggle() {
    if (busy) return;
    if (state.enabled) return perform(function () { return call('disable'); });
    if (_personaDirty) { toast('请先保存人格编辑，再开启测试功能', 'err'); return; }
    busy = true; render();
    try { var challenge = await call('challenge'); await consent(challenge); }
    catch (error) { toast(error.message || '开启失败', 'err'); }
    finally { busy = false; await refresh(); render(); }
  }
  function consent(challenge) {
    return new Promise(function (resolve) {
      var dialog = document.createElement('dialog');
      dialog.className = 'pe-consent'; dialog.setAttribute('aria-labelledby', 'peConsentTitle');
      dialog.innerHTML = '<div class="pe-dialog-body"><span class="pe-beta">请认真阅读 · 测试风险</span><h2 id="peConsentTitle">允许人格表达进化？</h2><p>这是测试功能，表达可能与你的预期不同。开启并不自动调用AI，每条建议都需要你审核。</p><ul><li>确认后先备份所有已保存的原始人格提示词与规则。</li><li>原提示词不被覆盖，附加层只影响表达风格。</li><li>生成时会将选定人格与优化目标发送至已配置的AI，可能产生额度消耗。</li><li>可随时关闭或恢复基础人格效果，备份不会被删除。</li></ul><div class="pe-countdown" role="status" aria-live="polite"></div><progress class="pe-progress" max="10" value="0" aria-label="风险阅读倒计时"></progress><div class="pe-actions"><button type="button" class="btn btn-out" data-pe-cancel>取消</button><button type="button" class="btn btn-pr" data-pe-confirm disabled>请等待10秒</button></div></div>';
      document.body.appendChild(dialog);
      var confirmButton = dialog.querySelector('[data-pe-confirm]'), cancelButton = dialog.querySelector('[data-pe-cancel]');
      var start = performance.now(), finished = false, confirming = false;
      function tick() {
        var elapsed = Math.min(10, (performance.now() - start) / 1000), remaining = Math.ceil(10 - elapsed);
        dialog.querySelector('progress').value = elapsed;
        dialog.querySelector('[role="status"]').textContent = remaining ? '请阅读风险说明 · 剩余 ' + remaining + ' 秒' : '阅读时间已满，可以确认开启。';
        confirmButton.disabled = remaining > 0 || confirming;
        confirmButton.textContent = remaining ? '请等待' + remaining + '秒' : confirming ? '正在备份并开启…' : '确认备份并开启';
      }
      var timer = setInterval(tick, 100); tick(); dialog.showModal(); cancelButton.focus();
      function finish() { if (finished) return; finished = true; clearInterval(timer); dialog.close(); dialog.remove(); resolve(); }
      async function cancel() {
        if (confirming) return;
        try { await call('cancel', {token: challenge.token}); } catch (error) { toast('取消确认失败，但功能未由此次弹窗开启', 'err'); }
        finish();
      }
      cancelButton.addEventListener('click', cancel);
      dialog.addEventListener('cancel', function (event) { event.preventDefault(); cancel(); });
      confirmButton.addEventListener('click', async function () {
        if (confirming || (performance.now() - start) < 10000) return;
        confirming = true; cancelButton.disabled = true; tick();
        try { var result = await call('confirm', {token: challenge.token}); toast(result.message, 'ok'); finish(); }
        catch (error) { toast(error.message, 'err'); confirming = false; cancelButton.disabled = false; tick(); }
      });
    });
  }
  async function generate() {
    var key = selected(), goal = goalDraft.trim();
    if (!goal) { toast('请输入表达优化目标', 'err'); return; }
    if (_personaDirty) { toast('请先保存人格，建议只针对已保存内容', 'err'); return; }
    if (!await panelConfirm('生成表达建议', '将“' + key + '”的完整已保存人格及优化目标发送给已配置的AI。可能消耗额度；不会自动应用。是否继续？', '确认生成')) return;
    return perform(function () { return call('generate', {key: key, goal: goal, confirmed: true}); });
  }
  async function apply(identity) {
    if (!await panelConfirm('应用风格建议', '只叠加这条建议中的固定表达风格，不覆盖基础提示词。关闭功能可停用，恢复基础人格可移除。', '确认应用')) return;
    return perform(function () { return call('apply', {id: identity, confirmed: true}); });
  }
  async function restore() {
    var key = selected();
    if (!await panelConfirm('恢复基础人格效果', '移除“' + key + '”的表达附加层，并取消尚待审核的旧建议。不会覆盖你手动编辑的基础人格，原始备份保留。', '确认恢复')) return;
    return perform(function () { return call('restore', {key: key, confirmed: true}); });
  }
  async function showBackup(identity) {
    try {
      var result = await api('GET', '/api/persona-evolution/backups/' + identity);
      if (!result.ok) throw new Error(result.message || '读取失败');
      openReviewModal('原始人格备份 · ' + result.backup.persona_key,
        '<p>这是实验前的完整基础人格快照，包括原始提示词、偏好与规则。仅在本地查看，未发送给AI。</p><pre class="pe-backup-text">' + safe(JSON.stringify(result.backup.original, null, 2)) + '</pre>',
        '<button type="button" class="btn btn-out" onclick="closeReviewModal()">关闭</button><button type="button" class="btn btn-pr" id="peDownloadBackup">下载备份 JSON</button>');
      document.getElementById('peDownloadBackup').addEventListener('click', function () {
        var url = URL.createObjectURL(new Blob([JSON.stringify(result.backup, null, 2)], {type: 'application/json'}));
        var anchor = document.createElement('a'); anchor.href = url; anchor.download = 'persona-original-' + identity + '.json'; anchor.click();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      });
    } catch (error) { toast(error.message, 'err'); }
  }
  window.refreshPersonaEvolution = refresh;
  window.renderPersonaEvolution = render;
  if (document.querySelector('#pg-psna.on')) refresh();
}());
