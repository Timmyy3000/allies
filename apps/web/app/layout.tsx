import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { Inter } from "next/font/google";
import "generative-loaders/styles.css";
import "streamdown/styles.css";
import "./globals.css";
import AppProviders from "./providers";
import { THEME_COLORS, THEME_INIT_SCRIPT } from "../lib/theme/theme";

const openRunde = localFont({
  src: [
    {
      path: "./fonts/OpenRunde-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/OpenRunde-Medium.woff2",
      weight: "500",
      style: "normal",
    },
    {
      path: "./fonts/OpenRunde-Semibold.woff2",
      weight: "600",
      style: "normal",
    },
    {
      path: "./fonts/OpenRunde-Bold.woff2",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-open-runde",
  display: "swap",
});

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://yourallies.io";
const siteTitle = "We're your allies";
const siteDescription = "Personal helpers built around what matters to you.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: siteTitle,
    template: "%s · Allies",
  },
  description: siteDescription,
  applicationName: "allies",
  appleWebApp: {
    capable: true,
    title: "allies",
  },
  authors: [{ name: "Allies" }],
  creator: "Allies",
  publisher: "Allies",
  alternates: {
    canonical: "/",
  },
  icons: {
    icon: [{ url: "/allies-icon.svg", type: "image/svg+xml" }],
    shortcut: ["/allies-icon.svg"],
    apple: [{ url: "/pwa/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "/",
    siteName: "Allies",
    title: siteTitle,
    description: siteDescription,
    images: [
      {
        url: "/og-image.png",
        width: 2048,
        height: 1024,
        alt: siteTitle,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
    images: ["/og-image.png"],
  },
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLORS.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLORS.dark },
  ],
  colorScheme: "light dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${openRunde.variable} ${inter.variable} ${openRunde.className} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
