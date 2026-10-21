"use client";

import { useEffect, useState, type CSSProperties } from "react";

import { api, type VaultNotes as VaultNotesData } from "@/lib/api";

// Styles are inline because this folder has no CSS module; colors come from the globals.css tokens.
const list: CSSProperties = { listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10 };
const item: CSSProperties = { borderTop: "1px solid var(--border)", paddingTop: 8, display: "grid", gap: 2 };
const excerptStyle: CSSProperties = { margin: "4px 0 0", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13 };
const pathStyle: CSSProperties = { overflowWrap: "anywhere" };
const example: CSSProperties = {
  margin: "6px 0",
  padding: "8px 10px",
  background: "var(--panel-2)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  fontSize: 12,
  overflowX: "auto",
};

function updatedLabel(iso: string | null): string | null {
  if (!iso) return null;
  const opts: Intl.DateTimeFormatOptions = { year: "numeric", month: "short", day: "numeric" };
  // The backend usually sends a date-only "YYYY-MM-DD" (frontmatter date or file mtime date).
  // JS parses that as midnight UTC, so format it in UTC to avoid showing the previous day
  // for viewers west of UTC. Full timestamps keep local-time formatting.
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", dateOnly ? { ...opts, timeZone: "UTC" } : opts);
}

function EmptyState({ symbol }: { symbol: string }) {
  const snippet = `---\ntype: thesis\nticker: ${symbol}\n---\n`;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="muted small">
      <p>
        No notes for {symbol} yet. Create a note anywhere in your vault outside the <code>Undertow/</code> folder with this frontmatter, or tag it{" "}
        <code>undertow/thesis</code> (plus <code>ticker: {symbol}</code>):
      </p>
      <pre style={example}>
        <code>{snippet}</code>
      </pre>
      <button type="button" className="btn" onClick={copy}>
        {copied ? "Copied" : "Copy example"}
      </button>
      <p>It appears here after the next read of the vault (about a minute).</p>
    </div>
  );
}

/** Read-only list of the user's own Obsidian thesis notes for one ticker. Excerpts render as plain text. */
export default function VaultNotes({ symbol }: { symbol: string }) {
  const [data, setData] = useState<VaultNotesData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    setData(null);
    api
      .vaultNotes(symbol)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return (
    <section className="panel" aria-labelledby="vault-notes-title">
      <h2 id="vault-notes-title">Your notes (Obsidian)</h2>
      {error && <p className="muted small">Notes unavailable right now.</p>}
      {!error && !data && <p className="muted small">Loading notes…</p>}
      {data && !data.enabled && <p className="muted small">Vault integration is off (VAULT_ENABLED).</p>}
      {data && data.enabled && data.notes.length === 0 && <EmptyState symbol={symbol} />}
      {data && data.enabled && data.notes.length > 0 && (
        <ul style={list}>
          {data.notes.map((n) => {
            const updated = updatedLabel(n.updated);
            return (
              <li key={n.path} style={item}>
                <strong>{n.title}</strong>
                <span className="muted small" style={pathStyle}>
                  {updated && (
                    <>
                      <time dateTime={n.updated ?? undefined}>Updated {updated}</time>
                      {" · "}
                    </>
                  )}
                  <code>{n.path}</code>
                </span>
                {n.excerpt && <p style={excerptStyle}>{n.excerpt}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
