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
from io import BytesIO

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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4992.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Referer': self.base_url,
            'Origin': self.base_url,
        })
        
    def decode_base64(self, s):
        """Base64解码，兼容UTF-8编码"""
        try:
            # 首先尝试直接解码
            return base64.b64decode(s).decode('utf-8')
        except UnicodeDecodeError:
            # 如果失败，尝试处理百分比编码
            try:
                return unquote(base64.b64decode(s).decode('utf-8'))
            except Exception:
                # 作为最后手段，使用latin-1解码
                return base64.b64decode(s).decode('latin-1')
    
    def get_cookie(self):
        """登录并获取Cookie"""
        logger.info(f"开始登录流程，邮箱: {self.email}")
        
        # 访问首页获取初始cookie
        try:
            logger.info("访问首页获取初始cookie...")
            self.session.get(self.base_url, timeout=15)
            logger.info("首页访问完成，已获取初始cookie")
        except Exception as e:
            logger.error(f"访问首页失败: {str(e)}")
            return False, None
        
        login_url = f"{self.base_url}/auth/login"
        
        # 使用表单数据形式提交
        data = {
            'email': self.email,
            'passwd': self.password  # 注意这里是'passwd'不是'password'
        }
        
        try:
            logger.info("尝试登录...")
            response = self.session.post(login_url, data=data, timeout=15)
            logger.info(f"登录响应状态码: {response.status_code}")
            
            try:
                result = response.json()
                logger.info(f"登录响应JSON: {result}")
                
                if result.get('ret') == 1:  # 原项目使用ret==1表示成功
                    logger.info("登录成功")
                    
                    # 从响应头获取Cookie
                    cookies = response.headers.get('set-cookie', [])
                    if cookies:
                        cookie_str = '; '.join([str(c) for c in cookies])
                        logger.info("成功获取Cookie")
                        return True, cookie_str
                    else:
                        logger.warning("未在响应头中找到Cookie")
                        return True, None
                
                else:
                    error_msg = result.get('msg', '未知错误')
                    logger.error(f"登录失败: {error_msg}")
                    return False, error_msg
                    
            except ValueError:
                logger.error("登录响应不是JSON格式")
                return False, "响应解析失败"
                
        except requests.exceptions.RequestException as e:
            logger.error(f"登录请求异常: {str(e)}")
            return False, str(e)
        except Exception as e:
            logger.error(f"登录异常: {str(e)}")
            return False, str(e)
    
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
                    # 检查是否已签到
                    if '已签到' in error_msg or 'already' in error_msg.lower():
                        logger.info(f"提示: {error_msg}")
                        return True, error_msg
                    else:
                        logger.error(f"签到失败: {error_msg}")
                        return False, error_msg
                    
            except ValueError:
                # 如果不是JSON响应，检查HTML内容
                html_content = response.text
                if 'already-checkin' in html_content or '已签到' in html_content:
                    logger.info("提示：已经签到过了")
                    return True, "今日已签到"
                else:
                    logger.error("无法确定签到状态：无法解析响应内容")
                    return False, "签到异常，无法解析响应"
                
        except requests.exceptions.RequestException as e:
            logger.error(f"签到请求异常: {str(e)}")
            return False, str(e)
        except Exception as e:
            logger.error(f"签到异常: {str(e)}")
            return False, str(e)
    
    def get_traffic(self, cookie=None):
    """获取流量信息 - 按照原项目逻辑"""
    logger.info("获取流量信息")
    
    user_url = f"{self.base_url}/user"
    
    try:
        # 构建请求头，如果提供了cookie则添加
        headers = self.session.headers.copy()
        if cookie:
            headers['Cookie'] = cookie
        
        response = self.session.get(user_url, headers=headers, timeout=15)
        logger.info(f"获取用户页面状态码: {response.status_code}")
        
        # 从HTML中提取Base64编码的字符串
        base64_match = re.search(r'var originBody = "([^"]+)"', response.text)
        
        if not base64_match:
            logger.error("未在页面中找到Base64编码的流量数据")
            return False, ["未找到流量数据"]
        
        base64_string = base64_match.group(1)
        logger.info(f"找到Base64编码字符串: {base64_string[:50]}...")
        
        # 解码Base64字符串
        try:
            decoded_data = self.decode_base64(base64_string)
            logger.info(f"Base64解码成功，长度: {len(decoded_data)}")
            
            # 打印解码后数据的开头部分用于调试
            logger.debug(f"解码后数据开头: {decoded_data[:200]}...")
        except Exception as e:
            logger.error(f"Base64解码失败: {str(e)}")
            return False, ["流量数据解码失败"]
        
        # 按照原项目，实现正则表达式匹配
        # 根据常见流量信息格式，我们定义如下正则表达式
        # 如果实际格式不同，需要用户提供实际解码后的数据进行调整
        
        todayTrafficReg = r'今日已用[：:]\s*([\d.]+)\s*([GMK]?B)'
        restTrafficReg = r'剩余流量[：:]\s*([\d.]+)\s*([GMK]?B)'
        
        logger.info(f"使用正则表达式匹配流量信息:")
        logger.info(f"  今日流量: {todayTrafficReg}")
        logger.info(f"  剩余流量: {restTrafficReg}")
        
        # 按照原项目逻辑进行匹配
        traffic_res = re.search(todayTrafficReg, decoded_data)
        rest_res = re.search(restTrafficReg, decoded_data)
        
        logger.info(f"匹配结果: 今日流量={traffic_res is not None}, 剩余流量={rest_res is not None}")
        
        if not traffic_res or not rest_res:
            logger.error("无法匹配流量信息")
            return False, ["查询流量失败，请检查正则和用户页面 HTML 结构"]

        # 提取流量信息，按照原项目逻辑
        today_value = traffic_res.group(1)
        today_unit = traffic_res.group(2) if traffic_res.lastindex > 1 else ''
        rest_value = rest_res.group(1)
        rest_unit = rest_res.group(2) if rest_res.lastindex > 1 else ''
        
        logger.info(f"今日流量: {today_value} {today_unit}")
        logger.info(f"剩余流量: {rest_value} {rest_unit}")
        
        return True, [
            f"今日已用：{today_value} {today_unit}",
            f"剩余流量：{rest_value} {rest_unit}"
        ]
        
    except Exception as e:
        logger.error(f"获取流量异常: {str(e)}")
        return False, [str(e)]
    
    def run(self):
        """单个账号执行流程"""
        try:
            logger.info(f"开始处理账号: {self.email}")
            
            # 登录并获取Cookie
            login_success, cookie = self.get_cookie()
            if not login_success:
                if isinstance(cookie, str) and "登录失败" in cookie:
                    return False, cookie, []
                return False, "登录失败获取Cookie", []
            
            # 签到
            checkin_success, checkin_msg = self.checkin()
            
            # 获取流量 (使用登录获取的Cookie)
            traffic_success, traffic_info = self.get_traffic(cookie)
            
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
        self.telegram_bot_token = os.getenv('TG_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TG_CHAT_ID', '')
    
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
            
            message = f"<b>iKuuu VPN 签到通知</b>\n"
            message += f"📊 <b>成功: {success_count}/{total_count}</b>\n\n"
            
            for email, success, result in results:
                status = "✅" if success else "❌"
                # 隐藏邮箱部分字符以保护隐私
                masked_email = self.mask_email(email)
                message += f"{status} <i>{masked_email}</i>: {result}\n"
            
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
