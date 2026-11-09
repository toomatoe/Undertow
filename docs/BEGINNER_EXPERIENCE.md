# Beginner experience: research and implementation plan

Date: 2026-11-08. Scope: help a reader with no finance or coding background complete a first research task in local Undertow.

## Evidence

Repository inspection found ten top-level tool tabs, a homepage whose primary action opened the working paper, and a Learn index leading into statistical lessons and an eight-week quant-developer curriculum. These are observed interface/content choices, not measured user failures. The owner's feedback is that the experience feels too complicated. No task analytics or beginner interviews are available; frequency and measured impact are unknown.

Published guidance consulted:

- [Nielsen Norman Group, Onboarding Tutorials vs. Contextual Help (2023)](https://www.nngroup.com/articles/onboarding-tutorials/): unsolicited tours interrupt work; optional, repeatable practice and help near the task are more appropriate. Application: a dedicated, voluntary tutorial with real choices and explanatory feedback.
- [Nielsen Norman Group, Progressive Disclosure (2006)](https://www.nngroup.com/articles/progressive-disclosure/): prioritize essential choices and make advanced detail available separately. Application: plain-language first steps before research lessons and the working paper.
- [W3C WAI, Multi-page Forms (2019)](https://www.w3.org/WAI/tutorials/forms/multi-page/): group controls logically, indicate progress, and avoid time limits. Application by analogy to a tutorial: named steps, visible progress, keyboard controls, back navigation and no timer.

The sources support design principles, not a claim that this particular tutorial improves learning. Public complaints about Undertow were not used: it is a personal local project, and unrelated product anecdotes would not establish its users' needs.

## Priorities and plan

1. High priority / high confidence in observed gap: give beginners a clear first action. Simplify the homepage introduction and link to `/tutorial.html` from Home, Learn and navigation.
2. High priority / medium confidence in benefit: teach a complete small task with three practice steps: understand a fictional filing, compare hypothetical outcomes, and recognize uncertainty. Include explanatory answer reveals, step links and a completion checklist with links into the app. Use no API or account.
3. Medium priority: preserve deeper research lessons and make their purpose clear. Avoid changing the study design, numbers, financial logic or live-data contracts.

Implementation constraint: the owner subsequently requested no JavaScript. The final tutorial is standalone HTML/CSS with native details/summary disclosures and anchor navigation; it does not track or save answers. Existing Next.js pages retain their framework, with links to the tutorial. No new TypeScript tutorial components remain.

Ownership and sequence: the tutorial builder owns `frontend/public/tutorial.html`. The integration owner owns Home, Learn index, Nav and sitemap. Docs follow integration. Correctness and content-contract reviews precede exclusive verification; only the verification owner runs the frontend build. All additions remain in existing frontend/docs graph modules.

## Acceptance and evaluation

- A beginner can find the tutorial from Home and Learn, reveal explanations for each practice answer, and navigate between the exercises and completion checklist.
- Fictional and hypothetical examples are unmistakable; averages are not forecasts, costs are explicit, and adverse outcomes remain visible.
- No JavaScript, storage, network data requests or account is required for the tutorial.
- Native keyboard controls and anchor navigation are available, with responsive layouts and matching dark/light design tokens.
- Existing research routes stay available; the tutorial works without the backend.
- Run TypeScript, lint, existing frontend tests and production build; check routes over HTTP. Browser interaction and visual verification require an available browser connection.

Next validation with a beginner: ask them to start from Home, explain what a filing signal means, compare the example with its benchmark, and find the live Signals page. Record where they hesitate and whether they mistake a past average for a prediction. This is proposed usability work, not a completed study. A broader navigation simplification should follow those observations.

## Verification outcome

Frontend tests (12), TypeScript, lint and production build passed. The initial build could not fetch existing Google Fonts under restricted network access; the permitted retry passed. Static checks confirm no tutorial scripts or event handlers and valid internal fragment links. Correctness and content reviews found no blocking issues. Browser connection was unavailable, so visual and real keyboard interaction checks remain unverified. No backend changes or study reruns were needed.
