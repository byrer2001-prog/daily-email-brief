"""MSAL 设备码授权：为 OAuth2 IMAP 获取/刷新访问令牌。

全程使用微软公开的公共客户端 ID（d3590ed6-...），无需注册 Azure 应用。
首次运行会打印设备码，用户在浏览器登录工作账号授权一次；
之后 refresh_token 静默刷新，每日运行无需再操作。
"""

import sys
from pathlib import Path

from msal import PublicClientApplication, SerializableTokenCache

# IMAP 访问权限。MSAL 会自动附加 offline_access/profile/openid，
# 这些保留 scope 不能手动传入，否则报错。
SCOPES = ["https://outlook.office.com/IMAP.AccessAsUser.All"]


class AuthError(Exception):
    """授权失败（用户需处理或联系 IT）。"""


class IMAPTokenAuth:
    """持有并刷新 IMAP 访问令牌。"""

    def __init__(self, config: dict):
        self.config = config
        self.email = config["email"]
        self.client_id = config["client_id"]
        self.tenant = config.get("tenant", "common")
        self.token_file = Path(__file__).parent / "token_cache.json"
        self.app = PublicClientApplication(
            client_id=self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant}",
            token_cache=self._load_cache(),
        )

    # ---- token 缓存 ----

    def _load_cache(self) -> SerializableTokenCache:
        cache = SerializableTokenCache()
        if self.token_file.exists():
            try:
                cache.deserialize(self.token_file.read_text(encoding="utf-8"))
            except Exception:
                # 缓存损坏时忽略，走设备码重新授权
                pass
        return cache

    def _save_cache(self) -> None:
        if self.app.token_cache.has_state_changed:
            self.token_file.write_text(
                self.app.token_cache.serialize(), encoding="utf-8"
            )

    # ---- 获取令牌 ----

    def get_token(self) -> str:
        """优先静默刷新；失败或没有缓存时走设备码流程。返回访问令牌。"""
        accounts = self.app.get_accounts(username=self.email)
        if accounts:
            result = self.app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]
            if result and "error" in result:
                print(
                    f"[授权] 静默刷新失败：{result.get('error_description', result.get('error'))}"
                )

        # 设备码流程（首次使用 / refresh_token 失效）
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise AuthError(
                f"设备码流程初始化失败：{flow.get('error_description', flow)}"
            )

        print("=" * 60)
        print("首次使用需要授权一次（之后每天自动刷新，无需再操作）：")
        print("1. 打开浏览器访问：https://microsoft.com/devicelogin")
        print(f"2. 输入代码：{flow['user_code']}")
        print("3. 用你的工作账号登录并确认授权")
        print("   （页面可能提示“此应用未验证”，属正常，选择继续即可）")
        print("=" * 60)
        sys.stdout.flush()

        result = self.app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            self._save_cache()
            return result["access_token"]
        raise AuthError(self._describe_error(result))

    # ---- 错误提示 ----

    @staticmethod
    def _describe_error(result: dict) -> str:
        error = result.get("error", "unknown")
        desc = result.get("error_description", "")
        hint = ""
        if "AADSTS65001" in desc or "admin_consent" in desc.lower():
            hint = "（租户禁止用户自助同意应用权限，需要 IT 管理员批准，见 README 排障章节）"
        elif "AADSTS50020" in desc:
            hint = "（请确认 config.json 里的 email 是正确的工作邮箱地址）"
        elif "AADSTS700016" in desc:
            hint = "（client_id 无效或租户不识别该应用）"
        return f"授权失败 [{error}]: {desc}{hint}"
