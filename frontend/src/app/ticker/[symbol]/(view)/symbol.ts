// Route-param -> ticker symbol, shared by layout.tsx and page.tsx.
//
// Next 15 already percent-decodes dynamic params (/ticker/OC%47N arrives as "OCGN"),
// so the param is never decoded again here: a second decodeURIComponent throws URIError on
// /ticker/%25 (param "%") and would map /ticker/%2541 to "A". A malformed escape such as
// /ticker/%E0%A4 that Next cannot decode arrives still encoded. Anything that is not symbol-shaped
// is rejected (caller calls notFound(), no API request), so odd input is a 404, never a 500.

/** Exchange tickers and SEC share-class forms: OCGN, BRK.B, BRK-B, ABCD-WT. */
const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-]{0,11}$/;

/** Upper-cased symbol, or null when the param cannot be a ticker. */
export function parseSymbol(raw: string): string | null {
  const s = raw.trim().toUpperCase();
  return SYMBOL_RE.test(s) ? s : null;
}
