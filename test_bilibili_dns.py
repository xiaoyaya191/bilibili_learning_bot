#!/usr/bin/env python3
"""测试 api.bilibili.com 的 DNS 解析与连接稳定性（模拟瞬断重试）"""

import asyncio
import time
import sys

# ── 测试1：纯 DNS 解析 ──
def test_dns_resolve(round_num=1):
    import socket
    try:
        results = socket.getaddrinfo("api.bilibili.com", 443)
        ips = sorted(set(r[4][0] for r in results))
        print(f"  [轮{round_num}] ✅ DNS解析成功 → {len(ips)} 个IP: {ips[:4]}{'…' if len(ips)>4 else ''}")
        return True
    except Exception as e:
        print(f"  [轮{round_num}] ❌ DNS解析失败: {e}")
        return False

# ── 测试2：TLS 连接 ──
async def test_tls_connect(round_num=1):
    import ssl
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("api.bilibili.com", 443, ssl=ssl.create_default_context()),
            timeout=5
        )
        writer.close()
        await writer.wait_closed()
        print(f"  [轮{round_num}] ✅ TLS连接成功")
        return True
    except Exception as e:
        print(f"  [轮{round_num}] ❌ TLS连接失败: {e}")
        return False

# ── 测试3：curl 级 HTTP 请求 ──
async def test_http_request(round_num=1):
    import urllib.request
    try:
        req = urllib.request.Request("https://api.bilibili.com/x/web-interface/nav")
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = await asyncio.get_event_loop().run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=5)
        )
        print(f"  [轮{round_num}] ✅ HTTP请求成功 → status={resp.status}")
        return True
    except Exception as e:
        print(f"  [轮{round_num}] ❌ HTTP请求失败: {e}")
        return False

# ── 测试4：bilibili-api 库调用 ──
async def test_bili_api(round_num=1):
    try:
        from bilibili_api import session as bili_session
        from bilibili_api import Credential
        cred = Credential()  # 空凭证，但 get_sessions 会尝试网络
        sessions = await asyncio.wait_for(
            bili_session.get_sessions(cred, session_type=1),
            timeout=10
        )
        print(f"  [轮{round_num}] ✅ bilibili-api.get_sessions 调用成功")
        return True
    except Exception as e:
        err_msg = str(e)
        if "Credential" in err_msg or "未登录" in err_msg or "credential" in err_msg.lower():
            print(f"  [轮{round_num}] ⚠️ bilibili-api 返回认证错误(属于正常): {err_msg[:80]}")
            return True  # 网络通了，只是没凭证
        print(f"  [轮{round_num}] ❌ bilibili-api 调用失败: {err_msg[:120]}")
        return False

# ── 测试5：连续高频 DNS 解析（压力测试） ──
def test_dns_burst(count=20, interval=0.5):
    import socket
    fails = 0
    t_start = time.time()
    for i in range(count):
        try:
            socket.getaddrinfo("api.bilibili.com", 443)
        except Exception:
            fails += 1
            print(f"  ❌ 第{i+1}次 DNS 失败")
        if i < count - 1:
            time.sleep(interval)
    elapsed = time.time() - t_start
    print(f"  连续 {count} 次 DNS 解析（间隔{interval}s）: {fails}/{count} 失败, 总耗时 {elapsed:.1f}s")
    return fails == 0

# ── 测试6：带重试的 get_sessions 模拟 ──
async def test_retry_get_sessions(max_retries=3, delay=2):
    """模拟你代码里的检查私信场景：DNS 瞬断时重试"""
    from bilibili_api import session as bili_session
    from bilibili_api import Credential
    cred = Credential()
    
    for attempt in range(1, max_retries + 1):
        try:
            sessions = await asyncio.wait_for(
                bili_session.get_sessions(cred, session_type=1),
                timeout=10
            )
            print(f"  ✅ 第{attempt}次尝试成功")
            return True
        except Exception as e:
            err_msg = str(e)
            # 如果是认证错误，网络其实是通的
            if "credential" in err_msg.lower() or "未登录" in err_msg:
                print(f"  ✅ 第{attempt}次尝试返回认证错误(网络通了)")
                return True
            if attempt < max_retries:
                print(f"  ⚠️ 第{attempt}次失败，{delay}s后重试… ({err_msg[:60]})")
                await asyncio.sleep(delay)
            else:
                print(f"  ❌ {max_retries}次全部失败: {err_msg[:120]}")
                return False
    return False

# ── MAIN ──
async def main():
    print("=" * 60)
    print("🔍 api.bilibili.com 网络诊断脚本")
    print("=" * 60)

    # 1. DNS
    print("\n📡 [1/5] DNS 解析测试 (3轮)...")
    dns_ok = all(test_dns_resolve(i+1) for i in range(3))

    # 2. TLS
    print("\n🔐 [2/5] TLS 连接测试 (3轮)...")
    tls_ok = all([await test_tls_connect(i+1) for i in range(3)])

    # 3. HTTP
    print("\n🌐 [3/5] HTTP 请求测试 (3轮)...")
    http_ok = all([await test_http_request(i+1) for i in range(3)])

    # 4. bilibili-api
    print("\n🎯 [4/5] bilibili-api 库调用测试...")
    api_ok = await test_bili_api()

    # 5. 连续DNS压力
    print("\n🔥 [5/5] DNS 压力测试 (连续20次)...")
    burst_ok = test_dns_burst(20, 0.3)

    # 6. 重试机制演示
    print("\n🔄 [Bonus] 带重试的 get_sessions 模拟...")
    retry_ok = await test_retry_get_sessions()

    # ── 总结 ──
    print("\n" + "=" * 60)
    print("📊 诊断总结")
    print("=" * 60)
    results = {
        "DNS解析": dns_ok,
        "TLS连接": tls_ok,
        "HTTP请求": http_ok,
        "bilibili-api": api_ok,
        "DNS压力测试": burst_ok,
        "重试机制": retry_ok,
    }
    all_ok = all(results.values())
    for name, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status}  {name}")
    
    if all_ok:
        print("\n🎉 全部通过！网络环境稳定，之前的错误是偶发DNS瞬断。")
        print("   建议：在 get_new_messages() 加 2 次重试即可防范。")
    else:
        print("\n⚠️ 部分测试失败，当前网络可能不稳定。")
    
    return all_ok

if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
