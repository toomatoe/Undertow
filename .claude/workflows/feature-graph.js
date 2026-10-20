export const meta = {
  name: 'feature-graph',
  description: 'Plan a goal into a dependency graph of work items, build them in parallel waves with file ownership, review, verify and critique',
  whenToUse: 'Any Afterfile feature or batch of roadmap items. args: {goal: string, context?: string, items?: [...pre-planned items], review_only?: boolean}',
  phases: [
    { title: 'Plan', detail: 'decompose the goal into work items over docs/agent-graph.json modules' },
    { title: 'Build', detail: 'one builder per item, items in a wave run in parallel' },
    { title: 'Review', detail: 'correctness + contract/content reviewers per item, fix loop' },
    { title: 'Verify', detail: 'serialized: rebuild image, full tests, type-check (one per wave)' },
    { title: 'Critic', detail: 'what is missing vs the goal' },
  ],
}

// ---- Graph engineering for the agent process ---------------------------------------
// Nodes: work items (from the planner) + one exclusive Verify node per wave + a Critic.
// Edges: item.depends_on, plus edges this script ADDS when two items' owned paths overlap
// (so two builders never edit the same file at once). Waves = topological levels.
// Shared resources (docker image build, frontend/.next, hotspot files) are only touched by
// the serialized Verify node, never by parallel builders. See docs/AGENT_PROCESS.md.

const goal = (args && args.goal) || ''
const context = (args && args.context) || ''
if (!goal && !(args && args.items)) throw new Error('feature-graph needs args.goal or args.items')

const ITEM = {
  type: 'object',
  properties: {
    id: { type: 'string', description: 'short kebab-case id' },
    title: { type: 'string' },
    task: { type: 'string', description: 'complete brief: what to build, where, how to verify, done criteria' },
    modules: { type: 'array', items: { type: 'string' }, description: 'module ids from docs/agent-graph.json' },
    owned_paths: { type: 'array', items: { type: 'string' }, description: 'exact files/dirs this item may create or edit' },
    depends_on: { type: 'array', items: { type: 'string' }, description: 'ids of items that must finish first' },
    acceptance: { type: 'array', items: { type: 'string' } },
  },
  required: ['id', 'title', 'task', 'modules', 'owned_paths', 'depends_on', 'acceptance'],
}
const PLAN = {
  type: 'object',
  properties: {
    items: { type: 'array', items: ITEM },
    notes: { type: 'string', description: 'assumptions, risks, anything that needs the user (keys, accounts, legal)' },
  },
  required: ['items', 'notes'],
}
const BUILD = {
  type: 'object',
  properties: {
    changed_files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    verified: { type: 'array', items: { type: 'string' }, description: 'commands/checks actually run, with results' },
    not_verified: { type: 'array', items: { type: 'string' } },
  },
  required: ['changed_files', 'summary', 'verified', 'not_verified'],
}
const REVIEW = {
  type: 'object',
  properties: {
    approved: { type: 'boolean' },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          file: { type: 'string' },
          problem: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'file', 'problem', 'fix'],
      },
    },
  },
  required: ['approved', 'issues'],
}
const VERIFY = {
  type: 'object',
  properties: {
    passed: { type: 'boolean' },
    checks: { type: 'array', items: { type: 'string' } },
    failures: { type: 'array', items: { type: 'object', properties: { check: { type: 'string' }, detail: { type: 'string' }, likely_item: { type: 'string' } }, required: ['check', 'detail', 'likely_item'] } },
  },
  required: ['passed', 'checks', 'failures'],
}
const CRITIC = {
  type: 'object',
  properties: {
    complete: { type: 'boolean' },
    gaps: { type: 'array', items: { type: 'string' } },
    next_items: { type: 'array', items: { type: 'string' }, description: 'suggested follow-up work items' },
  },
  required: ['complete', 'gaps', 'next_items'],
}

