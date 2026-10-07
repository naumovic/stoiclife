# Coaching migration — progress

Plan: `docs/coaching-plan.md` (original brief + 2026-10-05 scope change). Branch: `coaching-migration` (stoiclife repo).
Rule: update this file after every completed step and commit it with the code. Stop at the end of each phase for approval.

## Status

- [x] **Step 0: progress tracking**
  - [x] `docs/coaching-plan.md` saved, with the scope-change note
  - [x] `docs/PROGRESS.md` (this file)
  - [x] `CLAUDE.md` pointer in stoiclife + `~/.openclaw/workspace/CLAUDE.md`
- [x] **Phase 0: recon (read-only)** (findings below)
- [x] **Phase 1: `coach` agent**
  - [x] Draft `agents.list` (`main` default unchanged + `coach`, workspace `~/.openclaw/workspace-coach`); check every key against the 2026.6.8 docs
  - [x] Build the coach workspace: SOUL/AGENTS distilled from `workspace/TOOLS.md` "Stoic Journal" + `AGENTS.md` Stoic section, plus `stoic_knowledge.md` and the journal prompts
  - [x] Tool policy: keep `exec` (scripts need it); deny browser/web/write/edit etc.; no MEMORY.md; decide about Supermemory
  - [x] Per-agent model (Sonnet via the API-key profile)
  - [x] Show the config diff → approval → apply → `config validate` (no restart without asking)
    - Applied 2026-10-05 23:37 (backup `~/.openclaw/openclaw.json.bak-coach-20261005-233717`). The gateway **hot-reloaded `agents.list` with no restart** (log: `config hot reload applied (agents.list)`).
    - Verified: `agents list` shows `main` (default) + `coach` (🧭 Coach, Sonnet, workspace `coach-workspace`).
    - Verified: an undelivered test turn (`openclaw agent --agent coach --session-key agent:coach:phase1-test`) reported exactly `read, exec, process, message, session_status`, gave the coach persona, and answered a sleep question with figures matching `biometrics` (2026-10-05: 407 min, HRV 36.4, RHR 70).
    - Verified: Telegram default + WhatsApp still connected, WhatsApp traffic flowing. No BOOTSTRAP/template files were seeded into the workspace.
  - [x] Heartbeat is main-only. Verified 2026-10-06: the 00:23 heartbeat (14:23Z) ran in `agent:main:main` → `HEARTBEAT_OK`. The coach session files haven't been touched since 00:08, there's no `heartbeat poll` in any coach transcript, and `sessions.json` holds only `phase1-test` + `main`. Gotcha: `openclaw system heartbeat last` returned `{}` after the hot reloads and the gateway log doesn't record heartbeat runs, so the reliable signal is the `[OpenClaw heartbeat poll]` turn in the main transcript.
- [x] **Phase 2: Telegram bot** (complete 2026-10-06)
  - [x] Mihajlo creates the bot in @BotFather (@stoiclife_coach_bot; `getMe` ok, 2026-10-05)
  - [x] Token → `~/.openclaw/.env` `TELEGRAM_COACH_BOT_TOKEN`, referenced as `${TELEGRAM_COACH_BOT_TOKEN}` (`.env` is mode 664; propose chmod 600)
  - [x] `channels.telegram`: **top level left untouched** (= implicit `default` account, Travelboard) + `accounts.coach` {botToken `${…}`, dmPolicy allowlist [8917837483], groupPolicy disabled} + `defaultAccount: "default"`. Applied 2026-10-05 23:59 (backup `openclaw.json.bak-coach-p2-20261005-235942`), hot-applied with **no gateway restart**. The log shows `[coach] starting provider (@stoiclife_coach_bot)` + `[default] starting provider (@ewok_trip_bot)`, no duplicate start, no errors. `channels status`: coach, default and WhatsApp all connected. `~/.openclaw/.env` chmod 600
  - [x] Binding coach account → `coach` agent
  - [x] Diff → approval → apply → is-active, both bots connected
  - [x] Live test: Mihajlo DMs @stoiclife_coach_bot → lands in an `agent:coach:*` session; Travelboard `/itinerary` DM still answers (2026-10-06 00:07–00:10)
    - Coach: `/start` + "how did I sleep?" → session `agent:coach:main` (telegram, account `coach`, direct, to 8917837483), model `claude-sonnet-4-6`, workspace `coach-workspace`. Coach persona; one read-only `sqlite3` query on `biometrics`; figures match (2026-10-05: 407 min, deep 68, HRV 36.4, RHR 70). Log shows inbound on `@stoiclife_coach_bot`, tool policy removing 22 tools, no errors. The duplicate assistant lines in the transcript are `delivery-mirror` entries, not double sends.
    - Travelboard: `/itenerary` (typo) + a follow-up → `@ewok_trip_bot` → `agent:main:main` (account `default`, Gemini), ran `travelboard.py itinerary next` → "Nothing upcoming." Routing is unchanged. The follow-up's answer about the "last destination" was shaky, but that's Gemini on `main` and has nothing to do with this change.
    - Isolation: nothing coach-related went into `agent:main:*`, and nothing Travelboard-related went into `agent:coach:*`.
  - [x] `openclaw security audit` (run after the change and against the pre-change backup)
    - Pre-existing CRITICAL `channels.telegram.groups.allowFrom.missing`: the Travelboard group's deliberate `groupAllowFrom: []` (travelboard OPERATIONS.md gotcha 5). Fix = per-sender list of travellers' numeric IDs. **2026-10-06 Mihajlo: leave as is for now** (accepted, see Decisions).
    - New WARN `tools.exec.fs_tools_disabled_but_exec_enabled` for `coach`: accepted for single user (only Mihajlo can reach it). Must be resolved before multi-user (sandbox `all` or a plugin-only toolset).
    - Other WARNs (trusted proxies, multi-user heuristic, plugin tools reachable on main) are pre-existing and unrelated.
