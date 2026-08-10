import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const metadataBase = new URL(`${protocol}://${host}`);

  return {
    metadataBase,
    title: "套利监测看板",
    description: "跨品种比价、价差与历史分位监测看板，每日 20:00 更新。",
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
    openGraph: {
      title: "套利监测看板",
      description: "跟踪跨品种比价、价差与历史分位，每日 20:00 更新。",
      images: [{ url: "/og.png", width: 1745, height: 909, alt: "套利监测看板" }],
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: "套利监测看板",
      description: "跟踪跨品种比价、价差与历史分位，每日 20:00 更新。",
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
