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

# --- 🚨 手动修复配置 🚨 ---
# 想要重发哪天的日报，就把 REPAIR_MODE 设为 True，并填好日期
REPAIR_MODE = True 
REPAIR_DATE = "2026-01-12" 

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
        print(f"📧 邮件发送至 {to_email} 失败: {e}")
        return False

def get_tweets(target_date_obj):
    """抓取推文并实时打印采样数据，方便调试"""
    all_text = ""
    start = target_date_obj.replace(hour=0, minute=0, second=0)
    end = target_date_obj.replace(hour=23, minute=59, second=59)
    print(f"📡 正在检查时间段: {start.strftime('%Y-%m-%d %H:%M:%S')} 至 {end.strftime('%Y-%m-%d %H:%M:%S')}")
    
    total_found = 0
    for i, user in enumerate(AI_INFLUENCERS):
        try:
            print(f"   [{i+1}/{len(AI_INFLUENCERS)}] 正在请求 @{user}...")
            res = requests.get(f"https://{RAPIDAPI_HOST}/timeline.php", 
                               headers={"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": RAPIDAPI_HOST}, 
                               params={"screenname": user}, timeout=20)
            
            if res.status_code == 200:
                data = res.json()
                timeline = data.get('timeline', [])
                user_found_count = 0
                for tweet in timeline[:5]:
                    c_at = datetime.strptime(tweet['created_at'], "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
                    if start <= c_at <= end:
                        content = tweet.get('text') or tweet.get('full_text', "")
                        t_id = tweet.get('tweet_id')
                        t_url = f"https://x.com/{user}/status/{t_id}"
                        all_text += f"USER: @{user} | LINK: {t_url} | CONTENT: {content}\n"
                        total_found += 1
                        user_found_count += 1
                if user_found_count > 0:
                    print(f"      ✅ 发现 {user_found_count} 条动态: {content[:30]}...")
            elif res.status_code == 429:
                print("   ⚠️ 警告: RapidAPI 额度已用尽 (Rate Limit)。")
                break
            else:
                print(f"   ❓ API 返回状态码: {res.status_code}")
            time.sleep(1.2)
        except Exception as e:
            print(f"   ❌ 抓取 @{user} 异常: {e}")
            continue
            
    return all_text if total_found > 0 else None

def fetch_gemini_summary(new_content, date_label):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = """
   # Role
    你是一位顶级的 AI 行业分析师和资深 AI 产品经理导师。你的任务是追踪 Twitter (X) 上全球最前沿的 AI 开发者、产品经理及研究员的动态，并为一位“正从传统策略产品经理转型 AI 产品经理”的用户生成每日深度日报。
   # rules
    1. 只能使用 [数据源] 里的真实信息。
    2. 如果数据源里的推文少于 3 条，请如实告知用户今日动态较少，严禁编造。
    3. 严禁生成数据源之外的任何 x.com 链接。
    # Knowledge Source & Focus
    重点关注：
    1. 模型演进：LLM 新能力、多模态进展。
    2. Agent 架构：规划(Planning)、记忆(Memory)、工具使用(Tool Use)的实际案例。
    3. AI UX 设计：新的交互范式（如 Generative UI）。
    4. 技术落地：LLM和搜索结合的最新优化思路。
    5. 行业洞察：AI 产品的商业模式、估值与市场反馈。

    # Daily Report Structure (请严格按此 HTML 格式输出)
    1. 📅 [日期] AI 行业早报：[提炼核心关键起一个标题]
    2. 🔥 今日核心趋势 (Top 3)：分析今日最具启发性的 3 件事，包含动态描述和 PM 视角的价值判断。必须包含对应的 <a href="...">查看原文</a> 链接。
    3. 🛠 专家深度见解 (Expert Insights)：总结核心观点，必须包含对应的 <a href="...">查看原文</a> 链接。
    4. 🔍 搜索 vs. AI 专题 (Search to AI Bridge)：【针对性模块】帮助用户将搜索经验转化为 AI 能力的建议。
    5. 🚀 必读 Link & 产品拆解：提供 2-3 个 Demo 链接，必须使用 HTML 超链接。

    # Tone & Style
    - 专业、理性、启发性，拒绝废话。
    - 遇到技术术语需简单解释，直接给出产品经理能用的结论。
    
    注意：直接输出 HTML 内容，不要包裹任何 Markdown 标签。必须使用提供的原文链接进行溯源。
    """
    
    payload = {
        "contents": [{"parts": [{"text": f"日期：{date_label}\n[数据源]:\n{new_content}"}]}],
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

# --- 4. 业务逻辑 ---

def handle_otps():
    req_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("verification_requests")
    docs = req_ref.where(filter=FieldFilter("status", "==", "pending")).stream()
    for doc in docs:
        data = doc.to_dict()
        if send_email(data['email'], "【验证码】AI 日报订阅", f"验证码：{data['code']}"):
            doc.reference.update({"status": "sent", "sentAt": firestore.SERVER_TIMESTAMP})

def get_report_logic():
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    
    # 修复模式：直接指定日期并重新抓取
    if REPAIR_MODE:
        print(f"🛠 [修复模式启动] 正在为 {REPAIR_DATE} 重新生成报告...")
        target_date_obj = datetime.strptime(REPAIR_DATE, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
        raw_data = get_tweets(target_date_obj - timedelta(days=1)) # 抓取该日期前一天的推文
        
        report = fetch_gemini_summary(raw_data, REPAIR_DATE)
        if report:
            # 覆盖旧缓存
            db.collection("daily_history").document(REPAIR_DATE).set({
                "content": report, 
                "timestamp": firestore.SERVER_TIMESTAMP,
                "is_repaired": True 
            })
            return report, REPAIR_DATE
        return None, REPAIR_DATE

    # 正常模式
    today_str = bj_now.strftime('%Y-%m-%d')
    doc_ref = db.collection("daily_history").document(today_str)
    snap = doc_ref.get()
    if snap.exists:
        return snap.to_dict().get("content"), today_str
    
    raw_data = get_tweets(bj_now - timedelta(days=1))
    if not raw_data: return None, today_str
    
    report = fetch_gemini_summary(raw_data, today_str)
    if report:
        doc_ref.set({"content": report, "timestamp": firestore.SERVER_TIMESTAMP})
        return report, today_str
    return None, today_str

def broadcast_logic(report, date):
    print(f"📢 正在分发日报 ({date})...")
    subs_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers")
    docs = subs_ref.where(filter=FieldFilter("active", "==", True)).stream()
    
    for doc in docs:
        data = doc.to_dict()
        email = data['email']
        
        # 修复模式下：无视 last_received_date 检查，全员发送
        should_send = (data.get("last_received_date") != date) or REPAIR_MODE
        
        if should_send:
            print(f"   -> 正在发送修正版至: {email}")
            subject = f"✨ [修正版] AI 战略观察日报 [{date}]" if REPAIR_MODE else f"✨ AI 战略观察日报 [{date}]"
            footer = f'<hr><p style="font-size:12px;color:#999;">收到了错误信息？这是我们的修正版本。退订请点击 <a href="{WEB_URL}?action=unsubscribe&email={email}">此处</a></p>'
            
            if send_email(email, subject, report + footer):
                if not REPAIR_MODE: # 正常模式才更新日期，修复模式不更新以防干扰后续流程
                    doc.reference.update({"last_received_date": date})

if __name__ == "__main__":
    print(f"=== 引擎启动 (修复模式: {REPAIR_MODE}) ===")
    handle_otps()
    report_content, report_date = get_report_logic()
    
    if report_content:
        broadcast_logic(report_content, report_date)
        print("🎉 修正补发任务已完成。")
    else:
        print("🛑 任务失败：未能获取有效数据。")
