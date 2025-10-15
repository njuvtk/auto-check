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
from urllib.parse import quote

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IKUUUAutoCheckin:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        
        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")
        
        self.base_url = "https://ikuuu.de"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': self.base_url,
            'X-Requested-With': 'XMLHttpRequest'
        })
        
    def login(self):
        """执行登录流程"""
        logger.info(f"开始登录流程")
        
        login_url = f"{self.base_url}/auth/login"
        data = {
            'email': self.email,
            'password': self.password,
            'remember': 'on'
        }
        
        try:
            response = self.session.post(login_url, data=data)
            result = response.json()
            
            if result.get('ret') == 1:
                logger.info("登录成功")
                return True
            else:
                error_msg = result.get('msg', '未知错误')
                logger.error(f"登录失败: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"登录异常: {str(e)}")
            return False
    
    def checkin(self):
        """执行签到流程"""
        logger.info("开始签到流程")
        
        checkin_url = f"{self.base_url}/user/checkin"
        
        try:
            response = self.session.post(checkin_url)
            result = response.json()
            
            if result.get('ret') == 1:
                message = result.get('msg', '签到成功')
                logger.info(f"签到成功: {message}")
                return True, message
            else:
                error_msg = result.get('msg', '未知错误')
                logger.error(f"签到失败: {error_msg}")
                return False, error_msg
                
        except Exception as e:
            logger.error(f"签到异常: {str(e)}")
            return False, str(e)
    
    def get_traffic(self):
        """获取流量信息"""
        logger.info("获取流量信息")
        
        user_url = f"{self.base_url}/user"
        
        try:
            response = self.session.get(user_url)
            
            # 使用正则表达式提取流量信息
            used = re.search(r'已使用：.*?<\/td><td>(.*?)<span', response.text)
            left = re.search(r'剩余：.*?<\/td><td>(.*?)<span', response.text)
            total = re.search(r'总流量：.*?<\/td><td>(.*?)<span', response.text)
            
            if not all([used, left, total]):
                logger.warning("无法解析流量信息")
                return False, ["无法解析流量信息"]
                
            traffic_info = [
                f"已使用流量: {used.group(1).strip()}",
                f"剩余流量: {left.group(1).strip()}",
                f"总流量: {total.group(1).strip()}"
            ]
            
            logger.info(f"流量信息: {traffic_info}")
            return True, traffic_info
                
        except Exception as e:
            logger.error(f"获取流量异常: {str(e)}")
            return False, [str(e)]
    
    def run(self):
        """单个账号执行流程"""
        try:
            logger.info(f"开始处理账号: {self.email}")
            
            # 登录
            if not self.login():
                return False, "登录失败", []
            
            # 签到
            checkin_success, checkin_msg = self.checkin()
            
            # 获取流量
            traffic_success, traffic_info = self.get_traffic()
            
            # 汇总结果
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
        
        # 方法1: 冒号分隔多账号格式
        accounts_str = os.getenv('IKUUU_ACCOUNTS', '').strip()
        if accounts_str:
            try:
                logger.info("尝试解析冒号分隔多账号配置")
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
                    logger.info(f"从冒号分隔格式成功加载了 {len(accounts)} 个账号")
                    return accounts
                else:
                    logger.warning("冒号分隔配置中没有找到有效的账号信息")
            except Exception as e:
                logger.error(f"解析冒号分隔账号配置失败: {e}")
        
        # 如果所有方法都失败
        logger.error("未找到有效的账号配置")
        logger.error("请检查环境变量设置:")
        logger.error("IKUUU_ACCOUNTS: 冒号分隔多账号 (email1:pass1,email2:pass2)")
        
        raise ValueError("未找到有效的账号配置")
    
    def send_telegram_notification(self, results):
        """发送通知到Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.info("Telegram配置未设置，跳过通知")
            return
        
        try:
            # 构建通知消息
            success_count = sum(1 for _, success, _ in results if success)
            total_count = len(results)
            
            message = f"iKuuu VPN 签到通知\n"
            message += f"📊 成功: {success_count}/{total_count}\n\n"
            
            for email, success, result in results:
                status = "✅" if success else "❌"
                # 隐藏邮箱部分字符以保护隐私
                masked_email = self.mask_email(email)
                message += f"{status} {masked_email}: {result}\n"
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
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
                    wait_time = 5
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
        
        # 打印汇总结果
        self.print_results(results)
        
        # 发送Telegram通知
        self.send_telegram_notification(results)
        
        # 返回总体结果
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
            # 隐藏邮箱部分字符以保护隐私
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
            # 即使有失败，也不退出错误状态，因为可能部分成功
            exit(0)
            
    except Exception as e:
        logger.error(f"❌ 脚本执行出错: {e}")
        exit(1)

if __name__ == "__main__":
    main()
