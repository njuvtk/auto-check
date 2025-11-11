import os
import sys
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# 1. 从环境变量中读取配置
# Telegram Bot 配置
token = os.environ.get('BOT_TOKEN')
chat_id = os.environ.get('CHAT_ID')
# 账号配置 (格式: user1:pass1,user2:pass2)
accounts_str = os.environ.get('NTLB_ACCOUNTS')

# 2. 检查和解析账号
if not accounts_str:
    print('❌ 未配置账号 (ACCOUNTS 环境变量未设置)')
    sys.exit(1)

# 使用正则表达式按逗号或分号分割，并处理每个账号
account_list = []
# re.split allows multiple delimiters (',' or ';')
raw_accounts = re.split(r'[,;]', accounts_str)
for account in raw_accounts:
    if ':' in account:
        user, _, passwd = account.partition(':')
        user = user.strip()
        passwd = passwd.strip()
        if user and passwd:
            account_list.append({'user': user, 'pass': passwd})

if not account_list:
    print('❌ 账号格式错误，应为 username1:password1,username2:password2')
    sys.exit(1)

# 3. 发送 Telegram 通知的函数
def send_telegram(message):
    """向指定的 Telegram Chat 发送消息"""
    if not token or not chat_id:
        print("⚠️ 未配置 Telegram token 或 chat_id, 跳过发送通知")
        return

    # 获取并格式化香港时间 (UTC+8)
    utc_now = datetime.now(timezone.utc)
    hkt_now = utc_now.astimezone(timezone(timedelta(hours=8)))
    time_str = hkt_now.strftime('%Y-%m-%d %H:%M:%S') + " HKT"

    full_message = f"🎉 Netlib 登录通知\n\n登录时间：{time_str}\n\n{message}"
    
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': full_message
    }
    
    try:
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status() # 如果请求失败 (状态码 4xx or 5xx), 会抛出异常
        print('✅ Telegram 通知发送成功')
    except requests.exceptions.RequestException as e:
        print(f'⚠️ Telegram 发送失败: {e}')

# 4. 单个账号登录的函数
def login_with_account(user, password):
    """使用 Playwright 登录单个账号并返回结果"""
    print(f"\n🚀 开始登录账号: {user}")
    
    result = {'user': user, 'success': False, 'message': ''}
    
    # 注意：原脚本为每个账号启动一个新浏览器，效率较低但隔离性好。这里保持一致。
    # 优化建议：可以考虑所有账号共用一个 browser 实例，只创建新 page。
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = browser.new_page()
            page.set_default_timeout(30000)

            print(f"📱 {user} - 正在访问网站...")
            page.goto('https://www.netlib.re/', wait_until='networkidle')
            page.wait_for_timeout(3000)

            print(f"🔑 {user} - 点击登录按钮...")
            page.get_by_text("Login").click(timeout=5000)
            page.wait_for_timeout(2000)

            print(f"📝 {user} - 填写用户名...")
            # 使用更健壮的定位器
            page.locator('input[name="username"], input[type="text"]').fill(user)
            page.wait_for_timeout(1000)

            print(f"🔒 {user} - 填写密码...")
            page.locator('input[name="password"], input[type="password"]').fill(password)
            page.wait_for_timeout(1000)

            print(f"📤 {user} - 提交登录...")
            # 定位 "Validate" 按钮或 submit 类型的输入框
            page.locator('button:has-text("Validate"), input[type="submit"]').click()

            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(5000)

            # 检查登录是否成功
            page_content = page.content()
            if 'exclusive owner' in page_content or user in page_content:
                print(f"✅ {user} - 登录成功")
                result['success'] = True
                result['message'] = f"✅ {user} 登录成功"
            else:
                print(f"❌ {user} - 登录失败")
                result['message'] = f"❌ {user} 登录失败"

        except Exception as e:
            error_message = str(e).splitlines()[0] # 取错误信息的第一行，避免过长
            print(f"❌ {user} - 登录异常: {error_message}")
            result['message'] = f"❌ {user} 登录异常: {error_message}"
        finally:
            if 'browser' in locals() and browser.is_connected():
                browser.close()
    
    return result

# 5. 主执行函数
def main():
    """主执行逻辑"""
    print(f"🔍 发现 {len(account_list)} 个账号需要登录")
    
    results = []
    
    for i, account in enumerate(account_list):
        user = account['user']
        password = account['pass']
        
        print(f"\n📋 处理第 {i + 1}/{len(account_list)} 个账号: {user}")
        
        result = login_with_account(user, password)
        results.append(result)
        
        # 如果不是最后一个账号，等待3秒
        if i < len(account_list) - 1:
            print('⏳ 等待3秒后处理下一个账号...')
            time.sleep(3)
            
    # 汇总所有结果并发送一条消息
    success_count = sum(1 for r in results if r['success'])
    total_count = len(results)
    
    summary_lines = [f"📊 登录汇总: {success_count}/{total_count} 个账号成功", ""]
    for result in results:
        summary_lines.append(result['message'])
    
    summary_message = "\n".join(summary_lines)
    
    send_telegram(summary_message)
    
    print('\n✅ 所有账号处理完成！')

# 脚本入口
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n脚本执行时发生未捕获的错误: {e}")
        sys.exit(1)

