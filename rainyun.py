#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rainyun（雨云）每日签到，Python 版
- 多账号支持
- 顺序或并发执行（通过 MODE）
- 发送 Telegram 推送（可选）
"""

import os
import sys
import json
import time
import random
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ------------------------------------------------------------ #
# ---------- 配置常量 & 日志 -------------------------------- #
# ------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("Rainyun")

# 并发/顺序模式 1=顺序 2=并发
MODE = int(os.getenv("MODE", "1"))
# 并发最大数（仅在 MODE==2 时使用）
RUN_MAX = int(os.getenv("RUN_MAX", "3"))

# 账号读取方式：env → file
ENV_VAR_NAME = "yuyun"
FILE_NAME     = "yuyun.txt"

# Telegram 推送
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")

# ------------------------------------------------------------ #
# ---------- 单账号处理类 -------------------------------- #
# ------------------------------------------------------------ #
class RainyunAccount:
    """一个账号的完整签到流程"""

    def __init__(self, line: str, idx: int):
        if "#" not in line:
            raise ValueError(f"账号行格式错误，必须是 '手机号#密码'")
        self.phone, self.password = [p.strip() for p in line.split("#", 1)]
        self.idx = idx
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/108.0.0.0 Safari/537.36"
                )
            }
        )
        self.csrf_token = None

    # -------------------------------------- #
    # ------------- 业务实现 ----------------#
    # -------------------------------------- #
    def run(self):
        """完成一整套业务流程，返回 (成功, 结果消息)"""
        try:
            log.info(f"[{self.idx:02d}] 开始签到任务")
            if not self._login():
                return False, "登录失败"
            self._random_delay()

            ticket, rand = self._get_slide_verify()
            if not ticket:
                return False, "滑块验证码获取失败"

            self._log("滑块验证码获取成功")

            user_info = self._get_user_info()
            if not user_info:
                return False, "获取用户信息失败"

            ok, msg = self._sign_in(ticket, rand)
            if ok:
                msg = "签到成功"
            else:
                msg = f"签到错误：{msg}"

            # 再次拉取积分
            new_info = self._get_user_info()
            points = new_info["points"] if new_info else user_info["points"]

            summary = f"""
