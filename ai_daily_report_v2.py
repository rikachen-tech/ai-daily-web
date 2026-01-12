import os
import json
import requests
import smtplib
import time
import traceback
import firebase_admin
from firebase_admin import credentials, firestore
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime, timedelta, timezone

# --- 1. 配置加载与验证 ---
def get_config():
    """集中获取并检查配置"""
    config = {
        "RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "SENDER_EMAIL": os.environ.get("SENDER_EMAIL"),
        "SENDER_PASSWORD": os.environ.get("SENDER_PASSWORD"),
        "FIREBASE_JSON": os.environ.get("FIREBASE_CONFIG_JSON")
    }
    
    missing = [k for k, v in config.items() if not v]
    if missing:
        raise ValueError(f"GitHub Secrets 中缺少配置项: {', '.join(missing)}")
    
    return config

# 基础配置
APP_ID = "ai-daily-app"
WEB_URL = "https://ai-daily-web.vercel.app/"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# 核心大佬名单
AI_INFLUENCERS = [
    "OpenAI", "sama", "AnthropicAI", "DeepMind", "demishassabis", "MetaAI", "ylecun", "MistralAI", "huggingface", "clem_delangue",
    "karpathy", "AravSrinivas", "mustafasuleyman", "gdb", "therundownai", "rowancheung", "pete_huang", "tldr", "bentossell",
    "alliekmiller", "LinusEkenstam", "shreyas", "lennysan","garrytan","danshipper","Greg Isenberg", "Andrej Karpathy", "Swyx", 
    "Josh Woordward","Kevin Weil","Peter Yang", "Nan Yu","Madhu Guru", "Mckay Wrigley","Steven Johnson", "Amanda Askell", 
    "Cat Wu", "Thariq", "Google Labs", "George Mack", "Raiza Martin", "Amjad Masad", "Guillermo Rauch", "Riley Brown", 
    "Alex Albert", "Hamel Husain", "Aaron Levie", "Ryo Lu", "Lulu Cheng Meservey", "Justine Moore", "Matt Turck", 
    "Julie Zhuo", "Gabriel Peters", "PJ Ace", "Zara Zhang","DrJimFan", "llama_index"
]

# --- 2. 核心功能模块 ---

def send_email(config, to_email, subject, html_content):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8').encode()
    msg['From'] = formataddr(("AI Insights Bot", config["SENDER_EMAIL"]))
    msg['To'] = to_email
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(config["SENDER_EMAIL"], config["SENDER_PASSWORD"])
            server.sendmail(config["SENDER_EMAIL"], [to_email], msg.as_bytes())
        return True
    except Exception as e:
        print(f"📧 邮件发送失败 [{to_email}]: {e}")
        return False

