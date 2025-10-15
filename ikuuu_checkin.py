#!/usr/bin/env python3
"""
iKUUU 多账号自动签到脚本
变量名：IKUUU_ACCOUNTS
变量值：邮箱1:密码1,邮箱2:密码2,邮箱3:密码3
"""

import os
import time
import logging
import json
import requests
from urllib.parse import quote

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IkuuuAutoCheckin:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.host = os.getenv('HOST', 'ikuuu.one')
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        })
    
    def format_cookie(self, raw_cookie):
        """格式化Cookie"""
        if not raw_cookie:
            return ""
        
        cookie_parts = []
        for cookie_header in raw_cookie.split(';'):
            cookie_part = cookie_header.strip()
            if cookie_part:
                cookie_parts.append(cookie_part)
        
        return "; ".join(cookie_parts)
    
    def login(self):
        """登录获取Cookie"""
        logger.info(f"{self.email}: 登录中...")
        
        self.login_url = f'https://{self.host}/auth/login'
        
        data = {
            'host': self.host,
            'email': self.email,
            'passwd': self.password,
            'code': '',
            'remember_me': 'off'
        }
        
        try:
            response = self.session.post(
                self.login_url,
                data=data,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"网络请求错误 - {response.status_code}")
            
            result = response.json()
            
            if result.get('ret') != 1:
                raise Exception(f"登录失败: {result.get('msg', '未知错误')}")
            
            logger.info(f"{self.email}: {result.get('msg', '登录成功')}")
            
            # 获取Cookie
            raw_cookie = response.headers.get('Set-Cookie', '')
            self.cookie = self.format_cookie(raw_cookie)
            
            return True
            
        except Exception as e:
            logger.error(f"{self.email}: 登录失败 - {str(e)}")
            raise
    
    def checkin(self):
        """执行签到"""
        logger.info(f"{self.email}: 开始签到...")
        
        self.checkin_url = f'https://{self.host}/user/checkin'
        
        try:
            headers = {
                'Cookie': self.cookie,
                'Referer': self.checkin_url,
                'Origin': f'https://{self.host}'
            }
            
            response = self.session.post(
                self.checkin_url,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"网络请求错误 - {response.status_code}")
            
            result = response.json()
            message = result.get('msg', '签到完成')
            
            logger.info(f"{self.email}: {message}")
            return message
            
        except Exception as e:
            logger.error(f"{self.email}: 签到失败 - {str(e)}")
            raise
    
    def run(self):
        """执行完整流程"""
        try:
            self.login()
            result = self.checkin()
            return True, result
        except Exception as e:
            return False, str(e)
        finally:
            self.session.close()

class MultiAccountManager:
    """多账号管理器 - iKUUU版本"""
    
    def __init__(self):
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.accounts = self.load_accounts()
    
    def load_accounts(self):
        """从环境变量加载多账号信息 - iKUUU格式"""
        accounts = []
        
        logger.info("开始加载iKUUU账号配置...")
        
        # 方法1: 冒号分隔多账号格式 (IKUUU_ACCOUNTS)
        accounts_str = os.getenv('IKUUU_ACCOUNTS', '').strip()
        if accounts_str:
            try:
                logger.info("尝试解析iKUUU多账号配置")
                account_pairs = [pair.strip() for pair in accounts_str.split(',')]
                
                logger.info(f"找到 {len(account_pairs)} 个账号")
                
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
                            logger.info(f"成功添加第 {i+1} 个账号")
                        else:
                            logger.warning(f"账号对格式错误")
                    else:
                        logger.warning(f"账号对缺少冒号分隔符")
                
                if accounts:
                    logger.info(f"从iKUUU格式成功加载了 {len(accounts)} 个账号")
                    return accounts
                else:
                    logger.warning("多账号配置中没有找到有效的账号信息")
            except Exception as e:
                logger.error(f"解析多账号配置失败: {e}")
        
        # 方法2: 单账号格式 (IKUUU_EMAIL 和 IKUUU_PASSWORD)
        single_email = os.getenv('IKUUU_EMAIL', '').strip()
        single_password = os.getenv('IKUUU_PASSWORD', '').strip()
        
        if single_email and single_password:
            accounts.append({
                'email': single_email,
                'password': single_password
            })
            logger.info("加载了单个账号配置")
            return accounts
        
        # 如果所有方法都失败
        logger.error("未找到有效的账号配置")
        logger.error("请检查以下环境变量设置:")
        logger.error("1. IKUUU_ACCOUNTS: 冒号分隔多账号 (email1:pass1,email2:pass2)")
        logger.error("2. IKUUU_EMAIL 和 IKUUU_PASSWORD: 单账号")
        
        raise ValueError("未找到有效的iKUUU账号配置")
    
    def send_notification(self, results):
        """发送汇总通知到Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.info("Telegram配置未设置，跳过通知")
            return
        
        try:
            # 构建通知消息
            success_count = sum(1 for _, success, _ in results if success)
            total_count = len(results)
            
            message = f"iKUUU 签到通知\n"
            message += f"📊 成功: {success_count}/{total_count}\n\n"
            
            for email, success, result in results:
                status = "✅" if success else "❌"
                # 隐藏邮箱部分字符以保护隐私
                masked_email = email[:3] + "***" + email[email.find("@"):]
                message += f"{status} {masked_email}: {result}\n"
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram汇总通知发送成功")
            else:
                logger.error(f"Telegram通知发送失败: {response.text}")
                
        except Exception as e:
            logger.error(f"发送Telegram通知时出错: {str(e)}")
    
    def run_all(self):
        """运行所有账号的签到流程"""
        logger.info(f"开始执行 {len(self.accounts)} 个iKUUU账号的签到任务")
        
        results = []
        
        for i, account in enumerate(self.accounts, 1):
            logger.info(f"处理第 {i}/{len(self.accounts)} 个账号")
            
            try:
                auto_checkin = IkuuuAutoCheckin(account['email'], account['password'])
                success, result = auto_checkin.run()
                results.append((account['email'], success, result))
                
                # 在账号之间添加间隔，避免请求过于频繁
                if i < len(self.accounts):
                    wait_time = 3
                    logger.info(f"等待{wait_time}秒后处理下一个账号...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                error_msg = f"处理账号时发生异常: {str(e)}"
                logger.error(error_msg)
                results.append((account['email'], False, error_msg))
        
        # 发送汇总通知
        self.send_notification(results)
        
        # 返回总体结果
        success_count = sum(1 for _, success, _ in results if success)
        return success_count == len(self.accounts), results

def main():
    """主函数 - iKUUU版本"""
    try:
        manager = MultiAccountManager()
        overall_success, detailed_results = manager.run_all()
        
        if overall_success:
            logger.info("✅ 所有iKUUU账号签到成功")
            exit(0)
        else:
            success_count = sum(1 for _, success, _ in detailed_results if success)
            logger.warning(f"⚠️ 部分iKUUU账号签到失败: {success_count}/{len(detailed_results)} 成功")
            # 即使有失败，也不退出错误状态
            exit(0)
            
    except Exception as e:
        logger.error(f"❌ iKUUU脚本执行出错: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()
