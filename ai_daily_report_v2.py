import os
import json
import requests
import resend  # 统一使用 Resend SDK
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

# --- 配置管理 ---
class Config:
    APP_ID = "ai-daily-app"
    # 使用具备强搜索能力的模型
    GEMINI_MODEL = "gemini-2.5-flash-preview-09-2025"
    
    # 核心环境变量 (确保在 GitHub Secrets 中已配置)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
    FIREBASE_CONFIG_JSON = os.environ.get("FIREBASE_CONFIG_JSON")
    
    # 你的验证域名 (已在 Resend 验证成功)
    SENDER_DOMAIN = "insightdata.space"

# 你的“私人关注列表”
AI_INFLUENCERS = [
    "OpenAI (sama, gdb)", "Anthropic (Dario Amodei)", "DeepMind (Demis Hassabis)", 
    "Meta AI (Yann LeCun)", "Andrej Karpathy", "Mustafa Suleyman", "Aravind Srinivas (Perplexity)",
    "Rowan Cheung", "The Rundown AI", "Dr. Jim Fan (NVIDIA)", "LlamaIndex", "LangChain"
]

# --- AI Agent 类 ---
class AIAgentResearcher:
    def __init__(self):
        self._init_firebase()
        self.db = firestore.client()
        # 初始化 Resend
        resend.api_key = Config.RESEND_API_KEY

    def _init_firebase(self):
        """初始化数据库连接"""
        cred_dict = json.loads(Config.FIREBASE_CONFIG_JSON)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(cred_dict))

    def run_agent_task(self):
        """Agent 核心逻辑：定向追踪关注列表"""
        print(f"🕵️ Agent 正在定向追踪你的关注列表 ({len(AI_INFLUENCERS)} 个目标)...")
        
        influencer_list_str = ", ".join(AI_INFLUENCERS)
        
        # 针对产品经理视角的定向 Prompt
        prompt = f"""
        今天的日期是 {datetime.now().strftime('%Y-%m-%d')}。
        
        你现在的身份是我的“硅谷情报助理”。我有一个特定的关注列表：[{influencer_list_str}]。
        
        请利用搜索工具，专门调查这些人在过去 24 小时内在 Twitter(X)、官方博客或新闻中发布了哪些最新动态。
        
        任务要求：
        1. 聚焦：只关注我给出的这些人或公司的直出动态。
        2. 提炼：作为产品经理，请告诉我这些动态背后代表了什么产品趋势或竞争策略。
        3. 格式：以精美的 HTML 格式输出。每个动态必须包含：
           - 来源（是谁说的/做的）
           - 核心内容简述
           - PM 视角解读（为什么这个重要）
        
        如果没有查到特定的人的动态，请略过，只呈现最有价值的 3-5 条。
        """
        
        report_html = self._call_gemini_with_search(prompt)
        
        if report_html:
            print("✅ 定向研报已生成。")
            date_str = datetime.now().strftime('%Y-%m-%d')
            self._save_and_distribute(report_html, date_str)
        else:
            print("❌ Agent 未能获取到关注列表的最新动态。")

    def _call_gemini_with_search(self, prompt):
        """调用智能体搜索工具"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:generateContent?key={Config.GEMINI_API_KEY}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}], # 核心：开启谷歌搜索增强
            "systemInstruction": {
                "parts": [{"text": "你是一个专门追踪硅谷大佬动态的精英情报员。你善于穿透噪音，发现真正的行业趋势。"}]
            }
        }
        
        try:
            res = requests.post(url, json=payload, timeout=90)
            res.raise_for_status()
            res_data = res.json()
            
            content = res_data['candidates'][0]['content']['parts'][0]['text']
            return content.replace('```html', '').replace('```', '').strip()
        except Exception as e:
            print(f"Agent 运行异常: {e}")
            return None

    def _save_and_distribute(self, report, date_label):
        """保存历史并使用 Resend 推送给订阅者"""
        # 1. 存入数据库 (路径保持兼容)
        history_path = f"artifacts/{Config.APP_ID}/public/data/daily_history"
        self.db.collection(*history_path.split('/')).document(date_label).set({
            "content": report,
            "type": "influencer_tracking",
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        # 2. 获取活跃订阅者
        sub_path = f"artifacts/{Config.APP_ID}/public/data/subscribers"
        subs = [s.to_dict()["email"] for s in self.db.collection(*sub_path.split('/')).stream() if s.to_dict().get("active")]
        
        if not subs:
            print("📭 目前没有任何活跃订阅者。")
            return

        # 3. 使用 Resend 发送邮件
        subject = f"🔥 硅谷大佬动态追踪 | {date_label}"
        
        # 为了保护隐私并提高效率，使用 BCC (密送) 或者循环发送
        # 这里采用 Resend 推荐的循环发送，确保每个人都能看到自己的名字
        for email in subs:
            try:
                resend.Emails.send({
                    "from": f"AI Insights <report@{Config.SENDER_DOMAIN}>",
                    "to": email,
                    "subject": subject,
                    "html": report
                })
                print(f"📧 研报已送达: {email}")
            except Exception as e:
                print(f"❌ 邮件发送给 {email} 失败: {e}")

if __name__ == "__main__":
    agent = AIAgentResearcher()
    agent.run_agent_task()
