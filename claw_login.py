#!/usr/bin/env python3
"""
ClawCloud 自动登录脚本
- 等待设备验证批准（30秒）
- 每次登录后自动更新 Cookie
- Telegram 通知
- 企业微信 Bot 通知
"""

import os
import sys
import time
import base64
import re
import requests
from playwright.sync_api import sync_playwright

# ==================== 配置 ====================
CLAW_CLOUD_URL = "https://eu-central-1.run.claw.cloud"
SIGNIN_URL = f"{CLAW_CLOUD_URL}/signin"
DEVICE_VERIFY_WAIT = 30  # Mobile验证 默认等 30 秒
TWO_FACTOR_WAIT = int(os.environ.get("TWO_FACTOR_WAIT", "120"))  # 2FA验证 默认等 120 秒


class Telegram:
    """Telegram 通知"""
    
    def __init__(self):
        self.token = os.environ.get('TG_BOT_TOKEN')
        self.chat_id = os.environ.get('TG_CHAT_ID')
        self.ok = bool(self.token and self.chat_id)
    
    def send(self, msg):
        if not self.ok:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=30
            )
        except:
            pass
    
    def photo(self, path, caption=""):
        if not self.ok or not os.path.exists(path):
            return
        try:
            with open(path, 'rb') as f:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": self.chat_id, "caption": caption[:1024]},
                    files={"photo": f},
                    timeout=60
                )
        except:
            pass
    
    def flush_updates(self):
        """刷新 offset 到最新，避免读到旧消息"""
        if not self.ok:
            return 0
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"timeout": 0},
                timeout=10
            )
            data = r.json()
            if data.get("ok") and data.get("result"):
                return data["result"][-1]["update_id"] + 1
        except:
            pass
        return 0
    
    def wait_code(self, timeout=120):
        """
        等待你在 TG 里发 /code 123456
        只接受来自 TG_CHAT_ID 的消息
        """
        if not self.ok:
            return None
        
        # 先刷新 offset，避免读到旧的 /code
        offset = self.flush_updates()
        deadline = time.time() + timeout
        pattern = re.compile(r"^/code\s+(\d{6,8})$")  # 6位TOTP 或 8位恢复码也行
        
        while time.time() < deadline:
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={"timeout": 20, "offset": offset},
                    timeout=30
                )
                data = r.json()
                if not data.get("ok"):
                    time.sleep(2)
                    continue
                
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    chat = msg.get("chat") or {}
                    if str(chat.get("id")) != str(self.chat_id):
                        continue
                    
                    text = (msg.get("text") or "").strip()
                    m = pattern.match(text)
                    if m:
                        return m.group(1)
            
            except Exception:
                pass
            
            time.sleep(2)
        
        return None


