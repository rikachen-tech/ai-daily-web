import os
import json
import requests
import smtplib
import time
import re
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime, timedelta, timezone

# --- 1. 配置加载 (从 GitHub Secrets 获取) ---
def check_env_vars():
    required_vars = ["RAPIDAPI_KEY", "GEMINI_API_KEY", "SENDER_EMAIL", "SENDER_PASSWORD", "FIREBASE_CONFIG_JSON"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"❌ 启动失败：缺少 Secrets 配置: {', '.join(missing)}")
        exit(1)
        
check_env_vars()
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
        print("✅ Firebase 连接成功")
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
        print(f"📧 邮件发送至 {to_email} 失败: {e}")
        return False

def get_tweets(target_date_obj):
    all_text = ""
    start = target_date_obj.replace(hour=0, minute=0, second=0)
    end = target_date_obj.replace(hour=23, minute=59, second=59)
    print(f"📡 正在抓取昨日动态 ({start.strftime('%Y-%m-%d')})...")
    
    for i, user in enumerate(AI_INFLUENCERS):
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
            time.sleep(1.2)
        except: continue
    print(f"✅ 抓取完成")
    return all_text

def fetch_gemini_summary(new_content, date_label):
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
        "contents": [{"parts": [{"text": f"日期：{date_label}\n数据：\n{new_content}"}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }
    try:
        print("🤖 正在请求 Gemini 2.5 进行深度分析...")
        res = requests.post(url, json=payload, timeout=60)
        report = res.json()['candidates'][0]['content']['parts'][0]['text']
        return report.replace('```html', '').replace('```', '').strip()
    except Exception as e:
        print(f"❌ Gemini 分析失败: {e}")
        return None

# --- 4. 业务逻辑 ---

def handle_otps():
    """实时处理验证码"""
    print("🔍 扫描待处理验证码...")
    req_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("verification_requests")
    docs = req_ref.where(filter=FieldFilter("status", "==", "pending")).stream()
    
    count = 0
    for doc in docs:
        data = doc.to_dict()
        email, code = data['email'], data['code']
        if send_email(email, "【验证码】AI 日报订阅确认", f"您的验证码是：{code}"):
            doc.reference.update({"status": "sent", "sentAt": firestore.SERVER_TIMESTAMP})
            count += 1
    print(f"   -> 已处理 {count} 个验证码")

def get_today_report():
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    today_str = bj_now.strftime('%Y-%m-%d')
    doc_ref = db.collection("daily_history").document(today_str)
    
    snap = doc_ref.get()
    if snap.exists:
        return snap.to_dict().get("content"), today_str
    
    content = get_tweets(bj_now - timedelta(days=1))
    if not content: return None, today_str
    
    report = fetch_gemini_summary(content, today_str)
    if report:
        doc_ref.set({"content": report, "timestamp": firestore.SERVER_TIMESTAMP})
        return report, today_str
    return None, today_str

def broadcast_to_subscribers(report_html, report_date):
    """
    核心逻辑升级：基于用户状态的精准群发/补发。
    如果当日已经自动触发给 A，手动触发则跳过；如果 A 没收到，手动触发则补发。
    """
    print(f"📢 正在检查并分发日报 ({report_date})...")
    subs_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers")
    # 只针对已激活的用户
    docs = subs_ref.where(filter=FieldFilter("active", "==", True)).stream()
    
    sent_count = 0
    skip_count = 0
    
    for doc in docs:
        data = doc.to_dict()
        email = data['email']
        # 检查该用户最后一次接收日报的日期
        last_received = data.get("last_received_date", "")
        
        # 如果用户今天还没收到过日报
        if last_received != report_date:
            print(f"   -> 正在发送至: {email}")
            footer = f'<hr><p style="font-size:12px;color:#999;">您收到此件是因为已订阅。退订请点击 <a href="{WEB_URL}?action=unsubscribe&email={email}">此处</a></p>'
            if send_email(email, f"✨ AI 战略观察日报 [{report_date}]", report_html + footer):
                # 成功发送后，立即更新该用户的“最后接收日期”
                doc.reference.update({
                    "last_received_date": report_date,
                    "welcome_sent": True # 兼容旧逻辑
                })
                sent_count += 1
        else:
            skip_count += 1

    print(f"🎉 处理完毕：成功发送/补发 {sent_count} 位用户，跳过 {skip_count} 位已接收用户。")

if __name__ == "__main__":
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    print(f"=== 引擎启动 | 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # 1. 扫描验证码 (最高优先级)
    handle_otps()
    
    # 2. 获取/生成今日日报内容
    report, date_label = get_today_report()
    
    # 3. 执行分发逻辑 (不再区分定时和手动，统一由用户接收状态驱动)
    if report:
        broadcast_to_subscribers(report, date_label)
    else:
        print("⚠️ 无法获取当日报告内容，跳过分发环节。")
    
    print("=== ✅ 任务全部处理完毕 ===")
