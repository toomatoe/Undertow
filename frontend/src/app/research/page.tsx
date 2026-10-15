export default function ResearchPage() {
  return (
    <main className="page prose">
      <h1>Research</h1>
      <p className="muted">Coming next: an AI research assistant over the news database.</p>
      <section className="panel">
        <h2>Planned</h2>
        <ul>
          <li>Ask questions like “what moved semis this week?” and get answers with links to the articles behind them.</li>
          <li>Read-only tools: search news, pull price history, read SEC filings, run a backtest.</li>
          <li>Writes reports. It never places orders: any signal goes through backtest and the risk gate first.</li>
          <li>Semantic search over articles (pgvector is already in the Postgres image).</li>
        </ul>
      </section>
      <section className="panel">
        <h2>Why this order</h2>
        <p>
          The feasibility research found that tools and research products have far better evidence of making money
          than retail trading bots, and an honest backtest harness is the main defence against overfitting. See{" "}
          <code>docs/FEASIBILITY.md</code>.
        </p>
      </section>
    </main>
  );
}
