#!/usr/bin/env python3
"""
ClawCloud 自动登录脚本
- 等待设备验证批准（30秒）
- 每次登录后自动更新 Cookie
- Telegram 通知
- 企业微信 Bot 通知（仅文本+图片）
"""

import os
import sys
import time
import base64
import re
import hashlib
import requests
from playwright.sync_api import sync_playwright

# ==================== 配置 ====================
CLAW_CLOUD_URL = "https://eu-central-1.run.claw.cloud"
SIGNIN_URL = f"{CLAW_CLOUD_URL}/signin"
DEVICE_VERIFY_WAIT = 30  # Mobile验证 默认等 30 秒
TWO_FACTOR_WAIT = int(os.environ.get("TWO_FACTOR_WAIT", "120"))  # 2FA验证 默认等 120 秒
WECHAT_IMAGE_MAX_SIZE = 2 * 1024 * 1024  # 企业微信图片最大2M


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
    """企业微信机器人通知（仅文本+图片，贴合官方文档规范）"""
    
    def __init__(self):
        # 从环境变量获取企业微信机器人webhook
        self.webhook_url = os.environ.get('WXWORK_BOT_WEBHOOK')
        self.ok = bool(self.webhook_url)
        if self.ok:
            print("✅ 企业微信 Bot 通知已启用（文本+图片）")
        else:
            print("⚠️ 企业微信 Bot 通知未启用（需要配置 WXWORK_BOT_WEBHOOK 环境变量）")
    
    def send_text(self, content, mentioned_list=None, mentioned_mobile_list=None):
        """
        发送文本消息（参考官方文本类型规范）
        :param content: 文本内容（最长2048字节，UTF-8编码）
        :param mentioned_list: 要@的userid列表（@all表示所有人）
        :param mentioned_mobile_list: 要@的手机号列表（@all表示所有人）
        """
        if not self.ok:
            return
        
        # 文本长度限制校验
        if len(content.encode('utf-8')) > 2048:
            content = content[:500] + "..."  # 截断过长内容
            print("⚠️ 企业微信文本消息过长，已自动截断")
        
        # 构造请求数据
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        
        # 可选参数：@指定成员
        if mentioned_list:
            data["text"]["mentioned_list"] = mentioned_list
        if mentioned_mobile_list:
            data["text"]["mentioned_mobile_list"] = mentioned_mobile_list
        
        try:
            response = requests.post(
                self.webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            # 校验返回结果
            result = response.json()
            if result.get("errcode") != 0:
                print(f"❌ 企业微信文本消息发送失败：{result.get('errmsg', '未知错误')}")
        except Exception as e:
            print(f"❌ 企业微信文本消息发送异常：{str(e)}")
    
    def send_image(self, image_path, caption=None):
        """
        发送图片消息（参考官方图片类型规范）
        :param image_path: 图片文件路径（支持JPG/PNG，大小≤2M）
        :param caption: 图片说明（单独发送文本，因官方图片类型不支持直接带说明）
        """
        if not self.ok or not os.path.exists(image_path):
            return
        
        # 图片大小校验
        image_size = os.path.getsize(image_path)
        if image_size > WECHAT_IMAGE_MAX_SIZE:
            print(f"❌ 企业微信图片超过2M限制（当前{image_size/1024/1024:.1f}M），无法发送")
            return
        
        # 图片格式校验
        file_ext = os.path.splitext(image_path)[-1].lower()
        if file_ext not in ['.jpg', '.jpeg', '.png']:
            print(f"❌ 企业微信仅支持JPG/PNG格式图片，当前格式：{file_ext}")
            return
        
        try:
            # 1. 读取图片并计算base64和md5（官方必填参数）
            with open(image_path, 'rb') as f:
                image_data = f.read()
                base64_str = base64.b64encode(image_data).decode('utf-8')
                md5_str = hashlib.md5(image_data).hexdigest()
            
            # 2. 构造图片请求数据（严格遵循官方格式）
            data = {
                "msgtype": "image",
                "image": {
                    "base64": base64_str,
                    "md5": md5_str
                }
            }
            
            # 3. 发送图片
            response = requests.post(
                self.webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            
            # 4. 校验图片发送结果
            result = response.json()
            if result.get("errcode") != 0:
                print(f"❌ 企业微信图片发送失败：{result.get('errmsg', '未知错误')}")
            else:
                # 5. 若有说明文本，单独发送
                if caption and len(caption.strip()) > 0:
                    self.send_text(f"图片说明：{caption.strip()}")
        
        except Exception as e:
            print(f"❌ 企业微信图片发送异常：{str(e)}")


class SecretUpdater:
    """GitHub Secret 更新器"""
    
    def __init__(self):
        self.token = os.environ.get('REPO_TOKEN')
        self.repo = os.environ.get('GITHUB_REPOSITORY')
        self.ok = bool(self.token and self.repo)
        if self.ok:
            print("✅ Secret 自动更新已启用")
        else:
            print("⚠️ Secret 自动更新未启用（需要配置 REPO_TOKEN 环境变量）")
    
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
        self.wxwork = WeComBot()  # 初始化企业微信机器人（文本+图片）
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
            tg_msg = "🔑 Cookie 已自动更新\n\nGH_SESSION 已保存"
            wx_msg = "🔑 ClawCloud 自动登录通知\n\n✅ Cookie 已自动更新\nGH_SESSION 已保存至 GitHub Secrets"
            self.tg.send(tg_msg)
            self.wxwork.send_text(wx_msg)  # 企业微信文本通知
        else:
            # 通过 Telegram 和企业微信发送
            tg_msg = f"🔑 新 Cookie\n\n请更新 Secret GH_SESSION:\n<code>{value}</code>"
            wx_msg = f"🔑 ClawCloud 自动登录通知\n\n⚠️ 需要手动更新 GH_SESSION\n新 Cookie: {value[:15]}...{value[-8:]}"
            self.tg.send(tg_msg)
            self.wxwork.send_text(wx_msg)  # 企业微信文本通知
            self.log("已通过 Telegram 和企业微信发送 Cookie", "SUCCESS")
    
    def wait_device(self, page):
        """等待设备验证"""
        self.log(f"需要设备验证，等待 {DEVICE_VERIFY_WAIT} 秒...", "WARN")
        shot_path = self.shot(page, "设备验证")
        
        # 构造通知消息（纯文本，贴合企业微信规范）
        notify_msg = f"⚠️ ClawCloud 自动登录通知\n\n需要设备验证（{DEVICE_VERIFY_WAIT}秒内完成）\n1. 检查邮箱点击验证链接\n2. 或在 GitHub App 中批准本次登录"
        self.tg.send(notify_msg)
        self.wxwork.send_text(notify_msg)  # 企业微信文本通知
        
        # 发送验证页面截图
        if shot_path:
            self.tg.photo(shot_path, "设备验证页面")
            self.wxwork.send_image(shot_path, "设备验证页面截图")  # 企业微信图片通知
        
        for i in range(DEVICE_VERIFY_WAIT):
            time.sleep(1)
            if i % 5 == 0:
                self.log(f"  等待... ({i}/{DEVICE_VERIFY_WAIT}秒)")
                url = page.url
                if 'verified-device' not in url and 'device-verification' not in url:
                    self.log("设备验证通过！", "SUCCESS")
                    success_msg = "✅ ClawCloud 自动登录通知\n\n设备验证已通过，继续登录流程"
                    self.tg.send(success_msg)
                    self.wxwork.send_text(success_msg)  # 企业微信文本通知
                    return True
                try:
                    page.reload(timeout=10000)
                    page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass
        
        if 'verified-device' not in page.url:
            return True
        
        self.log("设备验证超时", "ERROR")
        error_msg = "❌ ClawCloud 自动登录通知\n\n设备验证超时，登录失败"
        self.tg.send(error_msg)
        self.wxwork.send_text(error_msg)  # 企业微信文本通知
        return False
    
    def wait_two_factor_mobile(self, page):
        """等待 GitHub Mobile 两步验证批准"""
        self.log(f"需要两步验证（GitHub Mobile），等待 {TWO_FACTOR_WAIT} 秒...", "WARN")
        
        # 先截图并发送
        shot_path = self.shot(page, "两步验证_mobile")
        notify_msg = f"⚠️ ClawCloud 自动登录通知\n\n需要两步验证（{TWO_FACTOR_WAIT}秒内完成）\n请打开手机 GitHub App 批准本次登录\n（需确认页面显示的数字）"
        self.tg.send(notify_msg)
        self.wxwork.send_text(notify_msg)  # 企业微信文本通知
        
        if shot_path:
            self.tg.photo(shot_path, "两步验证页面（数字在图中）")
            self.wxwork.send_image(shot_path, "两步验证页面（请确认图中数字）")  # 企业微信图片通知
        
        # 等待验证通过
        for i in range(TWO_FACTOR_WAIT):
            time.sleep(1)
            url = page.url
            
            # 如果离开 two-factor 流程页面，认为通过
            if "github.com/sessions/two-factor/" not in url:
                self.log("两步验证通过！", "SUCCESS")
                success_msg = "✅ ClawCloud 自动登录通知\n\n两步验证已通过，继续登录流程"
                self.tg.send(success_msg)
                self.wxwork.send_text(success_msg)  # 企业微信文本通知
                return True
            
            # 如果被刷回登录页，说明流程断了
            if "github.com/login" in url:
                self.log("两步验证后回到了登录页，需重新登录", "ERROR")
                error_msg = "❌ ClawCloud 自动登录通知\n\n两步验证流程异常，已返回登录页"
                self.tg.send(error_msg)
                self.wxwork.send_text(error_msg)  # 企业微信文本通知
                return False
            
            # 每10秒补发一次截图
            if i % 10 == 0 and i != 0:
                self.log(f"  等待... ({i}/{TWO_FACTOR_WAIT}秒)")
                shot_path = self.shot(page, f"两步验证_{i}s")
                if shot_path:
                    self.tg.photo(shot_path, f"两步验证页面（第{i}秒）")
                    self.wxwork.send_image(shot_path, f"两步验证页面（第{i}秒，仍需确认）")
        
        self.log("两步验证超时", "ERROR")
        error_msg = "❌ ClawCloud 自动登录通知\n\n两步验证超时，登录失败"
        self.tg.send(error_msg)
        self.wxwork.send_text(error_msg)  # 企业微信文本通知
        return False
    
    def handle_2fa_code_input(self, page):
        """处理 TOTP 验证码输入"""
        self.log("需要输入验证码", "WARN")
        shot_path = self.shot(page, "两步验证_code")
        
        # 尝试切换到验证码输入页面
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
                        shot_path = self.shot(page, "两步验证_code_切换后")
                        break
                except:
                    pass
        except:
            pass
        
        # 发送验证码输入提示
        notify_msg = f"🔐 ClawCloud 自动登录通知\n\n需要输入验证码（{TWO_FACTOR_WAIT}秒内完成）\n请在 Telegram 中发送指令：/code 你的6位验证码"
        self.tg.send(notify_msg)
        self.wxwork.send_text(notify_msg)  # 企业微信文本通知
        
        # 发送验证码页面截图
        if shot_path:
            self.tg.photo(shot_path, "两步验证页面")
            self.wxwork.send_image(shot_path, "验证码输入页面截图")  # 企业微信图片通知
        
        self.log(f"等待验证码（{TWO_FACTOR_WAIT}秒）...", "WARN")
        code = self.tg.wait_code(timeout=TWO_FACTOR_WAIT)
        
        if not code:
            self.log("等待验证码超时", "ERROR")
            error_msg = "❌ ClawCloud 自动登录通知\n\n等待验证码超时，登录失败"
            self.tg.send(error_msg)
            self.wxwork.send_text(error_msg)  # 企业微信文本通知
            return False
        
        # 提示收到验证码
        self.log("收到验证码，正在填入...", "SUCCESS")
        success_msg = "✅ ClawCloud 自动登录通知\n\n已收到验证码，正在提交验证"
        self.tg.send(success_msg)
        self.wxwork.send_text(success_msg)  # 企业微信文本通知
        
        # 填写验证码并提交
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
                        success_msg = "✅ ClawCloud 自动登录通知\n\n验证码验证通过，继续登录流程"
                        self.tg.send(success_msg)
                        self.wxwork.send_text(success_msg)  # 企业微信文本通知
                        return True
                    else:
                        self.log("验证码可能错误", "ERROR")
                        error_msg = "❌ ClawCloud 自动登录通知\n\n验证码验证失败，请检查验证码是否正确"
                        self.tg.send(error_msg)
                        self.wxwork.send_text(error_msg)  # 企业微信文本通知
                        return False
            except:
                pass
        
        self.log("没找到验证码输入框", "ERROR")
        error_msg = "❌ ClawCloud 自动登录通知\n\n未找到验证码输入框，登录失败"
        self.tg.send(error_msg)
        self.wxwork.send_text(error_msg)  # 企业微信文本通知
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
            
            # GitHub Mobile：等待手机批准
            if 'two-factor/mobile' in page.url:
                if not self.wait_two_factor_mobile(page):
                    return False
                try:
                    page.wait_for_load_state('networkidle', timeout=30000)
                    time.sleep(2)
                except:
                    pass
            
            else:
                # 验证码输入方式
                if not self.handle_2fa_code_input(page):
                    return False
                try:
                    page.wait_for_load_state('networkidle', timeout=30000)
                    time.sleep(2)
                except:
                    pass
        
        # 错误检测
        try:
            err = page.locator('.flash-error').first
            if err.is_visible(timeout=2000):
                err_msg = err.inner_text()
                self.log(f"错误: {err_msg}", "ERROR")
                wx_msg = f"❌ ClawCloud 自动登录通知\n\nGitHub 登录失败\n错误信息: {err_msg[:50]}..."
                self.wxwork.send_text(wx_msg)  # 企业微信文本通知
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
        error_msg = "❌ ClawCloud 自动登录通知\n\n重定向超时，登录失败"
        self.wxwork.send_text(error_msg)  # 企业微信文本通知
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
    
    def notify_final_result(self, ok, err=""):
        """发送最终登录结果通知（文本+图片）"""
        if not self.tg.ok and not self.wxwork.ok:
            return
        
        # 构造结果消息
        base_msg = f"🤖 ClawCloud 自动登录结果\n\n状态: {'✅ 登录成功' if ok else '❌ 登录失败'}\n用户: {self.username}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        if err:
            base_msg += f"\n错误信息: {err[:100]}..."
        
        # Telegram 通知
        self.tg.send(base_msg)
        
        # 企业微信文本通知（简化格式，纯文本展示）
        wx_msg = f"🤖 ClawCloud 自动登录结果\n\n状态: {'✅ 登录成功' if ok else '❌ 登录失败'}\n用户: {self.username}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        if err:
            wx_msg += f"\n错误信息: {err[:50]}..."
        self.wxwork.send_text(wx_msg)
        
        # 发送关键截图
        if self.shots:
            if not ok:
                # 失败时发送最后3张截图
                for s in self.shots[-3:]:
                    self.tg.photo(s, s)
                    self.wxwork.send_image(s, f"登录流程截图：{os.path.basename(s)}")
            else:
                # 成功时发送最终截图
                final_shot = self.shots[-1]
                self.tg.photo(final_shot, "登录完成")
                self.wxwork.send_image(final_shot, "ClawCloud 登录成功截图")
    
    def run(self):
        print("\n" + "="*50)
        print("🚀 ClawCloud 自动登录（企业微信通知：文本+图片）")
        print("="*50 + "\n")
        
        self.log(f"用户名: {self.username}")
        self.log(f"Session: {'有' if self.gh_session else '无'}")
        self.log(f"密码: {'有' if self.password else '无'}")
        
        if not self.username or not self.password:
            self.log("缺少凭据", "ERROR")
            self.notify_final_result(False, "未配置 GitHub 用户名或密码")
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
                    new_cookie = self.get_session(context)
                    if new_cookie:
                        self.save_cookie(new_cookie)
                    self.notify_final_result(True)
                    print("\n✅ 成功！\n")
                    return
                
                # 2. 点击 GitHub 登录
                self.log("步骤2: 点击 GitHub 登录", "STEP")
                if not self.click(page, [
                    'button:has-text("GitHub")',
                    'a:has-text("GitHub")',
                    '[data-provider="github"]'
                ], "GitHub 登录按钮"):
                    self.log("找不到 GitHub 登录按钮", "ERROR")
                    self.notify_final_result(False, "找不到 GitHub 登录按钮")
                    sys.exit(1)
                
                time.sleep(3)
                page.wait_for_load_state('networkidle', timeout=30000)
                self.shot(page, "点击 GitHub 后")
                
                url = page.url
                self.log(f"当前页面: {url}")
                
                # 3. GitHub 认证
                self.log("步骤3: GitHub 认证", "STEP")
                if 'github.com/login' in url or 'github.com/session' in url:
                    if not self.login_github(page, context):
                        self.shot(page, "GitHub 登录失败")
                        self.notify_final_result(False, "GitHub 登录失败")
                        sys.exit(1)
                elif 'github.com/login/oauth/authorize' in url:
                    self.log("Cookie 有效，直接授权", "SUCCESS")
                    self.oauth(page)
                
                # 4. 等待重定向
                self.log("步骤4: 等待重定向到 ClawCloud", "STEP")
                if not self.wait_redirect(page):
                    self.shot(page, "重定向失败")
                    self.notify_final_result(False, "重定向到 ClawCloud 超时")
                    sys.exit(1)
                
                self.shot(page, "重定向成功")
                
                # 5. 验证登录状态
                self.log("步骤5: 验证登录状态", "STEP")
                if 'claw.cloud' not in page.url or 'signin' in page.url.lower():
                    self.notify_final_result(False, "ClawCloud 登录状态验证失败")
                    sys.exit(1)
                
                # 6. 保活操作
                self.keepalive(page)
                
                # 7. 提取并保存新 Cookie
                self.log("步骤6: 更新 Session Cookie", "STEP")
                new_cookie = self.get_session(context)
                if new_cookie:
                    self.save_cookie(new_cookie)
                else:
                    self.log("未获取到新 Cookie", "WARN")
                    wx_msg = "⚠️ ClawCloud 自动登录通知\n\n登录成功，但未获取到新的 GH_SESSION Cookie"
                    self.wxwork.send_text(wx_msg)
                
                # 发送最终成功通知
                self.notify_final_result(True)
                print("\n" + "="*50)
                print("✅ ClawCloud 自动登录成功！")
                print("="*50 + "\n")
                
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.shot(page, "异常截图")
                import traceback
                traceback.print_exc()
                self.notify_final_result(False, str(e))
                sys.exit(1)
            finally:
                browser.close()


if __name__ == "__main__":
    AutoLogin().run()
