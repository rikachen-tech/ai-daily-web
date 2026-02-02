import os
import json
import requests
import smtplib
import time
import traceback
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr

import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. 配置管理 ---
class Config:
    APP_ID = "ai-daily-app"
    WEB_URL = "https://ai-daily-web.vercel.app/"
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    
    # 推荐使用的模型版本
    GEMINI_MODEL = "gemini-2.5-flash-preview-09-2025"
    
    # 手动订阅者列表
    MANUAL_SUBS = [
        # "example@gmail.com"
    ]

    @staticmethod
    def validate():
        required_keys = [
            "RAPIDAPI_KEY", "GEMINI_API_KEY", 
            "SENDER_EMAIL", "SENDER_PASSWORD", 
            "FIREBASE_CONFIG_JSON"
        ]
        config = {k: os.environ.get(k) for k in required_keys}
        missing = [k for k, v in config.items() if not v]
        if missing:
            raise ValueError(f"GitHub Secrets 缺失项: {', '.join(missing)}")
        return config

# 大佬名单
AI_INFLUENCERS = [
    "OpenAI", "sama", "AnthropicAI", "DeepMind", "demishassabis", "MetaAI", "ylecun", 
    "karpathy", "AravSrinivas", "mustafasuleyman", "gdb", "therundownai", "rowancheung",
    "pete_huang", "tldr", "bentossell", "alliekmiller", "DrJimFan", "llama_index","Andrew Karpathy", "Swyx", 
    "Greg Isenberg", "Lenny Rachitsky", "Josh Woodward", "Kevin Weil", "Peter Yang", "Nan Yu", "Madhu Guru", "Mckay Wrigley", 
    "Steven Johnson", "Amanda Askell", "Cat Wu", "Thariq", "Google Labs", "George Mack", "Raiza Martin", "Amjad Masad",
    "Guillermo Rauch", "Riley Brown", "Alex Albert", "Hamel Husain", "Aaron Levie", "Ryo Lu", "Garry Tan", 
    "Lulu Cheng Meservey", "Justine Moore", "Matt Turck", "Julie Zhuo", "Gabriel Peters","PJ Ace", "Zara Zhang"
]

# --- 2. 工具函数 ---
def request_with_retry(method, url, max_retries=3, **kwargs):
    for i in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            if response.status_code == 429:
                print("🚨 警告：RapidAPI 额度已耗尽 (429)！")
                return response
            response.raise_for_status()
            return response
        except Exception as e:
            if i == max_retries - 1: raise e
            time.sleep(2 ** i)
    return None

