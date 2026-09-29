import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { QueryProvider } from "@/providers/QueryProvider";
import { AuthProvider } from "@/providers/AuthProvider";
import LayoutBar from "@/components/LayoutBar/LayoutBar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "Билайн Бизнес — Панель управления выездными бригадами",
  description: "Интеллектуальная система планирования маршрутов и диспетчеризации сервисных инженеров",
  manifest: "/manifest.json",
};


import { ThemeProvider } from "@/providers/ThemeProvider";
import DevAccountSwitcher from "@/components/DevAccountSwitcher/DevAccountSwitcher";

export default function RootLayout({ children }) {
  return (
    <html lang="ru" data-theme="dark" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {/* Кастомный провайдер без него не сделать запросы TQ */}
        <QueryProvider>
          <AuthProvider>
            <ThemeProvider>
              {children}
              <LayoutBar />
              <DevAccountSwitcher />
            </ThemeProvider>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
