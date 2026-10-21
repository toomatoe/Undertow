import type { GraphMethod } from "@/lib/api";

import styles from "./graph.module.css";

/** Collapsible method note with research credits. Plain markup, works as a server or client child. */
export default function HowItWorks({ method }: { method?: GraphMethod | null }) {
  return (
    <details className={`panel ${styles.how}`}>
      <summary>How this works</summary>
      <div>
        <p>
          The idea comes from disaster research at the University of Louisville (J.B. Speed School of Engineering), where social media
          posts written during a natural disaster are linked into a graph so that related events show up as clusters that grow over time:
        </p>
        <ul>
          <li>
            Hoang, Nguyen &amp; Nguyen,{" "}
            <a href="https://arxiv.org/abs/2408.11133" target="_blank" rel="noopener noreferrer">
              Public Health in Disaster: Emotional Health and Life Incidents Extraction during Hurricane Harvey
            </a>{" "}
            (arXiv 2408.11133).
          </li>
          <li>
            Duong, Nguyen, Levin &amp; Gary,{" "}
            <a href="https://arxiv.org/abs/2602.02601" target="_blank" rel="noopener noreferrer">
              CaST: Causal Discovery via Spatio-Temporal Graphs in Disaster Tweets
            </a>{" "}
            (arXiv 2602.02601).
          </li>
        </ul>
        <p>Undertow applies the same picture to markets. Tweets become SEC filings and news items, and:</p>
        <ul>
          <li>
            <strong>Contextual edges</strong> (solid) join items with similar text.
          </li>
          <li>
            <strong>Spatial edges</strong> (dotted) join items about the same company (its market &quot;location&quot;) or the same size bucket.
          </li>
          <li>
            <strong>Temporal edges</strong> (dashed) join items published close together in time.
          </li>
          <li>
            Each item is embedded with TF-IDF, then smoothed by averaging with its graph neighbours (a GNN-style neighbourhood step, not a
            trained graph neural network).
          </li>
          <li>Clusters come from label propagation / modularity on that graph. Small leftovers are grouped as &quot;Other&quot;.</li>
          <li>
            Cluster names are built from each cluster&apos;s most distinctive terms; when Claude is configured it may suggest a name instead
            (marked &quot;AI-named&quot;).
          </li>
          <li>Mood is the mean sentiment score from the enrichment step, over the items that have one.</li>
          <li>
            The evidence line on a cluster is the historical event-study result for its most common signal and size bucket. It is a
            hypothetical, after-the-fact statistic, not a forecast.
          </li>
        </ul>
        <p>
          <strong>Edges show association and proximity, not cause and effect.</strong> CaST performs causal discovery using labelled data;
          Undertow has no such labels, so a link only means two items are similar, about the same company, or close in time. Research and
          education only, not investment advice.
        </p>
        {method && (
          <p className="muted small">
            This build: embedding {method.embedding}; smoothing {method.smoothing}; clustering {method.clustering}; edges {method.edges};
            naming {method.naming}. {method.note}
          </p>
        )}
      </div>
    </details>
  );
}
