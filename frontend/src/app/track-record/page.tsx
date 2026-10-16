"use client";

import { useEffect, useMemo, useState } from "react";

import JournalTable from "@/components/track/JournalTable";
import LiveVsExpected from "@/components/track/LiveVsExpected";
import OfferingSpotlight from "@/components/track/OfferingSpotlight";
import { STATUS_INFO } from "@/components/track/parts";
import { api, type JournalPage, type JournalStatus, type JournalSummary } from "@/lib/api";

const LIMIT = 2000; // the API maximum; counts below are from what was fetched

function Tile({ name, value, hint }: { name: React.ReactNode; value: React.ReactNode; hint: React.ReactNode }) {
  return (
    <div className="tile">
      <span className="muted small">{name}</span>
      <strong>{value}</strong>
      <span className="muted small">{hint}</span>
    </div>
  );
}

const Icon = ({ s }: { s: JournalStatus }) => <span aria-hidden="true">{STATUS_INFO[s].icon} </span>;

export default function TrackRecordPage() {
  const [journal, setJournal] = useState<JournalPage | null>(null);
  const [summary, setSummary] = useState<JournalSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    api.journal({ limit: LIMIT }).then(setJournal).catch((e) => setError(String(e?.message ?? e)));
    api.journalSummary().then(setSummary).catch((e) => setSummaryError(String(e?.message ?? e)));
  }, []);

  const counts = useMemo(() => {
    const c: Record<JournalStatus, number> = { waiting: 0, open: 0, complete: 0, data_ended: 0, no_data: 0 };
    for (const e of journal?.entries ?? []) c[e.status] = (c[e.status] ?? 0) + 1;
    return c;
  }, [journal]);

  if (error) {
    return (
      <main className="page wide bt">
        <h1>Track record</h1>
        <p className="error">Couldn&apos;t load the track record: {error}</p>
        <p className="muted small">Is the API running on port 8000? If it was built before the journal existed, rebuild it with docker compose up -d --build api.</p>
      </main>
    );
  }
  if (!journal) return <main className="page wide bt muted">Loading…</main>;

  const entries = journal.entries;
  const truncated = entries.length < journal.total;

  return (
    <main className="page wide bt tr">
      <div>
        <h1>Track record</h1>
        <p className="tr-intro">
          A public, timestamped forward test of every filing signal. Each signal is recorded the moment the filing appears on EDGAR and is never
          edited afterwards. It is then priced at the same close the backtest would trade (the close after the first close the stock could be
          traded on) and compared with the small-cap index fund IWM over the next 1, 5 and 20 trading days. That shows whether the patterns
          found in past data keep working on filings nobody had seen yet.
        </p>
        <p className="muted small">
          {journal.total.toLocaleString()} signals recorded
          {journal.since && <> since {new Date(journal.since).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}</>}
          {" · "}
          <strong>Simulated tracking, no trades, not advice.</strong>
        </p>
      </div>

      <div className="tiles bt-tiles" aria-label="Journal status">
        <Tile name="Signals recorded" value={journal.total.toLocaleString()} hint={truncated ? `Counts below cover the latest ${entries.length.toLocaleString()}` : "Every one is kept"} />
        <Tile name={<><Icon s="waiting" />Waiting for entry price</>} value={counts.waiting} hint="Priced after the next close or two" />
        <Tile name={<><Icon s="open" />Open</>} value={counts.open} hint="Priced; 1, 5 and 20-day results filling in" />
        <Tile name={<><Icon s="complete" />Complete</>} value={counts.complete} hint="20-day result in" />
        <Tile name={<><Icon s="data_ended" />Data ended / no data</>} value={counts.data_ended + counts.no_data} hint="Delisted, halted or never priced" />
      </div>

      {journal.total === 0 && (
        <section className="panel">
          <h2>No signals yet</h2>
          <p className="small">
            The journal fills in automatically: every ingest cycle records new signal filings for companies with a known size, and prices are
            added once a day. Check back after the next filings arrive.
          </p>
        </section>
      )}

      <LiveVsExpected summary={summary} error={summaryError} />
      <OfferingSpotlight entries={entries} summary={summary} />
      <JournalTable entries={entries} />

      <p className="muted small tr-foot">
        Borrow fee is the yearly cost to borrow shares for a short sale, from Interactive Brokers&apos; public file on the day the signal was
        recorded (“—” means no fresh file or the stock wasn&apos;t listed). Entries backfilled when the journal launched use the first snapshot,
        taken up to 3 days after filing. Prices are adjusted daily closes; results are before trading costs and borrow fees. Research only: no
        orders are placed and nothing here is investment advice.
      </p>
    </main>
  );
}
