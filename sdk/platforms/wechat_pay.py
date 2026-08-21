# -*- coding: utf-8 -*-
"""
微信支付平台工具类

封装微信支付商户平台的Cookie管理 + API调用 + 失效刷新

官方 vs 非官方（参考 dj_new_server 的分离模式）：
- official_api(): 微信支付APIv3，用商户证书+APIv3密钥签名，无需cookie
- web_api():      微信支付商户平台网页接口，用cookie + 网页请求头
"""
import json
from typing import Dict

from sdk.platforms import register_platform, PlatformBase


@register_platform("wechat_pay")
class WeChatPayPlatform(PlatformBase):
    """微信支付平台：Cookie管理 + 官方API + 非官方API + 失效刷新"""

    platform_name = "wechat_pay"
    root_domain = ".weixin.qq.com"  # 微信支付商户平台域名

    # 微信支付APIv3官方网关
    official_gateway = "https://api.mch.weixin.qq.com"

    default_headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    }

    def _sign_official(self, params: Dict, app_secret: str) -> str:
        """
        微信支付APIv3签名（需商户证书私钥，此处留接口，实际用证书签名）

        微信支付APIv3签名方式与京东/拼多多不同：
        - 使用商户私钥做RSA-SHA256签名
        - 签名串格式：HTTP方法\\n请求路径\\n时间戳\\n随机串\\n请求体\\n
        - 需要商户证书文件（.pem），不适合在通用params+app_secret模式中实现

        实际项目中微信支付官方接口建议单独封装（需要证书上下文），
        此处保留接口结构，如需使用请重写official_api()。
        """
        raise NotImplementedError(
            "[wechat_pay] 微信支付APIv3签名需商户证书私钥（RSA-SHA256），"
            "请在子类中重写official_api()方法并加载证书文件"
        )

    def _is_expired(self, resp, text: str) -> bool:
        """
        检测微信支付API响应是否表示cookie失效

        微信支付失效特征：
        - HTTP 401/302（重定向到登录页）
        - 响应含 'login' 或 redirect
        - session_key过期
        """
        if resp.status in (401, 302, 403):
            return True
        low_text = text.lower()[:800]
        if "login" in low_text or "登录" in text[:200]:
            return True
        # 微信支付特有：检查redirect到登录页
        if "redirect" in low_text and "login" in low_text:
            return True
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                # 微信支付返回base_resp中的ret_code非0表示错误
                base_resp = result.get("base_resp", {})
                ret_code = base_resp.get("ret", -1)
                if ret_code in (-1, 1001):
                    return True
        except Exception:
            pass
        return False
