import type { Metadata } from "next";
import { LegalPage } from "../../components/legal-page";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "The terms for using the Allies preview and product.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <LegalPage
      kind="terms"
      title="Terms of Service"
      intro="These terms cover your use of the Allies website, preview, waitlist, and related early product experiences."
      sections={[
        {
          heading: "Using Allies",
          paragraphs: [
            "Allies is an early product for creating personal helpers around what matters to you. Some parts of the product may be previews, experiments, or unavailable at different times. You may use Allies only in a lawful way and in line with these terms.",
          ],
        },
        {
          heading: "Your responsibilities",
          paragraphs: [
            "Keep information you use to access Allies accurate and keep your account or sign-in details secure. Do not misuse the service, interfere with its operation, attempt to access other users' information, or use Allies to break the law or harm someone.",
          ],
        },
        {
          heading: "Content and AI features",
          paragraphs: [
            "You are responsible for the information and instructions you provide to Allies. Any suggestions, summaries, or other output from an Ally are provided for general assistance and may be incomplete or incorrect. Review important outputs yourself and do not rely on Allies as a substitute for professional advice or your own judgment.",
          ],
        },
        {
          heading: "Third-party services",
          paragraphs: [
            "Allies may rely on third-party services for hosting, authentication, analytics, communications, or other product operations. Those services have their own terms and policies, and their availability may affect parts of Allies.",
          ],
        },
        {
          heading: "Availability and changes",
          paragraphs: [
            "We are building Allies at an early stage, so the service may change, be interrupted, or be unavailable. We may limit or suspend access when needed to protect the service, users, or others, or when these terms are violated.",
            "We may update these terms as the product develops. The updated version will be posted on this page with a new date. If a change is important, we will make a reasonable effort to draw attention to it.",
          ],
        },
      ]}
    />
  );
}
