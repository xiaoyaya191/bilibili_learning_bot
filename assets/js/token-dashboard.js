(function () {
  'use strict';
  const charts = {};
  const colors = ['#7b61ff', '#26ad97', '#e9b563', '#60a5fa', '#d77791', '#9c89b8', '#78b98e', '#d68757'];
  let busy = false, pending = false, page = 1, timer = null;
  const root = () => document.getElementById('pg-tokens');
  const element = id => document.getElementById('tk-' + id);
  const number = value => value == null ? '—' : new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 3}).format(value);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const labels = {success:'HTTP成功', http_error:'HTTP失败', network_error:'网络异常', invalid_response:'无效JSON', cancelled:'已取消'};
  function status(message, error = false) {
    element('status').textContent = message;
    element('status').setAttribute('role', error ? 'alert' : 'status');
  }
  function query() {
    const result = new URLSearchParams();
    ['start', 'end', 'timezone', 'model', 'provider', 'source', 'outcome'].forEach(key => {if (element(key).value) result.set(key, element(key).value);});
    result.set('page', page); result.set('limit', element('limit').value);
    return result;
  }
  function dateInZone(value) {
    return new Intl.DateTimeFormat('sv-SE', {timeZone: element('timezone').value, year:'numeric', month:'2-digit', day:'2-digit'}).format(value);
  }
  function preset(days) {
    const end = dateInZone(new Date());
    const start = new Date(end + 'T12:00:00Z');
    start.setUTCDate(start.getUTCDate() - days + 1);
    element('end').value = end; element('start').value = start.toISOString().slice(0, 10);
    page = 1; refresh();
  }
  function option(key, values) {
    const selected = element(key).value;
    if (selected && !values.includes(selected)) values = [...values, selected];
    element(key).innerHTML = '<option value="">全部</option>' + values.map(value => '<option value="' + escape(value) + '">' + escape(value) + '</option>').join('');
    element(key).value = selected;
  }
  function recolor(chart) {
    const style = getComputedStyle(root());
    const foreground = style.getPropertyValue('--text-secondary').trim() || style.color;
    const border = style.getPropertyValue('--border').trim() || '#cccccc';
    chart.options.plugins.legend.labels.color = foreground;
    Object.values(chart.options.scales || {}).forEach(scale => {
      scale.ticks.color = foreground;
      scale.grid.color = border;
      scale.border.color = border;
      scale.title.color = foreground;
    });
    chart.update('none');
  }
  function draw(id, type, labelsList, datasets, extra = {}) {
    if (charts[id]) charts[id].destroy();
    const container = element(id).parentElement;
    const hasValues = datasets.some(dataset => dataset.data.some(value => value > 0));
    if (!hasValues) container.dataset.empty = '暂无已知用量，请检查日期范围或接口 usage';
    else delete container.dataset.empty;
    if (typeof Chart === 'undefined') {container.dataset.empty = '图表库加载失败，仍可查看明细和导出CSV'; return;}
    const foreground = getComputedStyle(root()).color;
    charts[id] = new Chart(element(id), {type, data: {labels: labelsList, datasets}, options: {
      responsive:true, maintainAspectRatio:false, animation:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : {duration:450},
      plugins:{legend:{position:'bottom', labels:{color:foreground, boxWidth:10, padding:18}}, tooltip:{callbacks:{label:context => context.dataset.label + ': ' + number(context.parsed.y == null ? context.parsed : (type === 'bar' && extra.indexAxis === 'y' ? context.parsed.x : context.parsed.y))}}},
      ...extra
    }});
    recolor(charts[id]);
  }
  function render(result) {
    const summary = result.summary;
    const stats = [
      ['已知 Token 总量', number(summary.total_tokens), '输入 ' + number(summary.input_tokens) + ' · 输出 ' + number(summary.output_tokens)],
      ['实际请求次数', number(summary.requests), '每次重试单独计数 · HTTP成功 ' + number(summary.success)],
      ['用量覆盖率', number(summary.coverage_percent) + '%', '已知 ' + number(summary.known) + ' · 未知 ' + number(summary.unknown)],
      ['估算费用 · CNY', '¥' + summary.estimated_cny.toFixed(6), '可计价 ' + summary.priced_requests + '/' + summary.requests + ' · 非账单'],
      ['已知缓存输入 Token', number(summary.cached_tokens), '字段覆盖 ' + summary.field_coverage.cached_tokens + '/' + summary.requests + ' · 输入的子集'],
      ['已知推理 Token', number(summary.reasoning_tokens), '字段覆盖 ' + summary.field_coverage.reasoning_tokens + '/' + summary.requests + ' · 输出的子集'],
      ['平均响应耗时', number(summary.avg_latency_ms) + ' ms', '完整HTTP请求含连接/等待耗时'],
      ['P95 响应耗时', number(summary.p95_latency_ms) + ' ms', '最近排名法 · 含失败请求']
    ];
    element('stats').innerHTML = stats.map(item => '<article class="tk-stat"><small>' + item[0] + '</small><strong>' + item[1] + '</strong><span>' + item[2] + '</span></article>').join('');
    ['model','provider','source'].forEach(key => option(key, result.options[key]));
    const budget = result.settings.monthly_token_budget;
    element('budget-text').textContent = '本月已知用量 ' + number(result.month_tokens) + (budget ? ' / ' + number(budget) + ' Token · ' + (result.month_tokens / budget * 100).toFixed(1) + '%' : ' Token · 未设置预算');
    element('budget-bar').style.width = (budget ? Math.min(100, result.month_tokens / budget * 100) : 0) + '%';
    element('budget-warning').hidden = !result.budget_exceeded;
    element('coverage-warning').hidden = !summary.unknown;
    element('coverage-warning').textContent = summary.unknown + ' 次请求没有返回完整 usage：未知不代表零消耗，总量与预算只能反映已知下限。缓存/推理字段缺失时显示已知汇总，不推算补齐。';
    draw('trend', 'bar', result.daily.map(item => item.date), [
      {label:'输入Token（已知）', data:result.daily.map(item => item.input), backgroundColor:colors[0], borderRadius:3, stack:'tokens'},
      {label:'输出Token（已知）', data:result.daily.map(item => item.output), backgroundColor:colors[1], borderRadius:3, stack:'tokens'},
      {label:'总Token（已知）', data:result.daily.map(item => item.total), type:'line', borderColor:colors[3], backgroundColor:colors[3], borderDash:[4,4], tension:.25, pointRadius:2},
      {label:'请求数', data:result.daily.map(item => item.requests), type:'line', borderColor:colors[2], backgroundColor:colors[2], yAxisID:'requests', tension:.25, pointRadius:2}
    ], {scales:{x:{stacked:true, ticks:{maxTicksLimit:12}}, y:{stacked:true, beginAtZero:true, title:{display:true,text:'Token'}}, requests:{position:'right', beginAtZero:true, grid:{drawOnChartArea:false}, title:{display:true,text:'请求'}}}});
    const topModels = result.groups.model.slice(0, 8);
    const rest = result.groups.model.slice(8).reduce((sum, item) => sum + item.tokens, 0);
    if (rest) topModels.push({name:'其他模型（合计）', tokens:rest});
    draw('models', 'doughnut', topModels.map(item => item.name), [{label:'已知Token',data:topModels.map(item => item.tokens),backgroundColor:colors,borderWidth:0}], {cutout:'72%'});
    const sources = result.groups.source.slice(0, 12);
    draw('sources', 'bar', sources.map(item => item.name), [{label:'已知Token',data:sources.map(item => item.tokens),backgroundColor:colors[1],borderRadius:5}], {indexAxis:'y',scales:{x:{beginAtZero:true}}});
    const providers = result.groups.provider.slice(0, 12);
    draw('providers', 'bar', providers.map(item => item.name), [
      {label:'HTTP成功',data:providers.map(item => item.requests - item.failures),backgroundColor:colors[0],stack:'requests'},
      {label:'失败/异常',data:providers.map(item => item.failures),backgroundColor:colors[4],stack:'requests'}
    ], {scales:{x:{stacked:true},y:{stacked:true,beginAtZero:true,ticks:{precision:0}}}});
    const maximum = Math.max(1, ...result.heatmap.flat());
    let heat = '<span></span>' + Array.from({length:24}, (unused, hour) => '<span>' + hour + '</span>').join('');
    result.heatmap.forEach((hours, weekday) => {
      heat += '<span>' + ['一','二','三','四','五','六','日'][weekday] + '</span>';
      hours.forEach((count, hour) => {heat += '<div class="tk-cell" tabindex="0" aria-label="周' + ['一','二','三','四','五','六','日'][weekday] + ' ' + hour + '点：' + count + '次请求" title="' + count + ' 次请求" style="--heat:' + (count ? .18 + count / maximum * .82 : .035) + '"></div>';});
    });
    element('heatmap').innerHTML = heat;
    element('records').innerHTML = result.records.length ? result.records.map(row => '<tr><td>' + row.id + '</td><td>' + escape(row.timestamp) + '</td><td>' + escape(row.source) + '</td><td>' + escape(row.model) + '</td><td>' + escape(row.provider) + '</td><td>' + escape(row.endpoint || '—') + '</td><td class="' + (row.outcome === 'success' ? '' : 'tk-fail') + '">' + escape(labels[row.outcome] || row.outcome) + ' ' + (row.status || '') + '</td>' + ['input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens','latency_ms'].map(key => '<td>' + number(row[key]) + '</td>').join('') + '<td>' + (row.estimated_cny == null ? '—' : row.estimated_cny.toFixed(6)) + '</td></tr>').join('') : '<tr><td colspan="14">当前条件下暂无请求。升级前未记录的Token不能追溯；无需调用AI即可使用此页面。</td></tr>';
    element('pagination').textContent = '第 ' + result.page + ' / ' + result.pages + ' 页 · ' + summary.requests + ' 条';
    element('prev').disabled = result.page <= 1; element('next').disabled = result.page >= result.pages;
    if (!element('settings').open || !element('settings').dataset.dirty) {
      element('retention').value = result.settings.retention_days;
      element('budget').value = result.settings.monthly_token_budget;
      element('prices').value = JSON.stringify(result.settings.prices, null, 2);
    }
    status('更新于 ' + result.generated_at + ' · ' + result.timezone + ' · 包含结束日期整日');
  }
  async function refresh() {
    if (!root()) return;
    if (busy) {pending = true; return;}
    busy = true; element('refresh').disabled = true; root().setAttribute('aria-busy','true');
    status('正在读取当前账号的真实请求记录…');
    try {
      const result = await api('GET', '/api/tokens/report?' + query());
      if (!result.ok) throw Error(result.message || '读取失败');
      render(result);
    } catch (error) {status('加载失败：' + error.message + '。可点击刷新重试。', true);}
    finally {
      busy = false; element('refresh').disabled = false; root().setAttribute('aria-busy','false');
      if (pending) {pending = false; refresh();}
    }
  }
  function initialize() {
    if (!root()) return;
    element('timezone').value = 'Asia/Shanghai';
    const end = dateInZone(new Date());
    const start = new Date(end + 'T12:00:00Z'); start.setUTCDate(start.getUTCDate() - 6);
    element('start').value = start.toISOString().slice(0,10); element('end').value = end;
    root().querySelectorAll('[data-tk-days]').forEach(button => button.addEventListener('click', () => preset(Number(button.dataset.tkDays))));
    element('refresh').addEventListener('click',refresh);
    ['start','end','timezone','model','provider','source','outcome','limit'].forEach(key => element(key).addEventListener('change', () => {page = 1; refresh();}));
    element('prev').addEventListener('click', () => {page = Math.max(1, page - 1); refresh();});
    element('next').addEventListener('click', () => {page++; refresh();});
    element('export').addEventListener('click', () => {window.location.assign('/api/tokens/export?' + query());});
    element('auto').addEventListener('change', () => {
      if (timer) clearInterval(timer);
      const seconds = Number(element('auto').value);
      timer = seconds ? setInterval(() => {if (root().classList.contains('on') && !document.hidden) refresh();}, seconds * 1000) : null;
    });
    element('settings').addEventListener('input', () => {element('settings').dataset.dirty = '1';});
    new MutationObserver(() => {Object.values(charts).forEach(recolor);}).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
    element('save').addEventListener('click', async () => {
      element('save').disabled = true;
      try {
        const prices = JSON.parse(element('prices').value);
        const result = await api('POST','/api/tokens/settings', {retention_days:Number(element('retention').value),monthly_token_budget:Number(element('budget').value),prices});
        if (!result.ok) throw Error(result.message || '保存失败');
        delete element('settings').dataset.dirty; toast('Token 设置已保存','ok'); await refresh();
      } catch (error) {status('保存失败：' + error.message, true);}
      finally {element('save').disabled = false;}
    });
    element('prune').addEventListener('click', async () => {
      if (!await panelConfirm('清理历史Token记录','按已保存的保留天数删除旧记录，不可恢复。请先导出需要的数据。')) return;
      element('prune').disabled = true;
      try {
        const result = await api('POST','/api/tokens/prune',{confirmed:true});
        if (!result.ok) throw Error(result.message || '清理失败');
        toast('已清理 ' + result.removed + ' 条记录','ok'); page = 1; await refresh();
      } catch (error) {status('清理失败：' + error.message,true);}
      finally {element('prune').disabled = false;}
    });
    if (location.hash === '#tokens') nav('tokens');
  }
  window.rf_tokens = refresh;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',initialize); else initialize();
})();
