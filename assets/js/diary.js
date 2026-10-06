var diaryPreferences=null;
async function loadDiarySettings(){
var result=await api('GET','/api/diary/settings');
var box=document.getElementById('diarySettings');if(!box)return;
if(!result.ok){box.innerHTML='<div class="pc">'+esc(result.message||'设置读取失败')+'</div>';return}
diaryPreferences=result.settings;
var labels={enabled:'启用日记',auto_enabled:'自动生成',include_skipped:'包含跳过视频',include_blocked:'包含拦截或草稿互动',anonymize_contacts:'联系人脱敏',fallback_to_local:'AI失败时保存本地摘要'};
var html='<div class="pc"><h3>自动日记计划</h3><p class="form-hint">默认每24小时生成，面板服务或机器人运行期间检查（无需保持浏览器打开）；全部进程关闭时暂停，重启后按持久时间补查。选择对话、私信或评论来源时，相关内容会发送给你配置的模型，可能消耗额度。脱敏不能保证隐藏正文中的所有身份信息，请谨慎选择。</p><div class="btn-grp">';
Object.keys(labels).forEach(function(key){html+='<label><input type="checkbox" data-diary-key="'+key+'" '+(diaryPreferences[key]?'checked':'')+'> '+labels[key]+'</label>'});html+='</div><div class="fr"><div class="fg"><label>触发方式</label><select data-diary-key="trigger_mode"><option value="interval">间隔周期</option><option value="daily">每日指定时间</option><option value="events">事件达到阈值</option></select></div><div class="fg"><label>每日时间</label><input type="time" data-diary-key="daily_time"></div><div class="fg"><label>空周期行为</label><select data-diary-key="empty_behavior"><option value="skip">跳过</option><option value="write">写无新增记录的日记</option></select></div></div><h3>来源选择</h3><div class="btn-grp">';
var sources={learning:'学到的知识',videos:'观看视频',web_chat:'网页聊天',private_messages:'私信互动',comments:'评论互动'};
Object.keys(sources).forEach(function(key){html+='<label><input type="checkbox" data-diary-source="'+key+'" '+(diaryPreferences.sources.indexOf(key)>=0?'checked':'')+'> '+sources[key]+'（'+(result.counts[key]||0)+'）</label>'});html+='</div><div class="fr">';
var numbers={auto_interval_minutes:['间隔分钟（24小时=1440）',5,43200],event_threshold:['事件触发阈值',1,500],min_events_for_auto:['最少来源事件',0,500],lookback_hours:['回看小时',1,720],max_events:['最多事件',1,500],max_chars_per_source:['单来源字符上限',200,20000],max_total_chars:['总字符上限',1000,100000],retry_minutes:['失败/空周期重查分钟',1,1440],temperature:['AI温度',0,2],max_tokens:['最大输出Token',100,8000],ai_timeout_seconds:['AI超时秒数',10,600]};
Object.keys(numbers).forEach(function(key){var rule=numbers[key];html+='<div class="fg"><label>'+rule[0]+'</label><input type="number" data-diary-key="'+key+'" min="'+rule[1]+'" max="'+rule[2]+'" step="'+(key==='temperature'?'0.1':'1')+'"></div>'});html+='</div><div class="fr"><div class="fg"><label>时间段（逗号分隔，支持跨午夜，留空不限）</label><input id="diaryWindows" placeholder="08:00-12:00,20:00-23:00"></div><div class="fg"><label>星期（0周一至6周日，逗号分隔）</label><input id="diaryWeekdays"></div><div class="fg"><label>模型（留空使用主模型/接口池）</label><input data-diary-key="model"></div><div class="fg"><label>日记标题前缀</label><input data-diary-key="title_prefix"></div></div><div class="fg"><label>自定义写作要求</label><textarea data-diary-key="custom_prompt" rows="3" placeholder="例如：重点整理学习结论，区分已回复和未发送草稿"></textarea></div><div class="btn-grp"><button class="btn btn-pr" onclick="saveDiarySettings()">保存计划</button><button class="btn btn-out" onclick="generateDiaryNow()">立即生成一篇 · 消耗AI额度</button></div></div>';
var state=result.state;html+='<div class="pc"><h3>生成状态</h3><p>自动计划：'+(state.enabled?'已开启':'已关闭')+' · 上次成功：'+esc(state.last_success||'暂无')+'</p><p>计划时间（仍受时间段/星期限制）：'+esc(diaryPreferences.trigger_mode==='events'?'来源达到事件阈值时':state.next_due)+'</p><p>重查时间：'+esc(state.retry_at||'无')+' · 最近提示：'+esc(state.last_error||'无')+'</p>';
(result.warnings||[]).forEach(function(item){html+='<p class="form-hint">'+esc(item)+'</p>'});
var statusLabels={running:'生成中',success:'已完成',failed:'失败',skipped:'已跳过',interrupted:'已中断'};
(state.jobs||[]).slice(0,5).forEach(function(job){html+='<p>'+esc(job.started)+' · '+esc(statusLabels[job.status]||job.status)+' · '+esc(String(job.event_count||0))+' 条来源 · '+esc(job.note||'')+'</p>';if(job.status==='running')html+='<div class="diary-progress" role="progressbar" aria-label="AI正在生成日记"><span></span></div>'});html+='</div>';box.innerHTML=html;
box.querySelectorAll('[data-diary-key]').forEach(function(input){var value=diaryPreferences[input.dataset.diaryKey];if(input.type!=='checkbox')input.value=value});document.getElementById('diaryWindows').value=diaryPreferences.time_windows.join(',');document.getElementById('diaryWeekdays').value=diaryPreferences.weekdays.join(',');
}
async function saveDiarySettings(){
if(!diaryPreferences)return;var preferences=JSON.parse(JSON.stringify(diaryPreferences));
document.querySelectorAll('#diarySettings [data-diary-key]').forEach(function(input){preferences[input.dataset.diaryKey]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value});
preferences.sources=Array.from(document.querySelectorAll('[data-diary-source]:checked')).map(function(input){return input.dataset.diarySource});preferences.time_windows=document.getElementById('diaryWindows').value.split(/[,，]/).map(function(value){return value.trim()}).filter(Boolean);preferences.weekdays=document.getElementById('diaryWeekdays').value.split(/[,，]/).map(function(value){return value.trim()}).filter(Boolean).map(Number);
if(preferences.sources.some(function(source){return ['web_chat','private_messages','comments'].indexOf(source)>=0})&&!await panelConfirm('来源隐私提醒','所选对话和互动内容会发送给当前AI提供商。请确认你允许处理这些内容；联系人脱敏无法完全匿名正文。','确认保存'))return;
var result=await api('POST','/api/diary/settings',preferences);toast(result.message,result.ok?'ok':'err');if(result.ok)loadDiarySettings();
}
async function generateDiaryNow(){
if(!await panelConfirm('生成AI日记','使用已保存的来源设置，相关内容会发送给模型并可能消耗额度。此操作不会开启自动计划，也不会发送私信、评论或点赞。','确认生成'))return;
var result=await api('POST','/api/diary/generate',{confirmed:true});toast(result.message,result.ok?'ok':'err');if(result.ok){
loadDiarySettings();
var jobId=result.job_id,attempts=0;
var timer=setInterval(async function(){
try{var status=await api('GET','/api/diary/settings');var job=(status.state.jobs||[]).find(function(item){return item.id===jobId});attempts++;
if((job&&job.status!=='running')||attempts>210){clearInterval(timer);if(document.querySelector('.page.on')?.id==='pg-diary'){await rf_diary();setTimeout(loadDiarySettings,1000)}if(job)toast(job.status==='success'?'日记生成完成':job.note||'日记未生成',job.status==='success'?'ok':'err')}
}catch(error){clearInterval(timer);toast('生成状态读取失败，请刷新查看','err')}
},3000)
}
}
var diaryEntries=[],diaryHistoryPage=1;
function filterDiaryEntries(){diaryHistoryPage=1;renderDiaryHistory()}
function changeDiaryPage(delta){diaryHistoryPage+=delta;renderDiaryHistory()}
function renderDiaryHistory(){
var box=document.getElementById('diaryHistory');if(!box)return;
var query=(document.getElementById('diarySearch').value||'').trim().toLowerCase();
var entries=diaryEntries.filter(function(entry){return !query||(entry.title+' '+entry.content).toLowerCase().includes(query)});
var pages=Math.max(1,Math.ceil(entries.length/20));diaryHistoryPage=Math.max(1,Math.min(pages,diaryHistoryPage));
var html='<p class="form-hint">共 '+entries.length+' 篇 · 第 '+diaryHistoryPage+' / '+pages+' 页</p><div class="diary-timeline">';
entries.slice((diaryHistoryPage-1)*20,diaryHistoryPage*20).forEach(function(entry){
var id=encodeURIComponent(entry.id||'');
html+='<article class="diary-entry"><div class="diary-entry-meta">'+esc(entry.time||'')+' · '+esc(entry.source||'历史记录')+' · '+esc(entry.mood||'')+'</div><div class="diary-entry-title">'+esc(entry.title||'日记记录')+'</div><div class="diary-entry-content">'+esc(entry.content||'')+'</div><div class="diary-entry-actions"><button class="btn btn-out btn-sm" data-diary-view="'+esc(id)+'">查看全文</button><button class="btn btn-out btn-sm" data-diary-edit="'+esc(id)+'">编辑</button><button class="btn btn-out btn-sm danger-action" data-diary-delete="'+esc(id)+'">删除</button></div></article>'});
html+='</div><div class="btn-grp"><button class="btn btn-out" onclick="changeDiaryPage(-1)" '+(diaryHistoryPage===1?'disabled':'')+'>上一页</button><button class="btn btn-out" onclick="changeDiaryPage(1)" '+(diaryHistoryPage===pages?'disabled':'')+'>下一页</button></div>';
box.innerHTML=html;
box.querySelectorAll('[data-diary-view]').forEach(function(button){button.onclick=function(){viewDiaryEntry(button.dataset.diaryView)}});
box.querySelectorAll('[data-diary-edit]').forEach(function(button){button.onclick=function(){editDiaryEntry(button.dataset.diaryEdit)}});
box.querySelectorAll('[data-diary-delete]').forEach(function(button){button.onclick=function(){deleteDiaryEntry(button.dataset.diaryDelete)}});
}
