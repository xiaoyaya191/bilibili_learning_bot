# Claude 官方设计风格 — AI 代码生成严格提示词

> **用途**：将此文档全文提供给 AI（Claude / GPT / Copilot 等），要求其生成符合 Anthropic Claude 官网设计规范的网页。
> **版本**：v1.0 / 2026-07

---

## 一、设计哲学

Claude 官网的设计语言核心是 **极简黑白主义**，强调克制、留白、精密排版。用视觉的「少」传达内容的「多」。

### 三大原则
1. **去装饰化** — 不使用渐变、粗阴影、大面积圆角、华丽动效。
2. **字体即设计** — 字重对比（极细标题 vs 常规正文）是唯一的视觉层次来源。
3. **色彩克制** — 90% 黑/白/灰，10% 暖橙色点缀。暗色模式下精确反转。

---

## 二、CSS 变量 — 必须严格使用

```css
:root {
  /* 亮色模式 */
  --bg-primary: #FFFFFF;
  --bg-secondary: #F5F5F5;
  --bg-card: #FAFAFA;
  --text-primary: #0D0D0D;
  --text-secondary: #666666;
  --text-tertiary: #999999;
  --accent: #D97757;
  --accent-hover: #C56545;
  --accent-bg: rgba(217,119,87,0.08);
  --border: #E5E5E5;
  --border-light: #F0F0F0;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-lg: 0 20px 60px rgba(0,0,0,0.08);
}

[data-theme="dark"] {
  --bg-primary: #0D0D0D;
  --bg-secondary: #1A1A1A;
  --bg-card: #141414;
  --text-primary: #F5F5F5;
  --text-secondary: #999999;
  --text-tertiary: #666666;
  --accent: #E8916A;
  --accent-hover: #F0A585;
  --accent-bg: rgba(232,145,106,0.1);
  --border: #2A2A2A;
  --border-light: #1F1F1F;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-lg: 0 20px 60px rgba(0,0,0,0.5);
}
```

---

## 三、字体规范（强制）

