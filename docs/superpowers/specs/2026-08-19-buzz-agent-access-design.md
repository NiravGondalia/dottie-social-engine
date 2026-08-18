# Buzz agent access for MiloAgent

**Date:** 2026-08-19  
**Status:** approved  
**Repo:** MiloAgent stays the scan / score / write / post engine. Buzz is the control room.

## Goal

Let Buzz agents on `dottie.communities.buzz.xyz` trigger scans, review scored signals, iterate on a Reddit reply, and publish only after a human check reaction. Humans never hand Reddit credentials to an agent. This repo’s existing Reddit, scoring, safety, and HITL post path keep doing that work.

## Settled decisions

| ID | Decision |
|----|----------|
| D1 | New Buzz specialist **Dottie Social**. Alfred may @mention it; Alfred does not own the Reddit loop. |
| D2 | Agent-configurable schedule in Buzz **and** ad-hoc @mention scans. |
| D3 | After scan, list **scored signals only**. Do not generate a Reddit reply until the human explores an item. |
| D4 | Explore via **numbered digest** (`explore 3`, `explore 3 and 7`) **and** by **replying in that signal’s thread**. |
| D5 | Human may ask for copy changes in the draft thread. Latest draft is the candidate. |
| D6 | A **check reaction on the latest draft** is the only publish trigger. Check on the scan digest does nothing. |
| D7 | Publish calls this repo’s existing HITL approve/post path. Do not reimplement Reddit posting in Buzz. |
| D8 | Primary agent contract is a **stdio MCP** over the running MiloAgent process. Shelling `miloagent.py` is not the primary interface. |

## Actors

- **Human** (channel member): starts ad-hoc scans, picks signals, edits copy, check-reacts to post.
- **Dottie Social** (Buzz ACP agent): talks to humans in-channel; calls MiloAgent MCP; posts digests and drafts via `buzz-cli`.
- **Alfred**: optional orchestrator; may @mention Dottie Social; does not hold Reddit tools.
- **MiloAgent**: scan, score, generate/revise reply, rate-limit, post to Reddit, persist opportunities.

## Channel loop

```
schedule or @mention “scan”
  → MCP scan
  → wait until complete
  → MCP list_opportunities (scored, no reply required)
  → post numbered digest + one card per signal (each card starts a thread)

human: “explore 3”  OR  reply in signal 3’s thread
  → MCP generate_reply(opportunity_id)
  → post draft in that signal’s thread

human: “shorter / less promo / mention Saturday”
  → MCP revise_reply(opportunity_id, instruction, current_draft)
  → post new draft in the same thread (latest wins)

human: check reaction on the latest draft
  → MCP approve_post(opportunity_id, final_text)
  → MiloAgent posts to Reddit via existing HITL path
  → agent reports comment URL or failure in-thread
```

### Digest contents (required per signal)

Reuse fields the scan already stores: opportunity id, title, subreddit, URL, `dottie_score`, `final_score`, `why`, category, urgency, group size, meetup title. Rank by `final_score` descending. Cap the digest (default 20; agent may request more). No `reply_text` until explore.

### Check-reaction rules

- Ignored on digest messages and on signal cards that have no accepted draft.
- Honored only on the **latest draft** message in an explored thread.
- If a newer draft exists, a check on an older draft is ignored (or the agent says “react to the latest draft”).
- After a successful post, further checks on that thread are no-ops.

## What we build in this repo

Additive. No rewrite of Reddit web client, scoring (`dottie_discovery`), learning, or dashboard SPA.

### 1. Machine auth

Dashboard APIs today require a **browser session** from `/api/auth/login`. Agents cannot use that.

Add a scoped machine token (env, e.g. `MILO_AGENT_TOKEN`) accepted as `Authorization: Bearer` on a small agent API surface **or** used only inside a localhost MCP that never exposes Reddit cookies. Do not put `MILO_WEB_PASS`, Reddit passwords, or cookies in the Buzz persona env.

### 2. Waitable scan jobs

`POST /api/control/scan` currently starts a daemon thread and returns immediately. MCP `scan` must return a job handle (or block with a timeout) and `get_scan_status` must report `running | complete | failed` plus counts.