class WeComBot:
    """企业微信机器人通知"""
    
    def __init__(self):
        # 从环境变量获取企业微信机器人webhook
        self.webhook_url = os.environ.get('WXWORK_BOT_WEBHOOK')
        self.ok = bool(self.webhook_url)
        if self.ok:
            print("✅ 企业微信 Bot 通知已启用")
        else:
            print("⚠️ 企业微信 Bot 通知未启用（需要 WXWORK_BOT_WEBHOOK）")
    
    def send(self, msg):
        """发送文本消息到企业微信"""
        if not self.ok:
            return
        
        # 转换 Telegram 的 HTML 格式到企业微信支持的格式
        # 移除 Telegram 的 HTML 标签，保留核心内容
        clean_msg = re.sub(r'<[^>]+>', '', msg)
        # 替换一些特殊符号
        clean_msg = clean_msg.replace("🔹", "▪️").replace("ℹ️", "ℹ").replace("✅", "✔").replace("❌", "❌").replace("⚠️", "⚠").replace("🔑", "🔑")
        
        try:
            requests.post(
                self.webhook_url,
                json={
                    "msgtype": "text",
                    "text": {
                        "content": clean_msg
                    }
                },
                timeout=30
            )
        except Exception as e:
            print(f"❌ 企业微信消息发送失败: {e}")
            pass
    
    def send_markdown(self, msg):
        """发送Markdown消息到企业微信（支持简单格式）"""
        if not self.ok:
            return
        
        # 转换 Telegram HTML 到企业微信 Markdown
        markdown_msg = msg
        # 替换标签
        markdown_msg = re.sub(r'<b>(.*?)</b>', r'**\1**', markdown_msg)
        markdown_msg = re.sub(r'<code>(.*?)</code>', r'`\1`', markdown_msg)
        markdown_msg = re.sub(r'<[^>]+>', '', markdown_msg)
        # 替换特殊符号
        markdown_msg = markdown_msg.replace("🔹", "▪️").replace("ℹ️", "ℹ").replace("✅", "✔").replace("❌", "❌").replace("⚠️", "⚠").replace("🔑", "🔑")
        
        try:
            requests.post(
                self.webhook_url,
                json={
                    "msgtype": "markdown",
                    "markdown": {
                        "content": markdown_msg
                    }
                },
                timeout=30
            )
        except Exception as e:
            print(f"❌ 企业微信Markdown消息发送失败: {e}")
            pass
    
    def send_image(self, path, caption=""):
        """发送图片到企业微信"""
        if not self.ok or not os.path.exists(path):
            return
        
        try:
            # 企业微信图片需要先上传获取media_id
            # 1. 读取图片并base64编码
            with open(path, 'rb') as f:
                image_data = f.read()
                base64_data = base64.b64encode(image_data).decode()
            
            # 2. 获取图片md5
            import hashlib
            md5_hash = hashlib.md5(image_data).hexdigest()
            
            # 3. 上传图片
            upload_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media"
            params = {
                "key": self.webhook_url.split('key=')[-1],
                "type": "image"
            }
            files = {
                "media": (os.path.basename(path), image_data)
            }
            r = requests.post(upload_url, params=params, files=files, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if data.get("errcode") == 0 and data.get("media_id"):
                    # 4. 发送图片
                    requests.post(
                        self.webhook_url,
                        json={
                            "msgtype": "image",
                            "image": {
                                "media_id": data["media_id"]
                            }
                        },
                        timeout=30
                    )
                    # 如果有说明文字，单独发送文本
                    if caption:
                        self.send(f"图片说明：{caption}")
        except Exception as e:
            print(f"❌ 企业微信图片发送失败: {e}")
            pass


class SecretUpdater:
    """GitHub Secret 更新器"""
    
    def __init__(self):
        self.token = os.environ.get('REPO_TOKEN')
        self.repo = os.environ.get('GITHUB_REPOSITORY')
        self.ok = bool(self.token and self.repo)
        if self.ok:
            print("✅ Secret 自动更新已启用")
        else:
            print("⚠️ Secret 自动更新未启用（需要 REPO_TOKEN）")
    
    def update(self, name, value):
        if not self.ok:
            return False
        try:
            from nacl import encoding, public
            
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            # 获取公钥
            r = requests.get(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/public-key",
                headers=headers, timeout=30
            )
            if r.status_code != 200:
                return False
            
            key_data = r.json()
            pk = public.PublicKey(key_data['key'].encode(), encoding.Base64Encoder())
            encrypted = public.SealedBox(pk).encrypt(value.encode())
            
            # 更新 Secret
            r = requests.put(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/{name}",
                headers=headers,
                json={"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": key_data['key_id']},
                timeout=30
            )
            return r.status_code in [201, 204]
        except Exception as e:
            print(f"更新 Secret 失败: {e}")
            return False


class AutoLogin:
    """自动登录"""
    
    def __init__(self):
        self.username = os.environ.get('GH_USERNAME')
        self.password = os.environ.get('GH_PASSWORD')
        self.gh_session = os.environ.get('GH_SESSION', '').strip()
        self.tg = Telegram()
        self.wxwork = WeComBot()  # 初始化企业微信机器人
        self.secret = SecretUpdater()
        self.shots = []
        self.logs = []
        self.n = 0
        
    def log(self, msg, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STEP": "🔹"}
        line = f"{icons.get(level, '•')} {msg}"
        print(line)
        self.logs.append(line)
    
    def shot(self, page, name):
        self.n += 1
        f = f"{self.n:02d}_{name}.png"
        try:
            page.screenshot(path=f)
            self.shots.append(f)
        except:
            pass
        return f
    
    def click(self, page, sels, desc=""):
        for s in sels:
            try:
                el = page.locator(s).first
                if el.is_visible(timeout=3000):
                    el.click()
                    self.log(f"已点击: {desc}", "SUCCESS")
                    return True
            except:
                pass
        return False
    
    def get_session(self, context):
        """提取 Session Cookie"""
        try:
            for c in context.cookies():
                if c['name'] == 'user_session' and 'github' in c.get('domain', ''):
                    return c['value']
        except:
            pass
        return None
    
    def save_cookie(self, value):
        """保存新 Cookie"""
        if not value:
            return
        
        self.log(f"新 Cookie: {value[:15]}...{value[-8:]}", "SUCCESS")
        
        # 自动更新 Secret
        if self.secret.update('GH_SESSION', value):
            self.log("已自动更新 GH_SESSION", "SUCCESS")
            notify_msg = "🔑 <b>Cookie 已自动更新</b>\n\nGH_SESSION 已保存"
            self.tg.send(notify_msg)
            self.wxwork.send_markdown(notify_msg)  # 企业微信通知
        else:
            # 通过 Telegram 和企业微信发送
            notify_msg = f"""🔑 <b>新 Cookie</b>

请更新 Secret <b>GH_SESSION</b>:
<code>{value}</code>"""
            self.tg.send(notify_msg)
            self.wxwork.send_markdown(notify_msg)  # 企业微信通知
            self.log("已通过 Telegram 和企业微信发送 Cookie", "SUCCESS")
    
    def wait_device(self, page):
        """等待设备验证"""
        self.log(f"需要设备验证，等待 {DEVICE_VERIFY_WAIT} 秒...", "WARN")
        self.shot(page, "设备验证")
        
        notify_msg = f"""⚠️ <b>需要设备验证</b>

请在 {DEVICE_VERIFY_WAIT} 秒内批准：
1️⃣ 检查邮箱点击链接
2️⃣ 或在 GitHub App 批准"""
        self.tg.send(notify_msg)
        self.wxwork.send_markdown(notify_msg)  # 企业微信通知
        
        if self.shots:
            self.tg.photo(self.shots[-1], "设备验证页面")
            self.wxwork.send_image(self.shots[-1], "设备验证页面")  # 企业微信发送图片
        
        for i in range(DEVICE_VERIFY_WAIT):
            time.sleep(1)
            if i % 5 == 0:
                self.log(f"  等待... ({i}/{DEVICE_VERIFY_WAIT}秒)")
                url = page.url
                if 'verified-device' not in url and 'device-verification' not in url:
                    self.log("设备验证通过！", "SUCCESS")
                    success_msg = "✅ <b>设备验证通过</b>"
                    self.tg.send(success_msg)
                    self.wxwork.send(success_msg)  # 企业微信通知
                    return True
                try:
                    page.reload(timeout=10000)
                    page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass
        
        if 'verified-device' not in page.url:
            return True
        
        self.log("设备验证超时", "ERROR")
        error_msg = "❌ <b>设备验证超时</b>"
        self.tg.send(error_msg)
        self.wxwork.send(error_msg)  # 企业微信通知
        return False
    
    def wait_two_factor_mobile(self, page):
        """等待 GitHub Mobile 两步验证批准，并把数字截图提前发到电报和企业微信"""
        self.log(f"需要两步验证（GitHub Mobile），等待 {TWO_FACTOR_WAIT} 秒...", "WARN")
        
        # 先截图并立刻发出去（让你看到数字）
        shot = self.shot(page, "两步验证_mobile")
        notify_msg = f"""⚠️ <b>需要两步验证（GitHub Mobile）</b>

请打开手机 GitHub App 批准本次登录（会让你确认一个数字）。
等待时间：{TWO_FACTOR_WAIT} 秒"""
        self.tg.send(notify_msg)
        self.wxwork.send_markdown(notify_msg)  # 企业微信通知
        
        if shot:
            self.tg.photo(shot, "两步验证页面（数字在图里）")
            self.wxwork.send_image(shot, "两步验证页面（数字在图里）")  # 企业微信发送图片
        
        # 不要频繁 reload，避免把流程刷回登录页
        for i in range(TWO_FACTOR_WAIT):
            time.sleep(1)
            
            url = page.url
            
            # 如果离开 two-factor 流程页面，认为通过
            if "github.com/sessions/two-factor/" not in url:
                self.log("两步验证通过！", "SUCCESS")
                success_msg = "✅ <b>两步验证通过</b>"
                self.tg.send(success_msg)
                self.wxwork.send(success_msg)  # 企业微信通知
                return True
            
            # 如果被刷回登录页，说明这次流程断了（不要硬等）
            if "github.com/login" in url:
                self.log("两步验证后回到了登录页，需重新登录", "ERROR")
                error_msg = "❌ <b>两步验证后回到了登录页，需重新登录</b>"
                self.tg.send(error_msg)
                self.wxwork.send(error_msg)  # 企业微信通知
                return False
            
            # 每 10 秒打印一次，并补发一次截图（防止你没看到数字）
            if i % 10 == 0 and i != 0:
                self.log(f"  等待... ({i}/{TWO_FACTOR_WAIT}秒)")
                shot = self.shot(page, f"两步验证_{i}s")
                if shot:
                    self.tg.photo(shot, f"两步验证页面（第{i}秒）")
                    self.wxwork.send_image(shot, f"两步验证页面（第{i}秒）")  # 企业微信发送图片
            
            # 只在 30 秒、60 秒... 做一次轻刷新（可选，频率很低）
            if i % 30 == 0 and i != 0:
                try:
                    page.reload(timeout=30000)
                    page.wait_for_load_state('domcontentloaded', timeout=30000)
                except:
                    pass
        
        self.log("两步验证超时", "ERROR")
        error_msg = "❌ <b>两步验证超时</b>"
        self.tg.send(error_msg)
        self.wxwork.send(error_msg)  # 企业微信通知
        return False
    
    def handle_2fa_code_input(self, page):
        """处理 TOTP 验证码输入（通过 Telegram 发送 /code 123456）"""
        self.log("需要输入验证码", "WARN")
        shot = self.shot(page, "两步验证_code")
        
        # 先尝试点击"Use an authentication app"或类似按钮（如果在 mobile 页面）
        try:
            more_options = [
                'a:has-text("Use an authentication app")',
                'a:has-text("Enter a code")',
                'button:has-text("Use an authentication app")',
                '[href*="two-factor/app"]'
            ]
            for sel in more_options:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.click()
                        time.sleep(2)
                        page.wait_for_load_state('networkidle', timeout=15000)
                        self.log("已切换到验证码输入页面", "SUCCESS")
                        shot = self.shot(page, "两步验证_code_切换后")
                        break
                except:
                    pass
        except:
            pass
        
        # 发送提示并等待验证码
        notify_msg = f"""🔐 <b>需要验证码登录</b>

请在 Telegram 里发送：
<code>/code 你的6位验证码</code>

等待时间：{TWO_FACTOR_WAIT} 秒"""
        self.tg.send(notify_msg)
        self.wxwork.send_markdown(notify_msg)  # 企业微信通知
        
        if shot:
            self.tg.photo(shot, "两步验证页面")
            self.wxwork.send_image(shot, "两步验证页面")  # 企业微信发送图片
        
        self.log(f"等待验证码（{TWO_FACTOR_WAIT}秒）...", "WARN")
        code = self.tg.wait_code(timeout=TWO_FACTOR_WAIT)
        
        if not code:
            self.log("等待验证码超时", "ERROR")
            error_msg = "❌ <b>等待验证码超时</b>"
            self.tg.send(error_msg)
            self.wxwork.send(error_msg)  # 企业微信通知
            return False
        
        # 不打印验证码明文，只提示收到
        self.log("收到验证码，正在填入...", "SUCCESS")
        success_msg = "✅ 收到验证码，正在填入..."
        self.tg.send(success_msg)
        self.wxwork.send(success_msg)  # 企业微信通知
        
        # 常见 OTP 输入框 selector（优先级排序）
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[name="app_otp"]',
            'input[name="otp"]',
            'input#app_totp',
            'input#otp',
            'input[inputmode="numeric"]'
        ]
        
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.fill(code)
                    self.log(f"已填入验证码", "SUCCESS")
                    time.sleep(1)
                    
                    # 优先点击 Verify 按钮，不行再 Enter
                    submitted = False
                    verify_btns = [
                        'button:has-text("Verify")',
                        'button[type="submit"]',
                        'input[type="submit"]'
                    ]
                    for btn_sel in verify_btns:
                        try:
                            btn = page.locator(btn_sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click()
                                submitted = True
                                self.log("已点击 Verify 按钮", "SUCCESS")
                                break
                        except:
                            pass
                    
                    if not submitted:
                        page.keyboard.press("Enter")
                        self.log("已按 Enter 提交", "SUCCESS")
                    
                    time.sleep(3)
                    page.wait_for_load_state('networkidle', timeout=30000)
                    self.shot(page, "验证码提交后")
                    
                    # 检查是否通过
                    if "github.com/sessions/two-factor/" not in page.url:
                        self.log("验证码验证通过！", "SUCCESS")
                        success_msg = "✅ <b>验证码验证通过</b>"
                        self.tg.send(success_msg)
                        self.wxwork.send(success_msg)  # 企业微信通知
                        return True
                    else:
                        self.log("验证码可能错误", "ERROR")
                        error_msg = "❌ <b>验证码可能错误，请检查后重试</b>"
                        self.tg.send(error_msg)
                        self.wxwork.send(error_msg)  # 企业微信通知
                        return False
            except:
                pass
        
        self.log("没找到验证码输入框", "ERROR")
        error_msg = "❌ <b>没找到验证码输入框</b>"
        self.tg.send(error_msg)
        self.wxwork.send(error_msg)  # 企业微信通知
        return False
    
    def login_github(self, page, context):
        """登录 GitHub"""
        self.log("登录 GitHub...", "STEP")
        self.shot(page, "github_登录页")
        
        try:
            page.locator('input[name="login"]').fill(self.username)
            page.locator('input[name="password"]').fill(self.password)
            self.log("已输入凭据")
        except Exception as e:
            self.log(f"输入失败: {e}", "ERROR")
            return False
        
        self.shot(page, "github_已填写")
        
        try:
            page.locator('input[type="submit"], button[type="submit"]').first.click()
        except:
            pass
        
        time.sleep(3)
        page.wait_for_load_state('networkidle', timeout=30000)
        self.shot(page, "github_登录后")
        
        url = page.url
        self.log(f"当前: {url}")
        
        # 设备验证
        if 'verified-device' in url or 'device-verification' in url:
            if not self.wait_device(page):
                return False
            time.sleep(2)
            page.wait_for_load_state('networkidle', timeout=30000)
            self.shot(page, "验证后")
        
        # 2FA
        if 'two-factor' in page.url:
            self.log("需要两步验证！", "WARN")
            self.shot(page, "两步验证")
            
            # GitHub Mobile：等待你在手机上批准
            if 'two-factor/mobile' in page.url:
                if not self.wait_two_factor_mobile(page):
                    return False
                # 通过后等页面稳定
                try:
                    page.wait_for_load_state('networkidle', timeout=30000)
                    time.sleep(2)
                except:
                    pass
            
            else:
                # 其它两步验证方式（TOTP/恢复码等），尝试通过 Telegram 输入验证码
                if not self.handle_2fa_code_input(page):
                    return False
                # 通过后等页面稳定
                try:
                    page.wait_for_load_state('networkidle', timeout=30000)
                    time.sleep(2)
                except:
                    pass
        
        # 错误
        try:
            err = page.locator('.flash-error').first
            if err.is_visible(timeout=2000):
                self.log(f"错误: {err.inner_text()}", "ERROR")
                return False
        except:
            pass
        
        return True
    
    def oauth(self, page):
        """处理 OAuth"""
        if 'github.com/login/oauth/authorize' in page.url:
            self.log("处理 OAuth...", "STEP")
            self.shot(page, "oauth")
            self.click(page, ['button[name="authorize"]', 'button:has-text("Authorize")'], "授权")
            time.sleep(3)
            page.wait_for_load_state('networkidle', timeout=30000)
    
    def wait_redirect(self, page, wait=60):
        """等待重定向"""
        self.log("等待重定向...", "STEP")
        for i in range(wait):
            url = page.url
            if 'claw.cloud' in url and 'signin' not in url.lower():
                self.log("重定向成功！", "SUCCESS")
                return True
            if 'github.com/login/oauth/authorize' in url:
                self.oauth(page)
            time.sleep(1)
            if i % 10 == 0:
                self.log(f"  等待... ({i}秒)")
        self.log("重定向超时", "ERROR")
        return False
    
    def keepalive(self, page):
        """保活"""
        self.log("保活...", "STEP")
        for url, name in [(f"{CLAW_CLOUD_URL}/", "控制台"), (f"{CLAW_CLOUD_URL}/apps", "应用")]:
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state('networkidle', timeout=15000)
                self.log(f"已访问: {name}", "SUCCESS")
                time.sleep(2)
            except:
                pass
        self.shot(page, "完成")
    
    def notify(self, ok, err=""):
        """发送最终结果通知（Telegram + 企业微信）"""
        if not self.tg.ok and not self.wxwork.ok:
            return
        
        msg = f"""<b>🤖 ClawCloud 自动登录</b>

<b>状态:</b> {"✅ 成功" if ok else "❌ 失败"}
<b>用户:</b> {self.username}
<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"""
        
        if err:
            msg += f"\n<b>错误:</b> {err}"
        
        msg += "\n\n<b>日志:</b>\n" + "\n".join(self.logs[-6:])
        
        # 发送到 Telegram 和企业微信
        self.tg.send(msg)
        self.wxwork.send_markdown(msg)
        
        if self.shots:
            if not ok:
                for s in self.shots[-3:]:
                    self.tg.photo(s, s)
                    self.wxwork.send_image(s, s)  # 企业微信发送图片
            else:
                self.tg.photo(self.shots[-1], "完成")
                self.wxwork.send_image(self.shots[-1], "完成")  # 企业微信发送图片
    
    def run(self):
        print("\n" + "="*50)
        print("🚀 ClawCloud 自动登录")
        print("="*50 + "\n")
        
        self.log(f"用户名: {self.username}")
        self.log(f"Session: {'有' if self.gh_session else '无'}")
        self.log(f"密码: {'有' if self.password else '无'}")
        
        if not self.username or not self.password:
            self.log("缺少凭据", "ERROR")
            self.notify(False, "凭据未配置")
            sys.exit(1)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = context.new_page()
            
            try:
                # 预加载 Cookie
                if self.gh_session:
                    try:
                        context.add_cookies([
                            {'name': 'user_session', 'value': self.gh_session, 'domain': 'github.com', 'path': '/'},
                            {'name': 'logged_in', 'value': 'yes', 'domain': 'github.com', 'path': '/'}
                        ])
                        self.log("已加载 Session Cookie", "SUCCESS")
                    except:
                        self.log("加载 Cookie 失败", "WARN")
                
                # 1. 访问 ClawCloud
                self.log("步骤1: 打开 ClawCloud", "STEP")
                page.goto(SIGNIN_URL, timeout=60000)
                page.wait_for_load_state('networkidle', timeout=30000)
                time.sleep(2)
                self.shot(page, "clawcloud")
                
                if 'signin' not in page.url.lower():
                    self.log("已登录！", "SUCCESS")
                    self.keepalive(page)
                    # 提取并保存新 Cookie
                    new = self.get_session(context)
                    if new:
                        self.save_cookie(new)
                    self.notify(True)
                    print("\n✅ 成功！\n")
                    return
                
                # 2. 点击 GitHub
                self.log("步骤2: 点击 GitHub", "STEP")
                if not self.click(page, [
                    'button:has-text("GitHub")',
                    'a:has-text("GitHub")',
                    '[data-provider="github"]'
                ], "GitHub"):
                    self.log("找不到按钮", "ERROR")
                    self.notify(False, "找不到 GitHub 按钮")
                    sys.exit(1)
                
                time.sleep(3)
                page.wait_for_load_state('networkidle', timeout=30000)
                self.shot(page, "点击后")
                
                url = page.url
                self.log(f"当前: {url}")
                
                # 3. GitHub 登录
                self.log("步骤3: GitHub 认证", "STEP")
                
                if 'github.com/login' in url or 'github.com/session' in url:
                    if not self.login_github(page, context):
                        self.shot(page, "登录失败")
                        self.notify(False, "GitHub 登录失败")
                        sys.exit(1)
                elif 'github.com/login/oauth/authorize' in url:
                    self.log("Cookie 有效", "SUCCESS")
                    self.oauth(page)
                
                # 4. 等待重定向
                self.log("步骤4: 等待重定向", "STEP")
                if not self.wait_redirect(page):
                    self.shot(page, "重定向失败")
                    self.notify(False, "重定向失败")
                    sys.exit(1)
                
                self.shot(page, "重定向成功")
                
                # 5. 验证
                self.log("步骤5: 验证", "STEP")
                if 'claw.cloud' not in page.url or 'signin' in page.url.lower():
                    self.notify(False, "验证失败")
                    sys.exit(1)
                
                # 6. 保活
                self.keepalive(page)
                
                # 7. 提取并保存新 Cookie
                self.log("步骤6: 更新 Cookie", "STEP")
                new = self.get_session(context)
                if new:
                    self.save_cookie(new)
                else:
                    self.log("未获取到新 Cookie", "WARN")
                
                self.notify(True)
                print("\n" + "="*50)
                print("✅ 成功！")
                print("="*50 + "\n")
                
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.shot(page, "异常")
                import traceback
                traceback.print_exc()
                self.notify(False, str(e))
                sys.exit(1)
            finally:
                browser.close()


if __name__ == "__main__":
    AutoLogin().run()
