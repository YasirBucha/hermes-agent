# Global Rules Reference
> [!IMPORTANT]
> This project follows global development standards. ALWAYS read [GLOBAL_AGENTS.md](file:///GLOBAL_AGENTS.md) or [global-agents.md](file:///Users/yb/Dev/ai-rules/global-agents.md) first to align on universal instructions.

# Hermes Agent - Development Guide

Instructions for AI coding assistants and developers working on the hermes-agent codebase.

**Never give up on the right solution.**

## What Hermes Is

Hermes is a personal AI agent that runs the same agent core across a CLI, a
messaging gateway (Telegram, Discord, Slack, and ~20 other platforms), a TUI,
and an Electron desktop app. It learns across sessions (memory + skills),
delegates to subagents, runs scheduled jobs, and drives a real terminal and
browser. It is extended primarily through **plugins and skills**, not by
growing the core.

Two properties shape almost every design decision and are the lens for
reviewing any change:

- **Per-conversation prompt caching is sacred.** A long-lived conversation
  reuses a cached prefix every turn. Anything that mutates past context,
  swaps toolsets, or rebuilds the system prompt mid-conversation invalidates
  that cache and multiplies the user's cost. We do not do it (the one
  exception is context compression).
- **The core is a narrow waist; capability lives at the edges.** Every model
  tool we add is sent on every API call, so the bar for a new *core* tool is
  high. Most new capability should arrive as a CLI command + skill, a
  service-gated tool, or a plugin — not as core surface.

## Contribution Rubric — What We Want / What We Don't

This is the project's intent layer. Use it two ways:

1. **For humans and for your own work** — what gets merged and what gets
   rejected, so a contribution aims at the target.
2. **For automated review (the triage sweeper)** — guidance on when a PR is
   safe to close on the three allowed reasons (`implemented_on_main`,
   `cannot_reproduce`, `incoherent`) and, just as important, **when NOT to
   close** one. Taste-based "we don't want this / out of scope" closes are NOT
   an automated decision — those stay with a human maintainer. The sweeper's
   job here is to recognize design intent and *avoid wrongly closing a
   legitimate contribution*, not to make the won't-implement call itself.

Read the balance right: Hermes ships a **lot** — most merges are bug fixes to
real reported behavior, and the product surface (platforms, channels,
providers, models, desktop/TUI features) expands aggressively and on purpose.
The restraint below is aimed squarely at the **core agent + the model tool
schema**, the one place where every addition is paid for on every API call.
"Smallest footprint" governs *how a capability is wired into the core*, NOT
whether the product is allowed to grow. We are expansive at the edges and
conservative at the waist.

### What we want

- **Fix real bugs, well.** The bulk of what lands is `fix(...)` against an
  actual reported symptom. A good fix reproduces the symptom on current
  `main`, points to the exact line where it manifests, and fixes the whole bug
  class — sibling call paths included — not just the one site the reporter hit.
- **Expand reach at the edges.** New platform adapters, channels, providers,
  models, and desktop/TUI/dashboard features are welcome and land routinely,
  including large ones (a new messaging channel, a session-cap feature, a
  Windows PTY bridge). Breadth in the product is a goal, not a footprint
  concern — as long as it integrates with the existing setup/config UX
  (`hermes tools`, `hermes setup`, auto-install) rather than bolting on a raw
  env var.
- **Refactor god-files into clean modules.** Extracting a multi-thousand-line
  cluster out of `cli.py` / `run_agent.py` / `gateway/run.py` into a focused
  mixin or module is wanted work, even when the diff is huge and mechanical
  (large `+N/-N` refactors merge regularly). The "every line traces to the
  request" test applies to *feature* PRs; a declared refactor's request IS the
  extraction.
- **Keep the core narrow.** New *model tools* are the expensive exception —
  every tool ships on every API call. Prefer, in order: extend existing code →
  CLI command + skill → service-gated tool (`check_fn`) → plugin → MCP server
  in the catalog → new core tool (last resort). See "The Footprint Ladder."
- **Extend, don't duplicate.** Before adding a module/manager/hook, check
  whether existing infrastructure already covers the use case. When several PRs
  integrate the same *category*, design one shared interface instead of merging
  them one at a time (see the ABC + orchestrator note under the Footprint
  Ladder).
- **Behavior contracts over snapshots.** Tests should assert how two pieces of
  data must relate (invariants), not freeze a current value (model lists,
  config version literals, enumeration counts). See "Don't write
  change-detector tests."
- **E2E validation, not just green unit mocks.** For anything touching
  resolution chains, config propagation, security boundaries, remote
  backends, or file/network I/O, exercise the real path with real imports
  against a temp `HERMES_HOME`. Mocks hide integration bugs.
- **Cache-, alternation-, and invariant-safe.** Preserve prompt caching, strict
  message role alternation (never two same-role messages in a row; never a
  synthetic user message injected mid-loop), and a system prompt that is
  byte-stable for the life of a conversation.
- **Contributor credit preserved.** Salvage external work by cherry-picking
  (rebase-merge) so authorship survives in git history; don't reimplement from
  scratch when you can build on top.

### What we don't want (rejected even when well-built)

- **Speculative infrastructure.** Hooks, callbacks, or extension points with no
  concrete consumer. Adding a hook is easy; removing one after plugins depend
  on it is hard. A hook is NOT speculative if a contributor has a real, stated
  use case — even if the consumer ships separately.
- **New `HERMES_*` env vars for non-secret config.** `.env` is for secrets
  only (API keys, tokens, passwords). All behavioral settings — timeouts,
  thresholds, feature flags, display prefs — go in `config.yaml`. Bridge to an
  internal env var if the mechanism needs one, but user-facing docs point to
  `config.yaml`. Reject PRs that tell users to "set X in your .env" unless X
  is a credential.
- **A new core tool when terminal + file already do the job, or when a skill
  would.** If the only barrier is file visibility on a remote backend, fix the
  mount, not the toolset.
- **Lazy-reading escape hatches on instructional tools.** No `offset`/`limit`
  pagination on tools that load content the agent must read fully (skills,
  prompts, playbooks). Models will read page 1 and skip the rest.
- **"Fixes" that destroy the feature they secure.** A mitigation that kills the
  feature's purpose is the wrong mitigation. Read the original commit's intent
  (`git log -p -S`) before restricting behavior; find a fix that preserves the
  feature.
- **Outbound telemetry / usage attribution without opt-in gating.** No new
  analytics, third-party identifier tagging, or attribution tags until a
  generic user-facing opt-in (config gate + setup prompt + `hermes tools`
  toggle) exists. Park behind a label, do not merge.
- **Change-detector tests, cache-breaking mid-conversation, dead code wired in
  without E2E proof, and plugins that touch core files.** Plugins live in their
  own directory and work within the ABCs/hooks we provide; if a plugin needs
  more, widen the generic plugin surface, don't special-case it in core.
- **Third-party products / other people's projects integrated into the core
  tree.** Observability backends, vendor SaaS integrations, analytics dashboards,
  and similar "someone else's product" plugins do NOT land under `plugins/` in
  this repo. They place an ongoing maintenance burden on us to keep them working
  against a fast-moving core, for a backend we don't own. Ship them as a
  **standalone plugin repo** users install into `~/.hermes/plugins/` (or via a
  pip entry point), and promote them in the Nous Research Discord
  (`#plugins-skills-and-skins`). This is a coupling-and-maintenance decision, not
  a quality bar — the plugin can be excellent and still be a close. PRs that add
  such a directory to the tree are closed with a pointer to publish it as its own
  repo.

### Before you call it a bug — verify the premise (and when NOT to close)

The most common reason a well-written PR gets closed is not code quality — it
is that the change is built on a **wrong premise**, or it treats an
**intentional design as a gap**. These patterns cut both ways: they tell a
human reviewer what to scrutinize, and they tell the automated sweeper when a
PR is NOT safe to close as `implemented_on_main` / `cannot_reproduce` (when in
doubt, leave it open for a human). They are distilled from real closes.

- **"Intentional design, not a gap."** A limitation that looks like an
  oversight is often deliberate. Before "fixing" a missing link or a
  restriction, ask whether the isolation IS the design. Example: profiles are
  independent islands on purpose — a PR adding live config inheritance from the
  default profile was closed because coupling profiles together is exactly what
  the design prevents (the copy-at-creation `--clone` path already covers the
  legitimate "start from my default" case). Read the original commit's intent
  (`git log -p -S "<symbol>"`) before assuming something is unfinished.
