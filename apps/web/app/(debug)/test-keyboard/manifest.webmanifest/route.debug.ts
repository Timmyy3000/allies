export function GET() {
  if (process.env.NODE_ENV !== "development") return new Response(null, { status: 404 });
  return Response.json({
    id: "/test-keyboard",
    name: "Allies keyboard lab",
    short_name: "Keyboard lab",
    start_url: "/test-keyboard",
    scope: "/test-keyboard",
    display: "standalone",
    background_color: "#111111",
    theme_color: "#111111",
    icons: [
      { src: "/pwa/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/pwa/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  }, { headers: { "Content-Type": "application/manifest+json", "Cache-Control": "no-store" } });
}
