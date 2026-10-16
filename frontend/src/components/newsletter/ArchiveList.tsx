"use client";

import Link from "next/link";

import type { NewsletterIssueSummary } from "@/lib/api";

import styles from "./ArchiveList.module.css";
import { issuePath, weekLabel } from "./format";

/**
 * Archive sidebar. Each issue is a real link to its server-rendered page (/newsletter/<id>), so
 * crawlers can follow it; "Preview this week so far" stays an in-place client action.
 */
export default function ArchiveList({
  issues,
  activeId,
  previewActive,
  onNavigate,
  onPreview,
  previewLoading,
}: {
  issues: NewsletterIssueSummary[];
  /** Issue whose page is shown (highlighted unless the preview is on screen). */
  activeId: string | null;
  previewActive: boolean;
  /** Called when an issue link is clicked (lets the parent drop the preview when the link is the current page). */
  onNavigate: (id: string) => void;
  onPreview: () => void;
  previewLoading: boolean;
}) {
  return (
    <nav className="panel nl-archive" aria-label="Newsletter archive">
      <h2>Archive</h2>
      <button type="button" className={previewActive ? "nl-preview-btn active" : "nl-preview-btn"} onClick={onPreview} disabled={previewLoading}>
        {previewLoading ? "Building preview…" : "Preview this week so far"}
      </button>
      {issues.length === 0 ? (
        <p className="muted small">No issues yet. The first one is built automatically after the first full week (on Monday).</p>
      ) : (
        <ul className="nl-archive-list">
          {issues.map((i) => {
            const active = !previewActive && activeId === i.id;
            return (
              <li key={i.id}>
                <Link
                  href={issuePath(i.id)}
                  className={`nl-archive-item ${styles.item}${active ? " active" : ""}`}
                  onClick={() => onNavigate(i.id)}
                  aria-current={active ? "page" : undefined}
                >
                  <strong>{weekLabel(i)}</strong>
                  <span className="muted small">
                    {i.id} · {i.headline.signal_filings} filings · {i.headline.by_severity["3"]} high
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