- **"The premise doesn't hold against how X actually works."** A PR's
  justification frequently rests on a wrong mental model of an existing
  mechanism. Trace the real code/runtime before accepting the rationale. Two
  real closes: a rate-limit "re-probe during cooldown" PR (the breaker only
  trips on a *confirmed-empty* account bucket, so re-probing just hammers a
  bucket we've already proven empty); a usage-accumulation fix whose new branch
  **never executes at runtime** because an earlier guard already popped the
  state it depended on. If you can't point to the exact line where the bug
  manifests AND show the fix changes that line's behavior, you haven't verified
  the premise.
- **"This fix was wrong — the absence/omission was deliberate."** Adding the
  obvious-looking missing piece can break things the omission was protecting.
  Example: restoring "missing" `__init__.py` files made a test tree importable
  as a dotted package that shadowed the real plugin, deleting its `register()`
  at import time. The absence was load-bearing.
- **"Overreached / resurrected an approach we'd moved past."** Scope creep that
  supersedes an agreed-on base, or revives a direction the maintainers
  deliberately closed, gets rejected even when the code works. Keep the change
  to the narrow piece that was actually agreed; offer the rest as a focused
  follow-up.

The throughline: **verify the claim AND the intent against the codebase before
writing or merging a fix.** A confirmed reproduction on current `main` plus a
line-level account of where the fix acts beats a plausible-sounding rationale
every time. When in doubt about intent, it is cheaper to ask than to ship a
fix that fights the design.

### The Footprint Ladder (new capability decision)

Each rung adds more permanent surface than the one above. Choose the highest
(least-footprint) rung that correctly solves the problem:

1. **Extend existing code** — the capability is a variation of something that
   already exists. Zero new surface.
2. **CLI command + skill** — manages config/state/infra expressible as shell
   commands. The agent runs `hermes <subcommand>` guided by a skill. Zero
   model-tool footprint. Default choice for subscriptions, scheduled tasks,
   service setup. Examples: `hermes webhook`, `hermes cron`, `hermes tools`.
3. **Service-gated tool (`check_fn`)** — needs structured params/returns AND
   only appears when a prerequisite is configured. Zero footprint otherwise.
   Examples: Home Assistant tools (gated on token), memory-provider tools.
4. **Plugin** — third-party/niche/user-specific capability that doesn't ship in
   core. Lives in `~/.hermes/plugins/` or a pip package, discovered at runtime.
5. **MCP server (in the catalog)** — if the capability genuinely needs to be a
   tool (structured I/O the agent invokes) but isn't core-fundamental, prefer
   building it as an MCP server and adding it to the MCP catalog over growing
   the core toolset. The agent connects to it through the built-in MCP client;
   zero permanent core-schema footprint, and it's reusable by any MCP host.
6. **New core tool** — only when the capability is fundamental, broadly useful
   to nearly every user, and unreachable via terminal + file (or an MCP server).
   Examples of correct core tools: terminal, read_file, web_search,
   browser_navigate.

When 3+ open PRs try to integrate the same *category* of thing (memory
backends, providers, notifiers), don't merge them one at a time — design an
ABC + orchestrator, wrap the existing built-in as the first provider, and turn
the competing PRs into plugins against that interface.

### Surface capability is a property of the SESSION, never of the process env

A tool that only works because of *who is on the other end of the connection* —
the desktop app's panes, the in-app browser, message reactions, Projects — must
resolve its availability from the **session's own source**, not from an env var
on the backend process.

The client and the backend are separate machines on separate clocks. The
desktop app can be driving a backend Electron spawned locally, one over SSH,
one behind a plain URL + token, or Hermes Cloud. Only the first two are spawned
by us and carry `HERMES_DESKTOP=1`. Every env-keyed GUI gate is therefore a
silent no-op on the other half of the topologies, and the failure is invisible:
the tool is stripped from the schema before the model ever sees it, on the same
backend whose platform hint is telling the model it's *"chatting inside the
Hermes desktop app."*

The pattern that works:

- **The toolset is the surface gate.** Keep the tools off `_HERMES_CORE_TOOLS`
  (nobody else should pay their schema) and put them in a named toolset —
  `desktop_ui`, `project`. The GUI gateway's `_load_enabled_toolsets(platform)`
  folds that toolset in when the session's platform says GUI. One resolver,
  every topology.
- **`check_fn` answers reachability or user opt-in, not surface.** "Is the
  renderer bridge wired?", "did the user enable reactions?" — fine. "Was I
  spawned by Electron?" — not fine. `check_fn` results are also TTL-cached
  process-wide (`tools/registry.py`), so a per-session answer does not belong
  there at all: one process serves many sessions.
- **Ask which identity you actually mean.** `HERMES_DESKTOP=1` legitimately
  marks *"this backend process was spawned by the app"* — it gates the cron
  ticker and web-dist handling correctly. It does NOT mean "a GUI is watching",
  and the embedded terminal pane (`hermes --tui` against that same backend) is
  the standing counterexample.

Same test both ways: if the capability would still make sense with the client
on another machine, it is session-scoped. Cover it with a test that asserts the
GUI session gets the tool **with the env var absent** — that's the assertion
the original gate could never have passed.

## Development Environment

```bash
# Prefer .venv; fall back to venv if that's what your checkout has.
source .venv/bin/activate   # or: source venv/bin/activate
```

`scripts/run_tests.sh` probes `.venv` first, then `venv`, then
`$HOME/.hermes/hermes-agent/venv` (for worktrees that share a venv with the
main checkout).

## Project Structure

File counts shift constantly — don't treat the tree below as exhaustive.
The canonical source is the filesystem. The notes call out the load-bearing
entry points you'll actually edit.

```
hermes-agent/
├── run_agent.py          # AIAgent class — core conversation loop (~12k LOC)
├── model_tools.py        # Tool orchestration, discover_builtin_tools(), handle_function_call()
├── toolsets.py           # Toolset definitions, _HERMES_CORE_TOOLS list
├── cli.py                # HermesCLI class — interactive CLI orchestrator (~11k LOC)
├── hermes_state.py       # SessionDB — SQLite session store (FTS5 search)
├── hermes_constants.py   # get_hermes_home(), display_hermes_home() — profile-aware paths
├── hermes_logging.py     # setup_logging() — agent.log / errors.log / gateway.log (profile-aware)
├── batch_runner.py       # Parallel batch processing
├── agent/                # Agent internals (provider adapters, memory, caching, compression, etc.)
├── hermes_cli/           # CLI subcommands, setup wizard, plugins loader, skin engine
├── tools/                # Tool implementations — auto-discovered via tools/registry.py
│   └── environments/     # Terminal backends (local, docker, ssh, modal, daytona, singularity)
├── gateway/              # Messaging gateway — run.py + session.py + platforms/
│   ├── platforms/        # Adapter per platform (telegram, discord, slack, whatsapp,
│   │                     #   homeassistant, signal, matrix, mattermost, email, sms,
│   │                     #   dingtalk, wecom, weixin, feishu, qqbot, bluebubbles,
│   │                     #   yuanbao, webhook, api_server, ...). See ADDING_A_PLATFORM.md.
│   └── builtin_hooks/    # Extension point for always-registered gateway hooks (none shipped)
├── plugins/              # Plugin system (see "Plugins" section below)
│   ├── memory/           # Memory-provider plugins (honcho, mem0, supermemory, ...)
│   ├── context_engine/   # Context-engine plugins
│   ├── model-providers/  # Inference backend plugins (openrouter, anthropic, gmi, ...)
│   ├── kanban/           # Multi-agent board dispatcher + worker plugin
│   ├── hermes-achievements/  # Gamified achievement tracking
│   ├── observability/    # Metrics / traces / logs plugin
│   ├── image_gen/        # Image-generation providers
│   └── <others>/         # disk-cleanup, google_meet, platforms, spotify,
│                         #   strike-freedom-cockpit, ...
├── optional-skills/      # Heavier/niche skills shipped but NOT active by default
├── skills/               # Built-in skills bundled with the repo
├── ui-tui/               # Ink (React) terminal UI — `hermes --tui`
│   └── src/              # entry.tsx, app.tsx, gatewayClient.ts + app/components/hooks/lib
├── tui_gateway/          # Python JSON-RPC backend for the TUI
├── acp_adapter/          # ACP server (VS Code / Zed / JetBrains integration)
├── cron/                 # Scheduler — jobs.py, scheduler.py
├── scripts/              # run_tests.sh, release.py, auxiliary scripts
├── website/              # Docusaurus docs site
└── tests/                # Pytest suite (~17k tests across ~900 files as of May 2026)
```

**User config:** `~/.hermes/config.yaml` (settings), `~/.hermes/.env` (API keys only).
**Logs:** `~/.hermes/logs/` — `agent.log` (INFO+), `errors.log` (WARNING+),
`gateway.log` when running the gateway. Profile-aware via `get_hermes_home()`.
Browse with `hermes logs [--follow] [--level ...] [--session ...]`.

## TypeScript Style

Applies to TypeScript across Hermes: desktop, TUI, website, and future TS packages.

- Prefer small nanostores over component state when state is shared, reused, or read by distant UI.
- Let each feature own its atoms. Chat state belongs near chat, shell state near shell, shared state in `src/store`.
- Components that render from an atom should use `useStore`. Non-rendering actions should read with `$atom.get()`.
- Do not pass state through three components when the leaf can subscribe to the atom.
- Keep persistence beside the atom that owns it.
- Keep route roots thin. They compose routes and shell; they should not become controllers.
- No monolithic hooks. A hook should own one narrow job.
- Prefer colocated action modules over hidden god hooks.
- If a callback is pure side effect, use the terse void form:
  `onState={st => void setGatewayState(st)}`.
- Async UI handlers should make intent explicit:
  `onClick={() => void save()}`.
- Prefer interfaces for public props and shared object shapes. Avoid `type X = { ... }` for object props.
- Extend React primitives for props: `React.ComponentProps<'button'>`, `React.ComponentProps<typeof Dialog>`, `Omit<...>`, `Pick<...>`.
- Table-driven beats condition ladders when mapping ids, routes, or views.
- `src/app` owns routes, pages, and page-specific components.
- `src/store` owns shared atoms.
- `src/lib` owns shared pure helpers.

## File Dependency Chain

```
tools/registry.py  (no deps — imported by all tool files)
       ↑
tools/*.py  (each calls registry.register() at import time)
       ↑
model_tools.py  (imports tools/registry + triggers tool discovery)
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

---

## AIAgent Class (run_agent.py)

The real `AIAgent.__init__` takes ~60 parameters (credentials, routing, callbacks,
session context, budget, credential pool, etc.). The signature below is the
minimum subset you'll usually touch — read `run_agent.py` for the full list.

```python
class AIAgent:
    def __init__(self,
        base_url: str = None,
        api_key: str = None,
        provider: str = None,
        api_mode: str = None,              # "chat_completions" | "codex_responses" | ...
        model: str = "",                   # empty → resolved from config/provider later
        max_iterations: int = 500,         # tool-calling iterations (shared with subagents)
        enabled_toolsets: list = None,
        disabled_toolsets: list = None,
        quiet_mode: bool = False,
        save_trajectories: bool = False,
        platform: str = None,              # "cli", "telegram", etc.
        session_id: str = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
        credential_pool=None,
        # ... plus callbacks, thread/user/chat IDs, iteration_budget, fallback_model,
        # checkpoints config, prefill_messages, service_tier, reasoning_config, etc.
    ): ...

    def chat(self, message: str) -> str:
        """Simple interface — returns final response string."""

    def run_conversation(self, user_message: str, system_message: str = None,
                         conversation_history: list = None, task_id: str = None) -> dict:
        """Full interface — returns dict with final_response + messages."""
```

### Agent Loop

The core loop is inside `run_conversation()` — entirely synchronous, with
interrupt checks, budget tracking, and a one-turn grace call:

```python
while (api_call_count < self.max_iterations and self.iteration_budget.remaining > 0) \
        or self._budget_grace_call:
    if self._interrupt_requested: break
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(tool_call.name, tool_call.args, task_id)
            messages.append(tool_result_message(result))
        api_call_count += 1
    else:
        return response.content
```

Messages follow OpenAI format: `{"role": "system/user/assistant/tool", ...}`.
Reasoning content is stored in `assistant_msg["reasoning"]`.

---

## CLI Architecture (cli.py)

- **Rich** for banner/panels, **prompt_toolkit** for input with autocomplete
- **KawaiiSpinner** (`agent/display.py`) — animated faces during API calls, `┊` activity feed for tool results
- `load_cli_config()` in cli.py merges hardcoded defaults + user config YAML
- **Skin engine** (`hermes_cli/skin_engine.py`) — data-driven CLI theming; initialized from `display.skin` config key at startup; skins customize banner colors, spinner faces/verbs/wings, tool prefix, response box, branding text
- `process_command()` is a method on `HermesCLI` — dispatches on canonical command name resolved via `resolve_command()` from the central registry
- Skill slash commands: `agent/skill_commands.py` scans `~/.hermes/skills/`, injects as **user message** (not system prompt) to preserve prompt caching

### Slash Command Registry (`hermes_cli/commands.py`)

All slash commands are defined in a central `COMMAND_REGISTRY` list of `CommandDef` objects. Every downstream consumer derives from this registry automatically:

- **CLI** — `process_command()` resolves aliases via `resolve_command()`, dispatches on canonical name
- **Gateway** — `GATEWAY_KNOWN_COMMANDS` frozenset for hook emission, `resolve_command()` for dispatch
- **Gateway help** — `gateway_help_lines()` generates `/help` output
- **Telegram** — `telegram_bot_commands()` generates the BotCommand menu
- **Slack** — `slack_subcommand_map()` generates `/hermes` subcommand routing
- **Autocomplete** — `COMMANDS` flat dict feeds `SlashCommandCompleter`
- **CLI help** — `COMMANDS_BY_CATEGORY` dict feeds `show_help()`

### Adding a Slash Command

1. Add a `CommandDef` entry to `COMMAND_REGISTRY` in `hermes_cli/commands.py`:
```python
CommandDef("mycommand", "Description of what it does", "Session",
           aliases=("mc",), args_hint="[arg]"),
```
2. Add handler in `HermesCLI.process_command()` in `cli.py`:
```python
elif canonical == "mycommand":
    self._handle_mycommand(cmd_original)
```
3. If the command is available in the gateway, add a handler in `gateway/run.py`:
```python
if canonical == "mycommand":
    return await self._handle_mycommand(event)
```
4. For persistent settings, use `save_config_value()` in `cli.py`

**CommandDef fields:**
- `name` — canonical name without slash (e.g. `"background"`)
- `description` — human-readable description
- `category` — one of `"Session"`, `"Configuration"`, `"Tools & Skills"`, `"Info"`, `"Exit"`
- `aliases` — tuple of alternative names (e.g. `("bg",)`)
- `args_hint` — argument placeholder shown in help (e.g. `"<prompt>"`, `"[name]"`)
- `cli_only` — only available in the interactive CLI
- `gateway_only` — only available in messaging platforms
- `gateway_config_gate` — config dotpath (e.g. `"display.tool_progress_command"`); when set on a `cli_only` command, the command becomes available in the gateway if the config value is truthy. `GATEWAY_KNOWN_COMMANDS` always includes config-gated commands so the gateway can dispatch them; help/menus only show them when the gate is open.

**Adding an alias** requires only adding it to the `aliases` tuple on the existing `CommandDef`. No other file changes needed — dispatch, help text, Telegram menu, Slack mapping, and autocomplete all update automatically.

---

## TUI Architecture (ui-tui + tui_gateway)

The TUI is a full replacement for the classic (prompt_toolkit) CLI, activated via `hermes --tui` or `HERMES_TUI=1`.

### Process Model

```
hermes --tui
  └─ Node (Ink)  ──stdio JSON-RPC──  Python (tui_gateway)
       │                                  └─ AIAgent + tools + sessions
       └─ renders transcript, composer, prompts, activity
```

TypeScript owns the screen. Python owns sessions, tools, model calls, and slash command logic.

### Transport

Newline-delimited JSON-RPC over stdio. Requests from Ink, events from Python. See `tui_gateway/server.py` for the full method/event catalog.

### Key Surfaces

| Surface | Ink component | Gateway method |
|---------|---------------|----------------|
| Chat streaming | `app.tsx` + `messageLine.tsx` | `prompt.submit` → `message.delta/complete` |
| Tool activity | `thinking.tsx` | `tool.start/progress/complete` |
| Approvals | `prompts.tsx` | `approval.respond` ← `approval.request` |
| Clarify/sudo/secret | `prompts.tsx`, `maskedPrompt.tsx` | `clarify/sudo/secret.respond` |
| Session picker | `sessionPicker.tsx` | `session.list/resume` |
| Slash commands | Local handler + fallthrough | `slash.exec` → `_SlashWorker`, `command.dispatch` |
| Completions | `useCompletion` hook | `complete.slash`, `complete.path` |
| Theming | `theme.ts` + `branding.tsx` | `gateway.ready` with skin data |

### Slash Command Flow

1. Built-in client commands (`/help`, `/quit`, `/clear`, `/resume`, `/copy`, `/paste`, etc.) handled locally in `app.tsx`
2. Everything else → `slash.exec` (runs in persistent `_SlashWorker` subprocess) → `command.dispatch` fallback

### Dev Commands

```bash
cd ui-tui
npm install       # first time
npm run dev       # watch mode (rebuilds hermes-ink + tsx --watch)
npm start         # production
npm run build     # full build (hermes-ink + tsc)
npm run typecheck # typecheck only (tsc --noEmit)
npm run lint      # eslint
npm run fmt       # prettier
npm test          # vitest
```

### TUI in the Dashboard (`hermes dashboard` → `/chat`)

The dashboard embeds the real `hermes --tui` — **not** a rewrite.  See `hermes_cli/pty_bridge.py` + the `@app.websocket("/api/pty")` endpoint in `hermes_cli/web_server.py`.

- Browser loads `web/src/pages/ChatPage.tsx`, which mounts xterm.js's `Terminal` with the WebGL renderer, `@xterm/addon-fit` for container-driven resize, and `@xterm/addon-unicode11` for modern wide-character widths.
- `/api/pty?token=…` upgrades to a WebSocket; auth uses the same ephemeral `_SESSION_TOKEN` as REST, via query param (browsers can't set `Authorization` on WS upgrade).
- The server spawns whatever `hermes --tui` would spawn, through `ptyprocess` (POSIX PTY — WSL works, native Windows does not).
- Frames: raw PTY bytes each direction; resize via `\x1b[RESIZE:<cols>;<rows>]` intercepted on the server and applied with `TIOCSWINSZ`.

**Do not re-implement the primary chat experience in React.** The main transcript, composer/input flow (including slash-command behavior), and PTY-backed terminal belong to the embedded `hermes --tui` — anything new you add to Ink shows up in the dashboard automatically. If you find yourself rebuilding the transcript or composer for the dashboard, stop and extend Ink instead.

**Structured React UI around the TUI is allowed when it is not a second chat surface.** Sidebar widgets, inspectors, summaries, status panels, and similar supporting views (e.g. `ChatSidebar`, `ModelPickerDialog`, `ToolCall`) are fine when they complement the embedded TUI rather than replacing the transcript / composer / terminal. Keep their state independent of the PTY child's session and surface their failures non-destructively so the terminal pane keeps working unimpaired.

### Electron Desktop Chat App (`apps/desktop/`)

A **separate** chat surface from both the classic CLI and the dashboard's embedded TUI. It is an Electron + React + nanostore renderer (`@assistant-ui/react`) that talks to a `tui_gateway` backend over JSON-RPC (`requestGateway(method, params)`). The WebSocket/JSON-RPC transport lives in the framework-agnostic `apps/shared` package (`@hermes/shared` — `JsonRpcGatewayClient` + WS URL helpers), which the web dashboard (`web/`) also consumes; **desktop has no build/runtime dependency on the dashboard frontend** — it spawns a headless `hermes serve` backend server (the same gateway `dashboard` serves, minus the browser UI entirely: `serve` sets `headless_backend=True`, so `cmd_dashboard` skips `_build_web_ui` AND exports `HERMES_SERVE_HEADLESS=1` so `mount_spa()` disables the SPA even if a stray `web_dist/` exists — only the JSON-RPC/WS/API surface is reachable). `dashboard` and `serve` share `cmd_dashboard`/`start_server` but are independent surfaces — neither launches the other. The one exception is a backward-compat *fallback*: `serve` is newer, so the desktop spawn (`electron/backend-command.ts` + `backendSupportsServe()` in `electron/main.ts`) detects whether the resolved runtime registers `serve` and, only when it does not (an older managed install / PATH `hermes` the app hasn't updated yet), rewrites the argv to the legacy `dashboard --no-open`. Without that, a new app against an un-upgraded runtime would crash on an unknown subcommand and brick every mid-upgrade user. It does NOT embed `hermes --tui` — it has its own composer, transcript, and slash-command pipeline. For scoped Desktop architecture, state, resolver, transport, and testing rules, read `apps/desktop/AGENTS.md`.

**Slash commands in the desktop app are curated client-side, then dispatched to the backend.** The pipeline:

- **Backend already provides everything.** `tui_gateway/server.py` `commands.catalog` (empty-query list) and `complete.slash` (typed-query completions) both include built-in commands, user `quick_commands`, AND skill-derived commands (`scan_skill_commands()` / `get_skill_commands()`). The desktop app does not need a new RPC to see skills.
- **The renderer curates via `apps/desktop/src/lib/desktop-slash-commands.ts`.** This is the load-bearing file. It holds `DESKTOP_COMMAND_SPECS` (the built-ins and their Desktop surfaces) plus `NO_DESKTOP_SURFACE` block-lists for terminal-only / messaging-only / picker-owned / settings-owned / advanced commands that should NOT clutter the desktop popover.
  - `isDesktopSlashCommand(name)` — gates **execution**. Returns true for built-ins AND for any non-built-in (skill / quick command), so typed extension commands run.
  - `isDesktopSlashSuggestion(name)` — gates **discovery/completion**. Used by BOTH completion paths in `app/chat/composer/hooks/use-slash-completions.ts` (empty-query catalog filter + typed-query `complete.slash` filter) and by `filterDesktopCommandsCatalog`.
  - `isDesktopSlashExtensionCommand(name)` — true when the command is NOT a known Hermes built-in (i.e. a skill or user quick command). Both suggestion and catalog-filter paths allow extensions through so skill commands surface in the palette. (Added when fixing "skill commands missing from the desktop slash palette" — the curated allow-list was silently dropping every skill/quick command from completions even though they executed fine when typed.)
- **Dispatch** lives in `app/session/hooks/use-prompt-actions/slash.ts` (`runSlash`): built-ins that the desktop owns (`/skin`, `/help`, `/new`, …) are handled locally or via `commands.catalog`; everything else goes to `slash.exec`, falling back to `command.dispatch` (which the gateway resolves into skill / alias / exec directives). A skill command resolves to `{type: "skill", message}` and is submitted as a normal prompt.

**Rule:** the desktop slash palette's curation is about hiding noise (terminal-only / messaging-only built-ins), NOT about hiding user-activated extensions. Skill commands and `quick_commands` are extensions the backend surfaces — they belong in completions. If you tighten `desktop-slash-commands.ts`, keep `isDesktopSlashExtensionCommand` flowing into both the suggestion and catalog-filter paths. Tests: from `apps/desktop`, run `npx vitest run src/lib/desktop-slash-commands.test.ts` (workspace dependencies are installed at the repo root).

---

## Adding New Tools

Before adding any tool, settle the footprint question first (see "The
Footprint Ladder" in the Contribution Rubric): most capabilities should NOT
be core tools. For custom or local-only tools, do **not** edit Hermes core.
Use the plugin route instead: create `~/.hermes/plugins/<name>/plugin.yaml`
and `~/.hermes/plugins/<name>/__init__.py`, then register tools with
`ctx.register_tool(...)`. Plugin toolsets are discovered automatically and can be
enabled or disabled without touching `tools/` or `toolsets.py`.

Use the built-in route below only when the user is explicitly contributing a new
core Hermes tool that should ship in the base system.

Built-in/core tools require changes in **2 files**:

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add to `toolsets.py`** — either `_HERMES_CORE_TOOLS` (all platforms) or a new toolset. **This step is required:** auto-discovery imports the tool and registers its schema, but the tool is only *exposed to an agent* if its name appears in a toolset. `_HERMES_CORE_TOOLS` is not dead code — it's the default bundle every platform's base toolset inherits from.

Auto-discovery: any `tools/*.py` file with a top-level `registry.register()` call is imported automatically — no manual import list to maintain. Wiring into a toolset is still a deliberate, manual step.

The registry handles schema collection, dispatch, availability checking, and error wrapping. All handlers MUST return a JSON string.

**Path references in tool schemas**: If the schema description mentions file paths (e.g. default output directories), use `display_hermes_home()` to make them profile-aware. The schema is generated at import time, which is after `_apply_profile_override()` sets `HERMES_HOME`.

**State files**: If a tool stores persistent state (caches, logs, checkpoints), use `get_hermes_home()` for the base directory — never `Path.home() / ".hermes"`. This ensures each profile gets its own state.

**Agent-level tools** (todo, memory): intercepted by `run_agent.py` before `handle_function_call()`. See `tools/todo_tool.py` for the pattern.

---

## Dependency Pinning Policy

All dependencies must have upper bounds to limit supply-chain attack surface.
This policy was established after the litellm compromise (PR #2796, #2810) and
reinforced after the Mini Shai-Hulud worm campaign (May 2026).

| Source type | Treatment | Example |
|---|---|---|
| PyPI package | `>=floor,<next_major` | `"httpx>=0.28.1,<1"` |
| Git URL | Commit SHA | `git+https://...@<40-char-sha>` |
| GitHub Actions | Commit SHA + comment | `uses: actions/checkout@<sha>  # v4` |
| CI-only pip | `==exact` | `pyyaml==6.0.2` |

**When adding a new dependency to `pyproject.toml`:**
1. Pin to `>=current_version,<next_major` for post-1.0 (e.g. `>=1.5.0,<2`).
2. For pre-1.0 packages, use `<0.(current_minor + 2)` (e.g. `>=0.29,<0.32`).
3. Never commit a bare `>=X.Y.Z` without a ceiling — CI and reviewers will reject it.
4. Run `uv lock` to regenerate `uv.lock` with hashes.

Reference: #2810 (bounds pass), #9801 (SHA pinning + audit CI).

---

## Adding Configuration

### config.yaml options:
1. Add to `DEFAULT_CONFIG` in `hermes_cli/config.py`
2. Bump `_config_version` (check the current value at the top of `DEFAULT_CONFIG`)
   ONLY if you need to actively migrate/transform existing user config
   (renaming keys, changing structure). Adding a new key to an existing
   section is handled automatically by the deep-merge and does NOT require
   a version bump.

### Top-level `config.yaml` sections (non-exhaustive):

`model`, `agent`, `terminal`, `compression`, `display`, `stt`, `tts`,
`memory`, `security`, `delegation`, `smart_model_routing`, `checkpoints`,
`auxiliary`, `curator`, `skills`, `gateway`, `logging`, `cron`, `profiles`,
`plugins`, `honcho`.

`auxiliary` holds per-task overrides for side-LLM work (curator, vision,
embedding, title generation, session_search, etc.) — each task can pin
its own provider/model/base_url/max_tokens/reasoning_effort. See
`agent/auxiliary_client.py::_resolve_auto` for resolution order.

`curator` holds the background skill-maintenance config —
`enabled`, `interval_hours`, `min_idle_hours`, `stale_after_days`,
`archive_after_days`, `backup` (nested).

### .env variables (SECRETS ONLY — API keys, tokens, passwords):
1. Add to `OPTIONAL_ENV_VARS` in `hermes_cli/config.py` with metadata:
```python
"NEW_API_KEY": {
    "description": "What it's for",
    "prompt": "Display name",
    "url": "https://...",
    "password": True,
    "category": "tool",  # provider, tool, messaging, setting
},
```

Non-secret settings (timeouts, thresholds, feature flags, paths, display
preferences) belong in `config.yaml`, not `.env`. If internal code needs an
env var mirror for backward compatibility, bridge it from `config.yaml` to
the env var in code (see `gateway_timeout`, `terminal.cwd` → `TERMINAL_CWD`).

### Config loaders (three paths — know which one you're in):

| Loader | Used by | Location |
|--------|---------|----------|
| `load_cli_config()` | CLI mode | `cli.py` — merges CLI-specific defaults + user YAML |
| `load_config()` | `hermes tools`, `hermes setup`, most CLI subcommands | `hermes_cli/config.py` — merges `DEFAULT_CONFIG` + user YAML |
| Direct YAML load | Gateway runtime | `gateway/run.py` + `gateway/config.py` — reads user YAML raw |

If you add a new key and the CLI sees it but the gateway doesn't (or vice
versa), you're on the wrong loader. Check `DEFAULT_CONFIG` coverage.

### Working directory:
- **CLI** — uses the process's current directory (`os.getcwd()`).
- **Messaging** — uses `terminal.cwd` from `config.yaml`. The gateway bridges this
  to the `TERMINAL_CWD` env var for child tools. **`MESSAGING_CWD` has been
  removed** — the config loader prints a deprecation warning if it's set in
  `.env`. Same for `TERMINAL_CWD` in `.env`; the canonical setting is
  `terminal.cwd` in `config.yaml`.

---

## Skin/Theme System

The skin engine (`hermes_cli/skin_engine.py`) provides data-driven CLI visual customization. Skins are **pure data** — no code changes needed to add a new skin.

### Architecture

```
hermes_cli/skin_engine.py    # SkinConfig dataclass, built-in skins, YAML loader
~/.hermes/skins/*.yaml       # User-installed custom skins (drop-in)
```

- `init_skin_from_config()` — called at CLI startup, reads `display.skin` from config
- `get_active_skin()` — returns cached `SkinConfig` for the current skin
- `set_active_skin(name)` — switches skin at runtime (used by `/skin` command)
- `load_skin(name)` — loads from user skins first, then built-ins, then falls back to default
- Missing skin values inherit from the `default` skin automatically

### What skins customize

| Element | Skin Key | Used By |
|---------|----------|---------|
| Banner panel border | `colors.banner_border` | `banner.py` |
| Banner panel title | `colors.banner_title` | `banner.py` |
| Banner section headers | `colors.banner_accent` | `banner.py` |
| Banner dim text | `colors.banner_dim` | `banner.py` |
| Banner body text | `colors.banner_text` | `banner.py` |
| Response box border | `colors.response_border` | `cli.py` |
| Spinner faces (waiting) | `spinner.waiting_faces` | `display.py` |
| Spinner faces (thinking) | `spinner.thinking_faces` | `display.py` |
| Spinner verbs | `spinner.thinking_verbs` | `display.py` |
| Spinner wings (optional) | `spinner.wings` | `display.py` |
| Tool output prefix | `tool_prefix` | `display.py` |
| Per-tool emojis | `tool_emojis` | `display.py` → `get_tool_emoji()` |
| Agent name | `branding.agent_name` | `banner.py`, `cli.py` |
| Welcome message | `branding.welcome` | `cli.py` |
| Response box label | `branding.response_label` | `cli.py` |
| Prompt symbol | `branding.prompt_symbol` | `cli.py` |

### Built-in skins

- `default` — Classic Hermes gold/kawaii (the current look)
- `ares` — Crimson/bronze war-god theme with custom spinner wings
- `mono` — Clean grayscale monochrome
- `slate` — Cool blue developer-focused theme

### Adding a built-in skin

Add to `_BUILTIN_SKINS` dict in `hermes_cli/skin_engine.py`:

```python
"mytheme": {
    "name": "mytheme",
    "description": "Short description",
    "colors": { ... },
    "spinner": { ... },
    "branding": { ... },
    "tool_prefix": "┊",
},
```

### User skins (YAML)

Users create `~/.hermes/skins/<name>.yaml`:

```yaml
name: cyberpunk
description: Neon-soaked terminal theme

colors:
  banner_border: "#FF00FF"
  banner_title: "#00FFFF"
  banner_accent: "#FF1493"

spinner:
  thinking_verbs: ["jacking in", "decrypting", "uploading"]
  wings:
    - ["⟨⚡", "⚡⟩"]

branding:
  agent_name: "Cyber Agent"
  response_label: " ⚡ Cyber "

tool_prefix: "▏"
```

Activate with `/skin cyberpunk` or `display.skin: cyberpunk` in config.yaml.

---

## Plugins

Hermes has two plugin surfaces. Both live under `plugins/` in the repo so
repo-shipped plugins can be discovered alongside user-installed ones in
`~/.hermes/plugins/` and pip-installed entry points.

### General plugins (`hermes_cli/plugins.py` + `plugins/<name>/`)

`PluginManager` discovers plugins from `~/.hermes/plugins/`, `./.hermes/plugins/`,
and pip entry points. Each plugin exposes a `register(ctx)` function that
can:

- Register Python-callback lifecycle hooks:
  `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`,
  `on_session_start`, `on_session_end`
- Register new tools via `ctx.register_tool(...)`
- Register CLI subcommands via `ctx.register_cli_command(...)` — the
  plugin's argparse tree is wired into `hermes` at startup so
  `hermes <pluginname> <subcmd>` works with no change to `main.py`

Hooks are invoked from `model_tools.py` (pre/post tool) and `run_agent.py`
(lifecycle). **Discovery timing pitfall:** `discover_plugins()` only runs
as a side effect of importing `model_tools.py`. Code paths that read plugin
state without importing `model_tools.py` first must call `discover_plugins()`
explicitly (it's idempotent).

#### Native plugin compatibility policy

The canonical contract and deprecation policy live in
`website/docs/developer-guide/plugins/index.md#native-plugin-compatibility-contract`.
Compatibility is enforced as a behavior contract, not through a monolithic
`PLUGIN_API_VERSION`, a manifest-wide native `api:` match, or version literals
on unrelated payloads. Keep documented plugin surfaces additive:

- add hook payload data as keyword fields; signature-inspect callbacks so old
  narrow signatures receive only fields they declare, while `**kwargs`
  callbacks receive the complete payload;
- do not remove or rename `PluginContext` methods; make new parameters optional
  with defaults and keyword-only where possible;
- ignore unknown native manifest fields;
- give new provider methods default implementations, and signature-inspect
  optional callback kwargs rather than forwarding them unconditionally;
- use a local schema version only for a capability with a wire or persisted
  contract, and preserve old state/config/session replay or ship a migration.

Deprecations require a once-per-process warning, a documented replacement and
migration note, and at least two subsequent minor releases before removal.
Compatibility tests must load frozen plugins through the real discovery path
and assert outcomes. Do not replace these with exact registry/catalog counts,
source-reading tests, or assertions that a global version literal changed.

### Memory-provider plugins (`plugins/memory/<name>/`)

Separate discovery system for pluggable memory backends. Current built-in
providers include **honcho, mem0, supermemory, byterover, hindsight,
holographic, openviking, retaindb**.

Discovery covers the same four sources as the general `PluginManager` —
bundled, `$HERMES_HOME/plugins/`, `./.hermes/plugins/` (opt-in via
`HERMES_ENABLE_PROJECT_PLUGINS`), and `hermes_agent.memory_providers` entry
points — but with **bundled-first** precedence, the reverse of the general
system's later-wins order: a memory provider is activated by name, so a
dropped-in directory must not be able to shadow a shipped one. Discovery
enumerates without importing; nothing runs until `memory.provider` names it.

Each provider implements the `MemoryProvider` ABC (see `agent/memory_provider.py`)
and is orchestrated by `agent/memory_manager.py`. Lifecycle hooks include
`sync_turn(turn_messages)`, `prefetch(query)`, `shutdown()`, and optional
`post_setup(hermes_home, config)` for setup-wizard integration.

**CLI commands via `plugins/memory/<name>/cli.py`:** if a memory plugin
defines `register_cli(subparser)`, `discover_plugin_cli_commands()` finds
it at argparse setup time and wires it into `hermes <plugin>`. The
framework only exposes CLI commands for the **currently active** memory
provider (read from `memory.provider` in config.yaml), so disabled
providers don't clutter `hermes --help`.

**Rule (Teknium, May 2026):** plugins MUST NOT modify core files
(`run_agent.py`, `cli.py`, `gateway/run.py`, `hermes_cli/main.py`, etc.).
If a plugin needs a capability the framework doesn't expose, expand the
generic plugin surface (new hook, new ctx method) — never hardcode
plugin-specific logic into core. PR #5295 removed 95 lines of hardcoded
honcho argparse from `main.py` for exactly this reason.

**No new in-tree memory providers (policy, May 2026):** the set of
built-in memory providers under `plugins/memory/` is closed. New memory
backends must ship as **standalone plugin repos** that users install
into `~/.hermes/plugins/` (or via pip entry points) — they implement
the same `MemoryProvider` ABC, register through the same discovery
path, and integrate via `hermes memory setup` / `post_setup()` without
landing in this tree. PRs that add a new directory under
`plugins/memory/` will be closed with a pointer to publish the
provider as its own repo. Existing in-tree providers stay; bug fixes
to them are welcome.

**No new third-party-product plugins in-tree (policy, June 2026):** the
same rule applies beyond memory providers. Plugins that integrate
someone else's product or project — observability/metrics backends,
vendor SaaS connectors, analytics dashboards, paid-service tie-ins —
must ship as **standalone plugin repos** that users install into
`~/.hermes/plugins/` (or via pip entry points). They register through
the existing plugin discovery path and use the ABCs/hooks/ctx surface
we expose; nothing special is needed in core. The reason is
maintenance load: every product we absorb into the tree becomes our
burden to keep working against a fast-moving core, for a backend we
don't own. Promote standalone plugins in the Nous Research Discord
(`#plugins-skills-and-skins`). PRs that add such a directory under
`plugins/` are closed with a pointer to publish it as its own repo —
this is a coupling decision, not a quality judgment. (The
`observability/`, `kanban/`, `disk-cleanup/`, etc. directories already
in the tree are existing precedent, not an invitation to add more
third-party-product plugins alongside them.)

### Model-provider plugins (`plugins/model-providers/<name>/`)

Every inference backend (openrouter, anthropic, gmi, deepseek, nvidia, …)
ships as a plugin here. Each plugin's `__init__.py` calls
`providers.register_provider(ProviderProfile(...))` at module load.
`providers/__init__.py._discover_providers()` is a **lazy, separate
discovery system** — scanned on first `get_provider_profile()` or
`list_providers()` call, NOT by the general PluginManager.

Scan order:
1. Bundled: `<repo>/plugins/model-providers/<name>/`
2. User: `$HERMES_HOME/plugins/model-providers/<name>/`
3. Legacy: `<repo>/providers/<name>.py` (back-compat)

User plugins of the same name override bundled ones — `register_provider()`
is last-writer-wins. This lets third parties swap out any built-in
profile without a repo patch.

The general PluginManager records `kind: model-provider` manifests but does
NOT import them (would double-instantiate `ProviderProfile`). Plugins
without an explicit `kind:` get auto-coerced via a source-text heuristic
(`register_provider` + `ProviderProfile` in `__init__.py`).

Full authoring guide: `website/docs/developer-guide/model-provider-plugin.md`.

### Dashboard / context-engine / image-gen plugin directories

`plugins/context_engine/`, `plugins/image_gen/`, etc. follow the same
pattern (ABC + orchestrator + per-plugin directory). Context engines
plug into `agent/context_engine.py`; image-gen providers into
`agent/image_gen_provider.py`. Reference / docs-companion plugins
(`example-dashboard`, `strike-freedom-cockpit`, `plugin-llm-example`,
`plugin-llm-async-example`) live in the
[`hermes-example-plugins`](https://github.com/NousResearch/hermes-example-plugins)
companion repo, not in this tree.

### Bot Mode (`apps/desktop/src/plugins/hermes-bots/`)

The desktop "Bots" experience ships bundled in-tree. Each bot is a Hermes
agent **profile** with a persistent identity. Its design rests on one settled
invariant that has been regressed repeatedly, cost users real conversation
history each time, and is not open for re-litigation in a routine PR:

**One bot = ONE canonical forever-chat, identified by NAME.** The chat's one
and only identity is **(profile, session titled exactly "Bot Chat")** — the
state DB's UNIQUE(title) index makes that pair an exact registry of at most
one row. The full lifecycle when a bot row is clicked:

1. **Resolve the registry, every time.** Look up the profile's `Bot Chat`
   session by exact title via `session.list {title, include_hidden: true}`
   (indexed, window-free; hidden rows resolve because canonical chats are
   always hidden; compression lineages resolve to the live tip). Row exists →
   open it. That is the entire happy path.
2. **No row → create it,** titled `Bot Chat`, born hidden, kicked off with
   the bot's intro. Creation adopts-before-minting: it re-runs the registry
   lookup first, so a concurrent or pre-existing row is opened, never forked.
   (`set_session_title` silently drops conflicting titles — returns 0 rows —
   which is how the 2026-08 infinite fork loop started; adopt-before-mint is
   what kills it.)

**There is NO session-id pin.** The previous design stored a pointer in
`ui_meta['hermes-bots'].chat` and verified it per click; five hardening
waves (#88690, #90732, #90751, the #91791 revert, #92042) each guarded a new
way that pointer dangled or got stolen — rows[0] steals, `last_session`
adoptions, transient clears, drifted-title welds (a pin re-anchored onto a
cron session passed every guard). Name-as-identity removes the failure class:
a name cannot dangle, and a corrupted historical pointer simply never gets
read. Legacy `chat` keys in ui_meta are ignored and dropped from merges.

Why recency must never win (the #91791 → #92042 lesson): canonical Bot
Chats are **unconditionally hidden** from the Sessions sidebar, so the bot
row is the ONLY door to the forever-chat. A "newest visible session wins"
preference doesn't re-order two equivalent entry points — it walls the
entire relationship off behind a row that previews one session and opens
another, and any stray draft that catches a prompt captures the row.
Side-chats started via "New chat with this agent" are not plumbing-titled,
stay visible in the Sessions sidebar, and are reachable there; they are
never the bot row's target.

Corollaries for reviewers:

- There is no per-bot session browser, by explicit design (removed in
  #90732). Do not add one back.
- Reject any PR that reintroduces a stored session-id pointer as canonical
  identity — including "as a fallback tier" or "for verification". The
  registry lookup is the whole contract; pointers are how every prior
  incident started.
- Reject any PR that consults recency, visibility, or "where the user left
  off" for the bot row's target — reports that motivate such a change are
  almost always about side-chats, and the fix belongs in the Sessions
  sidebar (hide-sweep false positives), not in the bot row's target.
- The gateway reports the registry row per profile as `canonical_session`
  on `profiles.list` (resolved server-side by title); roster preview,
  activity signals, and the `/new`→`/compact` guard all read it, so preview
  identity and click identity are the same row by construction.

Regression tests encoding this contract:
`tests/canonical-chat-registry.test.mjs` (includes a tripwire asserting the
open path never reads or writes a stored pointer),
`tests/canonical-chat-creation.test.mjs`, `tests/hide-bot-chats.test.mjs`,
and `tests/tui_gateway/test_profiles_list_canonical_session.py`.

---

## Skills

Two parallel surfaces:

- **`skills/`** — built-in skills shipped and loadable by default.
  Organized by category directories (e.g. `skills/github/`, `skills/mlops/`).
- **`optional-skills/`** — heavier or niche skills shipped with the repo but
  NOT active by default. Installed explicitly via
  `hermes skills install official/<category>/<skill>`. Adapter lives in
  `tools/skills_hub.py` (`OptionalSkillSource`). Categories include
  `autonomous-ai-agents`, `blockchain`, `communication`, `creative`,
  `devops`, `email`, `health`, `mcp`, `migration`, `mlops`, `productivity`,
  `research`, `security`, `web-development`.

When reviewing skill PRs, check which directory they target — heavy-dep or
niche skills belong in `optional-skills/`.

### SKILL.md frontmatter

Standard fields: `name`, `description`, `version`, `author`, `license`,
`platforms` (OS-gating list: `[macos]`, `[linux, macos]`, ...),
`metadata.hermes.tags`, `metadata.hermes.category`,
`metadata.hermes.related_skills`, `metadata.hermes.config` (config.yaml
settings the skill needs — stored under `skills.config.<key>`, prompted
during setup, injected at load time).

Top-level `tags:` and `category:` are also accepted and mirrored from
`metadata.hermes.*` by the loader.

### Skill authoring standards (HARDLINE)

Every new or modernized skill — bundled, optional, or contributed —
must meet these standards before merge. Reviewers reject PRs that
violate them.

1. **`description` ≤ 60 characters, one sentence, ends with a period.**
   Long descriptions bloat skill listings and dilute the model's
   attention when many skills are loaded. State the capability, not
   the implementation. No marketing words ("powerful",
   "comprehensive", "seamless", "advanced"). Don't repeat the skill
   name. Verify with:
   ```python
   import re, pathlib
   m = re.search(r'^description: (.*)$',
                 pathlib.Path('skills/<cat>/<name>/SKILL.md').read_text(),
                 re.MULTILINE)
   assert len(m.group(1)) <= 60, len(m.group(1))
   ```

2. **Tools referenced in SKILL.md prose must be native Hermes tools or
   MCP servers the skill explicitly expects.** When the skill needs a
   capability, point at the proper tool by name in backticks
   (`` `terminal` ``, `` `web_extract` ``, `` `read_file` ``,
   `` `patch` ``, `` `search_files` ``, `` `vision_analyze` ``,
   `` `browser_navigate` ``, `` `delegate_task` ``, etc.). Do NOT
   name shell utilities the agent already has wrapped — `grep` →
   `search_files`, `cat`/`head`/`tail` → `read_file`, `sed`/`awk` →
   `patch`, `find`/`ls` → `search_files target='files'`. If the skill
   depends on an MCP server, name the MCP server and document the
   expected setup in `## Prerequisites`. Anything else (third-party
   CLIs, shell pipelines, etc.) is fair game inside script files but
   should not be the headline interaction surface in the prose.

3. **`platforms:` gating audited against actual script imports.**
   Skills that use POSIX-only primitives (`fcntl`, `termios`,
   `os.setsid`, `os.kill(pid, 0)` for liveness, `/proc`, `/tmp`
   hardcoded, `signal.SIGKILL`, bash heredocs, `osascript`, `apt`,
   `systemctl`) must declare their supported platforms. Default
   posture: try to fix it cross-platform first — `tempfile.gettempdir`,
   `pathlib.Path`, `psutil.pid_exists`, Python-level filtering instead
   of `grep`. Gate to a narrower set only when the dependency is
   genuinely platform-bound.

4. **`author` credits the human contributor first.** For external
   contributions, the contributor's real name + GitHub handle goes
   first; "Hermes Agent" is the secondary collaborator. If the
   contributor's commit shows "Hermes Agent" as author (because they
   used Hermes to draft the skill), replace it with their actual name
   — credit the human, not the tool.

5. **SKILL.md body uses the modern section order.** `# <Skill> Skill`
   title, 2-3 sentence intro stating what it does and doesn't do,
   `## When to Use`, `## Prerequisites`, `## How to Run`,
   `## Quick Reference`, `## Procedure`, `## Pitfalls`,
   `## Verification`. Target ~200 lines for a complex skill,
   ~100 lines for a simple one. Cut redundant intro fluff, marketing
   prose, and re-explanations of env vars already in
   `## Prerequisites`.

6. **Scripts go in `scripts/`, references in `references/`,
   templates in `templates/`.** Don't expect the model to inline-write
   parsers, XML walkers, or non-trivial logic every call — ship a
   helper script. Reference it from SKILL.md by path relative to the
   skill directory.

7. **Tests live at `tests/skills/test_<skill>_skill.py`** and use only
   stdlib + pytest + `unittest.mock`. No live network calls. Run via
   `scripts/run_tests.sh tests/skills/test_<skill>_skill.py -q`.

8. **`.env.example` additions are isolated to a clearly delimited
   block.** Don't touch the surrounding file — contributor-supplied
   `.env.example` versions are usually stale and edits outside the
   skill's own block must be dropped during salvage.

The full salvage / modernization checklist for external skill PRs
lives in the `hermes-agent-dev` skill at
`references/new-skill-pr-salvage.md` — load it before polishing
contributor skill PRs.

---

## Toolsets

All toolsets are defined in `toolsets.py` as a single `TOOLSETS` dict.
Each platform's adapter picks a base toolset (e.g. Telegram uses
`"messaging"`); `_HERMES_CORE_TOOLS` is the default bundle most
platforms inherit from.

Current toolset keys: `browser`, `clarify`, `code_execution`, `cronjob`,
`debugging`, `delegation`, `discord`, `discord_admin`, `feishu_doc`,
`feishu_drive`, `file`, `homeassistant`, `image_gen`, `kanban`, `memory`,
`messaging`, `moa`, `rl`, `safe`, `search`, `session_search`, `skills`,
`spotify`, `terminal`, `todo`, `tts`, `video`, `vision`, `web`, `yuanbao`.

Enable/disable per platform via `hermes tools` (the curses UI) or the
`tools.<platform>.enabled` / `tools.<platform>.disabled` lists in
`config.yaml`.

---

## Delegation (`delegate_task`)

`tools/delegate_tool.py` spawns a subagent with an isolated
context + terminal session. By default the parent waits for the
child's summary before continuing its own loop. With `background=true`,
Hermes returns a delegation id immediately and the result re-enters the
conversation later through the async-delegation completion queue.

Two shapes:

- **Single:** pass `goal` (+ optional `context`, `toolsets`).
- **Batch (parallel):** pass `tasks: [...]` — each gets its own subagent
  running concurrently. Concurrency is capped by
  `delegation.max_concurrent_children` (default 3).

Roles:

- `role="leaf"` (default) — focused worker. Cannot call `delegate_task`,
  `clarify`, `memory`, `send_message`, `cronjob`. Retains `execute_code`
  (programmatic tool calling).
- `role="orchestrator"` — retains `delegate_task` so it can spawn its
  own workers. Gated by `delegation.orchestrator_enabled` (default true)
  and bounded by `delegation.max_spawn_depth` (default 2).

Key config knobs (under `delegation:` in `config.yaml`):
`max_concurrent_children`, `max_spawn_depth`, `child_timeout_seconds`,
`orchestrator_enabled`, `subagent_auto_approve`, `inherit_mcp_toolsets`,
`max_iterations`.

Durability rule: background `delegate_task` is detached from the current
turn but still process-local. For work that must survive process restart, use
`cronjob` or `terminal(background=True, notify_on_complete=True)` instead.

---

## Curator (skill lifecycle)

Background skill-maintenance system that tracks usage on agent-created
skills and auto-archives stale ones. Users never lose skills; archives
go to `~/.hermes/skills/.archive/` and are restorable.

- **Core:** `agent/curator.py` (review loop, auto-transitions, LLM review
  prompt) + `agent/curator_backup.py` (pre-run tar.gz snapshots).
- **CLI:** `hermes_cli/curator.py` wires `hermes curator <verb>` where
  verbs are: `status`, `run`, `pause`, `resume`, `pin`, `unpin`,
  `archive`, `restore`, `prune`, `backup`, `rollback`.
- **Telemetry:** `tools/skill_usage.py` owns the sidecar
  `~/.hermes/skills/.usage.json` — per-skill `use_count`, `view_count`,
  `patch_count`, `last_activity_at`, `state` (active / stale /
  archived), `pinned`.

Invariants:
- Curator only touches skills with `created_by: "agent"` provenance —
  bundled + hub-installed skills are off-limits.
- Never deletes; max destructive action is archive.
- Pinned skills are exempt from every auto-transition and from the
  LLM review pass.
- `skill_manage(action="delete")` refuses pinned skills; patch/edit/
  write_file/remove_file go through so the agent can keep improving
  pinned skills.

Config section (`curator:` in `config.yaml`):
`enabled`, `interval_hours`, `min_idle_hours`, `stale_after_days`,
`archive_after_days`, `backup.*`.

Full user-facing docs: `website/docs/user-guide/features/curator.md`.

---

## Cron (scheduled jobs)

`cron/jobs.py` (job store) + `cron/scheduler.py` (tick loop). Agents
schedule jobs via the `cronjob` tool; users via `hermes cron <verb>`
(`list`, `add`, `edit`, `pause`, `resume`, `run`, `remove`) or the
`/cron` slash command.

Supported schedule formats:
- Duration: `"30m"`, `"2h"`, `"1d"`
- "every" phrase: `"every 2h"`, `"every monday 9am"`
- 5-field cron expression: `"0 9 * * *"`
- ISO timestamp (one-shot): `"2026-06-01T09:00:00Z"`

Per-job fields include `skills` (load specific skills), `model` /
`provider` overrides, `script` (pre-run data-collection script whose
stdout is injected into the prompt; `no_agent=True` turns the script
into the entire job), `context_from` (chain job A's last output into
job B's prompt), `workdir` (run in a specific directory with its
`AGENTS.md`/`CLAUDE.md` loaded), and multi-platform delivery.

Hardening invariants:
- **3-minute hard interrupt** on cron sessions — runaway agent loops
  cannot monopolize the scheduler.
- Catchup window: half the job's period, clamped to 120s–2h.
- Grace window: 120s for one-shot jobs whose fire time was missed.
- File lock at `~/.hermes/cron/.tick.lock` prevents duplicate ticks
  across processes.
- Cron sessions pass `skip_memory=True` by default; memory providers
  intentionally do not run during cron.

Cron deliveries are **not** mirrored into the target gateway session —
they land in their own cron session with a header/footer frame so the
main conversation's message-role alternation stays intact.

---

## Kanban (multi-agent work queue)

Durable SQLite-backed board that lets multiple profiles / workers
collaborate on shared tasks. Users drive it via `hermes kanban <verb>`;
workers spawned by the dispatcher drive it via a dedicated `kanban_*`
toolset so their schema footprint is zero when they're not inside a
kanban task.

- **CLI:** `hermes_cli/kanban.py` wires `hermes kanban` with verbs
  `init`, `create`, `list` (alias `ls`), `show`, `assign`, `link`,
  `unlink`, `comment`, `attach`, `attachments`, `attach-rm`, `complete`,
  `request-review`, `request-changes`, `reopen-review`, `block`, `unblock`, `archive`,
  `tail`, plus less-commonly-used `watch`, `stats`, `runs`, `log`,
  `assignees`, `heartbeat`, `notify-*`, `dispatch`, `daemon`, `gc`.
- **Worker/orchestrator toolset:** `tools/kanban_tools.py` exposes
  `kanban_show`, `kanban_complete`, `kanban_request_review`,
  `kanban_request_changes`, `kanban_block`,
  `kanban_heartbeat`, `kanban_comment`, `kanban_create`, `kanban_link`,
  `kanban_attach`, `kanban_attach_url`, `kanban_attachments`; profiles that
  explicitly enable the `kanban` toolset outside a dispatcher-spawned
  task also get `kanban_list` and `kanban_unblock` for board routing.
- **Dispatcher:** long-lived loop that (default every 60s) reclaims
  stale claims, promotes ready tasks, atomically claims, and spawns
  assigned profiles. Runs **inside the gateway** by default via
  `kanban.dispatch_in_gateway: true`.
- **Plugin assets:** `plugins/kanban/dashboard/` (web UI) +
  `plugins/kanban/systemd/` (`hermes-kanban-dispatcher.service` for
  standalone dispatcher deployment).

Isolation model:
- **Board** is the hard boundary — workers are spawned with
  `HERMES_KANBAN_BOARD` pinned in their env so they can't see other
  boards.
- **Tenant** is a soft namespace *within* a board — one specialist
  fleet can serve multiple businesses with workspace-path + memory-key
  isolation.
- After `kanban.failure_limit` consecutive non-success attempts on the
  same task (default: 2), the dispatcher auto-blocks it to prevent spin
  loops.

Full user-facing docs: `website/docs/user-guide/features/kanban.md`.

---

## Update Pipeline (`hermes update`)

The updater is transactional in shape (fleet-update campaign, #91277 —
Aug 2026). Every stage exists because its absence was a real field
failure; PRs that weaken a stage need to answer for the failure class it
guards:

```
plan → snapshot → apply → restart-per-kind → verify → report
```

- **Plan** (`hermes_cli/update_inventory.py`, `hermes update --plan`):
  read-only inventory — install kind, all profiles, every live gateway
  with supervisor + running code version. Deployment kinds are
  first-class: `git` updates in place; `docker`/`nix`/`apt` are NOT
  in-place-updatable and the updater reports the correct external
  command instead of fighting the deployment model.
- **Snapshot** (`hermes_cli/backup.py`): pre-update quick snapshot for
  EVERY profile (the code swap + fleet restart touch all of them), each
  into its own `state-snapshots/`, identical file set + 1 GiB per-file
  cap + keep=1. **Never add a partial/tiered snapshot set** — mixed
  coverage creates torn-restore states across schema generations. Quick
  snapshots are FILE-LOSS RECOVERY (the per-profile cron-jobs safety
  net restores from them), NOT code-rollback insurance; `--backup` full
  mode owns rollback.
- **Apply**: git pull, or the Windows ZIP fallback — which fires ONLY
  when git itself failed (`_should_zip_fallback_on_update_error`,
  argv-classified; a dependency-install failure must never trigger a
  tree-clobbering re-download), REFUSES a dirty working tree
  (`-uall`, plus a pre-swap TOCTOU re-check), and grafts the live
  `apps/desktop/release/` into the staged swap (the GitHub source ZIP
  has no built desktop app; without the graft the swap deletes it).
- **Restart-per-kind**: systemd and launchd restarts are FLEET-WIDE
  (every `hermes-gateway*` unit / `ai.hermes.gateway*` LaunchAgent),
  drain-first (SIGUSR1) with per-unit/per-label failure isolation.
  Restarting only the invoking profile's service leaves siblings on
  stale `sys.modules` until they crash — the largest dupe-PR cluster in
  the repo's history came from that bug.
- **Verify**: gateways stamp their running `code_sha`/`code_version`
  into `gateway_state.json` on every runtime-status write
  (`gateway/status.py`); after the restart phase the updater compares
  each live gateway against the fresh checkout and prints a fleet
  version matrix. A provably-stale gateway fails the update (exit 1) —
  automation must never treat a mixed-version fleet as healthy.
- **Report**: every run writes a machine-readable receipt to
  `~/.hermes/logs/update_receipts/` (`latest.json` pointer; steps,
  skips WITH reasons, restart outcome, plan, fleet snapshot).
  Finalization is owned by the `cmd_update` command boundary — early
  `sys.exit` paths (preflight refusals, fetch failures) still persist
  a receipt with the real exit code. A begun-but-unwritten receipt is
  a bug: the refused/failed runs are the ones receipts exist for.

Architecture direction: process-scan-based coordination between the
updater, serve/dashboard, and the gateway is being replaced by a
gateway-owned control socket (#92091). Do not add new scan heuristics
without checking that design; scans are the fallback layer.

### Gateway lifecycle vs. the Desktop app

`hermes serve` (control plane, desktop-spawned child) dies with the app
— by design. The messaging gateway (`gateway run`) SURVIVES the app: the
serve backend's `/api/gateway/*` endpoints spawn it detached
(`_spawn_hermes_action` — `start_new_session` / `DETACHED_PROCESS`), so
`before-quit`'s backend SIGTERM never reaches it. Bots keep running
when the user closes the app. The known breach of this contract is the
Windows shim-unlock teardown (`taskkill /T /F` on venv-shim holders,
#85265) — it exists to let updates proceed, and its replacement is
#92091's `pause-for-update`. Do not "fix" gateway-dies-with-app reports
by re-parenting the gateway under the backend, and do not "fix" update
locks by widening the tree-kill.

---

## Important Policies

### Prompt Caching Must Not Break

Hermes-Agent ensures caching remains valid throughout a conversation. **Do NOT implement changes that would:**
- Alter past context mid-conversation
- Change toolsets mid-conversation
- Reload memories or rebuild system prompts mid-conversation

Cache-breaking forces dramatically higher costs. The ONLY time we alter context is during context compression.

Slash commands that mutate system-prompt state (skills, tools, memory, etc.)
must be **cache-aware**: default to deferred invalidation (change takes
effect next session), with an opt-in `--now` flag for immediate
invalidation. See `/skills install --now` for the canonical pattern.

### Background Process Notifications (Gateway)

When `terminal(background=true, notify_on_complete=true)` is used, the gateway runs a watcher that
detects process completion and triggers a new agent turn. Control verbosity of background process
messages with `display.background_process_notifications`
in config.yaml (or `HERMES_BACKGROUND_NOTIFICATIONS` env var):

- `concise` — one-line status message on completion; failures append a short output tail (default)
- `all` — running-output updates + final raw-output message
- `result` — only the final raw-output completion message
- `error` — only the final raw-output message when exit code != 0
- `off` — no watcher messages at all

---

## Profiles: Multi-Instance Support

Hermes supports **profiles** — multiple fully isolated instances, each with its own
`HERMES_HOME` directory (config, API keys, memory, sessions, skills, gateway, etc.).

The core mechanism: `_apply_profile_override()` in `hermes_cli/main.py` sets
`HERMES_HOME` before any module imports. All `get_hermes_home()` references
automatically scope to the active profile.

### Rules for profile-safe code

1. **Use `get_hermes_home()` for all HERMES_HOME paths.** Import from `hermes_constants`.
   NEVER hardcode `~/.hermes` or `Path.home() / ".hermes"` in code that reads/writes state.
   ```python
   # GOOD
   from hermes_constants import get_hermes_home
   config_path = get_hermes_home() / "config.yaml"

   # BAD — breaks profiles
   config_path = Path.home() / ".hermes" / "config.yaml"
   ```

2. **Use `display_hermes_home()` for user-facing messages.** Import from `hermes_constants`.
   This returns `~/.hermes` for default or `~/.hermes/profiles/<name>` for profiles.
   ```python
   # GOOD
   from hermes_constants import display_hermes_home
   print(f"Config saved to {display_hermes_home()}/config.yaml")

   # BAD — shows wrong path for profiles
   print("Config saved to ~/.hermes/config.yaml")
   ```

3. **Module-level constants are fine** — they cache `get_hermes_home()` at import time,
   which is AFTER `_apply_profile_override()` sets the env var. Just use `get_hermes_home()`,
   not `Path.home() / ".hermes"`.

4. **Tests that mock `Path.home()` must also set `HERMES_HOME`** — since code now uses
   `get_hermes_home()` (reads env var), not `Path.home() / ".hermes"`:
   ```python
   with patch.object(Path, "home", return_value=tmp_path), \
        patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / ".hermes")}):
       ...
   ```

5. **Gateway platform adapters should use token locks** — if the adapter connects with
   a unique credential (bot token, API key), call `acquire_scoped_lock()` from
   `gateway.status` in the `connect()`/`start()` method and `release_scoped_lock()` in
   `disconnect()`/`stop()`. This prevents two profiles from using the same credential.
   See `plugins/platforms/irc/adapter.py` for the canonical pattern.

6. **Profile operations are HOME-anchored, not HERMES_HOME-anchored** — `_get_profiles_root()`
   returns `Path.home() / ".hermes" / "profiles"`, NOT `get_hermes_home() / "profiles"`.
   This is intentional — it lets `hermes -p coder profile list` see all profiles regardless
   of which one is active.

7. **Multiplex profile-scoped env reads MUST fail closed — never borrow from `os.environ`**
   (`agent/secret_scope.py` contract; #72348, #86905). Under `gateway.multiplex_profiles`,
   `os.environ` holds the **default profile's** values; a secondary profile's `.env` lives
   only in its secret scope (installed per-turn by `_profile_runtime_scope`). Any
   profile-level env config — credentials (`app_secret`, tokens) AND authorization
   (`FEISHU_ALLOWED_USERS`, `{PLATFORM}_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`,
   `group_policy`, `allow_bots`, ...) — must be read scope-aware:
   - Adapters: `_get_scoped_secret()` (canonical fail-closed copy in
     `plugins/platforms/feishu/adapter.py`, #86905).
   - Gateway authz: `_auth_env()` / `_platform_gate_env()` (`gateway/authz_mixin.py`).
   Rules:
   - Scope installed + multiplex active → a scoped miss returns the **default**.
     NEVER fall through to `os.environ` — that leaks another profile's value and
     silently breaks routing/admission (a leaked default allowlist skips the
     allow-all check and rejects every secondary-profile sender, #86905).
   - Unscoped default-profile path (`UnscopedSecretError`) and single-profile
     deployments keep the `os.environ` read — there it IS the profile's own value.
   - Authorization config is the sharpest edge: allowlist/allow-all leaks cause
     silent rejections (or worse, fail-open) that only show up as missing replies.
   - The `_get_scoped_secret` wrapper is copy-pasted across ~15 platform adapters —
     when touching any of them, make sure the fail-closed semantics are present;
     do not reintroduce the `except _UnscopedSecretError: val = os.getenv(...)`
     fallback-after-miss shape.

## Known Pitfalls

### DO NOT infer process identity from argv substrings
The bug class behind ~10 fleet-update issues (#90778, #87594, #78089,
#76129, #91964, ...): classifying a process by `"serve" in cmdline` or
similar. `kanban --preserve-cache` contains "serve"; a flag VALUE can
equal a subcommand (`-m dashboard serve`); truncated cmdlines hide the
real subcommand. Rules:
- Use the canonical matchers: `gateway.status.looks_like_gateway_command_line`
  (gateway run), `hermes_cli.update_cmd._hermes_holder_subcommand`
  (top-level subcommand of any Hermes argv). Never hand-roll token scans.
- Flag sets must be DERIVED from the parser
  (`_holder_value_flags()` introspects `build_top_level_parser()`), never
  hand-written lists — they drift.
- Never blanket-exclude ancestors from process scans: when `/update` runs
  as the gateway's child, a gateway ancestor must stay visible to the
  pause machinery (#87594). Exclude interactive ancestry, carve out
  gateway-shaped ancestors.
- Match on FULL cmdlines; truncate only at display time (#78089).
- Before adding any new scan heuristic, read #92091 — the gateway control
  socket replaces scans as the primary coordination mechanism; scans are
  the fallback layer for old/crashed processes.

### DO NOT hardcode `~/.hermes` paths
Use `get_hermes_home()` from `hermes_constants` for code paths. Use `display_hermes_home()`
for user-facing print/log messages. Hardcoding `~/.hermes` breaks profiles — each profile
has its own `HERMES_HOME` directory. This was the source of 5 bugs fixed in PR #3575.

### All CLI menu-pickers MUST use curses.
Interactive menus must use `hermes_cli/curses_ui.py`. See `hermes_cli/tools_config.py` for an example.

### DO NOT use `\033[K` (ANSI erase-to-EOL) in spinner/display code
Leaks as literal `?[K` text under `prompt_toolkit`'s `patch_stdout`. Use space-padding: `f"\r{line}{' ' * pad}"`.

### `_last_resolved_tool_names` is a process-global in `model_tools.py`
`_run_single_child()` in `delegate_tool.py` saves and restores this global around subagent execution. If you add new code that reads this global, be aware it may be temporarily stale during child agent runs.

### DO NOT hardcode cross-tool references in schema descriptions
Tool schema descriptions must not mention tools from other toolsets by name (e.g., `browser_navigate` saying "prefer web_search"). Those tools may be unavailable (missing API keys, disabled toolset), causing the model to hallucinate calls to non-existent tools. If a cross-reference is needed, add it dynamically in `get_tool_definitions()` in `model_tools.py` — see the `browser_navigate` / `execute_code` post-processing blocks for the pattern.

### The gateway has TWO message guards — both must bypass approval/control commands
When an agent is running, messages pass through two sequential guards:
(1) **base adapter** (`gateway/platforms/base.py`) queues messages in
`_pending_messages` when `session_key in self._active_sessions`, and
(2) **gateway runner** (`gateway/run.py`) intercepts `/stop`, `/new`,
`/queue`, `/status`, `/approve`, `/deny` before they reach
`running_agent.interrupt()`. Any new command that must reach the runner
while the agent is blocked (e.g. approval prompts) MUST bypass BOTH
guards and be dispatched inline, not via `_process_message_background()`
(which races session lifecycle).

### Streaming delivery contract (stream-is-the-message adapters) — duplicate-final class
Adapters with `draft_stream_is_message = True` (relay Slack native streaming)
keep ONE cumulative native stream per turn; the stream IS the final message.
Four invariants, each learned from a live duplicate-final incident (NS-658
canary ledger, hermes#85796 / gateway-gateway#210). Violating any of them
re-creates a duplicate or a frozen stream:

1. **Draft frames must be prefix-stable.** The connector computes append-only
   deltas: frame N must be a string prefix of frame N+1. NEVER mutate draft
   frames per-tick — no fence-closing (`ensure_closed_code_fences`), no cursor
   suffix, no segment-state resets at tool boundaries, no mrkdwn conversion.
   Any non-prefix frame triggers a whole-snapshot re-append on the platform
   ("stacked copies"). The finalize path may still transform the real final.
2. **The consumer declares the final; the adapter never guesses.**
   `finish(final_text)` carries the completed `final_response` (verifier
   footer, completion explainer included) as the authoritative finalize
   payload. New post-stream response augmentation MUST ride this payload —
   if it mutates `final_response` after the stream sealed, it re-opens the
   #11 bug (`delivered_final_matches` mismatch → corrective duplicate send).
3. **Interim sends must carry `_interim_send` metadata.** Any consumer-side
   `adapter.send()` that is NOT the turn-final (commentary, segment-tail
   flushes) must set `metadata["_interim_send"] = True`, or the relay
   adapter's seal-interception will seal the live stream with interim text.
   Seal-interception exists at BOTH egress doors (`send()` AND
   `send_for_platform()`); a new egress door needs the same two checks.
4. **Reconcile by edit, never by plain send.** Any lane that delivers a final
   beside an already-sealed stream (queued follow-ups, media-accompanied
   finals, future lanes) must first try `edit_message` on the consumer's
   `message_id`; plain `send()` is the fallback only when no editable message
   exists. A sealed native stream is a regular message — `chat.update` on it
   works (live-verified).

Contract tests: `tests/gateway/test_stream_final_contract.py` (all four
invariants, mutation-checked). Slack streaming API ground truth (live-probed,
also encoded in connector comments/tests): `chat.*Stream` speaks STANDARD
markdown, not mrkdwn; `stopStream.markdown_text` APPENDS (never replaces);
`startStream`/`stopStream` are rate-limit Tier 2 (~20/min).

Guard style note: check `draft_stream_is_message` with `is True` — MagicMock
adapters in older tests auto-create truthy attributes.

### Squash merges from stale branches silently revert recent fixes
Before squash-merging a PR, ensure the branch is up to date with `main`
(`git fetch origin main && git reset --hard origin/main` in the worktree,
then re-apply the PR's commits). A stale branch's version of an unrelated
file will silently overwrite recent fixes on main when squashed. Verify
with `git diff HEAD~1..HEAD` after merging — unexpected deletions are a
red flag.

### Don't wire in dead code without E2E validation
Unused code that was never shipped was dead for a reason. Before wiring an
unused module into a live code path, E2E test the real resolution chain
with actual imports (not mocks) against a temp `HERMES_HOME`.

### Tests must not write to `~/.hermes/`
The `_isolate_hermes_home` autouse fixture in `tests/conftest.py` redirects `HERMES_HOME` to a temp dir. Never hardcode `~/.hermes/` paths in tests.

**Profile tests**: When testing profile features, also mock `Path.home()` so that
`_get_profiles_root()` and `_get_default_hermes_home()` resolve within the temp dir.
Use the pattern from `tests/hermes_cli/test_profiles.py`:
```python
@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home
```

---

## Testing

### Python
**ALWAYS use `scripts/run_tests.sh`** — do not call `pytest` directly. The script enforces
hermetic environment parity with CI (unset credential vars, TZ=UTC, LANG=C.UTF-8,
per-file subprocess isolation via `scripts/run_tests_parallel.py` — no xdist,
worker count auto-scaled from CPU count). Direct `pytest`
on a 16+ core developer machine with API keys set diverges from CI in ways
that have caused multiple "works locally, fails in CI" incidents (and the reverse).

```bash
scripts/run_tests.sh                                  # full suite, CI-parity
scripts/run_tests.sh tests/gateway/                   # one directory
scripts/run_tests.sh tests/agent/test_foo.py -k test_x  # one test (file + -k; the runner is file-granular)
scripts/run_tests.sh -v --tb=long                     # pass-through pytest flags
```

**Flake policy:** the runner auto-retries a failing test FILE once in a fresh
subprocess (`--file-retries`, default 1; `HERMES_TEST_FILE_RETRIES=0` to
disable). Pass-on-retry counts as green but is printed in a `⚠ FLAKY` summary
section with both attempts' output. A FLAKY report is a bug to fix, not noise
to ignore — timing-sensitive tests must not assume a quiet runner (loose
wall-clock bounds ≥ 2s, event-based sync, no `assert not _wait_until(...)`
negative-timing races).

#### Subprocess-per-test-file isolation

Every test file runs in a freshly-spawned Python subprocess via `run_tests_parallel.py`. This means module-level dicts/sets and
ContextVars from one test file cannot leak into the next.

#### Why the wrapper

|                     | Without wrapper                             | With wrapper                              |
| ------------------- | ------------------------------------------- | ----------------------------------------- |
| Provider API keys   | Whatever is in your env (auto-detects pool) | All env vars except a specific few unset. |
| HOME / `~/.hermes/` | Your real config+auth.json                  | Temp dir per test                         |
| Timezone            | Local TZ (PDT etc.)                         | UTC                                       |
| Locale              | Whatever is set                             | C.UTF-8                                   |

### Where to place what tests

The CI change classifier (`scripts/ci/classify_changes.py`) runs specific jobs based on what files changed. A Python test that asserts
about the contents of `package.json`, `package-lock.json`, `.ts`/`.tsx`
source, or any other JS-side artifact will not run on a PR that only touches
those files. This means a regression can go green on a PR and red on `main` (where the
classifier fails open and runs everything).

Any test that reads or asserts about `package.json`,
`package-lock.json`, `tsconfig.json`, `.ts`/`.tsx`/`.js`/`.mjs`/`.cjs`
source files configuration belongs in the JS (vitest) test suite, not in `tests/*.py`.

### Don't fake the host OS

Hermes supports Linux, macOS and native Windows, and plenty of its behaviour
genuinely differs per host. Those differences are tested by running on the
host, not by patching `sys.platform`.

```python
@pytest.mark.linux_only
@pytest.mark.macos_only
@pytest.mark.windows_only
```

Things that are host-independent can stay unmarked:

- **Pure functions that take a platform as data** —
  `hidden_windows_child_options(opts, is_windows=True)` is input→output, not a
  fake host. (Contrast: setting a module-level `IS_WINDOWS` flag and then
  calling `windows_detach_flags()` *is* a fake.)
- **Declaration/packaging invariants** — "pyproject declares `tzdata` with a
  `sys_platform == 'win32'` marker" asserts about a file, not about runtime.

The line: **if the test needs the interpreter to believe it is on another OS
in order to pass, it belongs on that OS.**
When one test body walks several platforms in sequence, split it.
Keep the host-native arm on the Linux lane and move the other arm into its own marked test.

**Live Windows process-topology E2E: the `wine2e` lane.** For claims about
real Windows process behavior that mocks cannot reproduce (venv-holder
scans, process-tree parentage, launcher/worker chains, detach semantics),
there is an on-demand workflow `windows-venv-e2e.yml` that runs
`tests/hermes_cli/test_venv_holder_windows_live.py` on a real
`windows-latest` runner — spawning actual processes and driving the real
detection code, no mocked psutil. It fires ONLY on pushes to `wine2e/**`
branches (inert on PRs and main; costs nothing on normal work). The proven
workflow: write probes that pin CORRECT behavior, push to a `wine2e/`
branch to reproduce the bugs live on unfixed code, build the fix, iterate
until the lane is green, then open the PR — the live receipt on the exact
head is the Windows proof reviewers ask for. Extend the live suite when
touching that subsystem; assert against the gateway ANCESTOR found by
argv, not the direct parent (the venv shim makes every spawn a
launcher/worker chain).

**Use the marker, never a bare `skipif`.** `scripts/ci/list_os_marked_tests.py`
decides which files the macOS/Windows lanes import by grepping for the marker
*name*, and the lane then filters with `-m <marker>`. A test gated with
`@pytest.mark.skipif(sys.platform != "win32")` therefore skips on Linux AND is
never imported on the Windows lane — it runs on no host at all, silently. The
same trap catches a file-local alias (`windows_only = pytest.mark.skipif(...)`):
the grep matches the name, so the file *is* listed, but `-m windows_only`
deselects every test in it and the lane reports green over zero coverage.
Equally, don't `pytest.skip()` the non-host rows of a `@parametrize` over
platforms — split it into one marked test per OS, or only the host's row ever
executes.

### Don't write change-detector tests

A test is a **change-detector** if it fails whenever data that is **expected
to change** gets updated — model catalogs, config version numbers,
enumeration counts, hardcoded lists of provider models. These tests add no
behavioral coverage; they just guarantee that routine source updates break
CI and cost engineering time to "fix."

**Do not write:**

```python
# catalog snapshot — breaks every model release
assert "gemini-2.5-pro" in _PROVIDER_MODELS["gemini"]
assert "MiniMax-M2.7" in models

# config version literal — breaks every schema bump
assert DEFAULT_CONFIG["_config_version"] == 21

# enumeration count — breaks every time a skill/provider is added
assert len(_PROVIDER_MODELS["huggingface"]) == 8
```

**Do write:**

```python
# behavior: does the catalog plumbing work at all?
assert "gemini" in _PROVIDER_MODELS
assert len(_PROVIDER_MODELS["gemini"]) >= 1

# behavior: does migration bump the user's version to current latest?
assert raw["_config_version"] == DEFAULT_CONFIG["_config_version"]

# invariant: no plan-only model leaks into the legacy list
assert not (set(moonshot_models) & coding_plan_only_models)

# invariant: every model in the catalog has a context-length entry
for m in _PROVIDER_MODELS["huggingface"]:
    assert m.lower() in DEFAULT_CONTEXT_LENGTHS_LOWER
```

The rule: if the test reads like a snapshot of current data, delete it. If
it reads like a contract about how two pieces of data must relate, keep it.
When a PR adds a new provider/model and you want a test, make the test
assert the relationship (e.g. "catalog entries all have context lengths"),
not the specific names.

Reviewers should reject new change-detector tests; authors should convert
them into invariants before re-requesting review.

### Never read source code in tests

A test that reads a source file's text is testing *the shape of the
source code*, not its behavior. This is a hard antipattern, banned outright.
Any test that reads a .py, .ts, .tsx, etc., file is suspect.

**Why it's actively harmful, not just weak:**

- It passes when the implementation is subtly broken (the regex matches a
  call site that exists but is wired wrong) and fails when a correct
  refactor changes formatting, variable names, or control flow with
  identical runtime behavior. Both directions of failure are wrong.
- It can't be run against a built/bundled/minified artifact, so it silently
  stops testing anything the moment code moves, gets renamed, or a
  dependency reformats it.
- It actively blocks refactors: reviewers see "keeps a pattern intact" tests
  fail during pure structural cleanup with no behavior change, and either
  hand-wave the failure (dangerous) or waste time updating regexes that add
  nothing (waste).
- It gives false confidence. a green suite full of source-regex tests
  looks like coverage but has never once executed the code path it claims
  to guard.

**Do not write:**

```ts
const source = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8')

test('backend spawn hides the Windows console', () => {
  assert.match(source, /spawn\(\s*backend\.command,\s*backend\.args[\s\S]{0,300}hiddenWindowsChildOptions/)
})
```

**Do write — extract the logic into a small pure/DI-testable function and
call it for real:**

```ts
// backend-spawn.ts
export function hiddenWindowsChildOptions(options: SpawnOptionsLike = {}, isWindows = process.platform === 'win32') {
  if (!isWindows || 'windowsHide' in options) return options
  return { ...options, windowsHide: true }
}

// backend-spawn.test.ts
test('windowsHide defaults to true on Windows, is left alone elsewhere', () => {
  assert.equal(hiddenWindowsChildOptions({}, true).windowsHide, true)
  assert.equal(hiddenWindowsChildOptions({}, false).windowsHide, undefined)
  assert.equal(hiddenWindowsChildOptions({ windowsHide: false }, true).windowsHide, false)
})
```

If the logic lives inline in a god-file (`main.ts`, `cli.py`,
`gateway/run.py`) and extracting it feels disruptive: that's the actual
signal to do the extraction, not to regex around it.

## Cross-App Synchronized Updates Across the Connected Ecosystem (Mandatory)
Whenever any change is made in one connected ecosystem project (`BrainCore`, `NovoBiz`, `BIH-Dashboard`, `ControlX`, `AiMailx`, `Tony`, `MyDataX`, `Notely`, `GTD`, `Hermes`, `AgentBroker`, `OpenClaw`, `FloatMic`, `OpenIntelligentUI`), first check `/Users/yb/Dev/projects/BrainCore/config/connected-apps.json` and `/Users/yb/Dev/projects/BrainCore/brain-schema.yaml` to identify every linked/related app that produces, consumes, or displays that data or workflow. Update all linked projects, bridges, schemas, and sync pipelines in the same task so no connected app is ever left out of sync or unaware of a change made in another app.

## Complete UI/UX, Mobile App, Responsiveness, and Continuous Self-Learning Design Guidelines
Follow `/Users/yb/Dev/ai-rules/global-agents.md` §17 and `/Users/yb/Dev/projects/BrainCore/ECOSYSTEM_AI_RULES.md`:
1. **Responsive & Mobile/Tablet/Desktop Design Standards (From First Implementation)**: Responsive across mobile portrait (`375px–430px`), mobile landscape, tablet (`768px–1024px`), and widescreen desktop (`12-column` full-width utilization). Single-row scope bar; hide redundant `[ Entity ]` or `[ Entity + Brands / Entity Only ]` pills when an entity has `0` subsidiary brands; always show the normalized Business Sector badge for every Entity and every Brand. Sticky in-scroll headers (`z-10` below `z-40`/`z-30` top bar) & single-row adaptive segment/tab bars (short mobile labels, never wrapping onto 2–3 rows). Zero static policy rows & zero standalone closed-state toggle cards. Compact 2/3-column KPI cards & zero-horizontal-scroll tables app-wide (`< 1024px` single-DOM responsive table-to-card grids or compact 3-column `table-fixed`). `Quicksand` dominant UI font, **Title Case** labels, **No emojis** in product UI, signed-in Google profile image, read-only badges for system fields, optimistic UI, Drag-and-Drop + Click-to-Browse for all uploads, contextual related-record shortcuts, and PWA pull-to-refresh + foreground update checks.
   - **Edge-to-Edge Header & Card Padding Alignment**: Top header left/right distance from screen edges must match the card list below (`12px` on GTD phones in portrait and landscape, preserving native safe areas; the existing `6px` compact-mobile rule remains for other apps, `8px` on tablet, `14px` on wide desktop).
   - **Unified Top Header Chrome & Zero Vacant Secondary Headers**: Secondary views (`Organizations`, `Profile`, `Settings`, details, tools) must use a compact single-row top bar (`58px + safe-area-top`) with the **exact same UI chrome as the main Home Screen** (left **Back Arrow** + **iOS left-edge swipe-back** `startX <= 36px` + left-aligned `20px` title, and right notification count capsule + yellow bell + vertical divider + `32px` white-bordered circular profile avatar), while allowing only the header background color to differ by context. On directory screens (`Organizations`, `Memberships`), keep the 2-button action strip (`All Organizations (N)` + `Add` or `Brands`) and search bar inside a **fixed non-scrolling subheader** with **harmonized `32px` stadium capsules** (`999px` radius, `11.5px–12px` Title Case text, `14px` icons) and **zero extra gap** above the independently scrolling card list — **NEVER** render a manual `Sync NovoBiz` button on `Organizations` or `Memberships`; NovoBiz ↔ BrainCore synchronization must always run silently and automatically two-way in the background.
   - **Always Harmonized, Symmetric & Aligned Design Across All Headers, Cards, and Modal Sheets**: Every 3-row header (`Home Screen`, `Quick Tasks`, mode-strip views, `Organizations`, `Memberships`) must share identical total height (`--gtd-3row-height`), row vertical coordinates (`--gtd-3row-r1-top`, `--gtd-3row-r2-top`, `--gtd-3row-r3-top`), and a 100% identical full-width Row-3 search bar UI (`.gtd-search-bar` with `10px` radius, `18px` search icon, `16px` `Quicksand` bold input, and `22px` circular clear button with zero extra trailing buttons); every topbar icon, container, notification pill, bell, vertical divider, view-density toggle button/icon, back/menu button, avatar, title, and pending count capsule on `Quick Tasks` and all `.topbar` screens must scale by `var(--gtd-hdr-scale, 1)` to match the Home Screen (`My Tasks` / `Team Tasks`) to the exact pixel, with the horizontal gap between the left menu/back button and the view title (`My Tasks` / `Team Tasks` / page title) equal to the horizontal gap (`7px` design / `calc(7px * var(--gtd-hdr-scale, 1))`) between the title and its pending task count capsule; and every detail/editor modal sheet (`QuickTaskDetails`, `TaskDetails`, `QuickTaskEditor`, `TaskEditor`) must render as a symmetric floating card (`26px` radius, `10px` side inset, centered `.adalo-sheet-handle`, natural-height brand header band without hardcoded gradient seams, horizontally aligned top action buttons, balanced 3-column metadata cards, and framed URL/note cards).
   - **Dynamic Auto-Height Cards & Uncompressed Scroll Grid/Flex Tracks (Zero Card-Boundary Overflow)**: Every scrollable card list, directory grid, or panel stack across the app (`overflow-y: auto`) must use `grid-auto-rows: max-content` + `align-content: start` (when using CSS Grid) or `flex-shrink: 0` on every child card (when using Flexbox), and every card (`height: auto`, `grid-template-rows: auto`, `flex: 0 0 auto`, `overflow: hidden`) must dynamically expand to wrap multi-line titles, badges, and footer stats without compressing grid tracks to `min-height` or letting inner rows bleed across card borders.
   - **Native Drawer Dismissal & Streamlined Primary Menu**: Side drawers must support interactive swipe-left dismissal and backdrop tap dismissal without needing the `X` button, keep only core daily workflows in the primary drawer, and group secondary planning/intelligence/sync utilities inside Settings.
   - **Left-Aligned View Titles with Pending-Only Count Capsule ONLY on Task Views (`[ Black: Pending ]`)**: Primary and team/filtered task headers must stay consistently left-aligned (`left: 12px` on GTD phones in portrait and landscape, preserving native safe areas; retain existing spacing in other apps) with a compact black capsule showing **only the Pending (incomplete) count**, and **only on Task views** (`My Tasks`, `Team Tasks`, `Today`, `Focus`, `Quick Tasks`, `Scheduled`) — **never** render task count capsules on non-task screens (`Organizations`, `Profile`, `Settings`, `Completed`, `Memberships`, `Sync`, etc.).
   - **Entity & Organization Provenance Badge + Authentic NovoBiz Logo & Brand Sync (`NovoBiz · ENT-*` / `BRD-*` vs `Created in <App>`)**: Every organization, entity, or brand project card and detail view must clearly show whether it was synced from `NovoBiz / BrainCore` (`ENT-*` / `BRD-*`) or created locally (`Created in <App>`), display its authentic NovoBiz Firebase Storage `logoUrl` (`object-fit: contain` on white framed backing) and normalized Business Sector badge, and silently/automatically sync two-way in the background with the 7 canonical NovoBiz companies (`ENT-BIH`, `ENT-NS`, `ENT-CD`, `ENT-BP`, `ENT-BINC`, `ENT-PF`, `ENT-MC`) and 6 real NovoBiz brands (`Calorie Co.` `BRD-CAL`, `Little Things Co.` `BRD-LTC`, `Novo Lumina` `BRD-LUM`, `Novo Nexa` `BRD-NEX`, `Novo Praxis` `BRD-PRX`, `Buch Executive Villas` `BRD-BEV`) without any manual `Sync NovoBiz` button.
2. **Mandatory Audit of Existing Screens + Continuous Self-Learning Loop**: Whenever designing something new OR touching an existing screen across any project, audit the existing screen against these guidelines and fix any violations immediately. Whenever the owner points out a new UI/UX improvement or design change in the future, automatically update all global IDE rule files across all IDEs and launch a background subagent to fix matching occurrences across the project.

## Automatic Context Window Handoff (Mandatory)
If the task is **completed** (even in a long or compacted chat), update `docs/handoff.md` (when present) and tell Yasir directly that **the task is completed and there is no need for a handoff prompt** (do not output a paste-ready continuation prompt). Only when work is **still unfinished** AND a chat becomes genuinely long (**8+ substantive turns**, **~65%+ context usage**, or after **context compaction/truncation**)—never after just 1–3 prompts—**automatically and immediately** update `docs/handoff.md` (when present), output a **paste-ready continuation prompt** in chat, and tell Yasir directly to start the next chat. Never wait for Yasir to ask for a handoff prompt or offer a vague "if you think the chat is too long" choice. Follow `/Users/yb/Dev/ai-rules/global-agents.md` § **Context window handoff (all projects)**.

## AI MailX Formatted Self-Drafting Standard (All IDEs — 20 October 2026)

Whenever Yasir asks to draft, write, or prepare an email in **any** project or IDE:
1. **Automatically Save to AI MailX Drafts (`POST http://127.0.0.1:18790/emails/drafts` with `draft_html`)**: Never output an email only in chat or hold it only in a markdown file. Always save it directly into the **AI MailX** `Drafts` folder (`folder_path: "Drafts"`) via `POST http://127.0.0.1:18790/emails/drafts` with `draft_html` included on creation (and synced to `drafts.draft_html` + `emails.email_body`), using the matching sender account (`yasirbucha@buchhospital.com`, `yasirbucha@buchvillas.com`, `yasirbucha@novosphere.info`, `yasirbucha@binc.pk`, `yasirbucha@payfor.pk`, or `yasirbucha@gmail.com`) and its official HTML signature from `pim_data.db` (`email_signatures` / `signature_defaults`). When redrafting, delete the old draft ID first so AI MailX never serves a cached plain-text body.
2. **First-Name Greeting Only & Compose-Native Indented Lists (`<ol>` + Nested `<ul>`)**:
   - **Greeting**: Always open with the recipient's **first name + comma** in bold (e.g., `<p style="margin: 0.0px 0.0px 13.2px 0.0px; ..."><b>Fahad,</b></p>`) — **NEVER** write `"Dear ..."`, `"Hi ..."`, or `"Good day"`.
   - **Paragraphs & Nested Lists for `ComposeNativeTextEditor.swift`**: Use `<p style="margin: 0.0px 0.0px 13.2px 0.0px; font-size: 13.2px; font-family: Nunito, 'Trebuchet MS', Verdana, Helvetica, sans-serif; color: #000000; line-height: 1.35;">` (without `data-aimailx-compose-line="true"`, which `prepareHtmlForComposeEditor` strips to unstyled `<p>`) and real `<ol>` numbered items with nested `<ul>` sub-bullets (`<ol><li><b>Numbered Heading</b><ul><li>Indented sub-bullet...</li></ul></li></ol>`) so AppKit's `NSTextView` indents sub-bullets at Level 2 (`firstLineHeadIndent = 36pt`, `headIndent = 72pt`).
3. **First-Person Singular Voice, Plain-English Scenarios & Verified Recipients**: Always write in Yasir's first-person singular voice (`"I"`, `"my"`, `"me"` — never `"we"`, `"our"`, `"us"`), explain real-world scenarios and corrective plans in plain, simple English rather than raw database column jargon, and disambiguate recipients via `pim_data.db` / BIH-Dashboard designations before saving.


## Compact Dashboard Connected Apps (Owner, 21 October 2026)

For NovoBiz dashboards, place cross-app shortcuts in one compact **Connected Apps** button in the existing dashboard header. Open the full shortcut list only on demand; do not reserve a standalone always-visible bar for these secondary links. Preserve all six existing destinations, selected company/brand scope, permission checks, and contextual record links. Verify the menu on mobile and desktop. This is a dashboard presentation preference, not authorization to change destination contracts or unrelated workflows. Every IDE must preserve and synchronize future owner design guidelines across the shared IDE rules and connected app instructions.


## Brief Email Disclosure (Owner, 21 October 2026)

In AI MailX, opening Brief shows the Brief alone. Reveal the selected conversation below it only after **View Thread Below** is clicked; selecting a card or subject must not reveal it. Reopening Brief resets the revealed conversation, and closing Brief restores normal reading. Viewing a Brief or its conversation must not itself mark mail read. Apply the same behavior on mobile and desktop. This is a presentation rule, not permission to change shared data contracts. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.

## FloatMic iPhone Live Dictation At The Cursor (Owner, 21 October 2026)

For the FloatMic iPhone keyboard, Speak should display live dictated text at the active text-field cursor rather than inside the keyboard. Keep this scope specific to iPhone FloatMic; preserve surrounding user text and the existing final-transcription/history behavior. Shared computer/phone testing must wait for all earlier coordinator queue tasks and a fresh grant. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## NovoBiz Catalog Products And Raw Materials (Owner, 23 October 2026)

In NovoBiz, the default All catalog selection shows products and bundles only. Raw materials must stay separate and appear only when Raw Materials is explicitly selected. Catalog printing follows the visible selection so raw materials never enter a customer product catalog by default. Preserve inventory records, permissions, stock rules and channel eligibility; this is a catalog presentation rule, not a change to shared data contracts. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## NovoBiz Catalog Print Filter Disclosure (Owner, 23 October 2026)

Every NovoBiz catalog print or PDF must clearly state the applied filters in its report header or footer, including inventory type and sales channel (for example Finished Goods + Website, Shop, or Raw Materials), plus any other active filters and selected-item scope. Keep the displayed filter summary consistent with the actual printed selection. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## GTD Organization Detail Presentation (Owner, 23 October 2026)

In GTD organization details, show the category (for example Organization) below the organization name beside its logo, without a separate Organization badge or NovoBiz provenance badge in this detail identity. Place the organization sector badge (for example Healthcare) inline immediately after the Organization category. Keep OrgBrowse organization, project, and group topbar titles on one line; use a meaningful short name or acronym (for example GHA) only when the full name does not fit. Tapping the title opens an accessible dark dialog with a visible border, the full name, and scope-related project/group/member counts plus pending, completed, and overdue work statistics. Preserve existing permissions and data when calculating and displaying these details. Below the header, keep the Projects/Members segmented selector and search field together on one row; search placeholder and filtering follow the selected segment. Projects shows the project list; Members shows a searchable member list with an Invite button opening Email or HR Person options under existing permissions. Remove all NovoBiz source/provenance badges throughout GTD, including organization directories, cards, details, and widgets. This supersedes earlier instructions to preserve NovoBiz badges on other GTD surfaces. Continue hiding all provenance badges, including Created in GTD, in the OrgBrowse detail identity and project/group drill-down cards. Preserve authentic logos, sector badges, underlying provenance and sync data, and functional NovoBiz links and settings. Non-NovoBiz local-source badges outside OrgBrowse remain unchanged. Place the project sector badge (for example Quality & Accreditation) after the group/task counts with a vertical separator. Task cards inside organization, project, and group drill-down views must reuse the home-page task cards with their existing behavior and actions, rather than simplified title/date rows (Owner, 24 October 2026). In GTD organization, project, and group member lists, show each member’s profile photo, display name, and task statistics for the current scope. Do not show persistent role dropdowns or Remove buttons; use a press-and-hold/context menu with Make Admin, Remove Admin, and Remove From Organization/Project/Group actions as applicable. Demoting or removing the last administrator requires an eligible replacement (the acting user or another member). Removing a member requires reassignment of affected tasks so no tasks are orphaned. Preserve existing authorization and organization/project/group scope for all actions (Owner, 24 October 2026). GTD menu buttons, header labels, icons, and other app chrome must not select text or show the iOS Save Image/browser callout on long press. Preserve selection, copy, and paste in inputs, textareas, editable content, and meaningful text content; preserve intentional app press-and-hold actions such as member menus and task gestures (Owner, 24 October 2026). In GTD nested organization navigation, tapping Back or swiping from the left edge returns one hierarchy level; holding Back presents the available ancestor destinations (project, organization, Organizations) for a direct jump. Tasks/Members tab changes never add back-stack levels. Restore each level’s query, selected tab, and scroll position when returning. Keep the OrgBrowse top chrome, identity, tabs, and search together in one unified fixed header, without a white gap or separate-panel appearance; only the content list scrolls. Use the same dark grey background across the topbar and the identity, breadcrumbs, tabs, and search area through one shared header-background token, with contrasting text and controls and white logo frames. Include clickable ancestor breadcrumbs in that header: show the full path on desktop/tablet and a compact ancestor path on mobile using short names and … for older ancestors. Render the current destination name as plain text, and restore the saved navigation state when following an ancestor (Owner, 24 October 2026). In GTD member-management confirmation dialogs, Cancel and Confirm must have identical size and pill shape, share the same baseline, and use normal compact right-aligned widths with Title Case labels; preserve the secondary Cancel and primary Confirm color distinction. The GTD Go To ancestor-navigation dialog must use the same dark background as the unified header, reusing the shared --gtd-hdr-bg, --gtd-hdr-text, and --gtd-hdr-surface tokens with readable text and visible keyboard focus, and a subtle contrasting border that visibly defines the dark card. This GTD-specific presentation rule overrides the older requirement to display NovoBiz source/provenance badges app-wide and other provenance badges on the specified OrgBrowse surfaces; preserve underlying provenance data, non-NovoBiz local-source badges outside OrgBrowse, authentic logos, membership permissions, invitation behavior, and shared contracts. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## GTD Project And Group Names And Icons (Owner, 24 October 2026)

In GTD, organization admins can rename projects and groups and add or change their icons within their organization. Project admins can edit their own project and its child groups; group admins can edit their own group. Keep these controls within existing compact GTD styling and enforce the same scope permissions at the write boundary. Preserve scope IDs, tasks, memberships, and existing NovoBiz synchronization contracts; this GTD feature does not grant new permissions in other apps. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## GTD NovoBiz Scope Palette Accents (Owner, 24 October 2026)

Synchronize NovoBiz entity and brand primary, secondary, and tertiary colors into GTD and use them for organization, project, and group accents. An organization uses its entity palette; a project uses its brand palette with the organization palette as fallback; a group inherits its project palette. Keep all GTD header backgrounds dark grey and preserve readable contrast, existing permissions, scope relationships, and synchronization contracts. This is a GTD presentation requirement, not a theme or permission change for other apps. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.

## GTD Consistent Mobile Edge Spacing (Owner, 24 October 2026)

Throughout GTD on phones in portrait and landscape, use consistent 12px left and right outer spacing, with headers and content aligned to identical edges. Preserve native safe-area insets. This supersedes earlier GTD compact-mobile 6px edge spacing and any conflicting GTD mobile outer-inset guidance; keep tablet and desktop spacing unchanged. This is GTD-specific and does not change other apps’ spacing. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.

## GTD Scoped Overviews And Staff Invitations (Owner, 24 October 2026)

In GTD, use shared project/group admin overviews within their existing scope permissions. Keep GHA accreditation features and authorized member access inside its project, not a permanent main-menu entry. Separate person selection from invitation delivery and allow manual WhatsApp sharing. Generate organization-domain login IDs only for members without an existing organization email, using an explicitly approved organization domain, a random temporary password and a mandatory server-enforced first-login password change. Existing accounts and real email invitations remain unchanged; no generated login replaces HR contact email or grants cross-app permissions. Simplify Settings & Tools into Planning, Workspace Tools, AI Assistant, Connections and Settings. Favourites for organization, project and group navigation are approved under GTD Favourites Navigation below; individual task favourites remain outside this scope. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## NovoBiz Catalog Excel Photos And Pricing Rows (Owner, 24 October 2026)

NovoBiz catalog and pricing Excel exports show large embedded product photos in tall rows and hide internal Product ID and SKU columns while retaining upload matching data. Pricing exports use one row per product with separate Shop and Website current, AI-suggested and blank final-price columns in one workbook for the selected filters. Upload that workbook once and submit changes in batches of up to 100 products, preserving successful results, stale-price validation, scope permissions and independent approval. Keep legacy pricing uploads compatible. Missing photos must not block exports. This is NovoBiz-specific; preserve shared product contracts and other apps' presentation. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.

## Email Replies Are AI MailX Drafts Only (Owner, 24 October 2026)

Whenever Yasir asks to reply, reply all, respond to, write or prepare an email, use AI MailX and save the prepared email only in its normal Drafts folder (folder_path: "Drafts"). "Reply" and "reply all" are instructions to prepare an unsent draft, not authorization to send. Do not send, queue for sending, schedule delivery, or use another email app/provider to deliver it. Preserve the correct sender account, reply thread and reply-all recipients, formatted HTML, first-name greeting, first-person singular voice and that account's official signature. Verify the saved draft and report that it remains unsent. An explicit later request to send is a separate instruction and must not be inferred from a reply request. This supersedes any earlier interpretation that a reply request alone authorizes delivery.

## GTD Favourites Navigation (Owner, 24 October 2026)

In GTD, Favourites are navigation shortcuts to organizations, projects and groups. Place one Favourites menu entry directly after My Tasks and Team Tasks, opening a dedicated list rather than expanding saved destinations in the drawer. Each list item shows its icon, name and parent organization/project path. Place a small outline star beside each organization/project/group header title; tapping toggles the favourite and a filled star shows it is saved. Keep tapping the title reserved for scope information, and leave the Home header unchanged. Individual task favourites are not included. Preserve existing scope permissions, navigation behavior and shared data contracts. This approved implementation supersedes the earlier discussion-only deferral for this scope. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## GTD Simple Invitations And Acceptance (Owner, 24 October 2026)

In GTD, keep person selection separate from delivery: choose a person from HR or enter an existing email, then use one Email / WhatsApp delivery selector. Use the current organization/project/group context without asking for the organization again. Remove general Staff Login Settings from the normal invitation flow. For HR people without an organization email, reuse that organization’s explicitly approved login domain and offer WhatsApp sharing; ask an authorized organization administrator for the domain only when one is missing, never guess it from the organization name. Generated logins do not create email inboxes. Organization membership starts only after the recipient accepts; account existence and preparing or sharing an invitation must not grant membership. WhatsApp invitations must never create email drafts, and WhatsApp sharing remains manual. Email delivery retains the existing unsent AI MailX draft workflow. Preserve existing accounts and passwords, including AG Ansari’s agansari@buchhospital.com account, and preserve existing accepted memberships and scope permissions. Test with isolated fixtures; do not send real invitations or change real accounts without a separate explicit request. This supersedes conflicting GTD invitation presentation or automatic-membership guidance. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## GTD Organization Building Icon (Owner, 24 October 2026)

In GTD, use the same building icon (Lucide Building2) for semantic organization navigation and organization fallback glyphs, including the organization header shortcut, drawer, directory and membership cards, detail identity, favourites, organization actions and related organization shortcuts. Preserve authentic organization logos wherever present, and keep project, group and task icons unchanged. This is an icon presentation preference only; do not change organization data, permissions or navigation behavior. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## Short App-And-Purpose Helper Names (Owner, 24 October 2026)

Every agent-created helper, background service and automation must have a short, clear name identifying both its owning app and its job, for example `AgentBroker BrainCore Ledger Sync` or `FloatMic Transcription Service`. Never present a helper simply as Python, python3, Node, Helper or a similarly generic runtime name. Preserve the dedicated signed app wrapper, readable bundle/display/executable names and stable bundle identifier when changing schedules, commands, installers or runtime versions. Do not replace a named LaunchAgent command with a bare interpreter. Check the installed and loaded launch command and signed identity after changes; document any remaining macOS cached name instead of claiming it was corrected. Keep this rule in shared IDE instructions and connected app guidance for future sessions.

## Gmail Connector First For Yasir (Owner, 24 October 2026)

For the verified Gmail account `yasirbucha@gmail.com`, prefer the connected Google/Gmail tools for fresh email searches, full message bodies and original attachments instead of waiting for the AI MailX cache. Verify the connector profile before access; this rule does not authorize another similarly spelled account. When source content is missing in AI MailX, recover it into the matching existing account/message record using the app's supported import path when available, or an owner-authorized guarded local repair with a backup, exact account and RFC Message-ID matching, sender/subject checks, conditional fill of missing content, file/hash verification and readback. Preserve read/unread status, flags, folders, existing bodies, local IDs and user edits; do not create duplicate messages or transactions. Never mark truncated text, missing attachments or failed downloads as complete. Retain original attachment bytes and validate actual file type. Continue using AI MailX for drafts and replies under the unsent-drafts-only rule; connector-first reading does not authorize sending, deleting, relabeling or changing Gmail. Other email accounts keep their existing workflows. Propagate this preference across shared IDE instructions and connected app guidance.


## GTD Invitation Action Buttons And Phone (Owner, 24 October 2026)

In GTD Invite Someone, prefer an existing organization-domain email explicitly recorded for the HR person; otherwise show their saved HR contact email. Never guess mailbox existence, fabricate an organization email or replace an existing account. HR Person and Enter Email use direct Invite and WhatsApp action buttons, without a separate Share Invitation delivery selector or redundant final submit. Invite prepares an unsent AI MailX email draft; WhatsApp prepares manual sharing and never creates an email draft or claims delivery. Use the WhatsApp brand-green background with accessible contrasting text for WhatsApp actions. Add a Phone choice with an editable phone-number field and only the WhatsApp action. Prefill the phone when available in the permitted HR record; otherwise leave it blank and use the phone/numeric keypad. Keep the editable phone field visible at all times only in the Phone tab. In HR Person, use the permitted saved HR phone automatically for WhatsApp and reveal an editable phone field only after WhatsApp is clicked when no usable phone is available. In Enter Email, reveal the editable phone field only after WhatsApp is clicked. Ordinary HR/email selection and Invite must not display or require a phone number. This progressive disclosure supersedes any earlier always-visible phone-field presentation; preserve the protected lookup, manual sharing and acceptance requirements. Retrieve HR phone numbers through a protected, scope-authorized lookup; never copy them into the public HR mirror. Phone-only invitations use a private, expiring, one-time acceptance link: the recipient signs in with their own verified account and explicitly accepts before organization membership is created. Keep existing email/HR permission gates. These are implementation constraints, not authorization for real invitations, deployment or account/password changes. Preserve current organization/project/group scope, existing permissions, recipient acceptance before membership, accounts, passwords and HR data; entering or sharing a phone number alone never grants membership or authorizes inventing an email identity. This supersedes the older GTD delivery-selector presentation only. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected app instructions.


## Excel Table Borders (Owner, 24 October 2026)

Every Excel workbook created or downloaded for Yasir, including app export functionality, must have clearly visible borders around all table cells (headers, data and blank input cells), not just worksheet gridlines or bottom-only separators. Use consistent thin contrasting borders and preserve formulas, values, photos, hidden matching fields, validation and protection. Apply this by default to future spreadsheet work and synchronize the preference across shared IDE and connected-app instructions.

## Healthcare Assigned Dashboard Landing (Owner, 24 October 2026)

In BIH Dashboard and NovoBiz, sign-in opens the user’s assigned dashboard automatically. A user assigned the CEO profile lands on the CEO dashboard by default. Show only server-authorized assigned profiles; hide the profile selector when only one profile is assigned, and allow switching only between multiple genuinely assigned profiles. Do not expose global CEO/COO/Finance test choices or require the owner to choose a test dashboard. Preserve company/department scope, data restrictions, independent approvals and account permissions; selecting a dashboard never grants access. This is specific to BIH Dashboard and NovoBiz. Every IDE must preserve and synchronize this rule across shared IDE instructions and connected-app guidance.


## GTD Branded Invitation Cards (Owner, 24 October 2026)

GTD recipient organization invitation cards must show the authentic company logo and the GTD app logo in a polished, modern, responsive layout. Use clear invitation details, balanced spacing, framed logos and a prominent acceptance action; keep missing or failed logos graceful with the existing organization fallback. Apply this presentation consistently to the invitation email and in-app recipient card. Preserve explicit recipient acceptance before membership, existing authorization, unsent AI MailX email drafts and manual WhatsApp sharing. This is a GTD presentation preference only; it does not authorize sending invitations, changing accounts, exposing private organization data or granting new access. Every IDE must preserve and synchronize this preference across shared IDE instructions and connected-app guidance.

## Healthcare Original UI And Functional Details (Owner, 24 October 2026)

Preserve the existing BIH, NovoBiz and ControlX app shells, headers, navigation and CEO dashboard presentation. Role authorization belongs behind the existing UI; never add a duplicate executive header, CEO/COO/CFO test selector, Refresh or Sign Out toolbar. Sign-in opens the assigned dashboard automatically. CEO retains hospital-wide oversight; CMO, ACMO, COO, CFO, DCNO, HR, Procurement, IT, Marketing and Quality see only their function and assigned departments, with existing patient, payroll and independent-approval restrictions preserved. BIH provides operational views and related details; NovoBiz and ControlX provide governance views and related details. Missing or unverified sources are Unavailable, never invented or zero-filled. Profile assignment does not grant unrelated app permissions. This supersedes earlier role-dashboard wrapper presentation guidance. Preserve genuine multi-assignment access through existing app navigation where needed, without changing the CEO dashboard.

## Mandatory Ecosystem-Wide English-Only Transcription, Translation & Output Rule (Owner Directive — 25 October 2026)

Never transcribe, translate, summarize, or output in Urdu (`ur`), Hindi (`hi`), Arabic script, Devanagari script, or Roman Urdu. Always produce and display all transcripts, turn translations, summaries, action items, titles, keywords, executive minutes, email drafts, AI MailX calendar notes, BrainCore live context packets, GTD tasks, ControlX extractions, and MyDataX packets in plain English (`en`), even when spoken audio or source input is in Urdu, Hindi, Roman Urdu, or mixed speech. Every STT engine, local/cloud LLM prompt, translation pipeline, and cross-app bridge across the connected ecosystem (`Notely`, `FloatMic`, `AiMailx`, `BrainCore`, `GTD`, `ControlX`, `MyDataX`, `NovoBiz`, `BIH-Dashboard`, `Tony`, `Hermes`, `AgentBroker`, `OpenClaw`, `OpenIntelligentUI`) must enforce `en` output and block/remove `ur` and `hi` output modes.


## GTD Approved Monogram Icon (Owner, 26 October 2026)

GTD uses the approved GTD Monogram: a blue G with white inner space and a yellow checkmark on charcoal. Use the canonical `GTD/public/gtd-app-icon.png` to generate every GTD launcher icon, favicon, splash/login/profile fallback and invitation logo across web, macOS, iPhone/iPad and Android. Keep GTD representations in connected apps consistent when present; do not replace other apps’ own identities. Preserve platform masks, legibility, framed logos, and app data during updates. Every IDE must preserve and synchronize future owner design guidelines across shared IDE rules and connected-app instructions.

## Persistent Desktop Window Size And Position (Owner, 27 October 2026)

Every macOS and desktop app across the ecosystem (`BanX`, `GTD`, `AiMailx`, `Notely`, `BIH-Dashboard`, `NovoBiz`, `ControlX`, `MyDataX`, `Tony`, `PubX`, `Runway`, `ClipBoardX`, `FloatMic`, and all future desktop apps) must remember and restore the user's last resized window dimensions and screen position across app launches:
- **Automatic Save on Resize, Move, and Close**: Persist the main window's width, height, and screen coordinates whenever the user resizes, moves, or closes the window (`UserDefaults` + explicit `NSWindow` frame observer on SwiftUI/AppKit, `setFrameUsingName` / `setFrameAutosaveName` on Flutter macOS, `window-state.json` on Tauri and Electron).
- **Guard Against Launch-Screen Shrink & ASLR Autosave Drift**: Never allow launch screens (`ZStack` splash overlays), `.onOpenURL` `SceneBridgeReader` wrapper type changes, or initial layout passes to overwrite the saved window frame or shrink the window into a narrow/mobile strip on desktop. Enforce sensible desktop minimum bounds and clamp restored frames to the visible screen area.
- **Universal Synchronization**: Every IDE must preserve and synchronize this rule across shared IDE rules and connected-app instructions.


## GTD In-Card Sliders Edit Controls (Owner, 29 October 2026)

In GTD organization drill-down project and group cards, keep the edit action inside the card’s right edge, vertically aligned below the navigation chevron. Use the existing SlidersHorizontal icon for edit, never a pencil. Keep the name area clear, preserve separate accessible navigation and edit buttons with usable touch targets, and show edit only under existing scope permissions. Apply the same sliders edit icon to project/group detail identity controls. This changes GTD presentation only; preserve data, navigation, permissions and cross-app contracts. Every IDE must preserve and synchronize this preference across shared IDE rules and connected-app instructions.


## GTD Project Count And Scope Editor Presentation (Owner, 29 October 2026)

In GTD organization project lists, show the project count at the left of the same action row as the right-aligned Add Project button. Keep the shared project/group editor harmonious and symmetric with the app’s existing styling, balanced spacing and compact actions. Do not expose Firebase or storage image URLs in this editor; retain image selection, drag-and-drop upload and removal controls. Preserve existing scope permissions, saved images, data and navigation. Every IDE must preserve and synchronize this GTD-specific preference across shared IDE rules and connected-app instructions.


## GTD Stable Scope Editor And Image Sources (Owner, 29 October 2026)

The GTD project/group editor must stay open when the native photo chooser is dismissed or the user clicks outside. Only explicit Cancel or optimistic Save dismisses it; failed saves reopen it with the draft and selected image retained. Use an inline image-source chooser with Upload, Search Web Images and AI Design, following AI MailX’s image-menu pattern. AI Design creates a real image based on the project/group name with organization colors used only as subtle accents. Preserve existing permissions, validate selected image bytes before upload, show immediate loading/error feedback, and never replace generation with a fake placeholder. Every IDE must preserve and synchronize this GTD-specific preference across shared IDE rules and connected-app instructions.


## GTD Compact Quick Task Editor And Today-First Calendar (Owner, 29 October 2026)

Keep the GTD Quick Task editor compact and harmonious: remove vacant space, balance and align controls symmetrically, and keep the action footer visible while longer content scrolls. When opening its date picker, start calendar navigation at today rather than the task’s original date. Keep the existing saved/draft due date unchanged until the user explicitly selects a date; opening or cancelling the picker never reschedules a task. Preserve responsive layouts, safe areas, accessibility and existing task behavior. Every IDE must preserve and synchronize this GTD-specific preference across shared IDE rules and connected-app instructions.


## GTD Clear Multi-Selection And Bulk Dates (Owner, 29 October 2026)

In GTD task lists, long press enters a clear selection mode with a visible selected count and the instruction Tap Tasks To Select More; tapping more tasks toggles their selection instead of opening details. Replace the cluttered Done, Snooze, Someday, Focus, Context, Archive and Delete bulk panel with compact due-date actions Tomorrow, Next Week, Next Month and Custom, plus Clear Selection. Apply dates only to selected tasks under existing permissions; use local calendar arithmetic and clamp Next Month to the last valid day when needed. Show immediate action-specific loading feedback, disable duplicate actions, and retain selection with a clear error on failure. Every IDE must preserve and synchronize this GTD-specific preference across shared IDE rules and connected-app instructions.


## GTD Compact In-Card Multi-Selection (Owner, 30 October 2026)

GTD selection checkboxes stay compact inside each rounded task card; never create a continuous white checkbox rail beside the list. Selected cards use a subtle rounded tint and inset border instead of thick square outlines. Keep the bulk due-date toolbar compact, balanced and clear of the list, and hide conflicting task-creation floating buttons while selection is active. Preserve the selected count, date actions, readable touch targets, keyboard accessibility and existing scope permissions. Every IDE must preserve and synchronize this GTD-specific preference across shared IDE rules and connected-app instructions.
## No Em Dash (`—`) In AI Writing & Drafted Emails (Owner, 31 October 2026)

Never use the em dash character (`—` / `\u2014`) in chat replies, drafted emails, messages, documentation, or UI copy across any IDE or AI agent. Use a normal comma, period, colon, parentheses, or standard hyphen (`-`) instead. Every IDE must preserve and synchronize this rule across shared IDE rules and connected-app instructions.
