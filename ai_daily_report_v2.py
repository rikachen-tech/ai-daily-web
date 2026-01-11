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
WEB_URL = "https://rikachen-tech.github.io/ai-daily-web/" 

# 核心大佬名单 (已恢复完整 20+ 名单)
AI_INFLUENCERS = [
    "OpenAI", "sama", "AnthropicAI", "DeepMind", "demishassabis", "MetaAI", "ylecun", "MistralAI", "huggingface", "clem_delangue",
    "karpathy", "AravSrinivas", "mustafasuleyman", "gdb", "therundownai", "rowancheung", "pete_huang", "tldr", "bentossell",
    "alliekmiller", "LinusEkenstam", "shreyas", "lennysan","garrytan","danshipper","Greg Isenberg", "Justine Moore", "Andrej Karpathy", "Swyx", "Greg Isenberg", "Lenny Rachitsky", 
    "Josh Woordward","Kevin Weil","Peter Yang", "Nan Yu","Madhu Guru", "Mckay Wrigley","Steven Johnson", "Amanda Askell", "Cat Wu", "Thariq", "Google Labs", "George Mack", "Raiza Martin",
    "Amjad Masad", "Guillermo Rauch", "Riley Brown", "Alex Albert", "Hamel Husain", "Aaron Levie", "Ryo Lu", "Lulu Cheng Meservey", "Justine Moore", "Matt Turck", "Julie Zhuo", "Gabriel Peters", 
    "PJ Ace", "Zara Zhang"
]

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

# --- 3. 核心工具函数 ---

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

def get_tweets(target_date_obj):
    """抓取目标日期的推文数据"""
    all_text = ""
    start = target_date_obj.replace(hour=0, minute=0, second=0)
    end = target_date_obj.replace(hour=23, minute=59, second=59)
    print(f"📡 正在抓取推文数据 ({start.strftime('%Y-%m-%d')})...")
    
    for user in AI_INFLUENCERS:
        try:
            res = requests.get(f"https://{RAPIDAPI_HOST}/timeline.php", 
                               headers={"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": RAPIDAPI_HOST}, 
                               params={"screenname": user}, timeout=20)
            if res.status_code == 200:
                data = res.json()
                for tweet in data.get('timeline', [])[:3]:
                    # Twitter 时间解析
                    c_at = datetime.strptime(tweet['created_at'], "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
                    if start <= c_at <= end:
                        content = tweet.get('text') or tweet.get('full_text', "")
                        all_text += f"作者: @{user} | 内容: {content}\n"
            time.sleep(1.2) # 频率限制
        except: continue
    return all_text

def fetch_gemini_summary(new_content, date_label):
    """调用 Gemini 进行 PM 视角深度拆解，并确保包含原文超链接"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
    
    # 强化 PM 视角及超链接引用指令
    system_prompt = """
    你是一个顶级 AI 行业分析师和顶尖的产品经理（PM）。你的风格是：言简意赅、直击本质、拒绝废话。请对提供的推文动态进行深度拆解。
    
    核心规则：
    1. 视角：从产品价值、商业模式、用户体验和市场格局四个维度进行分析。
    2. 溯源：在分析具体观点或动态时，必须引用原文链接。请使用 HTML 超链接格式 `<a href="链接地址">查看原文</a>` 附在对应的分析段落末尾。
    3. 过滤：优先关注应用层和商业化的变动，减少纯学术和代码研究讨论。
    4. 格式：输出完整的 HTML 代码。包含以下模块，且每个模块至少包含 1-2 个具体的推文引用：
       - 📌 今日提纲
       - 🚀 Major Shifts (重大转向)
       - 💼 Business & Applications (商业与应用)
       - 🎨 UX & Interaction (体验与交互)
       - 📊 Market Dynamics (市场动态)
    
    注意：不要输出 Markdown 的 ```html 包裹标签，直接输出 HTML 内容。
    """
    
    
    payload = {
        "contents": [{"parts": [{"text": f"报告日期：{date_label}\n昨日推文动态：\n{new_content}"}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }
    try:
        res = requests.post(url, json=payload, timeout=60)
        report = res.json()['candidates'][0]['content']['parts'][0]['text']
        return report.replace('```html', '').replace('```', '').strip()
    except Exception as e:
        print(f"❌ Gemini 分析请求失败: {e}")
        return None

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

def crawl_and_generate_report(target_date_obj):
    """核心：生成当日简报（分析昨日数据）"""
    date_str = target_date_obj.strftime('%Y-%m-%d')
    print(f"🚀 正在生成今日简报 ({date_str})...")
    
    # 抓取昨天的推文
    yesterday_data = get_tweets(target_date_obj - timedelta(days=1))
    
    if not yesterday_data:
        print("📭 昨日无有效推文动态。")
        return None, date_str
    
    # AI 深度分析
    report_html = fetch_gemini_summary(yesterday_data, date_str)
    
    if report_html:
        db.collection("daily_history").document(date_str).set({
            "content": report_html,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
    return report_html, date_str

def get_latest_report_content():
    """获取最新的一份日报（今天或昨天）"""
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    today_str = bj_now.strftime('%Y-%m-%d')
    yesterday_str = (bj_now - timedelta(days=1)).strftime('%Y-%m-%d')

    # 先查今日数据库
    doc = db.collection("daily_history").document(today_str).get()
    if doc.exists:
        return doc.to_dict().get("content"), today_str
    
    # 数据库没有，则现场抓取昨日数据生成今日日报
    return crawl_and_generate_report(bj_now)

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
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    print(f"🕒 执行时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 优先发送验证码 (满足 1min 左右时效)
    handle_otps()
    
    # 2. 获取或生成当日日报 (分析昨日动态)
    report_html, report_date = get_latest_report_content()
    
    # 3. 检查是否有新用户需要补发日报 (满足 10min 内时效)
    if report_html:
        handle_new_subscribers(report_html, report_date)
    
    # 4. 每日定时群发逻辑 (北京时间 9 点)
    if bj_now.hour == 9 and bj_now.minute < 10:
        print("📢 触发每日例行全员群发...")
        if report_html:
            subs_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers")
            docs = subs_ref.where(filter=FieldFilter("active", "==", True)).stream()
            for doc in docs:
                email = doc.to_dict()['email']
                send_email(email, f"✨ AI 战略观察日报 [{report_date}]", report_html)
