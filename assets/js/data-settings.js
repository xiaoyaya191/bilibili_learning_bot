(function () {
  'use strict';
  var video = null, busy = false;
  function escape(value) { return esc(String(value == null ? '' : value)); }
  function checkbox(key, label) {
    return '<label class="ds-check"><input data-dv="' + key + '" type="checkbox" ' + (video[key] ? 'checked' : '') + '> ' + label + '</label>';
  }
  function number(key, label, minimum, maximum) {
    return '<label class="ds-field">' + label + '<input data-dv="' + key + '" type="number" min="' + minimum + '" max="' + maximum + '" value="' + Number(video[key]) + '"></label>';
  }
  async function request(path, data) {
    var result = await api(data ? 'POST' : 'GET', path, data);
    if (!result.ok) throw new Error(result.message || '操作失败');
    return result;
  }
  function renderVideo() {
    var box = document.getElementById('directVideoSettings');
    if (!box || !video) return;
    box.innerHTML = '<div class="ds-status"><span class="ds-dot ' + (video.enabled ? 'on' : '') + '"></span><strong>' + (video.enabled ? '已开启 · 指定视频模型' : '默认关闭 · 不会上传原视频') + '</strong></div>' +
      '<div class="ds-warning">需要模型与接口明确支持 <code>video_url + 内嵌MP4</code>，图片理解能力不代表能接收视频。只使用下方指定模型，不向接口池自动轮询，也不重复直传。视频可能包含声音、画面和个人信息，并产生费用。</div>' +
      '<div class="ds-checks">' + checkbox('enabled', '启用原视频投喂') + checkbox('capability_confirmed', '我已确认模型支持 video_url 内嵌 MP4 输入') + checkbox('use_vision_endpoint', '使用独立视觉API（未配置时使用主API）') + checkbox('fallback_to_frames', '失败或超预算时允许回退关键帧（还需已开启多模态/抽帧）') + '</div>' +
      '<div class="ds-grid"><label class="ds-field">视频专用模型名称<input data-dv="model" value="' + escape(video.model) + '" placeholder="填写服务商支持视频的具体模型"></label>' +
      number('max_size_mb', '原视频大小上限（MB，编码后约增大1/3）', 1, 128) + number('max_duration_seconds', '视频时长上限（秒）', 1, 1800) + number('timeout_seconds', '接口超时（秒）', 10, 600) + number('max_tokens', '输出 Token 上限', 100, 16000) + '</div>' +
      '<p class="form-hint">字幕和ASR仍优先；仅需要视觉理解时发送已经下载的MP4。封面、标题等先筛选，不直接发送BV号或B站网页链接。预算或兼容性失败按回退设置处理；修改此处不会自动开启全局抽帧。</p>' +
      '<button type="button" class="btn btn-pr" id="dvSave">保存视频直传设置</button><span id="dvMessage" class="ds-message" role="status"></span>';
    document.getElementById('dvSave').addEventListener('click', saveVideo);
  }
  async function saveVideo() {
    if (busy) return;
    var next = {};
    document.querySelectorAll('#directVideoSettings [data-dv]').forEach(function (input) { next[input.dataset.dv] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value.trim(); });
    if (next.enabled && (!next.model || !next.capability_confirmed)) { toast('请填写视频模型并确认兼容性', 'err'); return; }
    if (next.enabled && !await panelConfirm('开启视频投喂', '完整视频（包括可能的声音与个人信息）会发送至指定API服务商，可能产生额度消耗。最多 ' + next.max_size_mb + ' MB / ' + next.max_duration_seconds + ' 秒，实际接口限制可能更低。是否确认？', '确认保存')) return;
    busy = true;
    var button = document.getElementById('dvSave'); button.disabled = true;
    try {
      var result = await request('/api/direct-video/settings', {settings: next, confirmed: next.enabled});
      video = result.settings;
      if (window._confData) _confData.direct_video = video;
      renderVideo(); toast(result.message, 'ok');
    } catch (error) { toast(error.message, 'err'); }
    finally { busy = false; if (document.getElementById('dvSave')) document.getElementById('dvSave').disabled = false; }
  }
  async function loadDatabase() {
    var box = document.getElementById('databaseSettings');
    if (!box) return;
    var result = await request('/api/storage/database');
    box.innerHTML = '<div class="ds-status"><span class="ds-dot ' + (result.healthy ? 'on' : '') + '"></span><strong>SQLite · ' + (result.healthy ? '完整性检查通过' : '请检查数据库') + '</strong></div>' +
      '<div class="ds-metrics"><div><strong>' + result.records.length + '</strong><span>已数据库化记录</span></div><div><strong>' + result.original_count + '</strong><span>原始JSON快照</span></div><div><strong>账号隔离</strong><span>独立数据库与写入锁</span></div></div>' +
      '<p class="form-hint">账号Data目录及根目录旧记忆/索引JSON导入 <code>account_data.sqlite3</code>。配置、人格、日志等共享读写已接入数据库；旧模块仍使用JSON兼容镜像，外部修改读取时同步，原始快照不会被覆盖。暂不删除兼容文件。已有队列、Agent、日记计划等专用SQLite继续保留。</p>' +
      '<div class="btn-grp"><button type="button" class="btn btn-pr" id="dsMigrate">迁移 / 同步全部账号JSON</button><button type="button" class="btn btn-out" id="dsDownload">下载SQLite快照</button><button type="button" class="btn btn-out" id="dsRefresh">刷新检查</button></div>' +
      '<details class="ds-details"><summary>记录与版本（不显示内容或密钥）</summary><div class="ds-records">' + result.records.map(function (item) { return '<div><code>' + escape(item.name) + '</code><span>v' + item.revision + ' · ' + item.bytes + ' B</span></div>'; }).join('') + '</div></details>';
    document.getElementById('dsMigrate').addEventListener('click', migrate);
    document.getElementById('dsDownload').addEventListener('click', download);
    document.getElementById('dsRefresh').addEventListener('click', function () { loadDatabase().catch(function (error) { toast(error.message, 'err'); }); });
  }
  async function migrate() {
    if (busy || !await panelConfirm('迁移当前账号数据', '将当前账号Data目录及根目录中的JSON全部导入SQLite，保留原文件和原始快照。损坏文件会导致整批回滚。不会迁移其他账号的数据。', '确认迁移')) return;
    busy = true;
    var button = document.getElementById('dsMigrate'); button.disabled = true;
    try { var result = await request('/api/storage/database/migrate', {confirmed: true}); toast(result.message, 'ok'); await loadDatabase(); }
    catch (error) { toast(error.message, 'err'); }
    finally { busy = false; if (document.getElementById('dsMigrate')) document.getElementById('dsMigrate').disabled = false; }
  }
  async function download() {
    if (busy || !await panelConfirm('下载敏感数据库快照', '数据库包含API密钥、Cookie、聊天和人格数据。文件没有额外加密，请只保存在受保护位置，不要分享给他人。', '确认下载')) return;
    busy = true;
    try {
      var response = await fetch('/api/storage/database/download', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({confirmed: true})});
      if (!response.ok) { var failure = await response.json(); throw new Error(failure.message || '下载失败'); }
      var url = URL.createObjectURL(await response.blob()), anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'account-data-' + new Date().toISOString().slice(0, 10) + '.sqlite3'; anchor.click();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000); toast('数据库快照已下载，请妥善保管', 'ok');
    } catch (error) { toast(error.message, 'err'); }
    finally { busy = false; }
  }
  window.loadDataSettings = async function () {
    try { var result = await request('/api/direct-video/settings'); video = result.settings; renderVideo(); }
    catch (error) { var box = document.getElementById('directVideoSettings'); if (box) box.textContent = '视频设置加载失败：' + error.message; }
    try { await loadDatabase(); }
    catch (error) { var box = document.getElementById('databaseSettings'); if (box) box.textContent = '数据库状态读取失败：' + error.message; }
  };
}());
