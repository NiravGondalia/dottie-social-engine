# MiloAgent — agent notes

This process is the Reddit engine. Buzz Dottie Social is the operator.

## You may
- Call MCP tools (or `/api/agent/*` with `MILO_AGENT_TOKEN`) to scan, list scored signals, generate/revise replies, skip, and approve_post.
- Post numbered digests in Buzz. Explore only after a human picks a signal.

## You may not
- Put Reddit cookies or passwords in Buzz env.
- Call `approve_post` unless you observed a check reaction on the **latest draft** in that signal’s thread.
- Treat a check on the scan digest as publish.
- Generate replies for every signal at scan time.

## Loop
1. scan → wait get_scan_status until not running → list_opportunities
2. Numbered digest + one card per signal
3. `explore N` or thread reply → generate_reply
4. Human edits → revise_reply
5. Check on latest draft → approve_post → report comment URL
