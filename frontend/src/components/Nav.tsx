"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/news", label: "News" },
  { href: "/signals", label: "Signals" },
  { href: "/track-record", label: "Track record" },
  { href: "/paper", label: "Paper" },
  { href: "/newsletter", label: "Newsletter" },
  { href: "/lab", label: "Edge Lab" },
  { href: "/backtest", label: "Backtest" },
  { href: "/learn", label: "Learn" },
  { href: "/research", label: "Research" },
];

/** True when `path` is `href` or below it (segment-aware: /research does not match /researchers). */
function under(path: string, href: string): boolean {
  return path === href || path.startsWith(`${href}/`);
}

/**
 * Active tab: ticker pages belong to News; /research/paper highlights Research (not Paper, which is /paper);
 * the landing page `/` highlights no tab (the brand link is the way home).
 */
export function isActive(path: string, href: string): boolean {
  if (href === "/news") return under(path, "/news") || under(path, "/ticker");
  return under(path, href);
}

export default function Nav() {
  const path = usePathname() ?? "/";
  return (
    <header className="nav">
      <Link href="/" className="brand" aria-current={path === "/" ? "page" : undefined}>
        After<span>file</span>
      </Link>
      <nav aria-label="Main">
        {TABS.map((t) => {
          const on = isActive(path, t.href);
          return (
            <Link key={t.href} href={t.href} className={on ? "tab active" : "tab"} aria-current={on ? "page" : undefined}>
              {t.label}
            </Link>
          );
        })}
      </nav>
      <span className="nav-note">Runs locally · research only · not financial advice</span>
    </header>
  );
}
