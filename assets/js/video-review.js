(function () {
  'use strict';
  var preferences = null;
  var fields = [
    ['time_windows', '复习时间段', 'text', '例如 09:00-10:00, 22:00-01:00；留空全天'],
    ['weekdays', '每周执行日', 'days', '0=周一，6=周日；跨午夜按当前日；留空不自动执行'],
    ['categories', '视频类型', 'text', '按 B站分区名称，逗号分隔；留空不限'],
    ['keywords', '标题包含任一关键词', 'text', '留空不限'],
    ['exclude_keywords', '排除标题关键词', 'text', '逗号分隔'],
    ['up_names', '限定 UP 主', 'text', '按名称，逗号分隔；留空不限'],
    ['favorite_folders', '限定本地收藏夹', 'text', '按收藏夹名称，逗号分隔；留空不限'],
    ['min_score', '最低历史评分', 'number', '0 表示不限；无评分按 0 分'],
    ['min_age_hours', '观看/加入后等待小时', 'number', '0 表示不限制'],
    ['revisit_cooldown_minutes', '自动复习总间隔（分钟）', 'number', '按创建任务计算'],
    ['per_video_cooldown_minutes', '同视频复习间隔（分钟）', 'number', '从上次成功复习起算'],
    ['max_per_video', '每个视频最多复习次数', 'number', '0 表示不限'],
    ['daily_limit', '每天最多创建任务数', 'number', '包含失败和取消任务；0 表示不限']
  ];
  function inputField(field) {
    var key = field[0], type = field[2];
    var value = Array.isArray(preferences[key]) ? preferences[key].join(', ') : preferences[key];
    return '<div class="fg"><label for="vr-' + key + '">' + field[1] + '</label><input id="vr-' + key + '" type="' + (type === 'number' ? 'number' : 'text') + '" ' + (type === 'number' ? 'min="0" step="' + (key === 'min_score' || key === 'min_age_hours' ? '0.1' : '1') + '" ' : '') + 'value="' + esc(String(value)) + '"><p class="form-hint">' + field[3] + '</p></div>';
  }
  function card(video, extra) {
    return '<article class="review-video-card"><span class="tg">' + esc(video.category || '类型未记录') + '</span><h4>' + esc(video.title || video.bvid) + '</h4><p class="form-hint">' + esc(video.up || '') + ' · ' + Number(video.score || 0).toFixed(1) + ' 分 · ' + esc(video.bvid) + '</p>' + extra + '</article>';
  }
  async function request(method, path, body) {
    var result = await api(method, path, body);
    if (!result.ok) throw new Error(result.message || '请求失败');
    return result;
  }
  window.loadVideoReview = async function () {
    try {
      var result = await request('GET', '/api/video-review');
      preferences = result.settings;
      document.getElementById('videoReviewStatus').textContent = result.automatic ? (result.in_schedule ? '自动计划已开启' : '等待设置的时间段') : '自动复习关闭';
      var sources = {history: '观看历史', liked: '点赞记录', favorited: '平台收藏记录（本机）', local_favorites: '本地收藏夹'};
      var sourceHtml = Object.keys(sources).map(function (key) {return '<label class="review-choice"><input type="checkbox" data-review-source="' + key + '" ' + (preferences.sources.indexOf(key) >= 0 ? 'checked' : '') + '> ' + sources[key] + '</label>';}).join('');
      var basicKeys = ['categories', 'keywords', 'min_age_hours', 'min_score'];
      var advancedKeys = ['exclude_keywords', 'up_names', 'favorite_folders', 'revisit_cooldown_minutes', 'per_video_cooldown_minutes', 'max_per_video', 'daily_limit'];
      var basic = fields.filter(function (field) { return basicKeys.indexOf(field[0]) >= 0; }).map(inputField).join('');
      var advanced = fields.filter(function (field) { return advancedKeys.indexOf(field[0]) >= 0; }).map(inputField).join('');
      var weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map(function (day, index) { return '<label><input type="checkbox" data-review-day="' + index + '" ' + (preferences.weekdays.indexOf(index) >= 0 ? 'checked' : '') + '> ' + day + '</label>'; }).join('');
      document.getElementById('videoReviewRules').innerHTML = '<div class="review-preset-row"><button type="button" class="btn btn-out btn-sm" data-review-preset="gentle">填入：每天晚间复习</button><button type="button" class="btn btn-out btn-sm" data-review-preset="manual">填入：只手动复习</button><span class="form-hint">示例只填表，不保存、不自动执行。</span></div><section class="review-rule-section"><h3>1 · 开关与来源</h3><div class="fg"><label class="toggle-sw"><input id="vr-enabled" type="checkbox" ' + (result.automatic ? 'checked' : '') + '><span class="toggle-track"></span><span class="toggle-label">开启自动复习</span></label><p class="form-hint">默认关闭。手动任务独立执行，可在任务记录中取消尚未开始的任务。</p></div><div class="fg"><label>从哪里选择视频</label><div class="review-source-grid">' + sourceHtml + '</div></div></section><section class="review-rule-section"><h3>2 · 时间安排</h3>' + inputField(fields[0]) + '<div class="fg"><label>每周执行日</label><div class="weekday-picker">' + weekdays + '</div><input id="vr-weekdays" type="hidden" value="' + preferences.weekdays.join(',') + '"><p class="form-hint">全部不选时不自动执行；手动单次不受时间表限制。</p></div></section><section class="review-rule-section"><h3>3 · 基础筛选</h3><div class="review-basic-grid">' + basic + '</div><div class="fg"><label for="vr-order">选取顺序</label><select id="vr-order"><option value="oldest">最久未复习优先</option><option value="score">高评分优先</option><option value="least_reviewed">复习次数最少优先</option></select></div></section><details class="review-rule-section"><summary>高级规则：冷却、上限、指定作者与排除词</summary><div class="review-basic-grid">' + advanced + '</div><p class="form-hint">筛选规则本身不调用模型；复习视频理解仍可能消耗额度。</p></details>';
      document.querySelectorAll('[data-review-preset]').forEach(function (button) {
        button.onclick = function () {
          var gentle = button.dataset.reviewPreset === 'gentle';
          document.getElementById('vr-enabled').checked = false;
          document.getElementById('vr-time_windows').value = gentle ? '20:00-21:00' : '';
          document.getElementById('vr-min_age_hours').value = gentle ? '24' : '0';
          document.getElementById('vr-min_score').value = '0';
          document.getElementById('vr-daily_limit').value = gentle ? '2' : '0';
          document.querySelectorAll('[data-review-day]').forEach(function (input) { input.checked = gentle; });
          document.querySelectorAll('[data-review-source]').forEach(function (input) { input.checked = input.dataset.reviewSource === 'history' || input.dataset.reviewSource === 'local_favorites'; });
          toast('示例已填入，仍保持自动关闭；点击保存规则后才生效', 'ok');
        };
      });
      document.getElementById('vr-order').value = preferences.order;
      document.getElementById('videoReviewCount').textContent = result.candidate_total + ' 条符合规则，最多展示100条';
      document.getElementById('videoReviewCandidates').innerHTML = result.candidates.map(function (video) {return card(video, '<p class="form-hint">已复习 ' + Number(video.review_count || 0) + ' 次</p><button class="btn btn-out btn-sm" data-review-bvid="' + esc(video.bvid) + '">单次复习</button>');}).join('') || '<div class="review-empty">还没有符合规则的视频。先观看或收藏，也可以放宽等待时间、评分和类型。</div>';
      var labels = {pending: '等待执行', running: '复习中', done: '已完成', failed: '未完成', cancelled: '已取消'};
      document.getElementById('videoReviewHistory').innerHTML = result.history.map(function (task) {return card(task.video, '<p class="form-hint">' + labels[task.status] + ' · ' + (task.manual ? '手动单次' : '自动计划') + ' · ' + esc(task.created) + '</p>' + (task.note ? '<p class="review-note">' + esc(task.note) + '</p>' : '') + (task.status === 'pending' ? '<button class="btn btn-out btn-sm" data-review-cancel="' + task.id + '">取消待执行任务</button>' : ''));}).join('') || '<div class="review-empty">没有复习记录。计划默认关闭，只有你开启或手动提交后才会出现任务。</div>';
      document.querySelectorAll('[data-review-bvid]').forEach(function (button) {button.onclick = function () {window.runVideoReview(button.dataset.reviewBvid);};});
      document.querySelectorAll('[data-review-cancel]').forEach(function (button) {button.onclick = async function () {if (!await panelConfirm('取消复习', '仅取消这一条待执行任务？', '取消任务', 'danger')) return;try {await request('POST', '/api/video-review/cancel', {task_id: Number(button.dataset.reviewCancel), confirmed: true});await window.loadVideoReview();} catch (error) {toast(error.message, 'err');}};});
      if (window.lucide) lucide.createIcons();
    } catch (error) {toast(error.message, 'err');document.getElementById('videoReviewStatus').textContent = '读取失败';}
  };
  window.saveVideoReview = async function () {
    if (!preferences) return;
    var body = {enabled: document.getElementById('vr-enabled').checked, sources: [], order: document.getElementById('vr-order').value};
    document.querySelectorAll('[data-review-source]:checked').forEach(function (input) {body.sources.push(input.dataset.reviewSource);});
    document.getElementById('vr-weekdays').value = Array.from(document.querySelectorAll('[data-review-day]:checked')).map(function (input) { return input.dataset.reviewDay; }).join(',');
    fields.forEach(function (field) {
      var raw = document.getElementById('vr-' + field[0]).value.trim();
      body[field[0]] = field[2] === 'number' ? Number(raw) : raw.split(/[,，\n]/).map(function (value) {return value.trim();}).filter(Boolean);
      if (field[2] === 'days') body[field[0]] = body[field[0]].map(Number);
    });
    if (body.enabled && !await panelConfirm('开启自动复习', '机器人运行且观看队列为空时，按所选来源和时间段复习。内容分析可能消耗 AI 额度。确认开启？', '保存并开启', 'pr')) return;
    try {var result = await request('POST', '/api/video-review/settings', body);toast(result.message, 'ok');await window.loadVideoReview();} catch (error) {toast(error.message, 'err');}
  };
  window.runVideoReview = async function (bvid) {
    if (!await panelConfirm('单次视频复习', '使用已保存规则创建一条任务。需要机器人运行，已有观看队列优先；视频理解会使用现有 AI 配置并可能消耗额度。不开启自动计划。继续？', '创建单次任务', 'pr')) return;
    try {var result = await request('POST', '/api/video-review/run', {confirmed: true, bvid: bvid || null});toast(result.message, 'ok');await window.loadVideoReview();} catch (error) {toast(error.message, 'err');}
  };
  window.rf_video_review = window.loadVideoReview;
})();
