import type { Metadata } from "next";
import { Geist, Inter } from "next/font/google";
import { notFound } from "next/navigation";

import { FontPlayground } from "./font-playground";

const inter = Inter({ subsets: ["latin"], variable: "--font-playground-inter" });
const geist = Geist({ subsets: ["latin"], variable: "--font-playground-geist" });

export const metadata: Metadata = {
  title: "Chat type playground",
  robots: { index: false, follow: false },
};

export default function TestFontPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <FontPlayground fontVariables={`${inter.variable} ${geist.variable}`} />;
}
