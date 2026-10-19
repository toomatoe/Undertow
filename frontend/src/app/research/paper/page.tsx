import { readFile } from "node:fs/promises";
import path from "node:path";

import type { Metadata } from "next";
import Link from "next/link";
import { cache } from "react";

import Markdown, { headings, parseMarkdown, plainText } from "@/components/markdown/Markdown";
import { SITE_URL } from "@/lib/server-api";

import styles from "./paper.module.css";

// Static server component: the paper is read from disk at build time and rendered to HTML once.
// src/content/working-paper.md is a byte-identical copy of docs/paper/WORKING_PAPER.md (the frontend Docker
// build context cannot see docs/); backend/tests/test_paper_numbers.py enforces the copy and its numbers.
export const dynamic = "force-static";

const SOURCE = path.join(process.cwd(), "src", "content", "working-paper.md");
const PATH = "/research/paper";
const DESCRIPTION =
  "QuantDesk working paper: an in-sample event study of SEC filings by small US companies, a pre-registered out-of-sample replication and a pre-registered Form 4 insider-purchase study, judged after costs and borrow. Hypothetical results, not investment advice.";

const readPaper = cache(() => readFile(SOURCE, "utf8"));

function titleOf(source: string): string {
  const h1 = parseMarkdown(source).find((b) => b.type === "heading" && b.level === 1);
  return h1 && h1.type === "heading" ? plainText(h1.text) : "QuantDesk working paper";
}

export async function generateMetadata(): Promise<Metadata> {
  const title = `${titleOf(await readPaper())} · QuantDesk`;
  return {
    metadataBase: new URL(SITE_URL),
    title: { absolute: title },
    description: DESCRIPTION,
    alternates: { canonical: PATH },
    openGraph: { type: "article", siteName: "QuantDesk", url: PATH, title, description: DESCRIPTION },
    twitter: { card: "summary", title, description: DESCRIPTION },
  };
}

export default async function WorkingPaperPage() {
  const source = await readPaper();
  const toc = headings(source, [2]);

  return (
    <main className={`page ${styles.page}`}>
      <p className={styles.crumbs}>
        <Link href="/research">Research</Link> / Working paper
      </p>
      <p className={styles.notice} role="note">
        <strong>Working paper, hypothetical results, not investment advice.</strong> Event-study figures are historical, market-adjusted
        averages; net and backtest figures are hypothetical and depend on assumed costs and borrow. See the{" "}
        <Link href="/methodology">methodology</Link> and <Link href="/legal/disclaimer">disclaimer</Link>.
      </p>

      <div className={styles.layout}>
        {toc.length > 0 && (
          <nav className={styles.toc} aria-labelledby="paper-toc">
            <h2 id="paper-toc" className={styles.tocTitle}>
              Contents
            </h2>
            <ol>
              {toc.map((h) => (
                <li key={h.id}>
                  <a href={`#${h.id}`}>{h.text}</a>
                </li>
              ))}
            </ol>
          </nav>
        )}
        <article className={styles.article}>
          <Markdown source={source} />
          <p className={styles.footer}>
            Explore the underlying studies in the <Link href="/lab">Edge Lab</Link> and the strategy simulation on the{" "}
            <Link href="/backtest">Backtest</Link> page.
          </p>
        </article>
      </div>
    </main>
  );
}
