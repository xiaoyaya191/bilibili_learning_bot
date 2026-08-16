# bilibili_learning_bot C++ 重写（P0 地基）

按“完成一块测试一块”的方式推进。当前 P0 已完成并验证：

- 配置/Cookie：`config.json`、`bilibili_cookies.json` 与 Python 格式互通，自动补 buvid3
- 网络：libcurl + 阿里云公共 DNS（223.5.5.5/223.6.6.6，自研最小 DNS A 查询）+ 强制 IPv4 + 全局节流/-799 冷却
- WBI 签名：nav 取 key，urlencode 排序 + MD5，与 bilibili-api 算法一致
- 扫码登录：qrcodegen 生成 PNG + 轮询 + Set-Cookie 抓取 + 自动保存 Cookie
- 测试：`ctest` 通过（urlcodec/md5/config/buvid3/DNS）

## 构建与测试（WSL Ubuntu / Termux）

```bash
cd cxx
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j4
cd build && ctest --output-on-failure
```

## 运行

```bash
./build/bili -data <用户数据目录> -check   # 验证 Cookie + WBI + 基础 API
./build/bili -data <用户数据目录> -login -qr qr.png   # 扫码登录
```

真实账号验证结果：

```
[OK] nav code=0 isLogin=1 mid=1928778168 uname=xiong_da_big_cow
[OK] wbi view code=0 aid=116857134651143 title=最新视频来袭，快来看看吧！
```

## P1 监控主循环（已完成并验证）

- 评论扫描：账号最新视频 + 评论区候选（跳过自己/已处理）
- 回复通知流：msgfeed/reply 解析 + 首次基线
- @ 通知流：msgfeed/at 解析（source_id/business_id 双兼容）+ 观看心跳 + 视频信息/AI 总结证据
- AI 回复：/chat/completions + 模型自动拉取 + 空回复跳过 + AI 标记
- 一键三连：点赞/投币/收藏，每视频一次、每日投币上限、UP 主自投币跳过
- 去重：processed/replied/liked 三集合，与 Python comment_log.json 互通

```bash
./build/bili -data <目录> -once          # 一轮完整检查
./build/bili -data <目录> -video BVxxx  # 扫单个视频评论
./build/bili -data <目录> -chat 提示词  # 单测 AI
./build/bili -data <目录> -coin BVxxx   # 单测投币
```

真实账号验证：`-chat` AI 正常回复；`-video` 正常拉取评论；`-once` 完成一轮扫描（本机 IP 的 arc/search 被限流 -799，回复/@ 流正常）。

## P2 学习与内容分析（已完成核心链路）

- 字幕：x/player/wbi/v2 拉字幕列表 + 字幕 JSON，最多 500 行
- 弹幕：comment.bilibili.com/{cid}.xml 解析，最多 200 条
- 双总结：B 站 AI 结论接口 + 自研 AI 学习笔记
- 知识库：兼容 Python `knowledge_metadata.json`（categories/file_index），笔记落 Markdown，`_score_text` 评分与 Python RAG 对齐

```bash
./build/bili -data <目录> -analyze BVxxx      # 分析并保存知识库笔记
./build/bili -data <目录> -kb search 关键词    # 知识库检索
./build/bili -data <目录> -kb list            # 笔记统计
```

真实账号验证：`-analyze BV1dQTt6dEsq` 拉到 4 行字幕，AI 依据字幕生成学习笔记并保存；`-kb search 歌词` 命中该笔记（score 6.16）。

## P3 导出全家桶（已完成核心）

- 自研 ZIP writer（store + CRC32），docx 输出合法 OOXML
- txt / md / html：直接生成
- docx：word/document.xml 段落导出
- pdf：最小 PDF 1.4 结构（Helvetica；中文需嵌入字体，后续补）
- ppt：HTML 幻灯片（与项目 Python 版一致，ppt 即 html deck）
- mm：markmap HTML 思维导图（CDN 加载 d3/markmap）

```bash
./build/bili -data <目录> -export BVxxx -fmt md     # txt/md/html/docx/pdf/ppt/mm
```

真实验证：`BV1dQTt6dEsq` 六种格式全部生成，docx 通过 zipfile 校验（3 entries，无损坏），pdf 结构完整。

## P4 Web 面板（已完成核心，待浏览器实测）

- cpp-httplib 单头 HTTP 服务，`-web <port>` 启动
- `/` 内置仪表盘（状态卡片 + 监控启停 + 日志滚动）
- `/api/status`：UID/登录态/监控状态/知识库笔记数/导出文件列表
- `/api/config`：配置查看（API Key 已掩码）
- `/api/logs`：最近日志（进程内 ring buffer）
- `/api/monitor/start|stop`：后台监控线程启停

```bash
./build/bili -data <目录> -web 8080
```

已验证：status/config/logs/start/stop 全通；Windows 因 WSL2 NAT 访问不到 WSL 网卡 IP，同一局域网设备可访问 `http://<wsl-ip>:8080`（本次为 192.168.3.41）。

## 下一步

P4 浏览器实测 + CLI 交互菜单整合；P2 余项：deep_dive、知识库自动分类、RAG 分块、弹幕 protobuf。
