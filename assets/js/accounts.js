(function () {
  'use strict';
  var dialog = document.getElementById('accountDialog');
  var finishDialog = null;
  var loading = false;
  function node(tag, text, cls) { var item = document.createElement(tag); if (text != null) item.textContent = text; if (cls) item.className = cls; return item; }
  function message(text) { document.getElementById('message').textContent = text || ''; }
  async function api(path, method, body) {
    var response = await fetch(path, {method: method || 'GET', headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
    var result = await response.json(); if (!response.ok || !result.ok) throw new Error(result.message || '操作失败'); return result;
  }
  function ask(title, text, inputValue, danger) {
    if (finishDialog) finishDialog(null);
    document.getElementById('dialogTitle').textContent = title;
    document.getElementById('dialogText').textContent = text;
    var input = document.getElementById('dialogInput'); input.hidden = inputValue == null; input.value = inputValue || '';
    input.type = title === '修改端口' ? 'number' : 'text';
    input.setAttribute('aria-label', title === '修改端口' ? '新端口' : danger ? '删除确认账号 ID' : '新账号名称');
    document.getElementById('dialogSubmit').className = danger ? 'danger' : 'primary';
    dialog.showModal(); if (!input.hidden) input.focus();
    return new Promise(function (resolve) { finishDialog = resolve; });
  }
  function settle(value) { var resolve = finishDialog; finishDialog = null; dialog.close(); if (resolve) resolve(value); }
  document.getElementById('dialogCancel').onclick = function () { settle(null); };
  dialog.addEventListener('cancel', function (event) { event.preventDefault(); settle(null); });
  document.getElementById('dialogForm').onsubmit = function (event) { event.preventDefault(); settle(document.getElementById('dialogInput').hidden ? true : document.getElementById('dialogInput').value); };
  function button(text, handler, cls) {
    var item = node('button', text, cls); item.type = 'button';
    item.onclick = async function () { item.disabled = true; message(''); try { await handler(); await load(); } catch (error) { message(error.message); } finally { item.disabled = false; } }; return item;
  }
  function panelUrl(port) { var url = new URL(location.href); url.port = String(port); url.pathname = '/'; url.search = ''; url.hash = ''; return url.href; }
  function accountCard(account) {
    var card = node('article', null, 'account-card'), header = node('div', null, 'account-card-header'), copy = node('div');
    copy.append(node('h3', account.name), node('span', account.id, 'account-id'));
    var labels = {current: '当前主面板', running: '运行中', stopped: '未启动', occupied: '端口被占用'};
    header.append(copy, node('span', labels[account.status] || account.status, 'status ' + account.status));
    var metadata = node('div', null, 'account-metadata'), port = node('span', '独立端口'); port.append(node('strong', String(account.port)));
    metadata.append(port, node('span', '配置与数据独立隔离'));
    var controls = node('div', null, 'account-actions');
    controls.append(button('打开面板', async function () {
      var popup = window.open('about:blank', '_blank'); if (popup) popup.opener = null;
      try { await api('/api/accounts/' + account.id + '/open', 'POST', {}); if (popup) popup.location.href = panelUrl(account.port); else message('弹窗被拦截，请打开：' + panelUrl(account.port)); }
      catch (error) { if (popup) popup.close(); throw error; }
    }, 'primary'));
    if (account.status !== 'current') {
      controls.append(button(account.status === 'running' ? '停止' : '启动', function () { return api('/api/accounts/' + account.id + (account.status === 'running' ? '/stop' : '/start'), 'POST', {}); }));
    }
    var details = node('details'), menu = node('div', null, 'account-menu'); details.append(node('summary', '更多操作'));
    menu.append(button('修改名称', async function () { var value = await ask('修改账号名称', '名称仅用于识别账号，不会修改凭据或配置。', account.name); if (value != null) await api('/api/accounts/' + account.id, 'PATCH', {name: value}); }));
    if (account.status !== 'current') {
      menu.append(button('重启面板', async function () { if (await ask('重启账号面板', '运行中的任务将中断，已保存队列会保留。确认重启？', null)) await api('/api/accounts/' + account.id + '/restart', 'POST', {}); }));
      menu.append(button('修改端口', async function () { if (account.status === 'running') throw new Error('请先停止账号，再修改端口'); var value = await ask('修改端口', '输入 1024–65535 的空闲端口；每个账号必须使用不同端口。', String(account.port)); if (value != null) await api('/api/accounts/' + account.id, 'PATCH', {port: value}); }));
      menu.append(button('删除账号', async function () {
        if (account.status === 'running') throw new Error('请先停止账号，再删除');
        var confirmation = await ask('删除账号', '删除前会创建完整备份。请输入 ' + account.id + ' 确认，仅输入完全一致的账号 ID 才会删除。', '', true);
        if (confirmation == null) return;
        if (confirmation !== account.id) throw new Error('账号 ID 不匹配，未删除');
        var result = await api('/api/accounts/' + account.id, 'DELETE', {confirmation: confirmation}); message('账号已删除，备份位置：' + result.backup);
      }, 'danger'));
    }
    details.append(menu); controls.append(details); card.append(header, metadata, controls); return card;
  }
  async function load() {
    if (loading) return; loading = true;
    try {
      var result = await api('/api/accounts'); var box = document.getElementById('rows'); box.replaceChildren();
      result.accounts.forEach(function (account) { box.append(accountCard(account)); });
      if (!result.accounts.length) box.append(node('div', '暂无账号，先添加一个独立账号。', 'account-empty'));
      document.getElementById('accountCount').textContent = result.accounts.length + ' / ' + result.max_accounts + ' 个账号';
      document.getElementById('createSubmit').disabled = result.accounts.length >= result.max_accounts;
    } catch (error) { message(error.message); document.getElementById('rows').replaceChildren(node('div', '无法读取账号。请从主账号管理；首次升级需要重启以初始化工作空间。', 'account-empty')); }
    finally { loading = false; }
  }
  document.getElementById('create').onsubmit = async function (event) {
    event.preventDefault(); var submit = document.getElementById('createSubmit'); submit.disabled = true;
    try { await api('/api/accounts', 'POST', {name: document.getElementById('name').value, port: document.getElementById('port').value || null}); event.target.reset(); message('已创建独立账号。打开后请分别配置 AI 并登录 B站，不会复制其他账号凭据。'); await load(); }
    catch (error) { message(error.message); } finally { submit.disabled = false; }
  };
  document.getElementById('refresh').onclick = load;
  if (document.body.classList.contains('embedded')) {
    try { var parentRoot = parent.document.documentElement; var sync = function () { document.body.dataset.panelTheme = parentRoot.getAttribute('data-theme') || 'light'; }; sync(); new MutationObserver(sync).observe(parentRoot, {attributes: true, attributeFilter: ['data-theme']}); }
    catch (error) {}
  }
  load();
})();
