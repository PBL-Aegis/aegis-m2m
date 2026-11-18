import type { NextConfig } from "next";

// 화면은 Python 서버(agent_m2m/api.py)의 API 만 부른다. 브라우저가 보내는 /api/* 요청도 그쪽으로 넘긴다.
const API_URL = process.env.AGENT_M2M_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // 시연 화면에 개발 서버 표시(왼쪽 아래 N 아이콘)가 보이지 않게 끈다.
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
