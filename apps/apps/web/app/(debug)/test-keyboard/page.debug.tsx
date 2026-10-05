import { notFound } from "next/navigation";
import { KeyboardLab } from "./keyboard-lab";

export const metadata = {
  title: "Allies keyboard test",
  manifest: "/test-keyboard/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Keyboard lab" },
  robots: { index: false, follow: false },
};

export default function KeyboardTestPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <KeyboardLab />;
}
