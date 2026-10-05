import type { Metadata } from "next";
import { LegalPage } from "../../components/legal-page";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "How Allies handles information when you use the product.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <LegalPage
      kind="privacy"
      title="Privacy Policy"
      intro="Allies helps you shape personal helpers around what matters to you. This policy explains the information we use to run the product, operate the waitlist, and support sign-in."
      sections={[
        {
          heading: "Information we collect",
          paragraphs: [
            "You may give us information when you explore the Allies preview or join the waitlist, such as your email address and the choices you make while creating an Ally. If you sign in with Google, we receive the account information needed to recognize your Allies account and keep you signed in.",
            "We also receive basic technical information needed to keep the website working, such as browser and device information and information about how the site is used.",
          ],
        },
        {
          heading: "How we use information",
          paragraphs: [
            "We use information to provide and improve Allies, maintain accounts and sessions, operate the waitlist, communicate about product availability, prevent misuse, and understand which parts of the experience are useful.",
            "We do not sell your personal information. We use information only for the purposes described here and for other purposes you ask us to support.",
          ],
        },
        {
          heading: "Google sign-in",
          paragraphs: [
            "When Google sign-in is available and you choose to use it, Google provides the account information needed to create or access your Allies account. Allies uses that information for authentication and account operation. We do not ask for access to unrelated Google services as part of ordinary sign-in.",
          ],
        },
        {
          heading: "Cookies, sessions, and analytics",
          paragraphs: [
            "Allies may use cookies or browser storage to keep the website, sign-in, and session features working. You can control cookies through your browser settings, although some features may not work correctly without them.",
            "We may use product analytics to understand page visits, clicks, and product usage. Analytics settings may change as the product develops, and any provider we use may have its own privacy policy.",
          ],
        },
        {
          heading: "Sharing and storage",
          paragraphs: [
            "We may share information with service providers that help us host the website, provide authentication, operate the waitlist, or understand product usage. Those providers may process information only to provide services to us. We may also disclose information when required by law or when needed to protect Allies, our users, or others.",
            "We keep information for as long as it is needed for the purposes described in this policy, or as required for legitimate business, safety, and legal reasons. As a young product, our retention practices will continue to mature alongside the service.",
          ],
        },
        {
          heading: "Your choices and changes",
          paragraphs: [
            "You can choose whether to join the waitlist or use Google sign-in. You can also contact us through the website with questions about information associated with your use of Allies.",
            "We may update this policy as Allies changes. When we do, we will update the date on this page. Continuing to use Allies after an update means the updated policy applies to your use of the product.",
          ],
        },
      ]}
    />
  );
}