### 字体声明
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@100;200;300;400;500;600;700;800&display=swap" rel="stylesheet">
```

### 字重层级体系（必须遵守）
| 元素 | font-weight | 说明 |
|------|------------|------|
| 超大标题（Hero） | **200** | 极细，营造轻盈感 |
| 一级标题 | **200** | 纤细优雅 |
| 二级标题 | **300** | 稍粗但依然轻盈 |
| 三级标题（卡片标题） | **500** | 适度强调 |
| 正文 | **400** | 常规字重 |
| 辅助文字 / 灰色小字 | **400** | 用颜色降低，不用字重 |
| 强调 / 列表 strong | **500** | 仅用于极少量强调 |
| 数字 / 数据大数 | **200** | 与标题保持一致 |

### 禁止行为
- ❌ 使用粗体 600+ 作为标题
- ❌ 标题和正文使用相同字重
- ❌ 使用 `bold` 关键字，必须用数值 weight
- ❌ 对灰色辅助文字使用 `font-weight: 300`

---

## 四、图标系统

### 强制使用 Lucide Icons
```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
```
```js
lucide.createIcons({ attrs: { 'stroke-width': 1.5 } });
```

### 常用图标映射（仅供参考，按需选择）
```
写作  → pen-line        代码  → code-2
数据  → bar-chart-3     网络  → globe
搜索  → scan-search     消息  → message-circle
用户  → user            设置  → settings
邮箱  → mail            手机  → smartphone
文件  → file-text       下载  → download
箭头  → chevron-right   菜单  → menu
×     → x               勾选  → check
太阳  → sun             月亮  → moon
```

### 禁止行为
- ❌ 使用任何 emoji 作为图标
- ❌ 使用 Font Awesome / Material Icons（风格不协调）
- ❌ 给图标添加背景色块
- ❌ icon 描边宽度偏离 1.5px

---

## 五、组件规范

### 5.1 卡片 (Card)
```css
.card {
  background: var(--bg-card);
  border-radius: 14px;
  padding: 36px;
  border: 1px solid var(--border);
  /* hover 时边框变 accent 色 */
}
```
- 圆角固定 14px
- 边框默认 `--border`，hover 变 `--accent`
- 内边距 36px（桌面）

### 5.2 按钮 (Button) — 主要按钮
```css
.btn-primary {
  background: var(--text-primary);
  color: var(--bg-primary);
  border: none;
  border-radius: 8px;
  padding: 12px 28px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn-primary:hover { opacity: 0.85; }
```
- 亮色模式：黑底白字；暗色模式：白底黑字
- 通过 CSS 变量自动切换

### 5.3 次要按钮 (Ghost Button)
```css
.btn-ghost {
  background: transparent;
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 28px;
  font-size: 14px;
  font-weight: 400;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-ghost:hover { border-color: var(--text-primary); }
```

### 5.4 输入框 (Input)
```css
.input {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 15px;
  font-family: 'Inter', sans-serif;
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.2s;
}
.input:focus { border-color: var(--accent); }
```

### 5.5 分割线
```css
.divider {
  width: 40px;
  height: 2px;
  background: var(--accent);
  border-radius: 1px;
}
```
- 固定宽度 40px，不撑满
- 使用 accent 色

### 5.6 标签 (Tag/Badge)
```css
.tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 500;
  padding: 5px 14px;
  border-radius: 20px;
  background: var(--accent-bg);
  color: var(--accent);
  letter-spacing: 1px;
  text-transform: uppercase;
}
```

### 5.7 表格
```css
.table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}
.table th {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
}
.table td {
  padding: 16px 24px;
  font-size: 15px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-light);
}
```

---

## 六、布局规范

### 最大内容宽度
```css
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 48px;        /* 桌面 */
}
@media (max-width: 768px) {
  .container { padding: 0 24px; }
}
```

### 间距尺度（常用）
- **xs**: 8px
- **sm**: 16px
- **md**: 24px
- **lg**: 36px
- **xl**: 48px
- **2xl**: 64px
- **3xl**: 96px

### 标准 Hero 间距
```css
.hero-section {
  padding: 120px 0 80px;  /* 桌面 */
  min-height: 80vh;
  display: flex;
  align-items: center;
}
```

---

## 七、暗色模式（强制实现）

每个页面都必须包含：
1. CSS 变量中的 `[data-theme="dark"]` 块
2. 一个右上角圆形切换按钮（40px，`moon` / `sun` 图标）
3. JavaScript 切换逻辑，含 localStorage 持久化
4. 过渡动画 `transition: background 0.4s ease, color 0.4s ease`

```html
<button class="theme-toggle" id="themeToggle" onclick="toggleTheme()">
  <i data-lucide="moon" id="themeIcon"></i>
</button>
```

---

## 八、禁止事项（红线）

| 类别 | 禁止 |
|------|------|
| **色彩** | 渐变背景、多色主题、饱和度 > 10% 的非 accent 色 |
| **圆角** | 超过 14px 的圆角、胶囊按钮 |
| **阴影** | 彩色阴影、扩散半径 > 60px、多层叠加 |
| **字体** | 衬线字体、标题加粗 > 600、草书/手写体 |
| **图标** | emoji、多色图标、带背景的图标容器 |
| **动效** | 弹跳、旋转、脉冲、闪烁、视差滚动 |
| **布局** | box-shadow 分割线、彩色卡片背景 |
| **图片** | 低质量 placeholder、未压缩的大图 |

---

## 九、暗色模式截图参考

亮色模式 → 暗色模式的所有颜色关系：
- `#FFFFFF` ↔ `#0D0D0D`（背景互换）
- `#0D0D0D` ↔ `#F5F5F5`（文字反转）
- `#666666` ↔ `#999999`（灰色辅助文字）
- `#D97757` → `#E8916A`（accent 提亮）
- `#E5E5E5` → `#2A2A2A`（边框加深）
- `rgba(0,0,0,0.08)` → `rgba(232,145,106,0.1)`（accent-bg 调整）

---

## 十、生成检查清单

生成页面后，确认以下所有项：
- [ ] Inter 字体加载链接完整（100-800 全部字重）
- [ ] Lucide Icons 加载并在 JS 中初始化
- [ ] CSS 变量明确定义 `:root` 和 `[data-theme="dark"]`
- [ ] 标题使用 font-weight: 200 或 300
- [ ] 正文使用 font-weight: 400
- [ ] 无任何 emoji
- [ ] 无任何渐变
- [ ] 暗色模式切换按钮正常
- [ ] 所有颜色通过 var() 引用
- [ ] 响应式适配完成（768px 断点）
