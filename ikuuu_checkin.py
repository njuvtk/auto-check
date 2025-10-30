#!/usr/bin/env python3
"""
iKuuu 多账号自动签到脚本
变量名：IKUUU_ACCOUNTS
变量值：邮箱1:密码1,邮箱2:密码2,邮箱3:密码3
"""

import os
import time
import logging
import requests
import re
import json
import base64
from urllib.parse import quote, unquote

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IKUUUAutoCheckin:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        
        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")
        
        # 注意：host 跟 JS 版保持一致
        self.base_url = "https://ikuuu.org"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4992.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Referer': self.base_url,
            'Origin': self.base_url,
        })
        
    def decode_base64(self, s):
        """Base64解码，兼容UTF-8编码（仿 JS 逻辑）"""
        try:
            # 现代解码方法
            return base64.b64decode(s).decode('utf-8')
        except Exception:
            # 兼容 JS 的 SlowerDecodeBase64
            try:
                raw = base64.b64decode(s)
                percent_encoded = ''.join(['%{:02x}'.format(b) for b in raw])
                return unquote(percent_encoded)
            except Exception:
                return base64.b64decode(s).decode('latin-1')
    
    def get_cookie(self):
        """登录并获取Cookie，仿 JS 逻辑"""
        logger.info(f"开始登录流程，邮箱: {self.email}")
        
        try:
            self.session.get(self.base_url, timeout=15)
        except Exception as e:
            logger.error(f"访问首页失败: {str(e)}")
            return False, None
        
        login_url = f"{self.base_url}/auth/login"
        data = {
            'email': self.email,
            'passwd': self.password
        }
        
        try:
            response = self.session.post(login_url, data=data, timeout=15)
            logger.info(f"登录响应状态码: {response.status_code}")
            try:
                result = response.json()
                logger.info(f"登录响应JSON: {result}")
                if result.get('ret') == 1:
                    logger.info(f"✅ 登录成功：{self.email}")
                    cookies = response.headers.get('set-cookie', [])
                    if cookies:
                        if isinstance(cookies, list):
                            cookie_str = '; '.join([str(c) for c in cookies])
                        else:
                            cookie_str = str(cookies)
                        return True, cookie_str
                    else:
                        # requests 自动管理 cookie，不一定需要 set-cookie
                        return True, None
                else:
                    msg = f"❌ 登录失败：{result.get('msg', '未知错误')}"
                    logger.error(msg)
                    return False, msg
            except Exception:
                logger.error("登录响应不是JSON格式")
                return False, "响应解析失败"
        except Exception as e:
            msg = f"❌ 登录失败：{str(e)}"
            logger.error(msg)
            return False, msg
    
    def checkin(self):
        """执行签到流程"""
        logger.info("开始签到流程")
        checkin_url = f"{self.base_url}/user/checkin"
        try:
            response = self.session.post(checkin_url, timeout=15)
            logger.info(f"签到响应状态码: {response.status_code}")
            try:
                result = response.json()
                logger.info(f"签到响应JSON: {result}")
                if result.get('ret') == 1:
                    message = result.get('msg', '签到成功')
                    logger.info(f"签到成功: {message}")
                    return True, message
                else:
                    error_msg = result.get('msg', '未知错误')
                    if '已签到' in error_msg or 'already' in error_msg.lower():
                        logger.info(f"提示: {error_msg}")
                        return True, error_msg
                    else:
                        logger.error(f"签到失败: {error_msg}")
                        return False, error_msg
            except Exception:
                html_content = response.text
                if 'already-checkin' in html_content or '已签到' in html_content:
                    logger.info("提示：已经签到过了")
                    return True, "今日已签到"
                else:
                    logger.error("无法确定签到状态：无法解析响应内容")
                    return False, "签到异常，无法解析响应"
        except Exception as e:
            logger.error(f"签到请求异常: {str(e)}")
            return False, str(e)
    
    def get_traffic(self, cookie=None):
        """获取流量信息 - 仿 JS 项目逻辑"""
        logger.info("获取流量信息")
        user_url = f"{self.base_url}/user"

        todayTrafficReg = r"今日已用\n.*\s(\d+\.?\d*)([M|G|K]?B)"
        restTrafficReg = r"剩余流量[\s\S]*<span class=\"counter\">(\d+\.?\d*)<\/span> ([M|G|K]?B)"

        try:
            headers = self.session.headers.copy()
            if cookie:
                headers['Cookie'] = cookie

            response = self.session.get(user_url, headers=headers, timeout=15)
            logger.info(f"获取用户页面状态码: {response.status_code}")

            base64_match = re.search(r'var originBody = "([^"]+)"', response.text)
            decode_data = ""
            if base64_match and base64_match.group(1):
                base64_string = base64_match.group(1)
                try:
                    decode_data = self.decode_base64(base64_string)
                except Exception as e:
                    logger.error(f"Base64解码失败: {str(e)}")
                    return False, ["流量数据解码失败"]
            else:
                logger.error("未找到原始HTML")
                return False, ["未找到流量数据"]

            traffic_res = re.search(todayTrafficReg, decode_data)
            rest_res = re.search(restTrafficReg, decode_data)

            if not traffic_res or not rest_res:
                logger.error("无法匹配流量信息")
                return False, ["查询流量失败，请检查正则和用户页面 HTML 结构"]

            today, today_unit = traffic_res.group(1), traffic_res.group(2)
            rest, rest_unit = rest_res.group(1), rest_res.group(2)

            logger.info(f"今日流量: {today} {today_unit}")
            logger.info(f"剩余流量: {rest} {rest_unit}")

            return True, [
                f"今日已用：{today} {today_unit}",
                f"剩余流量：{rest} {rest_unit}"
            ]
        except Exception as e:
            logger.error(f"获取流量异常: {str(e)}")
            return False, [str(e)]
    
    def run(self):
        """单个账号执行流程"""
        try:
            logger.info(f"开始处理账号: {self.email}")
            login_success, cookie = self.get_cookie()
            if not login_success:
                if isinstance(cookie, str) and "登录失败" in cookie:
                    return False, cookie, []
                return False, "登录失败获取Cookie", []
            checkin_success, checkin_msg = self.checkin()
            traffic_success, traffic_info = self.get_traffic(cookie)
            overall_success = checkin_success and traffic_success
            result_msg = checkin_msg if checkin_success else "签到失败"
            logger.info(f"账号 {self.email} 处理完成 - 状态: {'成功' if overall_success else '部分成功'}")
            return overall_success, result_msg, traffic_info
        except Exception as e:
            error_msg = f"处理账号时发生异常: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, []

