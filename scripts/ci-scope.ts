import { execFileSync } from "node:child_process";

export function ciScope(paths: string[], full: boolean) {
  let web = full;
  let mobile = full;
  let browsers = full;
  let motion = full;
  for (const path of paths) {
    if (path.startsWith("apps/web/")) {
      web = true;
      if (/\.(tsx|jsx|css|svg|png|woff2?)$|(?:package\.json|\.config\.[^/]+)$|\/tests\//.test(path)) browsers = true;
      if (/ally-avatar|ally-artwork|ally-motion|playwright|package\.json/.test(path)) motion = true;
    } else if (path.startsWith("apps/mobile/")) {
      mobile = true;
    } else if (!path.startsWith("docs/") && !/^[^/]+\.md$/.test(path)) {
      web = mobile = browsers = motion = true;
    }
  }
  return { web, mobile, browsers, motion };
}

if (import.meta.main) {
  const base = process.env.CI_BASE_SHA;
  let full = process.env.CI_FULL === "true" || !base || !/^[a-f0-9]{40}$/i.test(base);
  let paths: string[] = [];
  if (!full) {
    try {
      paths = execFileSync("git", ["diff", "--name-only", "-z", base!, "HEAD"], {
        encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
      }).split("\0").filter(Boolean);
    } catch {
      console.error("Unable to compare CI refs; running full validation.");
      full = true;
    }
  }
  for (const [name, value] of Object.entries(ciScope(paths, full))) {
    console.log(`${name}=${value}`);
  }
}
