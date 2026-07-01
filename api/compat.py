"""bili/compat.py — bilibili_api 兼容层"""
from bilibili_api.utils.network import Api


async def request(method: str, url: str, data=None, credential=None, **kwargs):
    """兼容旧版 request() 函数，内部使用新版 Api 类。"""
    api = Api(url=url, method=method)
    if credential:
        api.credential = credential
        # [FIX] 必须设置 verify=True，Api._prepare_request 才会自动注入 csrf/csrf_token
        api.verify = True
    if data:
        api.update_data(**data)
    return await api.request(**kwargs)
