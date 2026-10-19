import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactElement } from "react";

import BaselinesLesson from "@/components/learn/lessons/BaselinesLesson";
import ClusteredErrorsLesson from "@/components/learn/lessons/ClusteredErrorsLesson";
import EventStudyLesson from "@/components/learn/lessons/EventStudyLesson";
import MultipleTestingLesson from "@/components/learn/lessons/MultipleTestingLesson";
import SharpeDsrLesson from "@/components/learn/lessons/SharpeDsrLesson";
import SurvivorshipLesson from "@/components/learn/lessons/SurvivorshipLesson";
import { getLesson, LESSON_SLUGS, lessonDocTitle, lessonPath, type Lesson } from "@/lib/learn/lessons";
import { SITE_URL } from "@/lib/server-api";

// Server-rendered for crawlers (metadata, canonical, JSON-LD, prose); do not convert to a useEffect client page.
// Live numbers come from server-api (cached 1 h); if the API is down the lesson renders with a note.
export const revalidate = 3600;
// Only the registry's slugs exist: any other /learn/<x> is a real HTTP 404 before anything streams.
export const dynamicParams = false;

export function generateStaticParams() {
  return LESSON_SLUGS.map((slug) => ({ slug }));
}

type Params = Promise<{ slug: string }>;

const BODIES: Record<string, (p: { lesson: Lesson }) => Promise<ReactElement>> = {
  "event-study": EventStudyLesson,
  baselines: BaselinesLesson,
  "multiple-testing": MultipleTestingLesson,
  "clustered-errors": ClusteredErrorsLesson,
  "survivorship-bias": SurvivorshipLesson,
  "sharpe-dsr-backtest-pitfalls": SharpeDsrLesson,
};

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const lesson = getLesson((await params).slug);
  if (!lesson) notFound();
  const title = lessonDocTitle(lesson);
  const path = lessonPath(lesson.slug);
  return {
    metadataBase: new URL(SITE_URL),
    title: { absolute: title },
    description: lesson.description,
    keywords: lesson.concepts,
    alternates: { canonical: path },
    openGraph: { type: "article", siteName: "QuantDesk", url: path, title, description: lesson.description },
    twitter: { card: "summary", title, description: lesson.description },
  };
}

export default async function LessonPage({ params }: { params: Params }) {
  const { slug } = await params;
  const lesson = getLesson(slug);
  const Body = BODIES[slug];
  if (!lesson || !Body) notFound();
  return <Body lesson={lesson} />;
}
