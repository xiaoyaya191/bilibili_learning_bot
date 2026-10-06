(function () {
  'use strict';
  var guides = {
    dash: ['仪表盘', '先确认接口和登录状态，再决定是否运行机器人。', ['检查 AI 接口', '完成 B站登录', '查看最近运行记录'], '运行时长是面板时长，不代表机器人一直在观看。'],
    tokens: ['Token 仪表盘', '按日期、模型和来源追踪实际请求，先看用量覆盖率。', ['选日期范围', '筛选调用来源', '导出 CSV'], '未返回 usage 的请求显示未知；费用是估算，不是账单。'],
    'learning-tools': ['学习与图片导出', '把已有视频笔记转为图片，或根据问题检索知识。', ['选择已学内容', '设置背景与样式', '预览并导出'], '示例：选一篇 Python 笔记，导出知识卡片；先预览，不会自动发布。'],
    ctrl: ['机器人控制', '先设置候选数量和会话限制，再手动启动。', ['检查登录与模型', '设置本轮上限', '启动并观察日志'], '示例：先运行 3 个视频。停止不会清空已保存的观看队列。'],
    monitor: ['实时监听', '监听消息与互动事件，平台写操作仍受统一权限限制。', ['完成 B站登录', '检查回复权限', '启动监听'], '回复可能消耗模型额度；建议先开启人工审核。'],
    observe: ['学习实况', '这里显示实际学习过程，不是任务创建就算学完。', ['启动或排队学习', '查看当前阶段', '核对完成记录'], '暂无记录时先添加一条视频到稍后观看，再启动机器人。'],
    goal: ['学习小目标', '用一个可检验的目标限定这一轮学习，而不是一次设所有选项。', ['输入目标', '设置本轮数量', '确认后启动'], '示例：弄懂 async 与 await，先学 2 条视频。'],
    'video-review': ['视频复习', '自动复习默认关闭，先选择来源与时间，再检查符合规则的视频。', ['选择观看历史或本地收藏', '设定时间与筛选', '保存规则或单次复习'], '单次复习不等于启用自动计划；需要机器人运行，已有队列优先。'],
    'learning-loop': ['学习闭环', '从一个小目标开始，按知识点逐条学习，再用真实自测更新掌握度。', ['创建目标', '添加知识点或生成路径', '观看并记录自测'], '示例：Python 异步编程 → 协程 → 看一条教程 → 做 5 题并记录；AI 规划会先确认。'],
    logs: ['完整日志', '日志按来源和时间显示，清理只影响日志，不会删除知识或待执行任务。', ['选择日志来源', '需要时先导出', '清空当前来源'], '选“全部”会清理机器人、监听和行为审核执行日志；之后的新日志仍会正常出现。'],
    login: ['B站登录', '扫码后需要在手机确认，等页面明确显示已登录再启动。', ['生成二维码', '手机扫码并确认', '检查登录状态'], '凭据仅用于当前账号工作空间，请勿把 Cookie 发给他人。'],
    'ai-permissions': ['AI API 权限', '这是 AI 操作平台的唯一授权入口；总开关和风险权限默认关闭。', ['选择必要能力', '保留人工审核', '逐项小范围启用'], '浏览内容和本地整理不需要开放删除收藏、发动态等高风险写权限。'],
    reviews: ['AI 行为审核', 'AI 提议与实际执行分开；批准前核对对象、内容和影响。', ['查看待审提案', '核对对象和正文', '批准或拒绝'], '批准后也会检查当前权限；不能用“已确认”提示词绕过安全限制。'],
    accounts: ['账号管理', '最多 10 个独立账号。每个账号都有自己的端口、配置、凭据和学习数据。', ['在主账号添加账号', '打开独立面板', '分别配置并登录'], '只有主账号管理账号；修改端口和删除前先停止。新账号不复制原账号密钥。'],
    switches: ['功能开关', '只控制明确需要的自动能力；字幕、ASR、平台权限在对应的统一入口设置。', ['阅读功能用途', '一次开启一个功能', '观察运行效果'], '开启能力不代表立即执行任务。高风险平台操作请到 AI API 权限授权。'],
    conf: ['配置编辑', '先只配置对话接口。项目固定为学习 + 陪伴，其他高级设置按需要展开。', ['填写地址、模型、密钥', '保存并测试连接', '再配置视觉或 ASR'], '示例：先保存一个可用的对话模型；不要一次修改轮询、安全和抽帧全部参数。'],
    psna: ['人格管理', '先选择或编辑一个基础人格；实验性人格进化默认关闭。', ['选择人格', '编辑并保存提示词', '按场景分配人格'], '人格进化需要风险确认并保存原提示词，不建议刚开始就启用。'],
    mood: ['心情管理', '心情影响表达风格，不代表模型真的有情绪。', ['查看当前心情', '选一个固定状态', '按需开启实时变化'], '示例：先使用“平静”，熟悉后再配置随机切换。'],
    behavior: ['行为设置', '这里调频率与行为策略；平台操作是否允许由 AI API 权限决定。', ['选择行为类别', '调低频率与每日上限', '保存后查看审核记录'], '示例：先只学习，不自动评论；需要回复时再到权限分区授权。'],
    interests: ['兴趣偏好', '手动兴趣、AI 建议和避雷词分开管理，先保持少量明确条目。', ['添加 3 个核心兴趣', '确认或拒绝 AI 建议', '设置不想看的内容'], '示例：Python、摄影、历史。不要把整段聊天内容都塞进兴趣名称。'],
    judge: ['判定提示词', '控制视频与互动的判断标准，不是授权 API 的地方。', ['阅读默认标准', '只修改需要的判断项', '小范围测试评分'], '示例：明确“教程需有可复现步骤”，避免要求 AI 无条件点赞。'],
    divesearch: ['深度搜索', '先手动搜索一个具体问题，熟悉结果后再考虑自动好奇心搜索。', ['输入具体主题', '选择 B站或联网', '限制结果数量'], '示例：Python 事件循环是什么，先搜 3 条；网络搜索依赖已配置搜索能力。'],
    upfu: ['UP主关注', '维护内容方向与质量画像，不是直接自动关注任意 UP 主。', ['查看已记录 UP 主', '编辑标签与质量', '核对关注权限'], '没有数据时先观看相关 UP 主的视频，或在授权后产生关注记录。'],
    dm: ['私聊管理', '查看会话与回复记录；真实发信需要登录、权限和审核。', ['选择聊天对象', '查看上下文', '核对回复后发送'], '请不要测试真实陌生人私信；优先在 AI 对话页测试人格。'],
    cmts: ['评论日志', '查看评论与执行结果，区分生成草稿和平台实际发送。', ['按对象或时间查找', '查看回复内容', '核对执行状态'], '有草稿不等于已发出，平台失败原因会记录在日志。'],
    'memory-manage': ['长期记忆与 B 友画像', '把长期记忆与每位聊天对象的画像分开维护。', ['选择记忆或用户', '编辑事实和偏好', '清理不准确信息'], '示例：记住对方喜欢 Python，但不要把模型推测保存为确定事实。'],
    fav: ['好感度', '实验功能默认关闭；即使关闭也可以手动建档，自动变化需要启用并有真实互动。', ['用 UID 手动建档', '设置初始分与上限', '按需启用自动变化'], '示例：给朋友建一个 50 分档案；启用好感度不会自动授予点赞或私信权限。'],
    mem: ['记忆知识库', '从实际学习生成的知识中检索；没有知识时先学一个视频或导入文本。', ['搜索知识', '查看来源与摘要', '整理或导出'], '知识辅导会基于检索结果回答，不应把无来源的模型输出当作原视频事实。'],
    'watch-history': ['观看历史', '查看真实学习过程、评分和采取的行动。', ['按标题或日期搜索', '打开单条详情', '收藏或加入队列'], '示例：查找昨天学过的 Python 视频，再重新加入稍后观看。'],
    'search-history': ['AI历史搜索', '复盘搜索主题、关键词和命中情况，避免重复低效搜索。', ['查找搜索记录', '比较关键词', '回到深度搜索调整'], '没有记录时先在深度搜索进行一次手动搜索。'],
    'watch-later': ['稍后再看', '这是持久化观看队列，不同于平台收藏夹，意外关闭后可继续。', ['添加 BV 号', '调整队首或重试', '设置看完是否移除'], '示例：粘贴一个 BV 号，不启动机器人也能先把清单保存下来。'],
    todos: ['待办与提醒', '先手动添加一个明确的提醒；AI 提取的提醒也进入同一份清单。', ['填写内容与时间', '保存提醒', '完成或取消'], '示例：今晚 21:00 整理异步编程笔记。'],
    dynamics: ['动态发布中心', '先保存草稿，不会因为生成文案就直接发布到 B站。', ['写草稿', '核对内容与隐私', '授权并审核发布'], '真实动态发布属于风险行为，默认关闭；请先用草稿预览。'],
    favorites: ['本地收藏夹', '先使用本地收藏整理知识，和 B站平台收藏分开。', ['创建本地收藏夹', '添加已看视频', '设置收藏目标'], '示例：新建“Python 基础”；平台收藏另需登录、权限和人工审核。'],
    diary: ['AI 日记', '按真实学习、聊天等来源生成日记，默认周期为 24 小时，可自定义。', ['选择内容来源', '配置触发间隔', '查看与编辑日记'], '日记生成会使用模型额度；请勿把私信中的敏感内容导出分享。'],
    evolution: ['AI 进化', '观察提案、证据与效果；进化不应绕过人工审核或 API 权限。', ['查看数据与提案', '评估变化与风险', '批准或回滚'], '先积累真实学习记录；空数据下不会有可靠的进化效果。'],
    acts: ['操作日志', '核对 AI 实际采取了哪些操作与结果，区分意图和成功执行。', ['查看最近操作', '查看对象与结果', '核对运行日志中的原因'], '清理运行日志不会删除这里的业务历史。'],
    tutor: ['知识辅导', '提问时优先检索已有知识库，再查看引用来源。', ['选择辅导目标', '问一个具体问题', '核对检索来源'], '示例：根据我看过的视频解释协程与线程的差别；先确保知识库有相关内容。'],
    chat: ['AI 对话', '不用启动机器人也能测试聊天；Agent 模式只有授权的工具可用。', ['新建会话', '选择人格与上下文', '发送问题'], '示例：给我一份 20 分钟 Python 学习计划。聊天本身可能消耗额度。'],
    skill: ['技能库', '技能是可复用的方法卡，不是模型凭空获得执行权限。', ['先填入手动示例', '保存名称、场景、步骤', '按需启用 AI 提炼'], '示例：费曼学习法。手动添加不调用模型；AI 提炼文本会消耗额度。'],
    tools: ['功能中心', '从你想完成的任务选择工具，不需要逐个功能都开启。', ['选择任务类别', '打开对应工具', '准备输入再执行'], '示例：已有笔记想复盘 → 思维导图；想保存视频内容 → 视频转网页。'],
    mindmap: ['思维导图', '把已保存知识转成可交互结构，先从一篇笔记试导出。', ['筛选知识文件', '选中一篇', '导出并预览'], '没有源文件时先观看视频或添加自定义知识。'],
    uplearn: ['UP批量学习', '批量任务请从少量视频开始，避免大量调用与平台请求。', ['填写 UP 主或空间地址', '限制数量', '确认后开始'], '示例：先学最近 2 条视频；检查队列后再提高上限。'],
    video2web: ['视频转网页', '将已分析内容导出为易读网页，先确认视频能获取字幕或 ASR。', ['填写视频链接', '选择处理设置', '完成后预览 HTML'], '模型分析可能消耗额度；静态网页导出不是实时视频播放器。'],
    customkb: ['自定义知识', '手动输入文本补充知识库，让后续辅导可检索。', ['输入名称与正文', '分类并保存', '到知识辅导检验检索'], '示例：添加自己的项目约定，避免导入密钥或个人敏感信息。'],
    'learn-tools': ['学习工具', '根据已有学习内容生成复盘材料，先选中明确的知识来源。', ['选择知识文件', '选择要生成的材料', '检查结果再导出'], '涉及模型生成时会消耗额度；空知识库需要先学习或导入。'],
    asr: ['ASR 语音识别', '字幕与 ASR 总开关集中在此；字幕缺失或不匹配时才需要 ASR。', ['先检查字幕开关', '按需启用本地 ASR', '配置模型与设备'], '本地 ASR 需安装模型和依赖，初次运行较慢；未启用时不会自动下载。'],
    agent: ['Agent 工作台', '先测试只读问题，再逐步授权工具；能对话不代表拥有平台写权限。', ['选择人格与会话', '询问已有学习内容', '查看工具过程与结果'], '示例：推荐我最近没看过的 Python 视频；真实写操作仍需权限与审核。'],
    mcp: ['MCP 服务', '给外部客户端提供项目能力，先确认访问控制与暴露范围。', ['查看启动命令', '配置客户端', '测试只读能力'], '不要把 MCP 服务无鉴权暴露到公网，也不要共享凭据。'],
    sys: ['系统管理', '这里是运行与维护入口，危险操作前先备份。', ['查看系统状态', '选择维护操作', '阅读确认内容'], '恢复出厂或删除数据不是普通刷新；需要保留的数据先导出。'],
    backup: ['备份还原', '修改大量设置前先备份，还原时核对当前账号与范围。', ['创建备份', '记录文件位置', '必要时确认还原'], '备份可能含配置和凭据，请保存在私有目录，不要公开上传。'],
    about: ['关于项目', '了解项目边界、主要能力和数据位置，再按新手指南逐步使用。', ['了解学习与陪伴', '打开新手指南', '查看数据位置'], '项目本地运行；模型与平台仍是外部服务，平台接口有风险。'],
    me: ['我的', '查看面板用户与个人设置，不是 B站账号身份入口。', ['查看面板资料', '修改需要的设置', '保存后核对'], 'B站登录请到 B站登录分区；多账号由主账号管理。']
  };
  function textElement(tag, text, className) {
    var node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node;
  }
  function goButton(text, page) {
    var button = textElement('button', text, 'btn btn-out btn-sm'); button.type = 'button';
    button.onclick = function () { nav(page); }; return button;
  }
  function showHelp(id) {
    var guide = guides[id]; if (!guide) return;
    var rows = guide[2].map(function (step, index) { return '<li class="tutorial-step"><span class="tutorial-step-icon">' + (index + 1) + '</span><div><strong>' + esc(step) + '</strong></div></li>'; }).join('');
    openReviewModal(guide[0] + ' · 使用说明', '<p class="tutorial-lead">' + esc(guide[1]) + '</p><ol class="tutorial-steps">' + rows + '</ol><div class="guide-example"><span>' + esc(guide[3]) + '</span></div>', '<button class="btn btn-out" onclick="closeReviewModal()">我知道了</button><button class="btn btn-pr" onclick="closeReviewModal();nav(\'guide\')">查看完整新手指南</button>');
  }
  function addHelp(id, guide) {
    var page = document.getElementById('pg-' + id); if (!page || page.querySelector('.page-quick-guide')) return;
    var callout = document.createElement('section'); callout.className = 'page-quick-guide';
    var copy = document.createElement('div'); copy.append(textElement('strong', '从这里开始'), textElement('p', guide[1]));
    var steps = document.createElement('div'); steps.className = 'guide-steps';
    guide[2].forEach(function (step, index) { steps.append(textElement('span', (index + 1) + ' · ' + step, 'guide-step-chip')); });
    copy.append(steps);
    var help = textElement('button', '示例与前提', 'btn btn-out btn-sm'); help.type = 'button'; help.onclick = function () { showHelp(id); };
    callout.append(copy, help);
    var header = page.querySelector('.divider') || page.querySelector('.ph') || page.firstElementChild;
    if (header) header.after(callout); else page.prepend(callout);
  }
  function buildDirectory(query) {
    var box = document.getElementById('guideDirectory'); if (!box) return;
    box.replaceChildren(); var term = String(query || '').trim().toLowerCase();
    Object.keys(guides).forEach(function (id) {
      var guide = guides[id]; if (term && (guide.join(' ') + id).toLowerCase().indexOf(term) < 0) return;
      var card = document.createElement('article'); card.className = 'guide-directory-card';
      card.append(textElement('h3', guide[0]), textElement('p', guide[1]), textElement('p', '示例 / 注意：' + guide[3]), goButton('打开 ' + guide[0], id)); box.append(card);
    });
    document.getElementById('guideResultCount').textContent = box.childElementCount + ' 个分区';
    if (!box.childElementCount) box.append(textElement('p', '没有匹配项，试试“视频”、“配置”、“聊天”或“日志”。', 'workspace-empty'));
  }
  function wrapSection(pageId, title, headings) {
    var page = document.getElementById('pg-' + pageId); if (!page) return;
    var cards = Array.from(page.querySelectorAll(':scope > .pc')).filter(function (card) { var header = card.querySelector('h3'); return header && headings.some(function (keyword) { return header.textContent.indexOf(keyword) >= 0; }); });
    if (!cards.length) return;
    var details = document.createElement('details'); details.className = 'section-supplement'; details.append(textElement('summary', title));
    cards[0].before(details); cards.forEach(function (card) { details.append(card); });
  }
  function examples() {
    var skill = document.getElementById('skillNewName');
    if (skill) {
      var button = textElement('button', '填入“费曼学习法”示例', 'btn btn-out btn-sm'); button.type = 'button';
      button.onclick = function () {
        skill.value = '费曼学习法'; document.getElementById('skillNewTrigger').value = '需要检验自己是否理解某个概念时';
        document.getElementById('skillNewSteps').value = '1. 选择一个概念\n2. 用自己的话讲给外行听\n3. 记录讲不清的地方并重新学习\n4. 用类比简化解释，再复述一次';
        skill.focus(); toast('仅填入示例，点击添加技能后才会保存', 'ok');
      };
      skill.closest('.pc').querySelector('h3').after(button);
    }
    var query = document.getElementById('dsQuery');
    if (query) {
      var sample = textElement('button', '填入入门搜索示例', 'btn btn-out btn-sm'); sample.type = 'button';
      sample.onclick = function () { query.value = 'Python 事件循环与协程入门'; document.getElementById('dsCount').value = '3'; query.focus(); toast('仅填入示例，不会发起搜索', 'ok'); };
      query.closest('.pc').querySelector('h3').after(sample);
    }
  }
  function init() {
    var tutorial = document.createElement('div'); tutorial.id = 'pg-guide'; tutorial.className = 'page';
    tutorial.innerHTML = '<div class="ph"><h1>新手指南</h1><p>不用先理解全部功能。从一段对话、一个目标或一个视频开始；这里包含每个分区的用途、前提和示例。</p></div><div class="divider"></div><section class="guide-route"><article class="guide-route-card"><b>01 / 连接</b><strong>准备好 AI 接口</strong><p>填写模型、地址和密钥，保存后测试；不要先开启所有自动功能。</p><button class="btn btn-out btn-sm" onclick="nav(\'conf\')">去配置</button></article><article class="guide-route-card"><b>02 / 体验</b><strong>先聊一次</strong><p>询问“给我 20 分钟 Python 学习计划”，不用启动机器人。</p><button class="btn btn-out btn-sm" onclick="nav(\'chat\')">开始对话</button></article><article class="guide-route-card"><b>03 / 学习</b><strong>保存一个小目标</strong><p>创建目标、添加知识点，再决定是否生成候选视频。</p><button class="btn btn-out btn-sm" onclick="nav(\'learning-loop\')">打开学习闭环</button></article><article class="guide-route-card"><b>04 / 运行</b><strong>小范围、可控地运行</strong><p>登录 B站后，先限制少量视频；保留审核，观察队列和用量。</p><button class="btn btn-out btn-sm" onclick="nav(\'ctrl\')">查看运行设置</button></article></section><section class="pc"><div class="interest-toolbar"><div><h3>全部分区使用手册</h3><p class="form-hint">学习 + 陪伴是固定默认方式；访问这些页面不会自动启动机器人。</p></div><span id="guideResultCount" class="guide-badge"></span></div><div class="fg"><label for="guideSearch">按功能或问题查找</label><input id="guideSearch" type="search" placeholder="例如：日志、复习、账号、没有知识"></div></section><section class="guide-directory" id="guideDirectory"></section>';
    var main = document.getElementById('pg-dash').parentElement; main.append(tutorial);
    var about = document.querySelector('.ni[data-pg="about"]');
    if (about) {
      var item = textElement('button', '新手指南', 'ni'); item.type = 'button'; item.dataset.pg = 'guide'; item.setAttribute('role', 'button'); item.onclick = function () { nav('guide', item); }; about.before(item);
    }
    Object.keys(guides).forEach(function (id) { addHelp(id, guides[id]); });
    document.getElementById('guideSearch').addEventListener('input', function () { buildDirectory(this.value); });
    buildDirectory(''); examples();
    wrapSection('divesearch', '高级设置：自动探索与提示词（新手可跳过）', ['好奇心', '提示词自定义']);
    wrapSection('skill', '进阶：使用 AI 从文本提炼技能（可能消耗额度）', ['AI 提炼技能']);
    var sectionManager = document.getElementById('sectionManagerBox');
    if (sectionManager) {
      var displaySettings = document.createElement('details'); displaySettings.className = 'section-supplement';
      displaySettings.append(textElement('summary', '进阶：管理侧栏显示（不影响功能和数据）'));
      sectionManager.before(displaySettings); displaySettings.append(sectionManager);
    }
    var storage = document.querySelector('#pg-about .storage-panel');
    if (storage) {
      var storageDetails = document.createElement('details'); storageDetails.className = 'section-supplement';
      storageDetails.append(textElement('summary', '数据位置与迁移（修改前建议备份）')); storage.before(storageDetails); storageDetails.append(storage);
    }
    var weights = document.querySelector('#pg-fav .fav-weights'), weightTitle = document.querySelector('#pg-fav .fav-weights-title');
    if (weights && weightTitle) {
      var weightSettings = document.createElement('details'); weightSettings.className = 'section-supplement';
      weightSettings.append(textElement('summary', '进阶：自定义各事件分值')); weightTitle.before(weightSettings); weightSettings.append(weightTitle, weights);
    }
    var accountContext = document.getElementById('accountsContext');
    if (accountContext) accountContext.parentElement.classList.add('account-context-card');
    var aboutBox = document.getElementById('aboutBox');
    if (aboutBox) {
      var overview = document.createElement('section'); overview.className = 'about-overview';
      [['学习整理', '视频分析、知识库、学习闭环与复习，形成可持续的学习记录。', 'learning-loop'], ['陪伴与对话', '网页聊天、人格与私信辅助，平台写操作由你明确授权。', 'chat'], ['本地与安全', '独立账号、持久队列、人工审核和可观测用量，不自动放开风险操作。', 'ai-permissions']].forEach(function (feature) {
        var card = document.createElement('article'); card.className = 'about-feature'; card.append(textElement('h3', feature[0]), textElement('p', feature[1]), goButton('了解并开始', feature[2])); overview.append(card);
      }); aboutBox.before(overview);
    }
    window.openNewUserTutorial = function () { closeReviewModal(); nav('guide'); };
    window.openSectionHelp = showHelp;
    window.rf_guide = function () { buildDirectory(document.getElementById('guideSearch').value); };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