def sync_tweets(config, db):
    """抓取过去 7 天动态存入资源池"""
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    start_date = (bj_now - timedelta(days=7))
    
    print(f"📡 正在同步推文资源池...")
    pool_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("tweet_pool")
    
    new_count = 0
    for user in AI_INFLUENCERS:
        try:
            res = requests.get(
                "https://twitter-api45.p.rapidapi.com/timeline.php",
                headers={"X-RapidAPI-Key": config["RAPIDAPI_KEY"], "X-RapidAPI-Host": "twitter-api45.p.rapidapi.com"},
                params={"screenname": user}, 
                timeout=20
            )
            if res.status_code == 200:
                timeline = res.json().get('timeline', [])
                for tweet in timeline[:8]:
                    t_id = str(tweet.get('tweet_id'))
                    c_at_str = tweet.get('created_at')
                    if not t_id or not c_at_str: continue
                    
                    c_at = datetime.strptime(c_at_str, "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
                    
                    if c_at >= start_date:
                        doc_ref = pool_ref.document(t_id)
                        if not doc_ref.get().exists:
                            doc_ref.set({
                                "user": user, 
                                "content": tweet.get('text', ""),
                                "url": f"https://x.com/{user}/status/{t_id}",
                                "created_at": c_at, 
                                "used_in_report": False
                            })
                            new_count += 1
            time.sleep(1.0) # 稍微降低频率
        except Exception as e:
            print(f"⚠️ 同步用户 {user} 失败: {e}")
            continue
    print(f"✅ 资源池更新完成，新增 {new_count} 条动态。")

def fetch_gemini_summary(config, new_content):
    """调用 Gemini 生成 HTML 格式报告"""
    if not new_content: return None
    api_key = config["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={api_key}"
    
    system_prompt = """
    # Role
    你是一位顶级的 AI 行业分析师和资深 AI 产品经理导师。你的任务是根据提供的推文资源池（包含过去 7 天未曾分析的全球最前沿的 AI 开发者、产品经理及研究员的动态）并为一位“正从传统策略产品经理转型 AI 产品经理”的用户生成每日深度日报。
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
        "contents": [{"parts": [{"text": f"待分析数据：\n{new_content}"}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }
    
    try:
        print("🤖 正在请求 Gemini 分析动态...")
        res = requests.post(url, json=payload, timeout=60)
        res.raise_for_status()
        res_data = res.json()
        if 'candidates' in res_data:
            report = res_data['candidates'][0]['content']['parts'][0]['text']
            return report.replace('```html', '').replace('```', '').strip()
        return None
    except Exception as e:
        print(f"❌ Gemini 分析失败: {e}")
        return None

def generate_report(config, db):
    """基于池中未使用的数据生成日报并保存"""
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    today_str = bj_now.strftime('%Y-%m-%d')
    
    # 1. 检查是否已有日报
    history_ref = db.collection("daily_history").document(today_str)
    existing_doc = history_ref.get()
    if existing_doc.exists:
        print(f"✨ 今日报告 ({today_str}) 已存在，直接读取。")
        return existing_doc.to_dict().get("content"), today_str

    # 2. 提取池中素材
    pool_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("tweet_pool")
    docs = list(pool_ref.where("used_in_report", "==", False).stream())
    
    if not docs:
        print("📭 资源池中没有未使用的素材。")
        return None, today_str

    # 排序并取前 50 条
    sorted_docs = sorted(docs, key=lambda x: x.to_dict().get('created_at', datetime(1970,1,1,tzinfo=timezone.utc)), reverse=True)
    target_docs = sorted_docs[:50]
    
    raw_text = ""
    ids_to_mark = []
    for d in target_docs:
        data = d.to_dict()
        raw_text += f"USER: @{data['user']} | LINK: {data['url']} | CONTENT: {data['content']}\n"
        ids_to_mark.append(d.id)

    # 3. 调用 AI 生成
    report_html = fetch_gemini_summary(config, raw_text)
    
    if report_html:
        # 4. 保存结果并标记素材已使用
        history_ref.set({
            "content": report_html, 
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        batch = db.batch()
        for t_id in ids_to_mark:
            batch.update(pool_ref.document(t_id), {"used_in_report": True})
        batch.commit()
        
        print(f"🎉 今日日报生成成功！标记了 {len(ids_to_mark)} 条素材。")
        return report_html, today_str
    
    return None, today_str

# --- 3. 主程序入口 ---

if __name__ == "__main__":
    try:
        print(f"=== 引擎自检启动 | {datetime.now().strftime('%H:%M:%S')} ===")
        
        # 1. 获取配置
        config = get_config()
        
        # 2. Firebase 初始化
        cred_dict = json.loads(config["FIREBASE_JSON"])
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(cred_dict))
        db = firestore.client()
        print("✅ 基础设施连接成功")

        # 3. 同步推文
        sync_tweets(config, db)
        
        # 4. 生成报告
        report, date_label = generate_report(config, db)
        
        # 5. 分发邮件
        if report:
            print(f"📢 正在分发日报...")
            subs_ref = db.collection("artifacts").document(APP_ID).collection("public").document("data").collection("subscribers")
            active_subs = subs_ref.where("active", "==", True).stream()
            
            for sub in active_subs:
                sub_data = sub.to_dict()
                email_addr = sub_data.get("email")
                if not email_addr: continue
                
                if sub_data.get("last_received_date") != date_label:
                    footer = f'<hr><p style="font-size:12px;color:#999;">退订请点击 <a href="{WEB_URL}?action=unsubscribe&email={email_addr}">此处</a></p>'
                    if send_email(config, email_addr, f"✨ AI 战略日报 [{date_label}]", report + footer):
                        sub.reference.update({"last_received_date": date_label})
                        print(f"✅ 已发送至: {email_addr}")
            
            print("✅ 分发任务结束")
        else:
            print("⚠️ 未生成报告，分发取消。")

    except Exception as e:
        print("\n" + "!"*40)
        print("❌ 脚本崩溃！详细报错如下：")
        print("!"*40)
        traceback.print_exc()
        exit(1)
    
    print("=== 🏁 任务顺利完成 ===")
