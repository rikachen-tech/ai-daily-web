/**
 * 这是一个运行在 Vercel 上的 Serverless 函数
 * 路径: /api/send-code
 */
import { Resend } from 'resend';
import { initializeApp, getApps, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

// 1. 初始化 Resend (发信服务)
const resend = new Resend(process.env.RESEND_API_KEY);

// 2. 初始化 Firebase Admin (存取验证码)
// 确保环境变量 FIREBASE_CONFIG_JSON 是完整的 JSON 字符串
const firebaseConfig = JSON.parse(process.env.FIREBASE_CONFIG_JSON);
if (!getApps().length) {
  initializeApp({
    credential: cert(firebaseConfig)
  });
}
const db = getFirestore();

export default async function handler(req, res) {
  // 安全检查：只允许 POST 请求
  if (req.method !== 'POST') {
    return res.status(405).json({ error: '仅支持 POST 请求' });
  }

  const { email } = req.body;
  if (!email) {
    return res.status(400).json({ error: '请输入邮箱' });
  }

  try {
    // A. 生成 6 位随机验证码
    const code = Math.floor(100000 + Math.random() * 900000).toString();

    // B. 将验证码存入 Firestore (设置 5 分钟有效期)
    // 路径遵循规范: /artifacts/ai-daily-app/public/data/verification_codes/{email}
    const appId = "ai-daily-app";
    const codePath = `artifacts/${appId}/public/data/verification_codes`;
    
    await db.collection(codePath).doc(email).set({
      code,
      expiresAt: Date.now() + 5 * 60 * 1000, // 5分钟后过期
      createdAt: new Date().toISOString()
    });

    // C. 调用 Resend API 发送邮件
    const { data, error } = await resend.emails.send({
      from: 'AI Daily <auth@your-verified-domain.com>', // 这里要换成你在 Resend 验证过的域名
      to: [email],
      subject: '您的登录验证码',
      html: `
        <div style="font-family: sans-serif; padding: 40px; border: 1px solid #eee; border-radius: 10px;">
          <h2 style="color: #000;">欢迎来到 AI Daily</h2>
          <p style="font-size: 16px; color: #666;">您的身份验证码是：</p>
          <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; margin: 20px 0; color: #000;">
            ${code}
          </div>
          <p style="font-size: 12px; color: #999;">该验证码将在 5 分钟后失效。请勿泄露给他人。</p>
        </div>
      `,
    });

    if (error) {
      console.error('Resend 发送失败:', error);
      return res.status(400).json({ error });
    }

    return res.status(200).json({ success: true, message: '验证码已发送' });
  } catch (err) {
    console.error('服务器内部错误:', err);
    return res.status(500).json({ error: '发送失败，请稍后再试' });
  }
}
