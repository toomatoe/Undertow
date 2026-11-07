import type { Article, ArticleFilters, ArticlePage } from "@/lib/api";

export interface FeedState {
  items: Article[];
  nextBefore: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  failedAction: "refresh" | "more";
  pending: boolean;
}

export type FetchPage = (filters: ArticleFilters) => Promise<ArticlePage>;
const unique = (items: Article[]) => {
  const seen = new Set<number>();
  return items.filter((item) => !seen.has(item.id) && !!seen.add(item.id));
};

/** Owns one filter selection. Request generations invalidate replaced and disposed work. */
export class FeedController {
  private state: FeedState = { items: [], nextBefore: null, loading: true, loadingMore: false, error: null, failedAction: "refresh", pending: false };
  private listeners = new Set<() => void>();
  private generation = 0;
  private revision = 0;
  private active = true;

  constructor(private fetchPage: FetchPage, private filters: ArticleFilters) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private update(patch: Partial<FeedState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  start = () => { this.active = true; return this.refresh(); };
  dispose = () => { this.active = false; this.generation++; };
  markUpdated = () => {
    if (!this.active) return;
    this.revision++;
    if (!this.state.pending) this.update({ pending: true });
  };
  refresh = async () => {
    if (!this.active) return;
    const generation = ++this.generation;
    const revision = this.revision;
    this.update({ loading: true, loadingMore: false, error: null });
    try {
      const page = await this.fetchPage({ ...this.filters, limit: 50 });
      if (!this.active || generation !== this.generation) return;
      this.update({ items: unique(page.items), nextBefore: page.next_before, pending: this.revision !== revision });
    } catch (error) {
      if (!this.active || generation !== this.generation) return;
      this.update({ error: error instanceof Error ? error.message : String(error), failedAction: "refresh" });
    } finally {
      if (this.active && generation === this.generation) this.update({ loading: false });
    }
  };
  loadMore = async () => {
    if (!this.active || this.state.loading || this.state.loadingMore || !this.state.nextBefore) return;
    const generation = this.generation;
    this.update({ loadingMore: true, error: null });
    try {
      const page = await this.fetchPage({ ...this.filters, before: this.state.nextBefore, limit: 50 });
      if (!this.active || generation !== this.generation) return;
      this.update({ items: unique([...this.state.items, ...page.items]), nextBefore: page.next_before });
    } catch (error) {
      if (!this.active || generation !== this.generation) return;
      this.update({ error: error instanceof Error ? error.message : String(error), failedAction: "more" });
    } finally {
      if (this.active && generation === this.generation) this.update({ loadingMore: false });
    }
  };
  retry = () => this.state.failedAction === "more" ? this.loadMore() : this.refresh();
}