### 3. stdio MCP server

Buzz-agent / `buzz-acp` spawn **stdio MCP only** (no native HTTP MCP). Ship a binary/module the specialist’s `mcp_command` points at.

| Tool | Behavior |
|------|----------|
| `scan` | Trigger existing orchestrator scan (`force=True` allowed while paused). |
| `get_scan_status` | Job state and opportunity counts. |
| `list_opportunities` | Pending signals, scored, **omit reply body**. |
| `get_opportunity` | One signal including thread metadata. |
| `generate_reply` | Create reply for one opportunity via existing content generation. Persist as draft on that opportunity. |
| `revise_reply` | Rewrite draft from human instruction + current text. Persist latest draft. |
| `approve_post` | Existing HITL `post_to_reddit` path with the finalized text. |
| `skip` | Existing skip/reject path. |
| `get_schedule` / `set_schedule` | Read/update scan cadence the agent is allowed to change (Buzz workflow remains the human-facing clock; this is for MiloAgent-side interval if kept). |

Tool results are JSON. Errors are structured (`code`, `message`). Never return secrets.

### 4. Agent-oriented HTTP (optional but likely)

If MCP wraps HTTP rather than importing the orchestrator in-process, add token-gated routes that mirror the tools above. Dashboard session auth stays for humans. Do not require the SPA login for MCP.

### 5. Repo orientation files

- `AGENTS.md` — what Dottie Social may call, HITL rules, never-do list.
- `.agents/skills/milo-social/SKILL.md` — digest format, explore grammar, check-reaction contract, MCP tool names.

These files are for Buzz/Claude/Codex once the agent’s workspace can see the repo **or** when copied into the nest skill tree. They do not replace MCP.

## What we configure in Buzz (not a MiloAgent rewrite)

- Persona **Dottie Social**: system prompt matching this spec; `mcp_command` = MiloAgent MCP; no Reddit env vars.
- Channel (e.g. social growth): agent is a member; humans @mention it.
- YAML workflow(s): `schedule` trigger that @mentions Dottie Social (or sends a fixed prompt). Agent may `buzz workflows create/update` to change cadence.
- Optional `reaction_added` workflow filtered to the check emoji, as a backup ping if the agent is idle. Publish still goes through MCP `approve_post`, not a raw webhook to Reddit.

## Safety

- Reddit credentials stay in MiloAgent.
- Emergency stop on the dashboard still blocks `approve_post`.
- Rate limiter, account rotation, content validation stay on the post path.
- MCP host should be localhost / private network. Token is a secret; not committed.
- Dottie Social must not call `approve_post` unless it observed a valid check on the latest draft (skill + optional workflow). Treat a missing check as a hard error.

## Out of scope

- Replacing the dashboard HITL UI (it may keep working in parallel).
- Auto-post without a check reaction.
- Making Buzz the Reddit client.
- HTTP MCP without a stdio bridge (Buzz limitation).
- Per-agent git workspace inside this checkout as the primary design (Buzz RFC #3364). A nest skill + MCP is enough.
- Twitter/Telegram agent tools in this pass.

## Success criteria

- From Buzz: @mention Dottie Social to scan; numbered scored list appears without reply bodies.
- `explore 3` and a thread reply both produce a draft in signal 3’s thread.
- “make it shorter” produces a new draft; check on the old draft does not post.
- Check on the latest draft results in a Reddit comment via the existing post helper; channel gets the comment URL or a clear error.
- Agent cannot post if emergency stop is on, or if no check was observed.
- Alfred can @mention Dottie Social without receiving Reddit MCP tools.

## Risks

- Buzz agents default cwd is `~/.buzz`, not this repo — MCP attachment is mandatory.
- Scan is currently fire-and-forget — without job wait, the digest will be empty or stale.
- Check-reaction on the wrong message is the main accidental-publish risk; rules above are load-bearing.
- Dual clocks (MiloAgent 12-min job + Buzz schedule) can double-scan; Dottie Social’s schedule is the Buzz-facing clock. Document whether the internal APScheduler stays, pauses, or is left for dashboard-only use (default: leave internal scheduler as-is for dashboard; Buzz scans are extra `force` scans).
