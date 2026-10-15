export default function TradingPage() {
  return (
    <main className="page prose">
      <h1>Trading</h1>
      <p className="muted">Not built yet. Paper trading only when it is.</p>
      <section className="panel">
        <h2>Build order</h2>
        <ol>
          <li>Historical data in Parquet + DuckDB, walk-forward backtest runner, cost model, log of every variant tested.</li>
          <li>First strategy: diversified trend following on daily bars (longest evidence record, latency irrelevant).</li>
          <li>Engine on Nautilus Trader so backtest and live share the same strategy and risk code.</li>
          <li>Risk gate: max order/position size, daily loss stop, price bands, order-rate limit, kill switch.</li>
          <li>Alpaca paper account, broker reconciliation, alerts. At least 3 months before any real money.</li>
        </ol>
      </section>
    </main>
  );
}
