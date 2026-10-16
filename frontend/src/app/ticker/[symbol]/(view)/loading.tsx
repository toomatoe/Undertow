export default function Loading() {
  return (
    <main className="page" aria-busy="true" aria-label="Loading ticker">
      <span className="back">← News</span>
      <div className="ticker-head">
        <div>
          <div className="skel skel-title" />
          <div className="skel skel-line" style={{ width: 260 }} />
        </div>
      </div>
      <div className="skel skel-line" />
      <div className="skel skel-line" style={{ width: "80%" }} />
      <section className="panel skel-panel">
        <div className="skel skel-line" style={{ width: 140 }} />
        <div className="skel skel-block" />
      </section>
      <section className="panel skel-panel">
        <div className="skel skel-line" style={{ width: 120 }} />
        <div className="skel skel-block" />
      </section>
    </main>
  );
}
