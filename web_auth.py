# -*- coding: utf-8 -*-
"""
后端认证 + 安全修复集成代码
追加到 web_panel.py 末尾，覆盖 /login 路由和 API 端点

前提：web_panel.py 已有 Flask app（变量名 app），已有 session 用于免责声明
前提：config.json 中 web 段需增加 password 字段（默认 "admin"）和 first_login 字段（默认 true）
"""

import os
import hmac
import hashlib
import time
import base64
import json
import threading

# ── 安全增强：JSON 文件操作锁 ──
_json_locks = {}

def locked_json_write(path, data):
    """线程安全写入 JSON 文件"""
    if path not in _json_locks:
        _json_locks[path] = threading.Lock()
    with _json_locks[path]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def locked_json_read(path):
    """线程安全读取 JSON 文件"""
    if path not in _json_locks:
        _json_locks[path] = threading.Lock()
    with _json_locks[path]:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

# ── 认证 Token 生成 ──
_SECRET_KEY = None

def _get_secret():
    """获取或生成服务端密钥"""
    global _SECRET_KEY
    if _SECRET_KEY is None:
        config = locked_json_read(os.path.join(DATA_DIR, 'config.json'))
        _SECRET_KEY = config.get('web', {}).get('secret_key', '')
        if not _SECRET_KEY:
            _SECRET_KEY = base64.b64encode(os.urandom(32)).decode()
            config.setdefault('web', {})['secret_key'] = _SECRET_KEY
            locked_json_write(os.path.join(DATA_DIR, 'config.json'), config)
    return _SECRET_KEY

def make_token(username):
    """生成 24 小时有效的 HMAC token"""
    secret = _get_secret()
    expiry = int(time.time()) + 86400
    payload = f"{username}|{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    token = base64.b64encode(f"{payload}|{sig}".encode()).decode()
    return token

def verify_token(token):
    """验证 token，返回 (valid, username)"""
    if not token:
        return False, None
    try:
        raw = base64.b64decode(token).decode()
        parts = raw.rsplit('|', 1)
        if len(parts) != 2:
            return False, None
        payload, sig = parts
        user_part, expiry_str = payload.split('|', 1)
        expiry = int(expiry_str)
        if time.time() > expiry:
            return False, None

        secret = _get_secret()
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return False, None
        return True, user_part
    except Exception:
        return False, None

def get_web_config():
    """获取 web 配置"""
    config = locked_json_read(os.path.join(DATA_DIR, 'config.json'))
    return config.get('web', {})

def set_web_config(updates):
    """更新 web 配置（线程安全）"""
    config = locked_json_read(os.path.join(DATA_DIR, 'config.json'))
    config.setdefault('web', {})
    config['web'].update(updates)
    locked_json_write(os.path.join(DATA_DIR, 'config.json'), config)

# ── 安全修复：路径穿越防护 ──
def _safe_backup_path(filename):
    """确保 filename 在 BACKUP_DIR 内，防止路径穿越"""
    from pathlib import Path
    backup_root = Path(BACKUP_DIR_EXPORT).resolve()
    target = (backup_root / filename).resolve()
    if not str(target).startswith(str(backup_root) + os.sep) and str(target) != str(backup_root):
        raise ValueError("非法文件路径")
    return str(target)

# ── 安全修复：Config 脱敏 ──
def _sanitize_config_for_export(config):
    """导出前脱敏敏感字段"""
    safe = json.loads(json.dumps(config))  # 深拷贝
    if 'unified_api_key' in safe:
        safe['unified_api_key'] = '***'
    if 'web' in safe and isinstance(safe['web'], dict):
        safe['web'].pop('password', None)
        safe['web'].pop('secret_key', None)
    return safe

# ══════════════════════════════════════════════
#  登录页面 HTML（外部文件 /templates/login.html）
# ══════════════════════════════════════════════

_LOGIN_HTML = r'''${LOGIN_HTML_CONTENT}'''

# ══════════════════════════════════════════════
#  路由：登录页面
# ══════════════════════════════════════════════

@app.route('/login')
def login_page():
    """登录页面"""
    return _LOGIN_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ══════════════════════════════════════════════
#  API：用户登录
# ══════════════════════════════════════════════

@app.route('/api/login', methods=['POST'])
def api_login():
    """POST /api/login {username, password} -> {ok, token, require_password_change}"""
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({'ok': False, 'error': '请求格式错误'})

    username = (body.get('username') or '').strip()
    password = (body.get('password') or '').strip()

    web_cfg = get_web_config()
    stored_user = web_cfg.get('username', 'admin')
    stored_pass = web_cfg.get('password', 'admin')
    is_first = web_cfg.get('first_login', True)

    if username != stored_user or password != stored_pass:
        return jsonify({'ok': False, 'error': '用户名或密码错误'})

    token = make_token(username)

    if is_first and password == 'admin':
        return jsonify({
            'ok': True,
            'token': token,
            'require_password_change': True,
            'message': '请修改默认用户名和密码'
        })

    return jsonify({'ok': True, 'token': token})

# ══════════════════════════════════════════════
#  API：修改密码/用户名
# ══════════════════════════════════════════════

