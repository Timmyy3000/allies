import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import PrivacyPage, { metadata as privacyMetadata } from "./privacy/page";
import TermsPage, { metadata as termsMetadata } from "./terms/page";

describe("legal pages", () => {
  it("renders a public privacy policy", () => {
    const html = renderToStaticMarkup(<PrivacyPage />);

    expect(html).toContain('data-testid="legal-page-privacy"');
    expect(html).toContain("Privacy Policy");
    expect(html).toContain("Google sign-in");
    expect(html).toContain("Cookies, sessions, and analytics");
    expect(html).toContain("Last updated: September 2, 2026");
    expect(html).toContain("inbox@yourallies.io");
  });

  it("renders public terms without promising unshipped features", () => {
    const html = renderToStaticMarkup(<TermsPage />);

    expect(html).toContain('data-testid="legal-page-terms"');
    expect(html).toContain("Terms of Service");
    expect(html).toContain("AI features");
    expect(html).toContain("Availability and changes");
    expect(html).not.toContain("billing");
    expect(html).not.toContain("team features");
    expect(html).toContain("inbox@yourallies.io");
  });

  it("publishes stable route metadata", () => {
    expect(privacyMetadata.alternates?.canonical).toBe("/privacy");
    expect(termsMetadata.alternates?.canonical).toBe("/terms");
    expect(privacyMetadata.title).toBe("Privacy Policy");
    expect(termsMetadata.title).toBe("Terms of Service");
  });
});