const RULES = `Repo rules for every agent:
- Read AGENTS.md (root), docs/agent-graph.json, and the AGENTS.md of every module you touch before editing.
- Edit ONLY your owned paths. If you need a change outside them, report it in not_verified instead of making it.
- Backend tests: run \`bash scripts/pytest.sh <test files>\` (mounts current source, safe in parallel). NEVER run \`docker compose build\`, \`docker compose up\` or \`docker compose run\`: the image build is an exclusive resource owned by the Verify step.
- Frontend: \`cd frontend && npx tsc --noEmit\` is fine. NEVER run \`next build\` (it clobbers the running dev server).
- New DB columns must be nullable (stopgap migration). Content rules in frontend/AGENTS.md apply to all user-facing text: no buy/sell language, label hypothetical results.
- Update the AGENTS.md of modules you change, and docs/agent-graph.json if you add a module (only if those paths are owned by you).
- Don't commit, don't switch branches. No secrets in code.`

// ---- Plan ----------------------------------------------------------------------------
phase('Plan')
let plan
if (args && args.items) {
  plan = { items: args.items, notes: 'pre-planned by orchestrator' }
} else {
  plan = await agent(
    `You are the planner for Afterfile. Goal: ${goal}\n${context ? `Context: ${context}\n` : ''}
Read AGENTS.md, docs/agent-graph.json, docs/PRODUCT_RESEARCH.md (roadmap) and the AGENTS.md files of relevant modules.
Decompose the goal into 1-6 work items that can be built by independent agents. Rules:
- Each item names its modules (ids from agent-graph.json) and the EXACT files/dirs it owns (owned_paths).
- Prefer items with disjoint owned_paths so they run in parallel. Hotspot files (main.py, models.py, config.py, api.ts, Nav.tsx) should be owned by one item; others that need them must depends_on it, or describe the exact small addition they need in their task.
- A docs item (README/root AGENTS.md updates) usually goes last and depends on the others.
- Each task must be a complete brief: what to build, constraints, how to verify (which tests), done criteria.
- Put anything that needs the user (API keys, accounts, payments, legal review) in notes, and design items to work without it (config-gated).`,
    { label: 'planner', phase: 'Plan', schema: PLAN },
  )
}
if (!plan || !plan.items.length) return { error: 'planner returned no items', plan }

// ---- Schedule: add ownership edges, compute waves ------------------------------------
// Normalize separators but keep a trailing "/" so "docs/" still matches SHARED_DOCS
const norm0 = (p) => p.replace(/\\/g, '/')
const items = plan.items.map((it) => ({ ...it, depends_on: [...new Set(it.depends_on || [])] }))
// Shared docs (guides several modules point at) belong to no feature item, so builders can't fix
// them. The graph always ends with a docs node that owns them and depends on everything else.
const SHARED_DOCS = ['README.md', 'AGENTS.md', '.env.example', 'docs/', 'frontend/AGENTS.md', 'backend/AGENTS.md']
if (!(args && args.review_only) && !items.some((it) => it.id === 'docs')) {
  const featureIds = items.map((it) => it.id)
  for (const it of items) it.owned_paths = it.owned_paths.filter((p) => !SHARED_DOCS.includes(norm0(p)))
  items.push({
    id: 'docs', title: 'Update shared docs for this batch', modules: ['docs', 'fe_core'], owned_paths: SHARED_DOCS, depends_on: featureIds,
    task: `Update shared documentation for the work just built (${featureIds.join(', ')}). Read git diff and each item's AGENTS.md. Update: README.md (features, API table, Done list), root AGENTS.md (directory map rows, env vars), frontend/AGENTS.md and backend/AGENTS.md (layout, pages/components, config tables), .env.example (every new env var with a comment), docs/agent-graph.json (new modules/paths, ownership), docs/AGENT_PROCESS.md if the process changed. Docs must match the code exactly.`,
    acceptance: ['every new file, route, endpoint and env var is documented', 'agent-graph.json paths cover all new files', 'no doc contradicts the code'],
  })
}
const byId = Object.fromEntries(items.map((it) => [it.id, it]))
const norm = (p) => p.replace(/\\/g, '/').replace(/\/+$/, '')
const overlaps = (a, b) => a.some((x) => b.some((y) => { const p = norm(x), q = norm(y); return p === q || p.startsWith(q + '/') || q.startsWith(p + '/') }))
const reaches = (from, to, seen = new Set()) => {
  if (from === to) return true
  if (seen.has(from)) return false
  seen.add(from)
  return (byId[from]?.depends_on || []).some((d) => reaches(d, to, seen))
}
const added = []
for (let i = 0; i < items.length; i++) {
  for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j]
    if (overlaps(a.owned_paths, b.owned_paths) && !reaches(a.id, b.id) && !reaches(b.id, a.id)) {
      b.depends_on.push(a.id)  // serialize: later item waits for the earlier one
      added.push(`${b.id} -> ${a.id}`)
    }
  }
}
if (added.length) log(`Ownership overlap: serialized ${added.join(', ')}`)
for (const it of items) it.depends_on = it.depends_on.filter((d) => byId[d])  // drop unknown ids
const level = {}
const depth = (id, stack = []) => {
  if (level[id] !== undefined) return level[id]
  if (stack.includes(id)) throw new Error(`dependency cycle: ${[...stack, id].join(' -> ')}`)
  const deps = byId[id].depends_on
  level[id] = deps.length ? 1 + Math.max(...deps.map((d) => depth(d, [...stack, id]))) : 0
  return level[id]
}
items.forEach((it) => depth(it.id))
const waves = []
items.forEach((it) => { (waves[level[it.id]] ||= []).push(it) })
log(`Graph: ${items.length} items in ${waves.length} wave(s): ${waves.map((w, i) => `W${i + 1}[${w.map((x) => x.id).join(', ')}]`).join(' ')}`)

