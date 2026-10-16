"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "News" },
  { href: "/signals", label: "Signals" },
  { href: "/track-record", label: "Track record" },
  { href: "/lab", label: "Edge Lab" },
  { href: "/backtest", label: "Backtest" },
  { href: "/research", label: "Research" },
  { href: "/trading", label: "Trading" },
];

export default function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" || path.startsWith("/ticker") : path.startsWith(href));
  return (
    <header className="nav">
      <Link href="/" className="brand">
        Quant<span>Desk</span>
      </Link>
      <nav>
        {TABS.map((t) => (
          <Link key={t.href} href={t.href} className={active(t.href) ? "tab active" : "tab"}>
            {t.label}
          </Link>
        ))}
      </nav>
      <span className="nav-note">Research only · not financial advice</span>
    </header>
  );
}
