# NEO_CONNECTOR -- MiloAgent
- service: milo
- base_url_prod: https://milo.soclose.co  (systemd, internally http://localhost:8420 ; docker-compose binds 127.0.0.1:${MILO_PORT:-8420}:8420)
- auth: Bearer ; header: Authorization: Bearer <token> ; env_var: MILO_WEB_USER + MILO_WEB_PASS (token obtained via POST /api/auth/login -> {token})
- env_required: [MILO_WEB_USER, MILO_WEB_PASS, MILO_WEB_TOKEN (fallback), MILO_PORT, MILO_CORS_ORIGINS (optional), MILO_SERVER_IP (optional), TELEGRAM_BOT_TOKEN, OPENAI_API_KEY]
- generated_at:

> Framework: FastAPI (single app, `dashboard/web.py` class `WebDashboard`, ~60 routes + 1 WebSocket). docs_url/redoc_url disabled. Auth = session bearer token from login (24h TTL, in-memory). WebSocket auth = token as query param. Reddit OAuth callback is the only public POST-flow-ish endpoint. No generate->poll->result async pipeline exists; the only "long-running" endpoints are POST /api/control/* which spawn a background thread and return immediately.

## Endpoints

### POST /api/auth/login
- auth: no (public; this is how you GET the token)
- async: false
- input:
  | param | type | requis | description |
  |-------|------|--------|-------------|
  | username | str | yes | LoginRequest.username (compared to MILO_WEB_USER, default "admin") |
  | password | str | yes | LoginRequest.password (bcrypt-verified vs MILO_WEB_PASS) |
- output: `{ok: true, token: "<hex64>"}`
- errors: 401 invalid credentials ; 429 too many attempts (rate limit 10/60s per IP)
- example_curl: `curl -sX POST https://milo.soclose.co/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"***"}'`

### GET /health
- auth: no (Docker healthcheck)
- async: false
- input: none
- output: `{status:"ok", uptime:int}`
- errors: none
- example_curl: `curl -s https://milo.soclose.co/health`

### GET /  |  GET /login  |  GET /robots.txt
- auth: no
- async: false
- input: none
- output: HTML (landing.html / index.html SPA) ; robots.txt is plaintext (Disallow /api/)
- errors: none
- example_curl: `curl -s https://milo.soclose.co/`

### GET /api/status
- auth: yes (Bearer)
- async: false
- input: none
- output: `{paused, mode, uptime_seconds, projects:[{name,enabled}], version, emergency_stopped}`
- errors: 401
- example_curl: `curl -s https://milo.soclose.co/api/status -H "Authorization: Bearer $T"`

### GET /api/stats
- auth: yes
- async: false
- input: none (always 24h window)
- output: `{total_actions, by_platform:{}, by_type:{}, opportunities, avg_opportunity_score}`
- errors: 401 ; `{error}` on internal failure
- example_curl: `curl -s https://milo.soclose.co/api/stats -H "Authorization: Bearer $T"`

### GET /api/actions
- auth: yes
- async: false
- input: `limit:int=30 (le 200)` query
- output: `[{action row...}]`
- errors: 401
- example_curl: `curl -s "https://milo.soclose.co/api/actions?limit=50" -H "Authorization: Bearer $T"`

### GET /api/actions/search
- auth: yes
- async: false
- input: query (all optional): `platform, account, project, action_type, hours:int=24 (le168), limit:int=50 (le500)`
- output: `[{action row...}]`
- errors: 401
- example_curl: `curl -s "https://milo.soclose.co/api/actions/search?platform=reddit&hours=48" -H "Authorization: Bearer $T"`

### GET /api/summary
- auth: yes
- async: false
- input: none
- output: `{total_actions_24h, success_rate, by_platform, by_project, pending_opportunities, paused, uptime_seconds}`
- errors: 401
- example_curl: `curl -s https://milo.soclose.co/api/summary -H "Authorization: Bearer $T"`

### GET /api/history
- auth: yes
- async: false
- input: `hours:int=168 (le720)` query
- output: `{hourly:[{hour,reddit,telegram}], daily:[{date,total}]}`
- errors: 401

### GET /api/accounts
- auth: yes
- async: false
- input: none
- output: `[{username,platform,total_24h,types,comments,likes,posts,status,has_cookies,persona,email,enabled,karma,tier,tier_name,daily_cap,can_post}]`
- errors: 401

### POST /api/accounts
- auth: yes
- async: false
- input (AccountCreate body):
  | param | type | requis | description |
  |-------|------|--------|-------------|
  | platform | "reddit"\|"telegram" | yes | |
  | username | str (1-100) | yes | |
  | password | str (1-256) | yes | |
  | email | str (<=200) | no | default "" |
  | persona | str (<=50) | no | default "helpful_casual" |
  | projects | list[str] | no | default [] |
- output: `{ok, message}`
- errors: 401

### DELETE /api/accounts/{platform}/{username}
- auth: yes
- async: false
- input: path params platform, username
- output: `{ok, message}`
- errors: 401

### GET /api/accounts/{platform}/{username}/health
- auth: yes
- async: false
- input: path params platform, username
- output: `{username,platform,status,actions_24h,action_types,success_rate,failures_24h,cookie_age_hours,write_disabled}`
- errors: 401

### GET /api/accounts/reddit/performance
- auth: yes
- async: false
- input: none
- output: `[{username,persona,assigned_projects,status,total_24h,total_4h,action_types,comments,posts,upvotes,subscribes,successes,failures,success_rate,subreddits_active,subreddits_count,has_cookies,has_reddit_session,cookie_age_hours,cooldown_remaining}]`
- errors: 401

### GET /api/projects
- auth: yes
- async: false
- input: none
- output: `[{name,url,enabled,weight,description,type,tagline,actions_24h}]`
- errors: 401

### GET /api/projects/{name}
- auth: yes
- async: false
- input: path param name
- output: full project object
- errors: 401 ; 404 not found

### POST /api/projects
- auth: yes
- async: false
- input (ProjectCreate body): `name str(1-100,req), url str(req), description str(1-500,req), project_type str="SaaS", weight float=1.0 (0-10), tagline str="", selling_points list=[], target_audiences list=[]`
- output: `{ok, filepath}`
- errors: 401 ; 409 duplicate ; 500
- example_curl: `curl -sX POST https://milo.soclose.co/api/projects -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"name":"X","url":"https://x.co","description":"..."}'`

### PUT /api/projects/{name}
- auth: yes
- async: false
- input (ProjectUpdate body, all optional): `enabled bool, weight float, description str, tagline str, url str, reddit_subreddits_primary list, reddit_subreddits_secondary list, reddit_keywords list, twitter_keywords list, twitter_hashtags list, tone_style str`
- output: `{ok}`
- errors: 401 ; 404 ; 500

### DELETE /api/projects/{name}
- auth: yes
- async: false
- input: path param name
- output: `{ok}`
- errors: 401 ; 404

### GET /api/cookies
- auth: yes
- async: false
- input: none
- output: `[{platform,username,cookies_file,has_cookies,size_kb,modified,key_cookies,count}]`
- errors: 401

### POST /api/cookies/paste
- auth: yes
- async: false
- input (PasteCookiesRequest body): `platform "reddit"|"telegram" (req), username str(1-100,req), cookies str(10-50000,req)` (accepts document.cookie or Netscape format; Reddit cookies verified via api/me.json)
- output: `{ok,message,key_cookies_found,key_cookies_missing,total,username,verified_user}`
- errors: 401 ; 404 account not found ; 400 invalid path/parse

### DELETE /api/cookies/{platform}/{username}
- auth: yes
- async: false
- input: path params platform, username
- output: `{ok, message}`
- errors: 401 ; 404

### POST /api/reddit/oauth/start
- auth: yes
- async: false (returns an auth_url the user opens in a browser; then Reddit hits the callback)
- input (OAuthStartModel body): `username str (req)`
- output: `{ok, username, auth_url}` or `{ok:false, error}` if Reddit API not configured
- errors: 401

### GET /api/reddit/oauth/callback
- auth: no (Reddit redirects the browser here directly)
- async: false
- input: query `code:str="", state:str="" (=username), error:str=""`
- output: HTML on success / `{ok:false,error}` ; exchanges code -> refresh_token, saves to account config
- errors: none (200 with error JSON)
- note: redirect_uri default = https://milo.soclose.co/api/reddit/oauth/callback

### GET /api/reddit/oauth/status
- auth: yes
- async: false
- input: none
- output: `{ok, api_configured, accounts:[{username,has_refresh_token}]}`
- errors: 401

### POST /api/reddit/search
- auth: yes
- async: false
- input (ManualSearchModel body): `subreddit str(req), query str(req), limit int=10`
- output: `{ok, results:[{id,title,author,score,num_comments,url}], count}`
- errors: 401
- note: NOT covered by NeoBot today (NeoBot/bot/milo.py calls a different /api/reddit/search path/shape -- verify)

### GET /api/opportunities
- auth: yes
- async: false
- input: `limit:int=20 (le100)` query
- output: `[{opportunity row...}]`
- errors: 401

### GET /api/opportunities/rejected
- auth: yes
- async: false
- input: query `hours:int=24 (le168), limit:int=50 (le200)`
- output: `[{rejected opportunity row...}]`
- errors: 401

### GET /api/decisions
- auth: yes
- async: false
- input: query `hours:int=2 (le24), decision_type:str="", limit:int=30 (le100)`
- output: `[{decision row...}]`
- errors: 401

### GET /api/schedule
- auth: yes
- async: false
- input: none
- output: `[{name, next_run(ISO), seconds_until, interval}]`
- errors: 401

### GET /api/insights
- auth: yes
- async: false
- input: none
- output: `{post_type_stats, sentiment, experiments:[{name,variable,variant_a,variant_b,a_eng,b_eng,a_n,b_n}]}`
- errors: 401

### GET /api/brain
- auth: yes
- async: false
- input: none
- output: large object: `{top_subreddits, promo_ratio, best_tone, discoveries, post_type_top, sentiment, ab_tests, evolved_prompts, llm_stats, relationships, resources, subreddit_intel_summary, recent_discoveries}` (graceful fallbacks)
- errors: 401

### GET /api/performance
- auth: yes
- async: false
- input: none
- output: `{score, grade(A+..F), components:{activity,balance,accounts,diversity}, max_per_component, improvements:[], total_actions}`
- errors: 401

### GET /api/server
- auth: yes
- async: false
- input: none
- output: `{cpu:{cores,load_1m,load_5m,load_15m,usage_pct}, ram:{total_gb,used_gb,available_gb,percent}, disk:{...}, process:{pid,rss_mb,uptime_seconds,threads}, database:{size_mb,wal_mb}, history:[{ts,cpu,ram,disk}]}`
- errors: 401

### GET /api/minimaps
- auth: yes
- async: false
- input: none
- output: `{reddit:[{subreddit,count_24h,stage,activity_level}], telegram:{groups:[{name,count}]}}`
- errors: 401

### GET /api/conversations
- auth: yes
- async: false
- input: `limit:int=30 (le100)` query
- output: `{dms:[{timestamp,direction,username,platform,content}], alerts:[{timestamp,message}]}`
- errors: 401

### GET /api/heatmap
- auth: yes
- async: false
- input: `days:int=28 (le90)` query
- output: `{grid:[{dow,hour,count}], max_count}`
- errors: 401

### GET /api/funnel
- auth: yes
- async: false
- input: `hours:int=24 (le168)` query
- output: `{stages:[{name,count}], conversion_rate}`
- errors: 401

### GET /api/network
- auth: yes
- async: false
- input: none
- output: `{nodes:[{id,label,type}], links:[{source,target,value}]}`
- errors: 401

### GET /api/settings
- auth: yes
- async: false
- input: none
- output: `{scan_interval_minutes, action_interval_minutes, active_hours, rate_limits, safety, http:{proxy,reddit_proxy}, promotion_rate, llm_providers:[names]}`
- errors: 401

### PUT /api/settings
- auth: yes
- async: false
- input: JSON body, allowed keys only: `scan_interval_minutes, action_interval_minutes, promotion_rate, active_hours, rate_limits`
- output: `{ok, changed:[keys]}`
- errors: 401 ; 500

### GET /api/communities
- auth: yes
- async: false
- input: none
- output: `{communities:[...], count}`
- errors: 401

### GET /api/communities/{subreddit}
- auth: yes
- async: false
- input: path param subreddit
- output: `{hub:{...}, setup_status:{...}}` (or error dict)
- errors: 401

### GET /api/takeover/targets
- auth: yes
- async: false
- input: none
- output: `{targets:[{subreddit_request row...}]}`
- errors: 401

### GET /api/takeover/requests
- auth: yes
- async: false
- input: none
- output: `{requests:[...], count}`
- errors: 401

### GET /api/intel/subreddits
- auth: yes
- async: false
- input: query `project:str="", limit:int=30 (le100)`
- output: `{subreddits:[{subreddit,project,updated_at,subscribers,active_users,posts_per_day,avg_hours_between_posts,median_post_score,avg_comments_per_post,mod_count,opportunity_score,relevance_score,description}], count}`
- errors: 401

### GET /api/intel/trends
- auth: yes
- async: false
- input: query `project:str="", hours:int=72 (le336)`
- output: `{trends:[{subreddit,project,timestamp,top_themes[],recurring_questions[],avg_score,hot_post_count}], count}`
- errors: 401

### GET /api/intel/knowledge
- auth: yes
- async: false
- input: query `project:str="", category:str="", limit:int=50 (le200)`
- output: `{entries:[{timestamp,project,category,topic,content,source,relevance_score,expires_at,used_count}], count}`
- errors: 401

### GET /api/intel/discoveries
- auth: yes
- async: false
- input: query `project:str="", status:str="", limit:int=30 (le100)`
- output: `{discoveries:[{timestamp,platform,project,discovery_type,value,source,score,status}], count}`
- errors: 401

### GET /api/intel/time-perf
- auth: yes
- async: false
- input: `project:str=""` query
- output: `{grid:[{hour_of_day,day_of_week,actions,avg_eng,removed}], max_engagement}`
- errors: 401

### GET /api/intel/failures
- auth: yes
- async: false
- input: query `project:str="", limit:int=20 (le50)`
- output: `{failures:[{project,subreddit,failure_type,pattern,frequency,last_seen,avoidance_rule}], count}`
- errors: 401

### GET /api/intel/sentiment
- auth: yes
- async: false
- input: query `project:str="", days:int=30 (le90)`
- output: `{by_subreddit:[{subreddit,avg_sentiment,total_replies,pos,neg}], by_tone:[{tone_style,avg_sentiment,total_replies}]}`
- errors: 401

### GET /api/intel/radar
- auth: yes
- async: false
- input: `project:str=""` query
- output: `{nodes:[{id,type,label,...}], links:[{source,target,value}]}`
- errors: 401

### GET /api/export/actions
- auth: yes
- async: false
- input: query `hours:int=24 (le720), platform:str=""`
- output: text/csv (StreamingResponse)
- errors: 401 ; 500

### GET /api/export/opportunities
- auth: yes
- async: false
- input: `status:str="pending"` query
- output: text/csv (StreamingResponse)
- errors: 401 ; 500

### POST /api/control/scan
- auth: yes
- async: false (spawns background thread `_scan_all_safe`, returns immediately)
- input: none
- output: `{ok, message}`
- errors: 401 ; refused if emergency-stopped
- example_curl: `curl -sX POST https://milo.soclose.co/api/control/scan -H "Authorization: Bearer $T"`

### POST /api/control/learn  |  /act  |  /engage  |  /auto-improve  |  /manage-communities  |  /animate-hubs  |  /scan-takeover  |  /research
- auth: yes
- async: false (each spawns its respective background thread, returns immediately)
- input: none
- output: `{ok, message}`
- errors: 401 ; refused if emergency-stopped

### POST /api/control/pause
- auth: yes
- async: false
- input: none
- output: `{ok, paused:true}`
- errors: 401

### POST /api/control/resume
- auth: yes
- async: false
- input: none
- output: `{ok, paused:false}` (refused if emergency stop active)
- errors: 401

### POST /api/control/emergency-stop
- auth: yes
- async: false
- input: none
- output: `{ok, message}` (sets _emergency_stopped, pauses scheduler)
- errors: 401

### POST /api/control/emergency-reset
- auth: yes
- async: false
- input: none
- output: `{ok, message}` (clears emergency stop, resumes scheduler)
- errors: 401

### POST /api/control/reload-config
- auth: yes
- async: false
- input: none
- output: `{ok, message}` (reloads projects + accounts from YAML)
- errors: 401

### POST /api/control/cleanup
- auth: yes
- async: false
- input: none
- output: `{ok, message}` (db.force_maintenance() + gc.collect())
- errors: 401

### WS /ws/logs
- auth: yes -- token passed as QUERY PARAM `?token=<session_token>` (NOT the Authorization header); invalid/expired closes with code 4001
- async: streaming
- input: query `token`
- output: stream of JSON log records `{seq,ts,level,logger,msg,cat}` ; sends 50 recent on connect, then polls every 0.5s ; capped at 20 concurrent clients
- errors: close 4001 invalid/expired token
- example: `wss://milo.soclose.co/ws/logs?token=$T`

## Flows
1. Auth: `POST /api/auth/login {username,password}` -> `{token}`. Use `Authorization: Bearer <token>` for all /api/* (24h TTL). For WebSocket use `?token=<token>`.
2. Control actions (fire-and-forget, NOT poll-able): `POST /api/control/<action>` returns `{ok}` immediately and runs in a background thread. There is NO status/result endpoint to poll -- observe progress via `GET /api/status`, `GET /api/actions`, or the `/ws/logs` WebSocket.
3. Reddit OAuth account linking: `POST /api/reddit/oauth/start {username}` -> `{auth_url}` ; user opens auth_url in a browser and approves ; Reddit redirects browser to `GET /api/reddit/oauth/callback?code=&state=<username>` which exchanges the code for a refresh_token and saves it ; confirm with `GET /api/reddit/oauth/status`.
4. Cookie-based account login (alternative to OAuth): `POST /api/cookies/paste {platform,username,cookies}` -> verifies + stores ; check via `GET /api/cookies`.
5. Export: `GET /api/export/actions` / `GET /api/export/opportunities` stream CSV directly (no job).

## Gaps
- base_url_prod confirmed as https://milo.soclose.co from the Reddit OAuth redirect_uri default in dashboard/web.py (~line 769) and NeoBot bot/config.py (`"milo": {... "domain":"milo.soclose.co", "port":8420}`). No explicit prod URL in README/docker-compose (compose binds only 127.0.0.1) -- a reverse proxy fronts it. Verify the proxy config (outside this repo).
- NeoBot drift (verify in NeoBot, not this repo): bot/milo.py and bot/integrations.py reference paths that DO NOT exist in this API: `/api/scan` (real one is `/api/control/scan`), `/api/learning/weights|discoveries|experiments` (real intel/insights endpoints are `/api/insights`, `/api/intel/*`), `/api/analytics/subreddits` (real is `/api/intel/subreddits`), and reddit write endpoints `/api/reddit/comment|post|upvote|subscribe` (NOT exposed by this API at all). These NeoBot tools likely 404. Check NeoBot/bot/milo.py + bot/integrations.py.
- Reddit write actions (comment/post/upvote/subscribe on demand) are NOT exposed as HTTP endpoints -- they only happen via the autonomous engine triggered by `/api/control/act` / `/api/control/engage`. If NeoBot needs direct write control, it is a genuine gap with no endpoint. Check platforms/reddit_bot.py + core/orchestrator.py.
- Request body model for `POST /api/reddit/oauth/start` (OAuthStartModel) and `POST /api/reddit/search` (ManualSearchModel) are defined inline inside `_setup_routes` (not at module top) -- field set proven from code at dashboard/web.py ~line 711 and ~line 765.
- `GET /api/projects/{name}` exact output shape depends on business_manager.get_project() -- not fully enumerated. Check core/business_manager.py.

## Récap (coverage vs NeoBot)
- Endpoints found in this API: ~63 routes (HTTP) + 1 WebSocket (/ws/logs). 5 public (login, callback, health, /, /login, robots), the rest Bearer-authed.
- Already covered by NeoBot's 10 milo_* tools (bot/milo.py) + integrations.py: /api/status, /api/stats, /api/accounts, /api/opportunities, /api/actions, /api/control/{pause,resume,scan,...}, /api/decisions, /api/performance, /api/accounts/reddit/performance, /api/communities, /api/brain, /api/projects (read). ~14 endpoints.
- NEW / not yet wired (high value): /api/summary, /api/history, /api/insights, /api/schedule, /api/server, /api/funnel, /api/heatmap, /api/network, /api/minimaps, /api/conversations, the full /api/intel/* suite (8), /api/takeover/*, /api/reddit/oauth/* (3), /api/reddit/search, /api/cookies + /api/cookies/paste, account health, settings GET/PUT, project create/update/delete, account create/delete, export CSV (2), emergency-stop/reset, and the remaining control actions (act/engage/auto-improve/learn/manage-communities/animate-hubs/scan-takeover/research/reload-config/cleanup). ~45 new endpoints.
- Plus the NeoBot-side drift noted under Gaps (several existing milo_* tools call paths that this API does not serve).
