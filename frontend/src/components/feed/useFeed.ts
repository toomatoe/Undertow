"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { api, type ArticleFilters } from "@/lib/api";
import { FeedController, type FetchPage } from "./controller";
import { subscribeToFeed } from "./stream";

export function useFeed(fetchPage: FetchPage, filters: ArticleFilters) {
  const controller = useMemo(() => new FeedController(fetchPage, filters), [fetchPage, filters]);
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot, controller.snapshot);
  const [live, setLive] = useState(false);

  useEffect(() => {
    void controller.start();
    return controller.dispose;
  }, [controller]);

  useEffect(() => {
    const stream = new EventSource(api.streamUrl);
    // Coalesce bursts into one notice. Never discard paginated rows automatically.
    return subscribeToFeed(stream, setLive, controller.markUpdated);
  }, [controller]);

  return { ...state, live, refresh: controller.refresh, loadMore: controller.loadMore, retry: controller.retry };
}
