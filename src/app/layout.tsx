import type { Metadata } from "next";
import type { ReactElement, ReactNode } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap"
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap"
});

export const metadata: Metadata = {
  title: "Discord Sentinel | Moderation Dashboard",
  description:
    "A futuristic Discord moderation and utility bot dashboard for welcome, auto-role, mass-role, command routing, and server overview.",
  openGraph: {
    title: "Discord Sentinel | Moderation Dashboard",
    description: "Welcome automation, role routing, moderation tools, and command controls.",
    type: "website"
  }
};

export const viewport = {
  width: "device-width",
  initialScale: 1
};

export default function RootLayout({
  children
}: Readonly<{
  children: ReactNode;
}>): ReactElement {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