- [x] **Phase 3: re-wire coaching to Telegram** (complete except the real-entry write test, which Mihajlo runs from 2026-10-06 in normal use)
  - [x] Make the formatters channel-aware (`coaching_format.py`, `build_payload.py`, `weekly_review.py`, `status.py`) + tests (2026-10-06)
    - New `channel_fmt.py`. Text stays authored in WhatsApp style and is converted at the edge; the only real difference is bold. In OpenClaw 2026.6.8, `markdownToTelegramHtml` turns `*x*` into **italic** (`<i>`), and only `**x**` becomes `<b>`.
    - Channel per invocation: `--channel` > `$STOICLIFE_CHANNEL` > `whatsapp`. It's deliberately not a config switch, because WhatsApp and Telegram crons run side by side until Phase 4.
    - `--channel` on `stoiclife_run.py`, `build_payload.py`, `record_coaching.py`, `coaching_format.py`, `weekly_review.py`. The runner passes it into the printed `record_coaching.py` command, so the validator checks the right bold. On Telegram, a message using WhatsApp bold is rejected.
    - The coach hook (`coach-workspace/AGENTS.md` step 6) now passes `--channel telegram`. This is live on the coach's next turn, since the workspace is this checkout, and it only affects the Telegram coach.
    - Tests: new `tests/test_channel_fmt.py` (19 cases). All 52 pass (19 + 19 + 14). WhatsApp output was **byte-identical** before and after for `weekly_review.py`, `build_payload.py --event-id 226` and a `stoiclife_run.py` dry run.
  - [x] New coach crons → telegram account `coach`, to 8917837483: morning 07:30 (Health Snapshot + Stoic morning prep + `set_prompt_state.py --session morning`) and evening 20:30 (`evening-prompt.sh`)
    - [x] `coach_morning.sh` (this repo): the brief's Health Snapshot + morning prep, without System/Calendar. Output checked by hand (2026-10-06).
    - [x] `STOICLIFE_SKIP_PROMPT_STATE=1` guard in `coach_morning.sh` and the workspace `evening-prompt.sh`, so test runs don't write `state.json`. Gotcha: running `evening-prompt.sh` by hand **does** set awaiting-evening. It was done once by mistake at 00:37 on 2026-10-06 and reverted (stray line left in `stoic.log`).
    - Design: **command payloads** (`--command`, no model turn; stdout delivered verbatim via announce, `NO_REPLY` = silent). This is deterministic, free, and can't paraphrase the prompt. Created **disabled**: hard cutover, so they're enabled in Phase 4 when the WhatsApp ones are disabled. travel-mode retimes every cron-kind job, disabled ones included, so the new jobs need no change there.
    - [x] Approved and created 2026-10-06 00:40, **disabled**: `Coach Morning (07:30)` `73c880ac` (`coach_morning.sh`) and `Coach Evening Review (20:30)` `7e8a7edd` (`evening-prompt.sh`). Both: agent `coach`, command payload, announce telegram account `coach` → 8917837483, tz Australia/Brisbane. Note: `cron list` hides disabled jobs, so check `cron_jobs` in `openclaw.sqlite` or use `--all`.
    - [x] Delivery test: one-shot `--at +1m --delete-after-run` copies with `--command-env STOICLIFE_SKIP_PROMPT_STATE=1`. Both `ok` / `delivered` in `cron_run_logs`. Gateway log: `telegram outbound send ok accountId=coach chatId=8917837483` (messageId 6, 7). `state.json` stayed idle and the one-shots removed themselves.
    - Finding for the capture-flow step: command-cron deliveries are **not mirrored** into `agent:coach:main`, so the coach's transcript doesn't contain the prompt. Prefixed replies and `state.json` attribution are unaffected, but a bare reply arrives with no prompt context. Decide during capture testing whether that matters (options: coach AGENTS.md reads `state.json` on an unprefixed reply, or switch to agentTurn into a fixed session key).
  - [x] Weekly-review section → coach cron; stoiclife Safety-Net → agent `coach` (2026-10-06, created **disabled**)
    - `Coach Weekly Review (Sun 08:00)` `5dcb0e1a`: command payload `weekly_review.py --section both --channel telegram`. Empty output → `NO_REPLY` (silent). Script failure → `exit 1` (recorded as an error, not silence). `weekly_review.py` is read-only.
    - `Coach Safety-Net (11:00)` `700b6841`: agentTurn on agent `coach` (Sonnet), isolated. Same instructions as `74b9acbe` but with `--channel telegram` on `stoiclife_run.py` + `record_coaching.py`, and "use exactly the bold markup the payload shows" instead of a hardcoded `*Observation:*`.
    - Tests (one-shot copies, all `ok`):
      - weekly: delivered (Telegram msg 8), Telegram bold.
      - safety-net on today's gate with `--dry-run`: `HEARTBEAT_OK` → `not-delivered`, as intended.
      - full path via `build_payload.py --event-id 226` + `coaching_format.py --channel telegram` (no record): Sonnet composed a valid `**Observation:**` message, delivered (msg 9), 44 s.
      - DB unchanged: `trigger_events` max id 232, `trigger_coaching` 19, `message_sent` 19.
    - Testing gotcha: a past firing date dry-runs as SILENT (cooldown), so the SEND_FULL path can only be exercised through `build_payload.py --event-id N`.
  - [x] Put the Stoic + Health sections of `morning-brief.sh` / `weekly-digest.sh` behind a flag (calendar/tasks stay on WhatsApp). Applied 2026-10-06 00:54 (workspace repo, synced on its `main`).
    - Knob: `~/.openclaw/stoic/coaching-channel` = `whatsapp` | `telegram`, read by the new `workspace/scripts/coaching-channel.sh`. Order: `$COACHING_CHANNEL` env → file → `whatsapp`. Unknown value → `whatsapp` + a stderr warning. **No file exists yet**, so behaviour is unchanged until Phase 4 writes `telegram`.
    - On `telegram`, `morning-brief.sh` skips `set_prompt_state.py --session morning`, the Health Snapshot and Morning Prep (System + Calendar stay), and `weekly-digest.sh` skips `weekly_review.py`.
    - Verified in a scratch copy with a stubbed `set_prompt_state.py`:
      - default/bogus output identical to the original (brief: apart from the live RAM figure); the state stub was called.
      - telegram: sections gone and the stub was **not** called.
    - Verified live: weekly digest default is byte-identical; morning brief in telegram mode drops the sections and leaves `state.json` untouched. The live brief was **not** run in whatsapp mode, because it would write prompt state.
    - Rollback: `echo whatsapp > ~/.openclaw/stoic/coaching-channel` (or `rm` it) + re-enable the WhatsApp crons.
  - [x] Fitbit failure alerts: add a coach-bot Telegram copy; the WhatsApp alert stays (applied 2026-10-06 00:56)
    - All three alert points (07:00 `f4aadce7` step 3; 10:00 `697feda9` steps 3 + 4) get: "Then send the same alert text a second time with the message tool using channel: "telegram", accountId: "coach", target: "8917837483"… Send both; if one send fails, still attempt the other." Nothing else changed.
    - `accountId` is required. Without it an isolated `main` turn falls back to the default Telegram account (the Travelboard bot): `readStringParam(params, "accountId") ?? agentAccountId`.
    - Backup of both jobs before the edit: `~/.openclaw/cron/bak-coach-fitbit-20261006-005659.json`. Rollback: `cron edit <id> --message` with the backed-up `payload.message`.
    - Test: a one-shot on `main` with the real step 3 wording and a stand-in command that always exits 3 (Gemini, 27 s). It retried, then sent both alerts: WhatsApp `Sent message 3EB0B2887435C7917E6665` at 00:58:29, Telegram `accountId=coach` msg 10 at 00:58:39. The real sync and the DB were not touched.
  - [ ] Capture flow (`morning prep:` / `evening review:`, `mood N`, 👍/👎) works in the coach chat; check whether Telegram reactions reach the agent
    - Test plan (agreed 2026-10-06): use **real** entries, not synthetic ones. Synthetic entries would mean DB cleanup, and the global Supermemory plugin (no per-agent isolation, `config: {}`) would also capture the fake text. Morning/evening: after the WhatsApp prompt (which sets `state.json`), Mihajlo replies in the **Telegram coach chat** with the prefix + `mood N`. Then check the `journal_entries` row, the manual mood, the reply, and the `stoiclife_run --channel telegram` event.
    - [x] Typed 👍 (2026-10-06 01:03): the coach ran `record_reaction.py --usefulness 1 --reaction "👍"` → exit 3 "no delivered, unrated push within 18h". No write (journal 210 / events 232 / coaching 19 unchanged). Correct. It then tried a read-only query with invented column names, recovered with `SELECT *`, and replied sensibly.
    - [x] Tap reaction: **does not reach the coach** (tested 2026-10-06 01:03–01:10). Mihajlo tapped 👍 on the cron-sent test push (msg 9) twice and on a coach in-conversation reply, then sent "Ok". The full turn prompt in the trajectory has no `Telegram reaction added`; no agent session anywhere has one. The coach answered "Ok" with NO_REPLY (correct).
      - Ruled out: the poller requests `message_reaction` (`resolveTelegramAllowedUpdates`). Routing would go to the coach session (`resolveAgentRoute` with accountId). The sent-message cache is keyed chatId+messageId in one global bucket per session store; that can give cross-bot false *matches*, not misses.
      - Not yet ruled out: `authorizeTelegramEventSender` (mode reaction) rejecting, or Telegram not delivering the update to the coach bot. Both are visible only at verbose log level, which likely needs a gateway restart.
      - Default position: parity with WhatsApp, where tap reactions never arrived either. **Typed 👍/👎 is the supported rating path.** Debugging tap reactions is optional, not a cutover blocker.
    - Default value `reactionNotifications: own` and the code path, for reference: `bot-*.js` `bot.on("message_reaction")` → `wasSentByBot` → `authorizeTelegramEventSender` → `enqueueSystemEvent` (in-memory, not in `openclaw.sqlite`).
    - [x] Forgotten-prefix rule added to `coach-workspace/AGENTS.md` §1: no prefix + `state.json` awaiting + reads like an answer → ask once "Save this as your morning prep?"; save only on a clear yes.
  - [x] Dry run + one manual cron run delivered to the coach bot: done during steps 2, 3 and 5 (one-shot copies of all four coach crons + the Fitbit alert, all delivered from `accountId=coach`).
