import { redirect } from "next/navigation";

/** The old "Trading (planned)" page is gone: the hypothetical paper portfolio replaced it. */
export default function TradingPage() {
  redirect("/paper");
}
