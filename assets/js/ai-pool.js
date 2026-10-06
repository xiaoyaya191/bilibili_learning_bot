(function () {
  'use strict';
  var preferences = null, health = [];
  var numeric = [
    ['rounds', '每次请求最多轮询轮数', 1, 10],
    ['attempt_limit', '每次请求总尝试上限', 1, 1000],
    ['total_timeout_seconds', '总耗时上限（秒）', 1, 3600],
    ['retry_delay_seconds', '初始重试等待（秒）', 0, 60],
    ['backoff_multiplier', '等待退避倍数', 1, 10],
    ['max_delay_seconds', '单次等待上限（秒）', 0, 300],
    ['failure_threshold', '连续失败冷却阈值', 1, 100],
    ['cooldown_seconds', '接口冷却时长（秒）', 0, 86400]
  ];
  function field(id, label, value, type, extra) {
    return '<div class="fg"><label for="' + id + '">' + label + '</label><input id="' + id + '" type="' + (type || 'text') + '" value="' + esc(String(value == null ? '' : value)) + '" ' + (extra || '') + '></div>';
  }
  function check(id, label, value) {return '<label class="ap-choice"><input id="' + id + '" type="checkbox" ' + (value ? 'checked' : '') + '> ' + label + '</label>';}
  function collect() {
    if (!preferences || !document.getElementById('ap-enabled')) return;
    ['enabled', 'include_primary', 'respect_retry_after', 'retry_network_errors'].forEach(function (key) {preferences[key] = document.getElementById('ap-' + key).checked;});
    preferences.strategy = document.getElementById('ap-strategy').value;
    numeric.forEach(function (item) {preferences[item[0]] = Number(document.getElementById('ap-' + item[0]).value);});
    ['retry_statuses', 'failover_statuses'].forEach(function (key) {preferences[key] = document.getElementById('ap-' + key).value.split(/[,，\s]+/).filter(Boolean).map(Number);});
    preferences.endpoints.forEach(function (endpoint) {
      var prefix = 'ap-' + endpoint.id + '-';
      ['name', 'base_url', 'api_key', 'model_chat', 'model_vision'].forEach(function (key) {endpoint[key] = document.getElementById(prefix + key).value.trim();});
      ['enabled', 'supports_vision', 'supports_tools'].forEach(function (key) {endpoint[key] = document.getElementById(prefix + key).checked;});
      ['weight', 'attempts', 'timeout_seconds'].forEach(function (key) {endpoint[key] = Number(document.getElementById(prefix + key).value);});
      var headers = document.getElementById(prefix + 'headers').value.trim();
      endpoint.headers = headers === '[已隐藏]' ? headers : JSON.parse(headers || '{}');
    });
  }
  function render() {
    var container = document.getElementById('aiPoolPanel');
    if (!container || !preferences) return;
    var html = '<div class="ap-switches">' + check('ap-enabled', '启用多API轮询', preferences.enabled) + check('ap-include_primary', '当前主API也参与', preferences.include_primary) + check('ap-respect_retry_after', '遵守服务端 Retry-After 冷却', preferences.respect_retry_after) + check('ap-retry_network_errors', '网络失败允许重试/切换', preferences.retry_network_errors) + '</div>';
    html += '<div class="fg"><label for="ap-strategy">选取策略</label><select id="ap-strategy"><option value="round_robin">顺序轮询（每次请求换起点）</option><option value="failover">按列表优先，失败才切换</option><option value="weighted">加权轮询（权重影响起点份额）</option><option value="random">随机起点</option></select></div><div class="ap-grid">';
    numeric.forEach(function (item) {html += field('ap-' + item[0], item[1], preferences[item[0]], 'number', 'min="' + item[2] + '" max="' + item[3] + '" step="1"');});
    html += field('ap-retry_statuses', '同接口允许重试的状态码', preferences.retry_statuses.join(', '));
    html += field('ap-failover_statuses', '允许切换其他接口的状态码', preferences.failover_statuses.join(', '));
    html += '</div><p class="form-hint">400/422 请求或安全拒绝不重放；401/402/403 不重复使用同一密钥。失败接口独立冷却，不拖住其他接口。0秒等待/冷却有效；轮数和总请求上限同时限制额度。冷却中的接口会跳过，全部冷却时立即返回。Retry-After 最多保存24小时。</p><div class="btn-grp"><button type="button" class="btn btn-pr" id="ap-save">保存接口池</button><button type="button" class="btn btn-out" id="ap-add">添加接口</button><button type="button" class="btn btn-out" id="ap-refresh">刷新设置与统计</button><button type="button" class="btn btn-out" id="ap-reset">重置冷却与统计</button></div><p class="form-hint">刷新会重新读取已保存设置，请先保存编辑。主API位于配置顶部；旧备用提供商在接口池开启时不自动加入，可在下方显式添加。</p><div class="ap-endpoints">';
    preferences.endpoints.forEach(function (endpoint, index) {
      var prefix = 'ap-' + endpoint.id + '-';
      var state = health.find(function (item) {return item.id === endpoint.id;}) || {};
      html += '<section class="ap-endpoint"><div class="v2w-block-head"><h3>' + esc(endpoint.name || endpoint.id) + '</h3><span class="form-hint">' + (index + 1) + ' / ' + preferences.endpoints.length + '</span></div><p class="form-hint">ID：' + esc(endpoint.id) + ' · 调用 ' + Number(state.calls || 0) + ' · 成功 ' + Number(state.successes || 0) + ' · 冷却 ' + Number(state.cooldown_remaining || 0) + '秒 · 状态 ' + esc(state.last_status || '未调用') + '</p><div class="ap-switches">' + check(prefix + 'enabled', '启用此接口', endpoint.enabled) + check(prefix + 'supports_vision', '允许视觉请求', endpoint.supports_vision) + check(prefix + 'supports_tools', '允许工具请求', endpoint.supports_tools) + '</div><div class="ap-grid">';
      html += field(prefix + 'name', '接口名称', endpoint.name);
      html += field(prefix + 'base_url', '接口 Base URL', endpoint.base_url, 'url');
      html += field(prefix + 'api_key', 'API Key（清空并保存可删除）', endpoint.api_key, 'password', 'autocomplete="new-password"');
      html += field(prefix + 'model_chat', '接口对话模型（空=调用方模型）', endpoint.model_chat);
      html += field(prefix + 'model_vision', '接口视觉模型（空=调用方模型）', endpoint.model_vision);
      html += field(prefix + 'weight', '轮询权重（1–100）', endpoint.weight, 'number', 'min="1" max="100"');
      html += field(prefix + 'attempts', '每轮此接口最多尝试（1–5）', endpoint.attempts, 'number', 'min="1" max="5"');
      html += field(prefix + 'timeout_seconds', '此接口超时上限（秒）', endpoint.timeout_seconds, 'number', 'min="1" max="1800"');
      html += '<div class="fg"><label for="' + prefix + 'headers">自定义请求头 JSON（整体保密）</label><textarea id="' + prefix + 'headers" rows="3" placeholder="{}">' + esc(endpoint.headers === '[已隐藏]' ? endpoint.headers : JSON.stringify(endpoint.headers)) + '</textarea></div></div><p class="form-hint">密钥/请求头保存后不返回明文；[已隐藏]表示保留，按ID匹配，不受排序影响。超时取此接口上限与调用方超时较小值，受总耗时进一步限制。视觉/工具能力为用户声明；测试仅验证文本。</p><div class="btn-grp"><button type="button" class="btn btn-out btn-sm" data-ap-up="' + endpoint.id + '" ' + (!index ? 'disabled' : '') + '>上移</button><button type="button" class="btn btn-out btn-sm" data-ap-down="' + endpoint.id + '" ' + (index === preferences.endpoints.length - 1 ? 'disabled' : '') + '>下移</button><button type="button" class="btn btn-out btn-sm" data-ap-test="' + endpoint.id + '">测试已保存接口</button><button type="button" class="btn btn-out btn-sm" data-ap-delete="' + endpoint.id + '">移除此接口</button></div></section>';
    });
    html += '</div>';
    if (!preferences.endpoints.length) html += '<p class="form-hint">尚未添加自定义接口。可保留主API，再添加不同地址、密钥和模型的接口。</p>';
    if (health.some(function (item) {return item.id === 'primary';})) {
      var primary = health.find(function (item) {return item.id === 'primary';});
      html += '<p class="form-hint">主API：调用 ' + primary.calls + ' · 成功 ' + primary.successes + ' · 冷却 ' + primary.cooldown_remaining + '秒</p>';
    }
    container.innerHTML = html;
    document.getElementById('ap-strategy').value = preferences.strategy;
    document.getElementById('ap-save').onclick = save;
    document.getElementById('ap-refresh').onclick = window.loadAiPool;
    document.getElementById('ap-add').onclick = function () {try {collect();if (preferences.endpoints.length >= 100) throw new Error('最多100个接口');preferences.endpoints.push({id: 'endpoint-' + Date.now() + '-' + Math.random().toString(16).slice(2, 6), name: '新接口', enabled: true, base_url: 'http://127.0.0.1:8000/v1', api_key: '', model_chat: '', model_vision: '', supports_vision: false, supports_tools: true, weight: 1, attempts: 1, timeout_seconds: 120, headers: {}});render();} catch (error) {toast(error.message, 'err');}};
    document.getElementById('ap-reset').onclick = async function () {if (!await panelConfirm('重置接口池', '清除当前账号的冷却、计数和轮询位置？不会删除接口或密钥。', '确认重置', 'danger')) return;try {await request('/api/ai-pool/reset', {confirmed: true});toast('已重置，点击刷新读取统计', 'ok');} catch (error) {toast(error.message, 'err');}};
    container.querySelectorAll('[data-ap-up],[data-ap-down],[data-ap-delete],[data-ap-test]').forEach(function (button) {button.onclick = async function () {
      try {
        var id = button.dataset.apUp || button.dataset.apDown || button.dataset.apDelete || button.dataset.apTest;
        if (button.dataset.apTest) {if (!await panelConfirm('API真实请求测试', '仅测试已保存的此接口：将发送固定测试消息给该提供商，可能产生费用；不会使用其他接口兜底。继续？', '确认测试', 'pr')) return;var result = await request('/api/ai-pool/test', {id: id, confirmed: true});toast(result.message + ' · ' + result.elapsed_ms + 'ms', 'ok');return;}
        collect();
        var index = preferences.endpoints.findIndex(function (item) {return item.id === id;});
        if (button.dataset.apDelete) {if (!await panelConfirm('移除接口', '从编辑列表移除此接口？保存后生效。', '移除', 'danger')) return;preferences.endpoints.splice(index, 1);}
        else {var target = index + (button.dataset.apUp ? -1 : 1);var temporary = preferences.endpoints[index];preferences.endpoints[index] = preferences.endpoints[target];preferences.endpoints[target] = temporary;}
        render();
      } catch (error) {toast(error.message, 'err');}
    };});
    if (window.lucide) lucide.createIcons();
  }
  async function request(path, body) {var result = await api(body ? 'POST' : 'GET', path, body);if (!result.ok) throw new Error(result.message || '请求失败');return result;}
  async function save() {
    try {
      collect();
      if (preferences.enabled && !await panelConfirm('启用多API轮询', 'AI消息可能依次发送给你启用的不同提供商，失败重试也可能消耗额度。确认接口可信且愿意按这些设置调用？', '保存并启用', 'pr')) return;
      var result = await request('/api/ai-pool', preferences);
      preferences = result.settings;health = result.status || [];
      if (window._confData) _confData.api_pool = preferences;
      toast(result.message, 'ok');render();
    } catch (error) {toast(error.message, 'err');}
  }
  window.loadAiPool = async function () {try {var result = await request('/api/ai-pool');preferences = result.settings;health = result.status || [];render();} catch (error) {var panel = document.getElementById('aiPoolPanel');if (panel) panel.textContent = '接口池读取失败：' + error.message;}};
})();
