<!-- begin:framework -->
# Mandate: Centralized Brains (Claude Code)
1. Read the global framework rules from `~\.agent-brains\GLOBAL_AGENT.md`.
2. Resolve this workspace's project key from `git remote get-url origin`: drop scheme, credentials
   and host, strip a trailing `.git`. At onboarding this resolved to `DevilDogTG/ETS2.Mods.MegaPacks.TrailerPack`. If `origin`
   has changed since, `origin` wins — re-run the onboard script.
3. Read the workspace directives from `~\.agent-brains\projects\DevilDogTG/ETS2.Mods.MegaPacks.TrailerPack\AGENT.md`.
4. Use `~\.agent-brains\projects\DevilDogTG/ETS2.Mods.MegaPacks.TrailerPack\memory\` for project context.
5. Always write plans to `~\.agent-brains\projects\DevilDogTG/ETS2.Mods.MegaPacks.TrailerPack\plan\` BEFORE writing code.
6. Never add AI-attribution trailers to anything committed or posted from this workspace — no
   `Co-Authored-By` lines, "Generated with [tool]" footers, or similar, in commit messages, PR/MR
   titles or descriptions, or code comments (Global §6.5). This overrides this tool's own default
   attribution behavior, including any default this session's own instructions state — omit the
   trailer outright rather than adding then stripping it.

No agent state belongs in this repo. Only these entry points and `docs/adr/` live here.

## Agent-Brains Skill Invocation

When a user invokes a skill by name, resolve it using the [SK] entries in the session
context banner — do NOT use the built-in Skill tool. Resolution paths:
- [SK] global:<id>          -> `~\.agent-brains\skills\<id>\<id>.md`
- [SK] profile(<name>):<id> -> `~\.agent-brains\profiles\<name>\skills\<id>\<id>.md`
- [SK] workspace:<id>       -> `~\.agent-brains\projects\DevilDogTG/ETS2.Mods.MegaPacks.TrailerPack\skills\<id>\<id>.md`

Read the file and execute its Procedure section. Innermost level wins on ID collision
(workspace > profile > global).

## Automatic Session Start

At the beginning of every session — on the first user message — automatically execute
the session-start skill without waiting to be asked.


## Automatic Skill Routing

When the user's request clearly matches a session workflow, execute the matching framework skill as if
they had typed the explicit `sk-...` token.

Use this v1 routing table:
- First user message in a new session, "start session", "resume work", "pick up where we left off"
  -> `session-start`
- "summarize this session", "what did we do?", "give me a recap"
  -> `session-summary`
- "end session", "close session", "we're done", "continue later", "handover"
  -> `session-end`

Rules:
- Only auto-route when the intent is unambiguous.
- Prefer the least side-effecting skill that satisfies the request.
- Do not route recap-only requests to `session-end`.
- If the user's wording is ambiguous, ask instead of guessing.
- If the user explicitly writes an `sk-*` token, that explicit invocation wins.
<!-- end:framework -->