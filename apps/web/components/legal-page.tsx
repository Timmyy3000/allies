import Link from "next/link";

type LegalSection = {
  heading: string;
  paragraphs: string[];
};

export function LegalPage({
  kind,
  title,
  intro,
  sections,
}: {
  kind: "privacy" | "terms";
  title: string;
  intro: string;
  sections: LegalSection[];
}) {
  return (
    <main className="legal-page" data-testid={`legal-page-${kind}`}>
      <article className="legal-page__article">
        <nav className="legal-page__nav" aria-label="Legal">
          <Link href="/">Allies</Link>
          <span aria-hidden="true">/</span>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
        </nav>
        <header className="legal-page__header">
          <p className="legal-page__eyebrow">Allies</p>
          <h1>{title}</h1>
          <p className="legal-page__intro">{intro}</p>
          <p className="legal-page__date">Last updated: September 2, 2026</p>
        </header>
        <div className="legal-page__content">
          {sections.map((section) => (
            <section key={section.heading}>
              <h2>{section.heading}</h2>
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </section>
          ))}
          <section>
            <h2>Contact</h2>
            <p>
              Questions about this page or Allies? Email <a href="mailto:inbox@yourallies.io">
                inbox@yourallies.io
              </a>{" "}
              or visit <Link href="/">yourallies.io</Link>.
            </p>
          </section>
        </div>
      </article>
    </main>
  );
}