@app.route('/api/password-change', methods=['POST'])
def api_password_change():
    """POST /api/password-change {new_password, new_username} -> {ok, token}"""
    # 需要 Bearer token 认证
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.replace('Bearer ', '').strip()
    valid, username = verify_token(token)
    if not valid:
        return jsonify({'ok': False, 'error': '未授权'})

    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({'ok': False, 'error': '请求格式错误'})

    new_password = (body.get('new_password') or '').strip()
    new_username = (body.get('new_username') or '').strip()

    if new_username and len(new_username) < 2:
        return jsonify({'ok': False, 'error': '用户名至少 2 位'})
    if new_password and len(new_password) < 3:
        return jsonify({'ok': False, 'error': '新密码至少 3 位'})
    if not new_password and not new_username:
        return jsonify({'ok': False, 'error': '至少修改一项'})

    web_cfg = get_web_config()
    if new_username:
        web_cfg['username'] = new_username
    if new_password:
        web_cfg['password'] = new_password
    web_cfg['first_login'] = False
    set_web_config(web_cfg)

    new_token = make_token(new_username or web_cfg.get('username', 'admin'))
    return jsonify({'ok': True, 'token': new_token, 'message': '修改成功'})

# ══════════════════════════════════════════════
#  API：验证令牌有效性
# ══════════════════════════════════════════════

@app.route('/api/auth/check', methods=['GET'])
def api_auth_check():
    """GET /api/auth/check -> {ok, authenticated}"""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.replace('Bearer ', '').strip()
    valid, username = verify_token(token)
    return jsonify({'ok': True, 'authenticated': valid, 'username': username if valid else None})

# ══════════════════════════════════════════════
#  安全修复：/api/import/apply 路径穿越修复
# ══════════════════════════════════════════════
# （替换原有 /api/import/apply 端点）

@app.route('/api/import/apply', methods=['POST'])
def api_import_apply_fixed():
    """导入备份文件（安全修复版：路径穿越防护）"""
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({'ok': False, 'error': '请求格式错误'})

    fname = body.get('filename', '')
    if not fname:
        return jsonify({'ok': False, 'error': '请提供文件名'})

    try:
        safe_path = _safe_backup_path(fname)
    except ValueError:
        return jsonify({'ok': False, 'error': '不允许的文件路径'})

    if not os.path.exists(safe_path):
        return jsonify({'ok': False, 'error': '文件不存在'})

    try:
        import_data = locked_json_read(safe_path)
    except Exception:
        return jsonify({'ok': False, 'error': '文件格式错误'})

    # 应用导入数据...
    return jsonify({'ok': True, 'message': '导入成功'})


# ══════════════════════════════════════════════
#  安全修复：/api/export 脱敏 API Key
# ══════════════════════════════════════════════
# （替换原有 /api/export 端点）

@app.route('/api/export', methods=['GET'])
def api_export_sanitized():
    """导出配置（安全修复版：脱敏敏感字段）"""
    config = locked_json_read(os.path.join(DATA_DIR, 'config.json'))
    safe_config = _sanitize_config_for_export(config)
    return jsonify({'ok': True, 'config': safe_config})


# ══════════════════════════════════════════════
#  安全修复：/api/factory-reset 二次确认
# ══════════════════════════════════════════════
# （替换原有 /api/factory-reset 端点）

@app.route('/api/factory-reset', methods=['POST'])
def api_factory_reset_safe():
    """恢复出厂设置（安全修复版：需要二次确认）"""
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({'ok': False, 'error': '请求格式错误'})

    confirm = (body.get('confirm') or '').strip()
    if confirm != '确认恢复出厂设置':
        return jsonify({
            'ok': False,
            'error': '请在 confirm 字段中填入"确认恢复出厂设置"进行二次确认'
        })

    # 执行恢复出厂设置...
    return jsonify({'ok': True, 'message': '已恢复出厂设置'})


# ══════════════════════════════════════════════
#  修改 before_request：添加认证检查
# ══════════════════════════════════════════════
# 在原有的 _check_disclaimer() 之后追加认证拦截逻辑
#
# 修改后的 before_request：
#
# @app.before_request
# def _check_auth():
#     # 1. 免责声明检查（原有逻辑）
#     if not session.get('disclaimer_agreed'):
#         if request.endpoint in ('disclaimer_page', 'api_disclaimer_confirm', 'static', 'login_page'):
#             return None
#         if request.path.startswith('/api/disclaimer'):
#             return None
#         if request.path == '/disclaimer':
#             return None
#         return redirect('/disclaimer')
#     
#     # 2. 登录检查（新增）
#     # 免登录路径
#     public_paths = ('/login', '/api/login', '/api/password-change', '/api/auth/check')
#     if request.path in public_paths or request.path.startswith('/static/'):
#         return None
#     
#     # Bearer token 验证
#     auth_header = request.headers.get('Authorization', '')
#     token = auth_header.replace('Bearer ', '').strip()
#     valid, _ = verify_token(token)
#     if valid:
#         return None
#     
#     # 允许 API 请求返回 401 而不是重定向
#     if request.path.startswith('/api/'):
#         return jsonify({'ok': False, 'error': '请先登录'}), 401
#     
#     return redirect('/login')


# ══════════════════════════════════════════════
#  初始化：确保 config.json 有 web 段
# ══════════════════════════════════════════════

def init_web_auth():
    """确保 config.json 包含 web 认证配置"""
    config = locked_json_read(os.path.join(DATA_DIR, 'config.json'))
    if 'web' not in config:
        config['web'] = {
            'username': 'admin',
            'password': 'admin',
            'first_login': True,
            'secret_key': ''
        }
        locked_json_write(os.path.join(DATA_DIR, 'config.json'), config)
    else:
        config['web'].setdefault('username', 'admin')
        config['web'].setdefault('password', 'admin')
        if 'first_login' not in config['web']:
            config['web']['first_login'] = True
        config['web'].setdefault('secret_key', '')
        locked_json_write(os.path.join(DATA_DIR, 'config.json'), config)