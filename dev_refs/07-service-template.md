# 新服务模块开发模板 (Service Module Template)

> 创建新的 service 模块（如 `services/your_feature.py`）时，请遵循此模板。
> 设计为同时供 CLI（`main.py` → `cli/app.py`）和 Web（`web_panel.py`）调用。

## 完整模板

```python
"""
your_feature.py — 功能简述

功能：
1. 功能点1
2. 功能点2

设计为同时供 CLI（main.py）和 Web（web_panel.py）调用。
"""

from __future__ import annotations

import json
import os
import re
import asyncio
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from colorama import Fore, Style

# ── 路径常量 ──
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Data"
KNOWLEDGE_BASE_DIR = BASE_DIR / "KnowledgeBase"
EXPORT_DIR = BASE_DIR / "html_exports" / "your_feature"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── LLM 客户端 ──
def _get_llm_client():
    """获取 LLM 客户端（同步）"""
    try:
        from openai import OpenAI
        from core.config import config
        api_key = config.get("api", {}).get("unified_api_key", "")
        base_url = config.get("api", {}).get("unified_base_url", "https://api.openai.com/v1")
        model = config.get("api", {}).get("model_brain", "gpt-4.1-mini")
        if not api_key:
            return None, None, None
        client = OpenAI(api_key=api_key, base_url=base_url)
        return client, model, config
    except Exception:
        return None, None, None


# ── 核心功能函数（供 CLI 和 Web 共用） ──
async def your_core_function(
    param1: str,
    param2: str = "default",
    option_count: int = 5,
) -> dict[str, Any]:
    """
    核心功能函数。
    
    参数:
        param1: 必填参数
        param2: 可选参数
        option_count: 数量
    
    返回:
        {"success": bool, "result": str, "saved_path": str, "error": str}
    """
    client, model, cfg = _get_llm_client()
    if not client:
        return {"success": False, "error": "请先配置 API Key"}
    
    # ... 业务逻辑 ...
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "系统提示词"},
                {"role": "user", "content": f"用户输入: {param1}"}
            ],
            temperature=0.7,
        )
        result = response.choices[0].message.content
        
        # 保存结果
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = EXPORT_DIR / f"result_{timestamp}.md"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(result)
        
        return {
            "success": True,
            "result": result,
            "saved_path": str(filepath),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── CLI 菜单函数 ──
async def your_feature_menu_cli():
    """CLI 交互菜单"""
    while True:
        print(f"\n{Fore.CYAN}{'='*50}")
        print("  你的功能名称")
        print(f"{'='*50}{Style.RESET_ALL}")
        print(f"  {Fore.GREEN}1.{Style.RESET_ALL} 选项1")
        print(f"  {Fore.GREEN}2.{Style.RESET_ALL} 选项2")
        print(f"  {Fore.RED}0.{Style.RESET_ALL} 返回上级")
        
        choice = input(f"{Fore.CYAN}请选择: {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            param = input("请输入参数: ").strip()
            if not param:
                print(f"{Fore.YELLOW}参数不能为空{Style.RESET_ALL}")
                continue
            result = await your_core_function(param1=param)
            if result["success"]:
                print(f"{Fore.GREEN}[OK] {result['result'][:200]}...{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] {result['error']}{Style.RESET_ALL}")
```

## 集成步骤

### 1. CLI 集成（main.py + cli/app.py）

```python
# cli/app.py — 在主菜单函数中添加选项
def show_main_menu():
    # ...
    print(f"  {Fore.CYAN}J.{Style.RESET_ALL} 🛠️ 学习工具 (📝 出题考试 | 🔬 深入了解)")
    # ...

# cli/app.py — 添加菜单处理函数
def show_your_feature_menu():
    import asyncio
    from services.your_feature import your_feature_menu_cli
    asyncio.run(your_feature_menu_cli())

# main.py — 导入并添加 case
from cli.app import show_your_feature_menu
# ...
elif choice.lower() == "j":
    show_your_feature_menu()
```

### 2. Web 集成（web_panel.py + web_panel.html）

```python
# web_panel.py — 添加 API 路由
@app.route('/api/your-feature/action', methods=['POST'])
def api_your_feature_action():
    try:
        body = request.get_json(force=True)
        param = body.get('param', '').strip()
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from services.your_feature import your_core_function
            result = loop.run_until_complete(your_core_function(param1=param))
        finally:
            loop.close()
        
        return jsonify(dict(
            ok=result['success'],
            result=result.get('result', ''),
            saved_path=result.get('saved_path', ''),
            error=result.get('error')
        ))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500
```

```html
<!-- web_panel.html — 在 pg-tools 区域添加 UI 卡片 -->
<div class="pc"><h3>🆕 你的功能</h3>
<p class="form-hint">功能描述</p>
<div class="fg"><label>参数</label><input id="yourInput" placeholder="..."></div>
<button class="btn btn-pr" onclick="yourFeatureAction()">执行</button>
<span id="yourMsg" class="msg-inline"></span>
<div id="yourResult" style="display:none">
  <div class="log-box" id="yourContent"></div>
  <div id="yourSaved"></div>
</div>
</div>

<script>
async function yourFeatureAction(){
  var msg=document.getElementById('yourMsg');
  msg.innerHTML='⏳ 处理中...';
  try{
    var r=await api('POST','/api/your-feature/action',{
      param:document.getElementById('yourInput').value
    });
    if(r.ok){
      msg.innerHTML='✅ 成功';
      document.getElementById('yourContent').textContent=r.result;
      document.getElementById('yourResult').style.display='block';
    }else{
      msg.innerHTML='❌ '+(r.error||r.message||'失败');
    }
  }catch(e){msg.innerHTML='❌ '+e.message}
}
</script>
```

## ⚠️ 关键约定

1. **核心函数返回 dict**: `{"success": bool, "result": str, "saved_path": str, "error": str}`
2. **CLI 和 Web 共用核心函数**: 菜单/路由只负责参数收集和结果展示
3. **async 函数**: 核心函数用 async，CLI 用 `asyncio.run()`，Web 用 `asyncio.new_event_loop()`
4. **错误处理**: 核心函数内部 try/except，返回 `{"success": False, "error": "..."}`
5. **文件导出**: 统一使用 `html_exports/` 下的子目录
6. **更新 DEV_REFERENCE.txt**: 新增功能后必须更新开发参考文档
