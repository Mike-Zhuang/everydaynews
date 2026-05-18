import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "今日新闻工作台",
  description: "按关键词抓取、总结并归档媒体清单中的新闻。"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
