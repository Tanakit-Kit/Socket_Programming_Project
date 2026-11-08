import type { Metadata } from "next";
import { Noto_Sans as SansFont, Geist_Mono as MonoFont, Noto_Sans_Thai as ThaiSansFont } from "next/font/google";
import "./globals.css";

const appThaiSans = ThaiSansFont({
  variable: "--font-app-thai-sans",
});

const appSans = SansFont({
  variable: "--font-app-sans",
  subsets: ["latin"],
});

const appMono = MonoFont({
  variable: "--font-app-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ช่องClaude Chat",
  description: "Private and group chat with Gemini",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${appSans.variable} ${appThaiSans.variable} ${appMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <style
          dangerouslySetInnerHTML={{
            __html: `
              /* Custom scrollbar - สีเทาเข้ม */
              ::-webkit-scrollbar {
                width: 8px;
                height: 8px;
              }
              ::-webkit-scrollbar-track {
                background: #f1f5f9;
              }
              ::-webkit-scrollbar-thumb {
                background: #94a3b8;
                border-radius: 4px;
              }
              ::-webkit-scrollbar-thumb:hover {
                background: #64748b;
              }
              [data-theme="dark"] ::-webkit-scrollbar-track {
                background: #0f172a;
              }
              [data-theme="dark"] ::-webkit-scrollbar-thumb {
                background: #334155;
              }
              [data-theme="dark"] ::-webkit-scrollbar-thumb:hover {
                background: #475569;
              }
            `
          }}
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var saved = localStorage.getItem('chat-theme');
                  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  var theme = saved || ( prefersDark ? 'dark' : 'light' );
                  document.documentElement.dataset.theme = theme;
                } catch (e) {}
              })();
            `
          }}  
        />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