class MultiAccountManager:
    """多账号管理器 - 简化配置版本"""
    
    def __init__(self):
        self.accounts = self.load_accounts()
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    
    def load_accounts(self):
        """从环境变量加载多账号信息，支持冒号分隔多账号"""
        accounts = []
        logger.info("开始加载账号配置...")
        accounts_str = os.getenv('IKUUU_ACCOUNTS', '').strip()
        if accounts_str:
            try:
                logger.info("尝试解析冒号分隔多账号配置")
                account_pairs = [pair.strip() for pair in accounts_str.split(',')]
                for i, pair in enumerate(account_pairs):
                    if ':' in pair:
                        email, password = pair.split(':', 1)
                        email = email.strip()
                        password = password.strip()
                        if email and password:
                            accounts.append({
                                'email': email,
                                'password': password
                            })
                            logger.info(f"成功添加第 {i+1} 个账号: {email[:5]}***")
                    else:
                        logger.warning(f"账号对缺少冒号分隔符: {pair}")
                if accounts:
                    logger.info(f"从冒号分隔格式成功加载了 {len(accounts)} 个账号")
                    return accounts
                else:
                    logger.warning("冒号分隔配置中没有找到有效的账号信息")
            except Exception as e:
                logger.error(f"解析冒号分隔账号配置失败: {e}")
        logger.error("未找到有效的账号配置")
        logger.error("请检查环境变量设置:")
        logger.error("IKUUU_ACCOUNTS: 冒号分隔多账号 (email1:pass1,email2:pass2)")
        raise ValueError("未找到有效的账号配置")
    
    def send_telegram_notification(self, results):
        """发送详细的汇总结果通知到Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.info("Telegram配置未设置，跳过通知")
            return
        
        try:
            success_count = sum(1 for r in results if r['success'])
            total_count = len(results)
            
            # 标题和摘要
            title = "<b>iKuuu VPN 签到结果</b>"
            summary = f"📊 <b>总览: {success_count} / {total_count} 成功</b>"
            
            message = f"{title}\n{summary}\n"
            message += "─" * 20 + "\n"

            # 每个账号的详细结果
            for r in results:
                status = "✅" if r['success'] else "❌"
                masked_email = self.mask_email(r['email'])
                
                # 使用HTML的code标签来格式化邮箱，更美观
                message += f"\n{status} <b>账号:</b> <code>{masked_email}</code>\n"
                message += f"<b>结果:</b> {r['result']}\n"
                
                if r['traffic']:
                    for traffic_line in r['traffic']:
                        # 使用空格进行缩进，使其看起来像一个列表项
                        message += f"  - {traffic_line}\n"
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            
            # 发送消息
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message.strip(),
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram通知发送成功")
            else:
                logger.error(f"Telegram通知发送失败: {response.text}")
        except Exception as e:
            logger.error(f"发送Telegram通知时出错: {e}")

    def run_all(self):
        """运行所有账号的签到流程"""
        logger.info(f"开始执行 {len(self.accounts)} 个账号的签到任务")
        results = []
        for i, account in enumerate(self.accounts, 1):
            logger.info(f"处理第 {i}/{len(self.accounts)} 个账号")
            try:
                auto_checkin = IKUUUAutoCheckin(account['email'], account['password'])
                success, result_msg, traffic_info = auto_checkin.run()
                results.append({
                    'email': account['email'],
                    'success': success,
                    'result': result_msg,
                    'traffic': traffic_info
                })
                # 在账号之间添加间隔，避免请求过于频繁
                if i < len(self.accounts):
                    wait_time = 8
                    logger.info(f"等待{wait_time}秒后处理下一个账号...")
                    time.sleep(wait_time)
            except Exception as e:
                error_msg = f"处理账号时发生异常: {str(e)}"
                logger.error(error_msg)
                results.append({
                    'email': account['email'],
                    'success': False,
                    'result': error_msg,
                    'traffic': []
                })
        self.print_results(results)
        self.send_telegram_notification(results)
        success_count = sum(1 for r in results if r['success'])
        return success_count == len(self.accounts), results
    
    def print_results(self, results):
        """打印汇总结果"""
        print("\n" + "="*60)
        print("iKuuu VPN 签到结果汇总")
        print("="*60)
        success_count = sum(1 for r in results if r['success'])
        print(f"📊 成功: {success_count}/{len(results)}")
        print("="*60)
        for result in results:
            status = "✅" if result['success'] else "❌"
            masked_email = self.mask_email(result['email'])
            print(f"\n{status} {masked_email}")
            print(f"结果: {result['result']}")
            if result['traffic']:
                print("流量信息:")
                for traffic in result['traffic']:
                    print(f"  - {traffic}")
        print("\n" + "="*60)
    
    def mask_email(self, email):
        """隐藏邮箱部分字符以保护隐私"""
        if '@' in email:
            username, domain = email.split('@', 1)
            return f"{username[:3]}***@{domain}"
        return email

def main():
    """主函数"""
    try:
        manager = MultiAccountManager()
        overall_success, detailed_results = manager.run_all()
        if overall_success:
            logger.info("✅ 所有账号签到成功")
            exit(0)
        else:
            success_count = sum(1 for r in detailed_results if r['success'])
            logger.warning(f"⚠️ 部分账号签到失败: {success_count}/{len(detailed_results)} 成功")
            # 即使部分失败，也正常退出，因为签到任务已完成
            exit(0)
    except Exception as e:
        logger.error(f"❌ 脚本执行出错: {e}")
        exit(1)

if __name__ == "__main__":
    main()