- [x] **Phase 4: hard cutover (no parallel run)**, done 2026-10-06 01:15–01:25 at Mihajlo's request ("do the phase 4 full cutover now and close this"; he tests the write path in normal use and reports bugs in a new session)
  - [x] Disable (don't delete) the WhatsApp coaching crons; flip the flags
    - Backup of every cron job first: `~/.openclaw/cron/bak-coach-cutover-20261006-011509.json`.
    - `~/.openclaw/stoic/coaching-channel` = `telegram`.
    - Disabled `12a4a4e5` Stoic Evening Review and `74b9acbe` stoiclife Safety-Net (WhatsApp).
    - Enabled the four coach jobs. First runs: morning 07:30 + safety-net 11:00 + evening 20:30 on 2026-10-06; weekly Sun 2026-10-11 08:00.
    - Morning Brief / Weekly Digest stay on WhatsApp, minus the Stoic/Health sections (verified live with the knob: brief = System + Calendar, `state.json` untouched; digest has no stoiclife block).
  - [x] Rollback runbook in OPERATIONS.md ("Coaching channel" → "Rollback to WhatsApp"). The old WhatsApp safety-net section is marked DISABLED and kept for rollback.
  - [x] Re-point `~/.openclaw/stoic/stoic_knowledge.md` → `coach-workspace/stoic_knowledge.md` (content identical; `build_payload.py` reads through the link). Ewok's TOOLS.md Stoic section is now a pointer, plus the Morning Brief / Weekly Digest / fitbit bullets; AGENTS.md has the Stoic Journal pointer + feedback line. Originals: `docs/ewok-stoic-sections-archived.md`. Sizes: TOOLS.md 14,567 / AGENTS.md 18,448 chars (limit 20,000), no truncation in the gateway log.
    - Verified with an undelivered `main` turn (session `agent:main:cutover-check`): Ewok says it would redirect `evening review:` to @stoiclife_coach_bot and that 🧭 ratings go there.
  - Gateway active; `channels status`: Telegram coach + default and WhatsApp all connected.
  - Side note: the CLI prints `supermemory: not configured`, so the global-capture concern for test text may be moot. Not investigated.
- **Deferred (multi-user, future):** `user_id` data layer, trusted-identity plugin, pairing onboarding, global dmScope, per-user caps/tz, Supermemory isolation, per-user Fitbit, /export /delete, privacy note.

## Findings (Phase 0, 2026-10-05, OpenClaw 2026.6.8)

**Where things live**
- Coaching engine: this repo. `stoiclife_run.py` (gate → SILENT/CLARIFY/SEND_FULL/HOLD_QUIET; never sends), `trigger_matrix.py`, `status.py`, `build_payload.py`, `coaching_format.py`, `record_coaching.py`, `record_reaction.py`, `weekly_review.py`, `sleep_score.py`, `spo2_signal.py`, `stoiclife_config.json`, `prompts/*.md`. Tests: `tests/test_late_morning.py` and `tests/test_manual_mood.py`, standalone scripts, 33 cases (Phase 3 added `tests/test_channel_fmt.py`).
- Journal flow is **not in git here**. It lives in `~/.openclaw/workspace/scripts/` (`save_entry.py`, `coach_context.py`, `update_entry.py`, `set_prompt_state.py`, `db_init.py`, `evening-prompt.sh`, `morning-brief.sh`, `weekly-digest.sh`) and is auto-synced by the workspace cron.
- Coach persona = instructions to Ewok in `workspace/TOOLS.md` ("Stoic Journal") + `AGENTS.md`. Framework: `workspace/stoic/stoic_knowledge.md`. Journal prompts: `workspace/stoic/prompts/`.
- Health ingestion: `~/projects/fitbit-sync` → `biometrics` table (single OAuth token).
- "Drawing prompts" in the brief = the journal prompts: morning prep at 07:30 inside the `Morning Brief` cron (`scripts/morning-brief.sh` → `stoic/prompts/morning_prompt.txt`), evening review at 20:30 via the `Stoic Evening Review` cron (`scripts/evening-prompt.sh`). Both call `set_prompt_state.py`.

**WhatsApp coupling**
- Crons announcing to `whatsapp +61410772771`: Morning Brief `01c20347` (mixed content), Stoic Evening Review `12a4a4e5`, Weekly Digest `a1fb56f7` (mixed), stoiclife Safety-Net `74b9acbe`. The Fitbit 10:00 payload text sends failure alerts by WhatsApp.
- Live cron store is `~/.openclaw/state/openclaw.sqlite` table `cron_jobs` (`~/.openclaw/cron/` holds stale copies).
- Formatting: `coaching_format.py` validator ("WhatsApp-safe", no `#`/tables, `*bold*`), `build_payload.py:157`, `weekly_review.py`, `status.py`.
- Capture uses the text prefixes `morning prep:` / `evening review:` and typed 👍/👎 (WhatsApp tap-reactions aren't delivered).
- The decision logic is already channel-agnostic: it prints, and the cron or agent delivers.

**OpenClaw config**
- One agent (`main`, defaults only), no `bindings`, no `session` block. WhatsApp DM and Telegram DM share session `agent:main:main`.
- Telegram: one bot (Travelboard), token in plaintext in `openclaw.json`, `dmPolicy: allowlist [8917837483]`, group `-5516645333`.
- Model: primary `google/gemini-3.1-flash-lite`. Anthropic auth order is `api_key` first, then a `token` profile as fallback.
- Secrets: openclaw.json, `~/.openclaw/.env`, `gateway.systemd.env`. `${VAR}` substitution is supported (`docs/gateway/configuration.md:678`), and so is Telegram `tokenFile`.
- `plugins.allow` is an allowlist. The memory slot is `openclaw-supermemory`, shared across the install.

**Docs verified (`~/.npm-global/lib/node_modules/openclaw/docs/`)**
- Multi-bot: `channels.telegram.accounts.<id>` + `bindings[].match.{channel, accountId}` (`concepts/multi-agent.md:327-364`).
  - With ≥2 accounts, set `defaultAccount` (`channels/telegram.md:1079`).
  - A binding without `accountId` matches the default account only.
- Per-agent `workspace` / `model` / `tools.allow|deny` / `sandbox`: `gateway/config-agents.md:1050-1095`, `concepts/multi-agent.md:566-600`. The workspace is the default cwd, **not** a sandbox.
- `session.dmScope`: `main | per-peer | per-channel-peer | per-account-channel-peer`.
- `dmPolicy`: `pairing | allowlist | open | disabled`.
- Dynamic per-user agents exist for **Feishu only**.
- For the future: plugin tool factories receive `toolContext.requesterSenderId`, "Trusted sender id from inbound context (runtime-provided, not tool args)" (`dist/types-*.d.ts`). This is the basis for a model-proof `user_id`.

**Config writes can restart the gateway (found in Phase 1 prep)**
- `gateway.reload` is unset, so it defaults to `hybrid`: "Hot-applies safe changes instantly. Automatically restarts for critical ones" (`docs/gateway/configuration.md:555`). Writing `openclaw.json` therefore counts as a possible restart.
- Procedure: build the candidate in the scratchpad → `OPENCLAW_CONFIG_PATH=<candidate> ~/.npm-global/bin/openclaw config validate` → show the diff → ask → back up `openclaw.json.bak-coach-<ts>` → write → `is-active` + gateway log.
- Heartbeat scope: "if any agent has a `heartbeat` block, only those agents run heartbeats" (`docs/gateway/heartbeat.md:120`), so `main` gets an explicit block.
- A new agent reads through to `main`'s auth profiles (`concepts/multi-agent.md:32-35`).

**Telegram multi-account internals (Phase 2, from 2026.6.8 source)**
- Top-level `botToken` stays the implicit `default` account even when `accounts` exists (`account-selection-*.js` `hasImplicitDefaultTelegramAccount`).
- `mergeTelegramAccountConfig` (`account-config-*.js`): multi-account mode only kicks in when `accounts` has **more than one** key; then each account takes `groups` **only** from its own block. Moving Travelboard into `accounts.default` beside `accounts.coach` would silently drop the `-5516645333` group config. That's why the top level stays put.
- A named account inherits every other top-level key (dmPolicy, allowFrom, groupPolicy, network IPv4 fix, mediaMaxMb, defaultTo). `allowFrom` merges, so a restrictive top-level list wins over an account `*`.
- Missing `${VAR}` produces only a **warning** at runtime (`resolveConfigForRead` `onMissing`), and `config validate` **does not check env refs** (a control test with an undefined var passed). The real check is `getMe` with the `.env` token.
- The config loader re-reads `~/.openclaw/.env` on each load (`maybeLoadDotEnvForConfig`), so a hot reload sees vars added after gateway start.
- Docs' reload table: `channels.*` and `bindings` hot-apply with no gateway restart.

**Multi-user blockers (why it's deferred)**
- DB `~/.openclaw/stoic/stoic_journal.db` has no `user_id` (`biometrics.date` is the PK).
- Global `state.json`, one timezone knob, "Mihajlo" hardcoded.
- The model calls scripts with ids and dates it chooses, plus raw sqlite.
- Supermemory is global, and there is one Fitbit token.

## Decisions

- **2026-10-05: branch lives in stoiclife, not the workspace.** `~/bin/sync-openclaw.sh` (hourly) runs `git add .` + commit on whatever branch the workspace has checked out, so a feature branch there would absorb Ewok's memory churn.
- **2026-10-05: descope to single user.** The migration risk is small; the multi-user risk (data isolation, identity, shared memory) is large. Do one at a time.
- **2026-10-05: still use a separate bot + `coach` agent.** It leaves Travelboard's bot and the `main` agent untouched, and it's the hardest part to retrofit when multi-user comes back.
- **2026-10-05: leave `session.dmScope` alone.** One allowlisted user, and session keys already include the agent id, so a global change would only split Mihajlo's Ewok WhatsApp/Telegram sessions for no gain.

- **2026-10-05: answers from Mihajlo.**
  1. "Drawing prompts" = the 07:30 and 20:30 journal prompts.
  2. Move only the Stoic part; calendar and tasks stay on WhatsApp. The Health Snapshot counts as coaching ("health-tracker stats"), so it moves too. Confirm at the start of Phase 3.
  3. Hard move, no parallel run; WhatsApp is kept ready for rollback.
  4. Fitbit failure alerts go to both channels.
- **2026-10-05: coach workspace = `~/projects/stoiclife/coach-workspace/`**, used directly as the agent workspace, so it's versioned on this branch without symlinks.
- **2026-10-05: coach model = Sonnet, Gemini Pro fallback, never Opus** (provider-fallback-spillover lesson). Tools are an allow-list: exec, process, read, message, session_status.

- **2026-10-06: Travelboard group allowlist stays `groupAllowFrom: []` for now.** The audit CRITICAL `channels.telegram.groups.allowFrom.missing` predates this work and is accepted. Revisit it before more travellers join or before going multi-user.

- **2026-10-06: Health Snapshot moves to the coach bot** (confirmed by Mihajlo). It leaves the WhatsApp Morning Brief and goes out in the 07:30 coach message alongside the Stoic morning prep.

- **2026-10-07: manual mood also accepted at the END of an entry.** The first real Telegram entries put it last (`... with the kids. mood:7`, a final `Mood 6` line), so the start-only parser ignored them and they were saved as inferred. `save_entry.parse_manual_mood` now checks the end too (a start token wins; mid-sentence still never matches). Tests: `tests/test_manual_mood.py` 26/26. Entries 212/213 set to `manual` (6/7) and the token removed from the text; DB backup `stoic_journal.db.bak-moodend-20261007-101914`.

- **2026-10-07: FEAT-06 Stoic modules.** Inline `module:<name>` (start or end, before or after mood) calls a module from `coach-workspace/STOIC-MODULES.md` (1 Happiness, 2 Creativity, 3 Emotions; aliases incl. number + `hapiness`; colon required). Parser `workspace/scripts/stoic_modules.py`; `save_entry.parse_inline_tags` strips both tokens in any order and stores `journal_entries.module` (new column, `db_init.py`; DB backup `stoic_journal.db.bak-feat06-20261007-103224`). `coach_context.py` appends a `=== STOIC MODULE … (requested, weight this) ===` block; coach `AGENTS.md` weights 1–2 of its principles, and on SEND_FULL sends module coaching first, then the stoiclife message. Unknown name → left in text, coach lists the modules. Tests `tests/test_stoic_modules.py` 29/29; scratch-DB end-to-end verified. Pending: first live `module:` entry. Later (optional): module counts in the weekly review.

- **2026-10-07: FEAT-07 (coach Telegram UX: buttons/keyboard/state routing) Phase 0 discovery.** `docs/CURRENT-STATE.md`: crons, inbound path, parsing locations, DB schema/counts, OpenClaw 2026.6.8 capability check. Plugin callback handler YES (`registerInteractiveHandler`, namespace `sc`, auto-ack), edit YES, silent send YES (CLI only), **ForceReply NO, reply keyboard NO**, reply-to metadata YES (but `inbound_claim` only for plugin-bound conversations), voice YES/unverified. 7 plan mismatches listed there (mood 1–10 vs 1–5, evening review, no coaching response id, …). No code/data changed.

- **2026-10-07: FEAT-07 Phase 1 (foundation) built and live.** Working file `docs/FEAT07-UX-TELEGRAM-SEED.md` (plan v2 + review gaps G1–G20). Migration runner `migrate.py` + `migrations/001_ux_tables.sql` (checkin_events, coaching_responses (+text), response_feedback, ui_messages); live DB backup `stoic_journal.db.bak-mig001-20261007-222424`, pre-existing counts unchanged. `checkins.py` (logical-day local_date, upsert, G9 merge rule), `tg.py` (CLI send/edit, pending state in state.json, ui_messages), `sc_dispatch.py` (all button/command logic), `send_coaching.py` (r/t, not wired in yet), `sc_test_button.py`. Plugin `plugin/stoic-coach-ui/` = thin JS shim → sc_dispatch.py; linked install + coach `inlineButtons: dm`; one gateway restart 22:25, all channels back. Workspace scripts touched (D16): `save_entry.py` (merge check-ins after insert; reset keeps `pending`), `set_prompt_state.py` (read-modify-write). Tests `tests/test_feat07_phase1.py` 68/68; existing suites green. Rollback in OPERATIONS.md.
- **2026-10-07: FEAT-07 Phase 1 acceptance passed.** Live tap on `sc:mood:7` (msg 64) → `checkin_events` row (mood 7, button) + in-place edit; `sc:fb:r1:up` → logged "lands in Phase 2", ignored; no gateway/agent activity during either tap, no `callback_data` in the coach session; a plain "hi" got the normal coach reply after the restart. Test rows removed (check-in, coaching_responses 1, ui_messages 64–66); new tables back to 0 rows, pre-existing counts unchanged.

- **2026-10-07: FEAT-07 Phase 2 (feedback buttons) done and merged.** Every coaching reply (`send_coaching --kind r`, journal flow incl. SILENT/HOLD_QUIET/CLARIFY) and every stoiclife push (`record_coaching --send` → `send_coaching --kind t`, journal SEND_FULL + 11:00 cron) now arrives with 👍/👎. 👎 → reasons (2×2) → "Tell me more" → typed note (`save_feedback_note.py`, AGENTS.md step 0). Typed 👍/👎/neutral → `record_feedback.py` (latest unrated r|t, 18h). `t` ratings mirror to trigger_coaching via `record_reaction.py --coaching-id`. Buttons change, coaching text never re-edited (keeps bold). 11 discrepancies vs plan v2 fixed (P2-D1..D11 in `docs/FEAT07-UX-TELEGRAM-PROGRESS.md`), notably: the normal reply is still sent on SILENT, and text goes on stdin (the coach can't write files). Cron `700b6841` message updated (backup `~/.openclaw/cron/bak-feat07-p2-safetynet-20261007-225138.json`). Live: bold via CLI ✓, DM `NO_REPLY` ✓, button paths ✓, full pipeline on a throwaway entry ✓ (test rows + its quiet-hours hold deleted). Tests: phase2 43/43, phase1 67/67, existing green. No workspace scripts or gateway config touched.

- **2026-10-07: FEAT-07 Phase 3 (mood/module check-ins) done and merged.** `/mood` and `/module` send one check-in card (mood 1–5 / 6–10 via `channelData.telegram.buttons`, 3 modules, note buttons). Every tap re-renders it from the DB. Buttons carry their day (`sc:mood:7:YYYYMMDD`), so an old card says "expired". "📝 Add a note" → typed note on `checkin_events.note`. Inline `mood N` / `module:x` are also logged as `legacy_prefix` check-ins, stamped at the entry's `created_at` so G9 doesn't leak them onto the next entry. `/journal` and `/skip` stay "Coming soon" until Phase 4. `save_feedback_note.py` → `save_pending_note.py`. **Bug P3-B1** (found live): OpenClaw glues the inbound text onto the history block, the coach misread it and skipped step 0, so a note was lost. Fixed with a plugin `message_received` hook that saves pending notes deterministically + a consumed marker for step 0, and firmer AGENTS.md wording. Two gateway restarts (23:14 shim pass-through, 23:25 hook). Tests phase3 48/48, phase1/2 updated, all green. No workspace scripts touched. Lesson for Phase 4: route in the plugin hook, not via an LLM-run script.

- **2026-10-08: FEAT-07 Phase 4 (morning/evening without prefixes) done, merged and pushed.** Routing on arrival (spec D41–D52): the plugin's awaited `before_dispatch` hook runs `route_entry.py` (prefix → reply-to → note → ✍️/`/journal` → open window (`?` → hold) → late (hold) → conversation) and records it in `route_events`; the awaited `before_prompt_build` hook puts the route line, with the message text, into the coach's prompt. Notes are answered by the plugin with no agent turn. Hold and confirm (`[📝 It's my entry] [❓ It's a question]`, `[📝 Save as morning prep] [💬 Just chatting]`) holds the message, and the tap is passed on as a synthetic `callback_data: sc:hold:…` turn that carries the held text. Prompts are sent by `send_prompt.py` with ✍️ / Skip / 🙂 Check in (`prompt_events`, migration 002; backup `bak-mig002-20261007-235648`); `coach_morning.sh` has a new layout; new `coach_evening.sh` (cron `7e8a7edd` repointed, backup `bak-feat07-p4-evening-20261007-235652`). AGENTS.md: act on the route line; prefix detection, forgotten-prefix question and step 0 removed. One restart (23:57). Live: hold → question answered from the held text; plain text → evening entry + one coaching reply; note LLM-free; route recorded → injected every time (0.2–0.4 s); command-cron `NO_REPLY` verified. Bug P4-B1 (coach silent on "Thanks") → route line now forbids NO_REPLY on conversation; to verify. Tests: phase4 62/62, phase1–3 updated, all green. No workspace scripts touched.

## Open questions for Mihajlo

- (none open)

## Next step

**Migration complete (2026-10-06).** Remaining, in normal use:
- Mihajlo's first real `morning prep:` / `evening review:` entries in the coach chat (the Phase 3 write test). Check the `journal_entries` row: date from prompt state, manual mood, themes; also the `trigger_events` row from `stoiclife_run --channel telegram` and the reply format.
- First live runs: 07:30 morning, 11:00 safety-net, 20:30 evening (2026-10-06), weekly Sun 2026-10-11 08:00. Check `cron_run_logs`.
- Bugs → new session; start from OPERATIONS.md "Coaching channel" and this file.
- Later (optional): debug Telegram tap reactions (verbose log); multi-user (deferred list above).
