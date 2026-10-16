"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type NewsletterIssue, type NewsletterIssueSummary } from "@/lib/api";

import ArchiveList from "./ArchiveList";
import { issuePath, parseIssueId } from "./format";
import IssueView from "./IssueView";

function saveFile(text: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Clipboard API needs a secure context; fall back to a hidden textarea
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

/**
 * Archive sidebar + export toolbar + issue body, shared by /newsletter and /newsletter/[issue].
 * The pages fetch on the server and pass the data in, so the issue is in the initial HTML.
 * Client-only extras: "Preview this week so far" (POST, never archived), copy/download/email actions,
 * a retry when the server could not reach the API, and the legacy /newsletter?issue=<id> redirect.
 */
export default function NewsletterWorkspace({
  issues: serverIssues,
  issue: serverIssue,
  legacyQuery = false,
}: {
  /** Archive list from the server; null when the API was unreachable (retried in the browser). */
  issues: NewsletterIssueSummary[] | null;
  /** Issue rendered by default (the page's issue, or the latest one on /newsletter). */
  issue: NewsletterIssue | null;
  /** /newsletter only: redirect old ?issue=<id> links to the issue page. */
  legacyQuery?: boolean;
}) {
  const router = useRouter();
  const [issues, setIssues] = useState(serverIssues);
  const [current, setCurrent] = useState(serverIssue);
  const [preview, setPreview] = useState<NewsletterIssue | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  // Old links (/newsletter?issue=2026-W41) point at the issue page now.
  useEffect(() => {
    if (!legacyQuery) return;
    const wanted = parseIssueId(new URLSearchParams(window.location.search).get("issue") ?? "");
    if (wanted) router.replace(issuePath(wanted));
  }, [legacyQuery, router]);

  // Server could not reach the API (or the page was cached while it was down): try again from the browser.
  useEffect(() => {
    const needLatest = !serverIssue;
    if (serverIssues !== null && !(needLatest && serverIssues[0])) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      const list = serverIssues ?? (await api.newsletterIssues());
      if (cancelled) return;
      setIssues(list);
      if (needLatest && list[0]) {
        const latest = await api.newsletterIssue(list[0].id);
        if (!cancelled) setCurrent(latest);
      }
    })()
      .catch((e) => {
        if (cancelled) return;
        setIssues((prev) => prev ?? []);
        setError(String(e?.message ?? e));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [serverIssues, serverIssue]);

  const loadPreview = () => {
    setShowPreview(true);
    setPreviewLoading(true);
    setError(null);
    api
      .newsletterPreview()
      .then(setPreview)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setPreviewLoading(false));
  };

  const note = (msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 2500);
  };

  const shown = showPreview ? preview : current;
  const isPreview = showPreview && !!preview;
  const fileBase = shown ? `small-cap-filing-radar-${isPreview ? `${shown.id}-preview` : shown.id}` : "";
  const busy = !shown || loading || (showPreview && previewLoading);

  const copyMarkdown = async () => {
    if (!shown) return;
    await copyText(shown.markdown);
    note("Markdown copied");
  };

  const downloadHtml = async () => {
    if (!shown) return;
    try {
      const html = isPreview ? shown.html ?? "" : await api.newsletterHtml(shown.id);
      saveFile(html, `${fileBase}.html`, "text/html;charset=utf-8");
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  };

  const openEmail = () => {
    if (!shown) return;
    if (isPreview) {
      const url = URL.createObjectURL(new Blob([shown.html ?? ""], { type: "text/html;charset=utf-8" }));
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } else {
      window.open(api.newsletterHtmlUrl(shown.id), "_blank", "noopener");
    }
  };

  return (
    <div className="nl-layout">
      <ArchiveList
        issues={issues ?? []}
        activeId={current?.id ?? null}
        previewActive={showPreview}
        onNavigate={(id) => {
          // Same page: the link is a no-op, so leave the preview here.
          if (id === current?.id) setShowPreview(false);
        }}
        onPreview={loadPreview}
        previewLoading={previewLoading}
      />

      <div className="nl-main">
        <div className="nl-actions" role="toolbar" aria-label="Export">
          <button type="button" onClick={copyMarkdown} disabled={busy}>
            Copy Markdown
          </button>
          <button type="button" onClick={downloadHtml} disabled={busy}>
            Download HTML
          </button>
          <button type="button" onClick={openEmail} disabled={busy}>
            Open email version
          </button>
          {showPreview && current && (
            <button type="button" onClick={() => setShowPreview(false)}>
              Back to {current.id}
            </button>
          )}
          {flash && (
            <span className="muted small" role="status">
              {flash}
            </span>
          )}
        </div>

        {error && (
          <div className="panel">
            <p className="error">Couldn&apos;t load the newsletter: {error}</p>
            <p className="muted small">Is the API running on port 8000? If it was built before the newsletter existed, rebuild it with docker compose up -d --build api.</p>
          </div>
        )}
        {loading || (showPreview && previewLoading && !preview) ? (
          <p className="muted">Loading…</p>
        ) : shown ? (
          <IssueView issue={shown} />
        ) : (
          !error && (
            <div className="panel">
              <h2>No issues yet</h2>
              <p className="small">
                Issues are built automatically on Monday for the week that just ended. Use “Preview this week so far” to see what this week&apos;s issue looks
                like right now.
              </p>
            </div>
          )
        )}
      </div>
    </div>
  );
}
