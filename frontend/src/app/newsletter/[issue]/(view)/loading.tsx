export default function Loading() {
  return (
    <main className="page wide nl" aria-busy="true" aria-label="Loading newsletter issue">
      <span className="back">← Newsletter archive</span>
      <div className="skel skel-title" />
      <div className="skel skel-line" style={{ width: 320 }} />
      <section className="panel skel-panel">
        <div className="skel skel-line" style={{ width: 160 }} />
        <div className="skel skel-block" />
      </section>
      <section className="panel skel-panel">
        <div className="skel skel-line" style={{ width: 140 }} />
        <div className="skel skel-block" />
      </section>
    </main>
  );
}
