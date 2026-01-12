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
    "PJ Ace", "Zara Zhang","DrJimFan", "karpathy", "bentossell", "itakush", "p_sharma", "llama_index"
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
    """抓取目标日期的推文数据并附带链接"""
    all_text = ""
    start = target_date_obj.replace(hour=0, minute=0, second=0)
    end = target_date_obj.replace(hour=23, minute=59, second=59)
    print(f"📡 正在抓取推文数据 (范围: {start.strftime('%Y-%m-%d %H:%M:%S')} 至 {end.strftime('%Y-%m-%d %H:%M:%S')})...")
    
    count = 0
    for user in AI_INFLUENCERS:
        try:
            res = requests.get(f"https://{RAPIDAPI_HOST}/timeline.php", 
                               headers={"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": RAPIDAPI_HOST}, 
                               params={"screenname": user}, timeout=20)
            if res.status_code == 200:
                data = res.json()
                for tweet in data.get('timeline', [])[:3]:
                    c_at = datetime.strptime(tweet['created_at'], "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
                    if start <= c_at <= end:
                        content = tweet.get('text') or tweet.get('full_text', "")
                        t_id = tweet.get('tweet_id')
                        t_url = f"https://x.com/{user}/status/{t_id}"
                        all_text += f"作者: @{user} | 原文链接: {t_url} | 内容: {content}\n"
                        count += 1
            time.sleep(1.2)
        except Exception as e:
            print(f"⚠️ 抓取 @{user} 失败: {e}")
            continue
    print(f"✅ 抓取完成，共获得 {count} 条推文动态。")
    return all_text

def fetch_gemini_summary(new_content, date_label):
    """调用 Gemini 进行 PM 导师视角的深度拆解"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = """
    # Role
    你是一位顶级的 AI 行业分析师和资深 AI 产品经理导师。你的任务是追踪 Twitter (X) 上全球最前沿的 AI 开发者、产品经理及研究员的动态，并为一位“正从搜索产品经理转型 AI 产品经理”的用户生成每日深度日报。

    # Knowledge Source & Focus
    重点关注：
    1. 模型演进：LLM 新能力、多模态进展。
    2. Agent 架构：规划(Planning)、记忆(Memory)、工具使用(Tool Use)的实际案例。
    3. AI UX 设计：新的交互范式（如 Generative UI）。
    4. 技术落地：RAG 与搜索结合的最新优化思路。
    5. 行业洞察：AI 产品的商业模式、估值与市场反馈。

    # Daily Report Structure (请严格按此 HTML 格式输出)
    1. 📅 [日期] AI 行业早报：从搜索迈向 Agent
    2. 🔥 今日核心趋势 (Top 3)：分析今日最具启发性的 3 件事，包含动态描述和 PM 视角的价值判断。
    3. 🛠 专家深度见解 (Expert Insights)：总结核心观点，必须包含对应的 <a href="...">查看原文</a> 链接。
    4. 🔍 搜索 vs. AI 专题 (Search to AI Bridge)：【针对性模块】帮助用户将搜索经验转化为 AI 能力的建议。
    5. 🚀 必读 Link & 产品拆解：提供 2-3 个 Demo 链接，必须使用 HTML 超链接。

    # Tone & Style
    - 专业、理性、启发性，拒绝废话。
    - 遇到技术术语需简单解释，直接给出产品经理能用的结论。
    
    注意：直接输出 HTML 内容，不要包裹任何 Markdown 标签。必须使用提供的原文链接进行溯源。
    """
    
    payload = {
        "contents": [{"parts": [{"text": f"报告日期：{date_label}\n昨日推文及链接数据：\n{new_content}"}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }
    try:
        res = requests.post(url, json=payload, timeout=60)
        res_data = res.json()
        if 'candidates' in res_data:
            report = res_data['candidates'][0]['content']['parts'][0]['text']
            return report.replace('```html', '').replace('```', '').strip()
        else:
            print(f"❌ Gemini 返回异常: {res_data}")
            return None
    except Exception as e:
        print(f"❌ Gemini 请求失败: {e}")
        return None

# --- 4. 业务逻辑 ---

def handle_otps():
    """实时处理验证码"""
    print("🔍 正在扫描待处理的验证码请求...")
    req_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("verification_requests")
    docs = req_ref.where(filter=FieldFilter("status", "==", "pending")).stream()
    for doc in docs:
        data = doc.to_dict()
        email, code = data['email'], data['code']
        body = f"您的 AI 战略日报订阅验证码为：<b style='font-size:20px; color:#3498db;'>{code}</b>。10分钟内有效。"
        if send_email(email, "【验证码】AI 战略日报订阅确认", body):
            doc.reference.update({"status": "sent", "sentAt": firestore.SERVER_TIMESTAMP})

def crawl_and_generate_report(target_date_obj):
    """生成日报并存入数据库"""
    date_str = target_date_obj.strftime('%Y-%m-%d')
    print(f"🚀 正在生成今日简报 ({date_str})...")
    
    # 抓取昨天的动态
    yesterday_data = get_tweets(target_date_obj - timedelta(days=1))
    if not yesterday_data:
        return None, date_str
    
    report_html = fetch_gemini_summary(yesterday_data, date_str)
    if report_html:
        db.collection("daily_history").document(date_str).set({
            "content": report_html,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "broadcast_done": False
        })
    return report_html, date_str

def get_latest_report_content():
    """获取最新日报 (优先今日缓存)"""
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    today_str = bj_now.strftime('%Y-%m-%d')
    doc_ref = db.collection("daily_history").document(today_str)
    doc = doc_ref.get()
    
    if doc.exists:
        return doc.to_dict().get("content"), today_str
    return crawl_and_generate_report(bj_now)

def handle_new_subscribers(report_html, report_date):
    """为新激活用户即刻推送首份日报"""
    print("🔍 正在扫描新激活订阅者...")
    subs_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers")
    docs = subs_ref.where(filter=FieldFilter("active", "==", True)).stream()
    for doc in docs:
        data = doc.to_dict()
        if data.get("welcome_sent"): continue
        
        email = data['email']
        footer = f'<hr><p style="font-size:12px;color:#999;">您收到此件是因为刚订阅。退订请点击 <a href="{WEB_URL}?action=unsubscribe&email={email}">此处</a></p>'
        if send_email(email, f"🚀 欢迎！AI 战略观察日报 ({report_date})", report_html + footer):
            doc.reference.update({"welcome_sent": True, "firstPushAt": firestore.SERVER_TIMESTAMP})

if __name__ == "__main__":
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    print(f"🕒 执行时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 发送验证码
    handle_otps()
    
    # 2. 获取当日日报
    report_html, report_date = get_latest_report_content()
    
    # 3. 为新用户即刻推送
    if report_html:
        handle_new_subscribers(report_html, report_date)
    
    # 4. 定时群发任务 (北京时间 9:00 - 10:00 窗口)
    if bj_now.hour == 9:
        today_str = bj_now.strftime('%Y-%m-%d')
        doc_ref = db.collection("daily_history").document(today_str)
        doc_snap = doc_ref.get()
        if doc_snap.exists and not doc_snap.to_dict().get("broadcast_done", False):
            print(f"📢 触发 {today_str} 全员例行群发...")
            active_docs = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers").where(filter=FieldFilter("active", "==", True)).stream()
            for sub in active_docs:
                email = sub.to_dict()['email']
                footer = f'<hr><p style="font-size:12px;color:#999;">退订请点击 <a href="{WEB_URL}?action=unsubscribe&email={email}">此处</a></p>'
                send_email(email, f"✨ AI 战略观察日报 [{report_date}]", report_html + footer)
            doc_ref.update({"broadcast_done": True})
