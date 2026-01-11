import os
import json
import requests
import smtplib
import time
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime, timedelta, timezone

# --- 1. 配置加载 (从 GitHub Secrets 获取) ---
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = "twitter-api45.p.rapidapi.com"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
FIREBASE_JSON_STR = os.environ.get("FIREBASE_CONFIG_JSON")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
APP_ID = "ai-daily-app"
# 替换为您部署后的正式网页地址
WEB_URL = "https://yourname.github.io/ai-daily-web" 

# 核心大佬名单
AI_INFLUENCERS = ["OpenAI", "sama", "AnthropicAI", "DeepMind", "ylecun", "karpathy", "AravSrinivas"]

# --- 2. 初始化 Firebase ---
if not firebase_admin._apps:
    try:
        cred_dict = json.loads(FIREBASE_JSON_STR)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"❌ Firebase 初始化失败: {e}")
        exit(1)
db = firestore.client()

# --- 3. 邮件工具 ---
def send_email(to_email, subject, html_content):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8').encode()
    msg['From'] = formataddr(("AI Insights Bot", SENDER_EMAIL))
    msg['To'] = to_email
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, [to_email], msg.as_bytes())
        return True
    except Exception as e:
        print(f"📧 发送邮件至 {to_email} 失败: {e}")
        return False

# --- 4. 业务逻辑 ---

def handle_otps():
    """实时处理验证码请求 (目标：1min 内发送)"""
    print("🔍 正在扫描待处理的验证码请求...")
    req_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("verification_requests")
    docs = req_ref.where(filter=FieldFilter("status", "==", "pending")).stream()
    
    count = 0
    for doc in docs:
        data = doc.to_dict()
        email, code = data['email'], data['code']
        body = f"您的 AI 战略日报订阅验证码为：<b style='font-size:20px; color:#3498db;'>{code}</b>。10分钟内有效。"
        if send_email(email, "【验证码】AI 战略日报订阅确认", body):
            doc.reference.update({"status": "sent", "sentAt": firestore.SERVER_TIMESTAMP})
            count += 1
    print(f"✅ 已处理 {count} 个验证码请求")

def get_latest_report_content():
    """获取最新的一份日报（今天或昨天）"""
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    today_str = bj_now.strftime('%Y-%m-%d')
    yesterday_str = (bj_now - timedelta(days=1)).strftime('%Y-%m-%d')

    # 先查今天，再查昨天
    for date_str in [today_str, yesterday_str]:
        doc = db.collection("daily_history").document(date_str).get()
        if doc.exists:
            return doc.to_dict().get("content"), date_str
    
    # 如果都没有，则抓取数据生成一份 (初次运行逻辑)
    return crawl_and_generate_report(bj_now)

def crawl_and_generate_report(target_date_obj):
    """真正的抓取和生成逻辑"""
    print(f"📡 正在抓取推文并生成新简报 ({target_date_obj.strftime('%Y-%m-%d')})...")
    # 此处省略复杂的推文抓取代码，逻辑同前
    # 模拟生成的报告内容
    content = "<h3>今日 AI 行业深度动态</h3><p>内容由 Gemini 2.5 分析生成...</p>" 
    db.collection("daily_history").document(target_date_obj.strftime('%Y-%m-%d')).set({
        "content": content,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
    return content, target_date_obj.strftime('%Y-%m-%d')

def handle_new_subscribers(report_html, report_date):
    """给新用户即刻推送 (目标：验证后 10min 内收到)"""
    print("🔍 正在扫描新激活的订阅者...")
    subs_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers")
    docs = subs_ref.where(filter=FieldFilter("active", "==", True)).stream()
    
    count = 0
    for doc in docs:
        data = doc.to_dict()
        if data.get("welcome_sent") == True:
            continue
        
        email = data['email']
        footer = f'<hr><p style="font-size:12px;color:#999;">您收到此件是因为刚订阅。退订请点击 <a href="{WEB_URL}?action=unsubscribe&email={email}">此处</a></p>'
        subject = f"🚀 欢迎！AI 战略观察日报 ({report_date})"
        
        if send_email(email, subject, report_html + footer):
            doc.reference.update({"welcome_sent": True, "firstPushAt": firestore.SERVER_TIMESTAMP})
            count += 1
    print(f"✅ 已为 {count} 位新订阅者推送首份日报")

if __name__ == "__main__":
    # 1. 优先发送验证码 (满足 1min 左右时效)
    handle_otps()
    
    # 2. 获取或生成日报
    report_html, report_date = get_latest_report_content()
    
    # 3. 检查是否有新用户需要补发日报 (满足 10min 内时效)
    if report_html:
        handle_new_subscribers(report_html, report_date)
    
    # 4. 定时群发逻辑 (每天 9 点触发)
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    if bj_now.hour == 9 and bj_now.minute < 10:
        print("📢 触发每日例行群发...")
        # 此处可以增加群发所有 active 用户的逻辑
