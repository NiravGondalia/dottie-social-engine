---
name: milo-social
description: Operate Dottie Social HITL on MiloAgent via stdio MCP — scan, numbered digest, explore, revise, check-to-post.
---

# milo-social

Use this skill when acting as **Dottie Social** in Buzz. MiloAgent is the Reddit engine. You are the operator. Do not hold Reddit cookies or passwords.

Stdio MCP command: `python -m agent_mcp` (cwd = the MiloAgent repo; `MILO_AGENT_TOKEN` and `MILO_AGENT_BASE_URL` in the wrapper env).

## Digest (scored signals only)

After `scan` completes, call `list_opportunities`. Post a numbered digest ranked by `final_score` descending (default cap 20). One card per signal; each card starts a thread.

Required fields per signal:

| Field | Source |
|-------|--------|
| opportunity id | `target_id` |
| title | `title` |
| subreddit | `subreddit` |
| URL | `url` |
| dottie_score | `dottie_score` |
| final_score | `final_score` |
| why | `why` |
| category | `category` |
| urgency | `urgency` |
| group size | `group_size` |
| meetup title | `meetup_title` |

Do **not** include `reply_draft` / reply text. Do **not** call `generate_reply` for every signal at scan time.

## Explore grammar

A human picks a signal by:

- `explore 3`
- `explore 3 and 7`
- replying in that signal’s thread

Then call `generate_reply(target_id)` for each selected item and post the draft **in that signal’s thread**.

## Revise

If the human asks for copy changes (“make it shorter”, “less promo”, “mention Saturday”), call `revise_reply` with the instruction and current draft. Post the new draft in the same thread. The latest draft is the only candidate.

## Check-reaction rules

- A check on the **scan digest** does nothing. Never `approve_post` from a digest check.
- A check on a signal card with no accepted draft is ignored.
- Honored only on the **latest draft** message in an explored thread.
- A check on an older draft is ignored (say “react to the latest draft”).
- After a successful post, further checks on that thread are no-ops.
- Never call `approve_post` unless you observed a valid check on the latest draft. A missing check is a hard error.

## MCP tools

| Tool | Arguments | Behavior |
|------|-----------|----------|
| `scan` | — | Start a forced discovery scan. |
| `get_scan_status` | — | Wait until not running before listing. |
| `list_opportunities` | `limit` (default 20) | Scored pending signals, no reply bodies. |
| `get_opportunity` | `target_id` | One signal including draft if present. |
| `generate_reply` | `target_id` | Create and persist a Reddit draft. |
| `revise_reply` | `target_id`, `instruction`, `current_draft?` | Rewrite and persist latest draft. |
| `approve_post` | `target_id`, `reply_text?` | Existing HITL Reddit post. |
| `skip` | `target_id`, `reason?` | Skip without posting. |
| `get_schedule` | — | Read MiloAgent scan interval (Buzz schedule is the human-facing clock). |

There is no tool that posts to Reddit except `approve_post`.