// ---- Per-item chain: build -> review (2 lenses) -> fix loop ------------------------------
const buildPrompt = (it, extra = '') => `${RULES}

You are the builder for work item "${it.id}": ${it.title}
Owned paths (edit only these): ${it.owned_paths.join(', ')}
Modules: ${it.modules.join(', ')}
Task:
${it.task}
Acceptance criteria:
${it.acceptance.map((a) => `- ${a}`).join('\n')}
${extra}
Return what you changed and exactly what you verified (commands + results) and what you could not verify.`

const LENSES = [
  { id: 'correctness', prompt: 'Correctness and tests: does the change do what the task and acceptance criteria require? Bugs, edge cases, missing or weak tests, time zones (store UTC), migrations (new columns nullable), error handling, files edited outside owned paths. Run the module tests with scripts/pytest.sh or tsc yourself if useful.' },
  { id: 'contract', prompt: 'Contracts and content: backend schema/endpoint changes mirrored in frontend/src/lib/api.ts types; AGENTS.md updated for changed modules; user-facing text follows frontend/AGENTS.md content rules (no buy/sell/advice language, hypothetical labels); no secrets or personal data; nothing contradicts docs/agent-graph.json ownership.' },
]

async function chain(it) {
  // review_only: the work already exists (e.g. built earlier); start at the Review node
  let build = args && args.review_only
    ? { changed_files: it.owned_paths, summary: it.built_summary || 'built before this run', verified: [], not_verified: [] }
    : await agent(buildPrompt(it), { label: `build:${it.id}`, phase: 'Build', schema: BUILD })
  if (!build) return { id: it.id, status: 'build_failed' }
  let reviews = []
  for (let round = 0; round < 3; round++) {
    reviews = (await parallel(LENSES.map((l) => () => agent(
      `Review work item "${it.id}" (${it.title}) in the current working tree. Lens: ${l.prompt}
Task given to the builder:\n${it.task}\nAcceptance:\n${it.acceptance.join('\n')}
Builder's report:\n${JSON.stringify(build)}
Inspect the actual files (git diff, read them). Approve only if there are no blocker/major issues. Be specific: file, problem, fix.`,
      { label: `review:${it.id}:${l.id}${round ? `#${round + 1}` : ''}`, phase: 'Review', schema: REVIEW },
    )))).filter(Boolean)
    const blocking = reviews.flatMap((r) => r.issues.filter((x) => x.severity !== 'minor'))
    if (!blocking.length || round === 2) break
    log(`${it.id}: ${blocking.length} blocking issue(s), fix round ${round + 1}`)
    build = await agent(buildPrompt(it, `\nReviewers found these issues. Fix all of them (stay within owned paths):\n${JSON.stringify(blocking, null, 1)}`),
      { label: `fix:${it.id}#${round + 1}`, phase: 'Build', schema: BUILD }) || build
  }
  const open = reviews.flatMap((r) => r.issues.filter((x) => x.severity !== 'minor'))
  return { id: it.id, title: it.title, status: open.length ? 'needs_attention' : 'approved', build, open_issues: open,
           minor: reviews.flatMap((r) => r.issues.filter((x) => x.severity === 'minor')) }
}

// ---- Waves: items in parallel, then one exclusive Verify node ---------------------------
const results = []
const verifies = []
for (let w = 0; w < waves.length; w++) {
  phase('Build')
  const done = await pipeline(waves[w], (it) => chain(it))
  results.push(...done.filter(Boolean))

  phase('Verify')
  const changed = [...new Set(done.filter(Boolean).flatMap((r) => r.build?.changed_files || []))]
  let v = await agent(
    `You are the ONLY agent allowed to use shared resources right now (docker image build). Verify wave ${w + 1}.
Changed files: ${changed.join(', ') || '(none reported)'}
Run, in order, and report each result:
1. docker compose build -q api
2. docker compose run --rm api pytest -q   (full suite)
3. cd frontend && npx tsc --noEmit
4. docker compose up -d api, wait for http://localhost:8000/api/health, then curl 2-3 endpoints touched by this wave.
Do NOT run next build. Do not fix code: just report failures and which work item most likely caused each.`,
    { label: `verify:wave${w + 1}`, phase: 'Verify', schema: VERIFY },
  )
  if (v && !v.passed && v.failures.length) {
    const byItem = {}
    v.failures.forEach((f) => { (byItem[f.likely_item] ||= []).push(f) })
    await parallel(Object.entries(byItem).filter(([id]) => byId[id]).map(([id, fs]) => () => agent(
      buildPrompt(byId[id], `\nThe integration verify step failed. Fix these failures (owned paths only), re-run the relevant tests with scripts/pytest.sh / tsc:\n${JSON.stringify(fs, null, 1)}`),
      { label: `fix-verify:${id}`, phase: 'Build', schema: BUILD })))
    v = await agent(`Re-verify wave ${w + 1} after fixes: docker compose build -q api; docker compose run --rm api pytest -q; cd frontend && npx tsc --noEmit. Report.`,
      { label: `verify:wave${w + 1}#2`, phase: 'Verify', schema: VERIFY }) || v
  }
  verifies.push({ wave: w + 1, ...(v || { passed: false, checks: [], failures: [{ check: 'verify', detail: 'verify agent failed', likely_item: '' }] }) })
}

// ---- Critic --------------------------------------------------------------------------
phase('Critic')
const critic = await agent(
  `Goal: ${goal || '(pre-planned items)'}\nPlan notes: ${plan.notes}
Results: ${JSON.stringify(results.map((r) => ({ id: r.id, status: r.status, summary: r.build?.summary, not_verified: r.build?.not_verified, open: r.open_issues })))}
Verify: ${JSON.stringify(verifies)}
Look at the working tree (git status, git diff). What is missing versus the goal: unbuilt pieces, unverified claims, docs not updated (README, AGENTS.md, docs/agent-graph.json), user-facing text that breaks content rules? List concrete follow-up items.`,
  { label: 'critic', phase: 'Critic', schema: CRITIC },
)

return { plan: { items: items.map(({ id, title, modules, owned_paths, depends_on }) => ({ id, title, modules, owned_paths, depends_on })), notes: plan.notes, waves: waves.map((w) => w.map((i) => i.id)), added_edges: added }, results, verifies, critic }
