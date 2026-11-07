type FeedStream = Pick<EventSource, "onopen" | "onerror" | "addEventListener" | "close">;

/** Wire a stream with cleanup guards, including failures before its first connection. */
export function subscribeToFeed(
  stream: FeedStream,
  onLive: (live: boolean) => void,
  onUpdate: () => void,
) {
  let active = true;
  let opened = false;
  let disconnected = false;
  onLive(false);
  stream.onopen = () => {
    if (!active) return;
    onLive(true);
    if (opened || disconnected) onUpdate();
    opened = true;
    disconnected = false;
  };
  stream.onerror = () => {
    if (!active) return;
    disconnected = true;
    onLive(false);
  };
  const updated = () => { if (active) onUpdate(); };
  stream.addEventListener("article", updated);
  stream.addEventListener("article_updated", updated);
  return () => {
    active = false;
    stream.close();
  };
}
