import { NextRequest, NextResponse } from 'next/server';

/**
 * Proxy AI image generation requests to backend.
 * This API route is needed because Next.js rewrites have a 1MB body size limit,
 * and base64 image payloads can exceed that.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const auth = req.headers.get('authorization');
    if (!auth) {
      return NextResponse.json(
        { code: 401, message: '请先登录后再生成图片', data: null },
        { status: 401 }
      );
    }

    const backendOrigin = process.env.BACKEND_ORIGIN || 'http://localhost:8000';
    const baseUrl = `${backendOrigin.replace(/\/$/, '')}/api/v1`;
    const res = await fetch(`${baseUrl}/ai-image/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth ? { Authorization: auth } : {}),
      },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { code: 500, message: '代理请求失败', data: null },
      { status: 500 }
    );
  }
}
