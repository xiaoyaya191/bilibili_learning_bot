var videoQueueHistoryPage = 1;
var videoQueueLoading = false;
var videoQueueFields = [
  ['enabled', '自动继续观看本地队列', 'bool'],
  ['remove_completed', '看完或明确跳过后移出本地队列', 'bool'],
  ['keep_history', '保留队列观看历史与实际行动', 'bool'],
  ['skip_watched', '筛选新一轮时跳过已处理视频', 'bool'],
  ['review_interest_again', '入选后再次进行兴趣筛选', 'bool'],
  ['sync_platform', '把入选队列同步到B站稍后再看', 'bool'],
  ['remove_platform_completed', '看完后移除本队列已同步的B站条目', 'bool'],
  ['max_selected', '每轮最多入选（0 = 不限，最多候选池数量）', 'number', 0, 100],
  ['history_limit', '保留历史条数（0 = 不限）', 'number', 0, 10000],
  ['max_retries', '失败后最多额外重试次数', 'number', 0, 10],
  ['retry_delay_seconds', '失败重试等待秒数', 'number', 0, 86400]
];

function videoQueueRenderSettings(preferences) {
  var container = document.getElementById('videoQueueSettingsFields');
  if (!container || container.dataset.loaded) return;
  container.innerHTML = videoQueueFields.map(function (field) {
    var identifier = 'videoQueueSetting-' + field[0];
    if (field[2] === 'bool') return '<label class="video-queue-switch toggle-sw"><input id="' + identifier + '" type="checkbox"' + (preferences[field[0]] ? ' checked' : '') + '><span class="toggle-track"></span><span class="toggle-label">' + esc(field[1]) + '</span></label>';
    return '<div class="fg"><label for="' + identifier + '">' + esc(field[1]) + '</label><input id="' + identifier + '" type="number" min="' + field[3] + '" max="' + field[4] + '" step="1" value="' + preferences[field[0]] + '"></div>';
  }).join('');
  container.dataset.loaded = 'true';
}

function videoQueueButton(label, action, bvid) {
  return '<button type="button" class="btn btn-out btn-sm" data-queue-action="' + action + '" data-bvid="' + esc(bvid) + '">' + label + '</button>';
}

function videoQueueRenderRow(row, history) {
  var labels = {pending: '待观看', watching: '正在观看', done: '已看完', skipped: '已跳过', failed: '失败待处理'};
  var video = row.video || {};
  var owner = video.owner || {};
  var up = owner.name || video.author || '';
  var bvid = String(row.bvid || '');
  var cover = video.pic || video.cover;
  var image = cover ? '<img class="video-queue-cover" loading="lazy" referrerpolicy="no-referrer" src="' + esc(coverSrc(cover)) + '" alt="">' : '<div class="video-queue-cover video-queue-placeholder"><i data-lucide="play"></i></div>';
  var status = row.status || row.outcome;
  var buttons = '';
  if (history) buttons = videoQueueButton('重新加入', 'restore', bvid);
  else {
    if (status === 'pending') buttons += videoQueueButton('提到队首', 'prioritize', bvid);
    if (['failed', 'done', 'skipped'].indexOf(status) >= 0) buttons += videoQueueButton('重新排队', 'retry', bvid);
    if (status !== 'watching') buttons += videoQueueButton('移除', 'remove', bvid);
  }
  var description = [];
  if (up) description.push('@' + up);
  if (row.score !== null && row.score !== undefined) description.push('评分 ' + row.score + ' / 10');
  if (row.attempts) description.push('尝试 ' + row.attempts + ' 次');
  if (row.finished_at) description.push(row.finished_at.replace('T', ' '));
  var actions = history && row.actions && row.actions.length ? '<p class="video-queue-actions">实际行动：' + esc(row.actions.join(' · ')) + '</p>' : '';
  if (history && row.assessment && row.assessment.thought) actions += '<p class="video-queue-actions">评分理由：' + esc(row.assessment.thought) + '</p>';
  var error = row.error ? '<p class="video-queue-error">' + esc(row.error) + '</p>' : '';
  return '<article class="video-queue-row">' + image + '<div class="video-queue-copy"><div class="video-queue-row-head"><a href="https://www.bilibili.com/video/' + encodeURIComponent(bvid) + '" target="_blank" rel="noopener">' + esc(video.title || bvid) + '</a><span class="video-queue-status ' + status + '">' + (labels[status] || '等待') + '</span></div><small>' + esc(bvid + (description.length ? ' · ' + description.join(' · ') : '')) + '</small>' + actions + error + '</div><div class="video-queue-buttons">' + buttons + '</div></article>';
}

