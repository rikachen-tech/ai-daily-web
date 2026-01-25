/**
 * 校验验证码并正式激活订阅
 * 路径: /api/verify-code
 */
import { initializeApp, getApps, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

// 1. 初始化 Firebase Admin
const firebaseConfig = JSON.parse(process.env.FIREBASE_CONFIG_JSON);
if (!getApps().length) {
  initializeApp({
    credential: cert(firebaseConfig)
  });
}
const db = getFirestore();

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: '仅支持 POST 请求' });
  }

  const { email, code } = req.body;
  const appId = "ai-daily-app";

  try {
    // A. 从数据库读取该邮箱对应的验证码
    const codeRef = db.collection(`artifacts/${appId}/public/data/verification_codes`).doc(email);
    const doc = await codeRef.get();

    if (!doc.exists) {
      return res.status(400).json({ error: '验证码不存在，请重新发送' });
    }

    const data = doc.data();

    // B. 校验逻辑：验证码是否一致 && 是否过期
    if (data.code !== code) {
      return res.status(400).json({ error: '验证码错误' });
    }

    if (Date.now() > data.expiresAt) {
      return res.status(400).json({ error: '验证码已过期' });
    }

    // C. 校验成功：将用户加入订阅者名单 (subscribers)
    const subRef = db.collection(`artifacts/${appId}/public/data/subscribers`).doc(email);
    await subRef.set({
      email: email,
      active: true,
      source: "web_signup",
      created_at: new Date().toISOString()
    });

    // D. 清理：删除已经使用过的验证码
    await codeRef.delete();

    return res.status(200).json({ success: true, message: '订阅成功' });
  } catch (err) {
    console.error('校验失败:', err);
    return res.status(500).json({ error: '服务器内部错误，请稍后再试' });
  }
}