⚡  签到状态：{msg}
💰  当前积分：{points}
🏠  最后登录地点：{user_info.get('lastLoginArea', '')} ({user_info.get('lastIP', '')})
"""
            self._log(summary.strip())

            return True, msg

        except Exception as exc:
            log.error(f"[{self.idx:02d}] 任务异常：{exc}")
            log.debug(traceback.format_exc())
            return False, str(exc)

    # -------------------------------------- #
    # ------------ 具体实现 ----------------#
    # -------------------------------------- #

    def _log(self, msg):
        prefix = f"[{self.idx:02d}] {self.phone[:4]}****{self.phone[7:]}"
        log.info(f"{prefix} {msg}")

    def _random_delay(self):
        delay = random.randint(10, 20)
        self._log(f"随机延迟 {delay} 秒")
        time.sleep(delay)

    def _login(self) -> bool:
        """登录，提取 CSRF Token"""
        try:
            resp = self.session.post(
                "https://api.v2.rainyun.com/user/login",
                json={"field": self.phone, "password": self.password},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            self._log(f"HTTP 登录异常：{exc}")
            return False

        # 解析 CSRF
        cookie = resp.cookies.get("X-CSRF-Token")
        if not cookie:
            self._log("Cookie 里缺少 X-CSRF-Token")
            return False
        self.csrf_token = cookie
        self._log(f"提取 CSRF Token：{cookie[:8]}...")
        return True

    def _get_slide_verify(self):
        """调用外部滑块验证码服务"""
        url = "https://txdx.vvvcx.me/solve_captcha?aid=2039519451&type=1"
        for i in range(3):
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == 200 and data.get("message") == "Success":
                    d = data.get("data", {})
                    ticket, randstr = d.get("ticket"), d.get("randstr")
                    if ticket and randstr:
                        return ticket, randstr
            except Exception as exc:
                self._log(f"第 {i+1} 次校验请求异常：{exc}")
            time.sleep(2)
        return None, None

    def _get_user_info(self):
        """获取用户信息"""
        if not self.csrf_token:
            self._log("CSRF Token 为空，无法获取用户信息")
            return None
        try:
            resp = self.session.get(
                "https://api.v2.rainyun.com/user/?no_cache=false",
                headers={"x-csrf-token": self.csrf_token, "Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "name": data.get("Name"),
                "email": data.get("Email"),
                "points": data.get("Points"),
                "lastIP": data.get("LastIP"),
                "lastLoginArea": data.get("LastLoginArea"),
            }
        except Exception as exc:
            self._log(f"获取用户信息异常：{exc}")
            return None

    def _sign_in(self, ticket, randstr):
        """签到接口"""
        try:
            resp = self.session.post(
                "https://api.v2.rainyun.com/user/reward/tasks",
                headers={
                    "x-csrf-token": self.csrf_token,
                    "Content-Type": "application/json",
                },
                json={
                    "task_name": "每日签到",
                    "verifyCode": "",
                    "vticket": ticket,
                    "vrandstr": randstr,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 200:
                return True, data.get("message", "签到成功")
            else:
                return False, data.get("message", f"业务码 {data.get('code')}")
        except Exception as exc:
            self._log(f"签到请求异常：{exc}")
            return False, str(exc)


# ------------------------------------------------------------ #
# ---------- 多账号管理 -------------------------------- #
# ------------------------------------------------------------ #
def load_accounts():
    """读取账号列表，返回 RainyunAccount 实例列表"""
    raw = os.getenv(ENV_VAR_NAME, "").strip()
    if not raw and os.path.exists(FILE_NAME):
        log.info(f"未在环境变量中找到账号，尝试读取文件 {FILE_NAME}")
        with open(FILE_NAME, "r", encoding="utf-8") as f:
            raw = f.read()
    if not raw:
        raise ValueError("⚠️ 未找到任何账号信息，请检查 YUYUN_ACCOUNTS 或 yuyun.txt")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    log.info(f"共解析到 {len(lines)} 个账号")
    return [RainyunAccount(line, idx + 1) for idx, line in enumerate(lines)]


def main():
    try:
        accounts = load_accounts()
    except Exception as exc:
        log.error(f"账号读取异常：{exc}")
        sys.exit(1)

    if MODE == 2:
        log.info(f"并发执行，最大 {RUN_MAX} 个线程")
        results = []
        with ThreadPoolExecutor(max_workers=RUN_MAX) as pool:
            futures = {pool.submit(ac.run): ac for ac in accounts}
            for fut in as_completed(futures):
                ac = futures[fut]
                try:
                    ok, msg = fut.result()
                except Exception as exc:
                    ok, msg = False, f"异常：{exc}"
                results.append((ac.phone, ok, msg))
                log.info(f"[{ac.idx:02d}] {ac.phone[:4]}****{ac.phone[7:]} => {msg} ({'✅' if ok else '❌'})")
    else:
        log.info("顺序执行")
        results = []
        for ac in accounts:
            ok, msg = ac.run()
            results.append((ac.phone, ok, msg))
            log.info(f"[{ac.idx:02d}] {ac.phone[:4]}****{ac.phone[7:]} => {msg} ({'✅' if ok else '❌'})")

    # 发送 Telegram 推送
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        try:
            title = "Rainyun 签到通知"
            success_count = sum(1 for _, ok, _ in results if ok)
            total = len(results)
            body = f"✅ 成功 {success_count}/{total}\n\n"
            for phone, ok, msg in results:
                status = "✅" if ok else "❌"
                body += f"{status} {phone[:3]}****{phone[7:]}: {msg}\n"
            send_telegram_message(title, body)
            log.info("Telegram 通知已发送")
        except Exception as exc:
            log.error(f"Telegram 推送失败：{exc}")
    else:
        log.info("Telegram 参数未完整，跳过推送")

    # 如果有人失败，exit 1
    if not all(ok for _, ok, _ in results):
        log.warning("部分账号签到失败")
        sys.exit(1)


# ------------------------------------------------------------ #
# ---------- Telegram 推送 -------------------------------- #
# ------------------------------------------------------------ #
def send_telegram_message(title: str, text: str):
    """通过 Bot API 发送消息，使用 uni‑code / markdown """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT,
        "text": f"*{title}*\n{text}",
        "parse_mode": "Markdown",
    }
    resp = requests.post(url, data=payload, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API 返回 {resp.status_code}: {resp.text}")


if __name__ == "__main__":
    main()