async function loadVideoQueue() {
  if (videoQueueLoading) return;
  var list = document.getElementById('videoQueueList');
  if (!list) return;
  videoQueueLoading = true;
  try {
    var size = Number((document.getElementById('videoQueueHistorySize') || {}).value) || 20;
    var result = await api('GET', '/api/watch-queue?history_page=' + videoQueueHistoryPage + '&history_size=' + size);
    if (!result.ok) throw new Error(result.message || '队列读取失败');
    var rows = result.items || [];
    var pending = rows.filter(function (row) { return row.status === 'pending' || row.status === 'watching'; }).length;
    document.getElementById('videoQueueSummary').textContent = (result.settings.enabled ? '自动继续' : '队列暂停') + ' · 待完成 ' + pending + ' 条 · 共 ' + rows.length + ' 条';
    list.innerHTML = rows.length ? rows.map(function (row) { return videoQueueRenderRow(row, false); }).join('') : '<div class="video-queue-empty"><i data-lucide="list-video"></i><strong>等待下一批优质内容</strong><p>AI 多选结果会先写入这里，再逐条观看。也可手动加入 BV 号。</p></div>';
    videoQueueRenderSettings(result.settings);
    var history = result.history || [];
    document.getElementById('videoQueueHistory').innerHTML = history.length ? history.map(function (row) { return videoQueueRenderRow(row, true); }).join('') : '<p class="form-hint" style="padding:20px 0">暂无队列观看历史</p>';
    document.getElementById('videoQueueHistorySummary').textContent = '共 ' + result.history_total + ' 条';
    var pages = Math.max(1, Math.ceil(result.history_total / size));
    if (videoQueueHistoryPage > pages) { videoQueueHistoryPage = pages; setTimeout(loadVideoQueue, 0); }
    document.getElementById('videoQueueHistoryPager').innerHTML = '<button type="button" onclick="videoQueueGoHistory(-1)"' + (videoQueueHistoryPage <= 1 ? ' disabled' : '') + '>上一页</button><span>' + videoQueueHistoryPage + ' / ' + pages + '</span><button type="button" onclick="videoQueueGoHistory(1)"' + (videoQueueHistoryPage >= pages ? ' disabled' : '') + '>下一页</button>';
    if (window.lucide) lucide.createIcons({attrs: {'stroke-width': 1.5}});
  } catch (error) {
    document.getElementById('videoQueueSummary').textContent = '读取失败：' + (error.message || error);
  } finally { videoQueueLoading = false; }
}

function videoQueueGoHistory(direction) {
  videoQueueHistoryPage = Math.max(1, videoQueueHistoryPage + direction);
  loadVideoQueue();
}

async function saveVideoQueueSettings() {
  var payload = {};
  for (var field of videoQueueFields) {
    var input = document.getElementById('videoQueueSetting-' + field[0]);
    if (!input) return;
    if (field[2] === 'bool') payload[field[0]] = input.checked;
    else {
      if (!input.checkValidity()) { input.reportValidity(); return; }
      payload[field[0]] = Number(input.value);
    }
  }
  try {
    var result = await api('POST', '/api/watch-queue/settings', payload);
    document.getElementById('videoQueueSettingsMessage').textContent = result.message || '';
    toast(result.message, result.ok ? 'ok' : 'err');
    if (result.ok) loadVideoQueue();
  } catch (error) { toast(error.message || error, 'err'); }
}

async function videoQueueAdd() {
  var input = document.getElementById('videoQueueBvid');
  var bvid = (input.value || '').trim();
  if (!bvid) { toast('请输入 BV 号', 'err'); return; }
  await videoQueueAction('add', bvid);
}

async function videoQueueAction(action, bvid) {
  if (action === 'remove' && !await panelConfirm('移除本地待观看项', '只移除本地队列，不删除B站条目或观看历史。', '移除', 'danger')) return;
  try {
    var result = await api(action === 'remove' ? 'DELETE' : 'POST', '/api/watch-queue', {action: action, bvid: bvid, confirmed: action === 'remove'});
    toast(result.message, result.ok ? 'ok' : 'err');
    if (result.ok) {
      if (action === 'add') document.getElementById('videoQueueBvid').value = '';
      loadVideoQueue();
    }
  } catch (error) { toast(error.message || error, 'err'); }
}

async function clearVideoQueueHistory(resetSeen) {
  var description = resetSeen ? '清除本地 BV 去重记录，下一轮可以再次入选已看视频；不会删除知识库、历史或B站数据。' : '只清除本地队列观看历史，保留 BV 去重记录、知识库与B站数据。';
  if (!await panelConfirm(resetSeen ? '重置已看去重' : '清除队列历史', description, '确认清除', 'danger')) return;
  try {
    var result = await api('DELETE', '/api/watch-queue/history', {confirmed: true, reset_seen: resetSeen});
    toast(result.message, result.ok ? 'ok' : 'err');
    if (result.ok) { videoQueueHistoryPage = 1; loadVideoQueue(); }
  } catch (error) { toast(error.message || error, 'err'); }
}

document.addEventListener('click', function (event) {
  var button = event.target.closest('[data-queue-action]');
  if (button) videoQueueAction(button.dataset.queueAction, button.dataset.bvid);
});
setInterval(function () {
  var page = document.getElementById('pg-watch-later');
  if (page && page.classList.contains('on') && !document.hidden) loadVideoQueue();
}, 8000);
