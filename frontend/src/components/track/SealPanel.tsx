"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { API_BASE, api, type ChainVerify, type JournalChain } from "@/lib/api";

import { formatDay, formatFiled } from "./parts";
import styles from "./SealPanel.module.css";

/**
 * Tamper-evident seal of the journal (backend/app/journal/digest.py): chain head from /api/journal/chain,
 * verification status from /api/journal/verify, and how anyone can recompute a day's hash.
 */
export default function SealPanel() {
  const [chain, setChain] = useState<JournalChain | null>(null);
  const [verify, setVerify] = useState<ChainVerify | null>(null);
  const [chainError, setChainError] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.journalChain().then((c) => live && setChain(c)).catch((e) => live && setChainError(String(e?.message ?? e)));
    api.journalVerify().then((v) => live && setVerify(v)).catch((e) => live && setVerifyError(String(e?.message ?? e)));
    return () => {
      live = false;
    };
  }, []);

  const head = chain?.head ?? (verify?.head_hash && verify.head_day ? { head_hash: verify.head_hash, head_day: verify.head_day, days: verify.days } : null);
  const late = verify ? verify.late_days.length : chain ? chain.lines.filter((l) => l.sealed_late).length : null;
  const exampleDay = head?.head_day ?? "YYYY-MM-DD";

  let status: { cls: string; text: string; detail?: string };
  if (verifyError) status = { cls: "muted", text: "Verification unavailable", detail: verifyError };
  else if (!verify) status = { cls: "muted", text: "Checking…" };
  else if (verify.days === 0) status = { cls: "muted", text: "Nothing sealed yet", detail: "The first day is sealed after the first full UTC day of journal entries." };
  else if (verify.ok) status = { cls: styles.ok, text: `✓ Verified: all ${verify.days} sealed days match the database` };
  else if (verify.first_mismatch)
    status = {
      cls: styles.bad,
      text: `✗ Mismatch on ${verify.first_mismatch.day}`,
      detail: `Stored hash ${verify.first_mismatch.expected.slice(0, 12)}… but the entries now hash to ${verify.first_mismatch.actual.slice(0, 12)}…`,
    };
  else status = { cls: styles.bad, text: "✗ Chain file broken", detail: verify.broken_link?.reason ?? "unknown reason" };

  return (
    <section className="panel" aria-labelledby="seal-heading">
      <h2 id="seal-heading">Tamper-evident seal</h2>
      <p className="small">
        Every completed UTC day, the record-time fields of that day&apos;s journal entries are hashed (SHA-256) together with the previous
        day&apos;s hash. Editing or deleting any sealed entry later changes every hash after it. The head hash is also printed in each weekly
        newsletter, so an old issue proves what the record looked like then.
      </p>
      {chainError && !head ? (
        <p className="muted small">Couldn&apos;t load the chain: {chainError}</p>
      ) : (
        <div className="tiles bt-tiles">
          <div className="tile">
            <span className="muted small">Chain head</span>
            <strong title={head?.head_hash}>{head ? `${head.head_hash.slice(0, 12)}…` : "—"}</strong>
            <span className="muted small">SHA-256, first 12 characters</span>
          </div>
          <div className="tile">
            <span className="muted small">Sealed through</span>
            <strong>{head ? formatDay(head.head_day) : "—"}</strong>
            <span className="muted small">UTC day</span>
          </div>
          <div className="tile">
            <span className="muted small">Days sealed</span>
            <strong>{head?.days ?? 0}</strong>
            <span className="muted small">one hash per day</span>
          </div>
          <div className="tile">
            <span className="muted small">Sealed late</span>
            <strong>{late ?? "—"}</strong>
            <span className="muted small">sealed more than 2 days after the day</span>
          </div>
        </div>
      )}
      <p className="small" role="status">
        <strong className={status.cls}>{status.text}</strong>
        {status.detail && <span className="muted"> · {status.detail}</span>}
        {verify && verify.days > 0 && <span className="muted"> · checked {formatFiled(verify.checked_at)} (cached up to 10 minutes)</span>}
      </p>
      {chain?.error && <p className="error small">Chain file problem: {chain.error}</p>}

      <details className={styles.details}>
        <summary className="small">Verify it yourself</summary>
        <ol className={`small ${styles.steps}`}>
          <li>
            Download one sealed day: <code>{`${API_BASE}/api/journal/chain/${exampleDay}`}</code>. It contains the day, the previous
            day&apos;s hash, the stored hash and the entries.
          </li>
          <li>
            Rebuild the payload <code>{`{"day": ..., "prev": prev_hash, "entries": [...]}`}</code> and serialize it as compact JSON with
            sorted keys and ASCII escaping.
          </li>
          <li>Take its SHA-256. It must equal the stored hash, and the stored prev_hash must equal the previous day&apos;s hash.</li>
        </ol>
        <pre className={styles.code}>{`import hashlib, json, urllib.request
d = json.load(urllib.request.urlopen("${API_BASE}/api/journal/chain/${exampleDay}"))
payload = {"day": d["day"], "prev": d["prev_hash"], "entries": d["entries"]}
blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
print(hashlib.sha256(blob.encode("ascii")).hexdigest() == d["hash"])`}</pre>
        <p className="muted small">
          Only record-time fields are sealed (ticker, form, signals, filing and record times, borrow snapshot). Prices and results are filled in
          later by a deterministic computation and are not part of the hash. <Link href="/learn">Learn</Link> how the rest of the evidence is
          built.
        </p>
      </details>
    </section>
  );
}