# --- 3. 核心引擎类 ---
class AIDailyEngine:
    def __init__(self, config_dict):
        self.config = config_dict
        self.db = self._init_firebase()
        self.session = requests.Session()
        # 按照规范设置路径
        self.pool_path = f"artifacts/{Config.APP_ID}/public/data/tweet_pool"
        self.history_path = f"artifacts/{Config.APP_ID}/public/data/daily_history"
        self.sub_path = f"artifacts/{Config.APP_ID}/public/data/subscribers"

    def _init_firebase(self):
        cred_dict = json.loads(self.config["FIREBASE_CONFIG_JSON"])
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(cred_dict))
        return firestore.client()

    def sync_manual_subscribers(self):
        """将代码中手动定义的邮箱同步到数据库"""
        if not Config.MANUAL_SUBS:
            return
            
        print(f"👥 正在同步手动订阅者列表 ({len(Config.MANUAL_SUBS)} 个)...")
        subs_ref = self.db.collection(*self.sub_path.split('/'))
        
        for email in Config.MANUAL_SUBS:
            if not email: continue
            email = email.strip().lower()
            doc_ref = subs_ref.document(email)
            if not doc_ref.get().exists:
                doc_ref.set({
                    "email": email,
                    "active": True,
                    "source": "manual_import",
                    "last_received_date": "",
                    "created_at": firestore.SERVER_TIMESTAMP
                })
                print(f"➕ 已新增订阅者: {email}")
        print("✅ 手动订阅者同步完成")

    def sync_tweets(self):
        bj_now = datetime.now(timezone(timedelta(hours=8)))
        start_date = bj_now - timedelta(days=1)
        
        print(f"📡 开始同步推文资源池（目标：24h 内动态）...")
        new_count = 0
        
        headers = {
            "X-RapidAPI-Key": self.config["RAPIDAPI_KEY"],
            "X-RapidAPI-Host": "twitter-api45.p.rapidapi.com"
        }

        for index, user in enumerate(AI_INFLUENCERS):
            try:
                res = self.session.get(
                    "https://twitter-api45.p.rapidapi.com/timeline.php",
                    headers=headers,
                    params={"screenname": user},
                    timeout=20
                )
                
                remaining = res.headers.get('x-ratelimit-requests-remaining')
                if index == 0 and remaining:
                    print(f"📊 提示：当前 API 剩余可用额度约: {remaining}")

                if res.status_code != 200: 
                    if res.status_code == 429: break 
                    continue
                
                timeline = res.json().get('timeline', [])
                for tweet in timeline[:10]:
                    t_id = str(tweet.get('tweet_id'))
                    c_at_str = tweet.get('created_at')
                    if not t_id or not c_at_str: continue
                    
                    c_at = datetime.strptime(c_at_str, "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
                    
                    if c_at >= start_date:
                        doc_ref = self.db.collection(*self.pool_path.split('/')).document(t_id)
                        if not doc_ref.get().exists:
                            doc_ref.set({
                                "user": user,
                                "content": tweet.get('text', ""),
                                "url": f"https://x.com/{user}/status/{t_id}",
                                "created_at": c_at,
                                "used_in_report": False,
                                "synced_at": firestore.SERVER_TIMESTAMP
                            })
                            new_count += 1
                time.sleep(0.5) 
            except Exception as e:
                print(f"⚠️ 同步用户 {user} 失败: {e}")
        
        print(f"✅ 资源池更新完成，新增 {new_count} 条。")

    def generate_daily_report(self):
        bj_now = datetime.now(timezone(timedelta(hours=8)))
        today_str = bj_now.strftime('%Y-%m-%d')
        
        history_ref = self.db.collection(*self.history_path.split('/')).document(today_str)
        existing = history_ref.get()
        if existing.exists:
            print(f"✨ 今日报告 {today_str} 已存在。")
            return existing.to_dict().get("content"), today_str

        pool_ref = self.db.collection(*self.pool_path.split('/'))
        docs = list(pool_ref.stream())
        unused_docs = [d for d in docs if not d.to_dict().get("used_in_report")]
        
        if not unused_docs:
            print("📭 无新素材可供分析。")
            return None, today_str

        sorted_docs = sorted(unused_docs, key=lambda x: x.to_dict().get('created_at', datetime(1970,1,1,tzinfo=timezone.utc)), reverse=True)[:50]
        
        input_data = ""
        ids_to_mark = []
        for d in sorted_docs:
            data = d.to_dict()
            content = data['content'].replace('\n', ' ')[:500] 
            input_data += f"源: @{data['user']} | 链接: {data['url']} | 内容: {content}\n"
            ids_to_mark.append(d.id)

        report_html = self._call_gemini_api(input_data)
        
        if report_html:
            history_ref.set({
                "content": report_html,
                "timestamp": firestore.SERVER_TIMESTAMP,
                "sources": len(ids_to_mark)
            })
            
            batch = self.db.batch()
            for t_id in ids_to_mark:
                batch.update(pool_ref.document(t_id), {"used_in_report": True})
            batch.commit()
            return report_html, today_str
            
        return None, today_str

    def _call_gemini_api(self, text):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:generateContent?key={self.config['GEMINI_API_KEY']}"
        
        # 恢复了你的完整版 System Prompt
        system_prompt = f"""
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
            "contents": [{"parts": [{"text": f"待分析数据：\n{text}"}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]}
        }
        
        try:
            res = request_with_retry("POST", url, json=payload, timeout=60)
            res_data = res.json()
            report = res_data['candidates'][0]['content']['parts'][0]['text']
            # 清理可能的 markdown 包裹
            return report.replace('```html', '').replace('```', '').strip()
        except Exception as e:
            print(f"❌ Gemini 分析失败: {e}")
            return None

    def distribute_email(self, report, date_label):
        subs_ref = self.db.collection(*self.sub_path.split('/'))
        active_subs = [s for s in subs_ref.stream() if s.to_dict().get("active")]
        
        print(f"📢 准备发送至 {len(active_subs)} 位订阅者...")
        
        for sub in active_subs:
            data = sub.to_dict()
            email = data.get("email")
            if not email or data.get("last_received_date") == date_label:
                continue
            
            full_content = f"""
            <html>
                <body style="font-family: sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: auto;">
                    <div style="background: #f4f4f7; padding: 20px; border-radius: 8px;">
                        {report}
                    </div>
                    <footer style="margin-top: 20px; font-size: 12px; color: #999; text-align: center;">
                        <p>这是由 AI 引擎自动生成的行业日报</p>
                        <p><a href="{Config.WEB_URL}?action=unsubscribe&email={email}">退订</a> | <a href="{Config.WEB_URL}">查看网页版</a></p>
                    </footer>
                </body>
            </html>
            """
            
            if self._send_smtp(email, f"✨ AI 战略动态 [{date_label}]", full_content):
                sub.reference.update({"last_received_date": date_label})
                print(f"✅ 已发送: {email}")

    def _send_smtp(self, to_email, subject, html):
        msg = MIMEMultipart('alternative')
        msg['Subject'] = Header(subject, 'utf-8').encode()
        msg['From'] = formataddr(("AI Insights Bot", self.config["SENDER_EMAIL"]))
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        
        try:
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                server.login(self.config["SENDER_EMAIL"], self.config["SENDER_PASSWORD"])
                server.sendmail(self.config["SENDER_EMAIL"], [to_email], msg.as_bytes())
            return True
        except Exception as e:
            print(f"📧 邮件异常 [{to_email}]: {e}")
            return False

# --- 4. 运行入口 ---
if __name__ == "__main__":
    print(f"=== 🚀 AI 洞察引擎启动 | {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    try:
        env_config = Config.validate()
        engine = AIDailyEngine(env_config)
        
        engine.sync_manual_subscribers()
        engine.sync_tweets()
        
        report_content, date_tag = engine.generate_daily_report()
        
        if report_content:
            engine.distribute_email(report_content, date_tag)
            print("🎉 所有任务已圆满完成！")
        else:
            print("😴 今日无新内容产出，跳过分发。")
            
    except Exception:
        print("\n🔥 严重错误：")
        traceback.print_exc()
        exit(1)
