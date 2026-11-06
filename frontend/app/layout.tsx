import type { Metadata } from "next";
import { Geist as SansFont, Geist_Mono as MonoFont } from "next/font/google";
import "./globals.css";

const appSans = SansFont({
  variable: "--font-app-sans",
  subsets: ["latin"],
});

const appMono = MonoFont({
  variable: "--font-app-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Chat Application",
  description: "Private and group chat with Gemini",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${appSans.variable} ${appMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
