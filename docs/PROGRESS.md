# Coaching migration — progress

Plan: `docs/coaching-plan.md` (original brief + 2026-10-05 scope change). Branch: `coaching-migration` (stoiclife repo).
Rule: update this file after every completed step and commit it with the code. Stop at the end of each phase for approval.

## Status

- [x] **Step 0: progress tracking**
  - [x] `docs/coaching-plan.md` saved, with the scope-change note
  - [x] `docs/PROGRESS.md` (this file)
  - [x] `CLAUDE.md` pointer in stoiclife + `~/.openclaw/workspace/CLAUDE.md`
- [x] **Phase 0: recon (read-only)** (findings below)
- [ ] **Phase 1: `coach` agent**
  - [ ] Draft `agents.list` (`main` default unchanged + `coach`, workspace `~/.openclaw/workspace-coach`); check every key against the 2026.6.8 docs
  - [ ] Build the coach workspace: SOUL/AGENTS distilled from `workspace/TOOLS.md` "Stoic Journal" + `AGENTS.md` Stoic section, plus `stoic_knowledge.md` and the journal prompts
  - [ ] Tool policy: keep `exec` (scripts need it); deny browser/web/write/edit etc.; no MEMORY.md; decide about Supermemory
  - [ ] Per-agent model (Sonnet via the API-key profile)
  - [ ] Show the config diff → approval → apply → `config validate` (no restart without asking)
- [ ] **Phase 2: Telegram bot**
  - [ ] Mihajlo creates the bot in @BotFather
  - [ ] Token → `~/.openclaw/.env` `TELEGRAM_COACH_BOT_TOKEN`, referenced as `${TELEGRAM_COACH_BOT_TOKEN}`
  - [ ] `channels.telegram.accounts` {default = current Travelboard bot moved verbatim, coach = allowlist [8917837483]} + `defaultAccount: "default"`
  - [ ] Binding coach account → `coach` agent
  - [ ] Diff → approval → `config validate` → restart (with OK) → is-active, Travelboard DM + group OK, coach bot answers only Mihajlo in an `agent:coach:*` session
  - [ ] `openclaw security audit`, report and fix
- [ ] **Phase 3: re-wire coaching to Telegram**
  - [ ] Make the formatters channel-aware (`coaching_format.py`, `build_payload.py`, `weekly_review.py`, `status.py`) + tests
  - [ ] Crons: Stoic Evening Review + stoiclife Safety-Net → agent `coach`, telegram account `coach`
  - [ ] Split the Stoic part out of Morning Brief / Weekly Digest into a coach cron
  - [ ] Capture flow (`morning prep:` / `evening review:`, 👍/👎) works in the coach chat; check whether Telegram reactions reach the agent
  - [ ] Dry run + one manual cron run delivered to the coach bot
- [ ] **Phase 4: parallel run & cutover**
  - [ ] Parallel run (1–2 weeks)
  - [ ] Remove coaching crons/instructions from WhatsApp/Ewok; update OPERATIONS.md, TOOLS.md (20k bootstrap char limit)
- **Deferred (multi-user, future):** `user_id` data layer, trusted-identity plugin, pairing onboarding, global dmScope, per-user caps/tz, Supermemory isolation, per-user Fitbit, /export /delete, privacy note.

## Findings (Phase 0, 2026-10-05, OpenClaw 2026.6.8)

**Where things live**
- Coaching engine: this repo. `stoiclife_run.py` (gate → SILENT/CLARIFY/SEND_FULL/HOLD_QUIET; never sends), `trigger_matrix.py`, `status.py`, `build_payload.py`, `coaching_format.py`, `record_coaching.py`, `record_reaction.py`, `weekly_review.py`, `sleep_score.py`, `spo2_signal.py`, `stoiclife_config.json`, `prompts/*.md`. Tests: `tests/test_late_morning.py` and `tests/test_manual_mood.py`, standalone scripts, 33 cases.
- Journal flow is **not in git here**. It lives in `~/.openclaw/workspace/scripts/` (`save_entry.py`, `coach_context.py`, `update_entry.py`, `set_prompt_state.py`, `db_init.py`, `evening-prompt.sh`, `morning-brief.sh`, `weekly-digest.sh`) and is auto-synced by the workspace cron.
- Coach persona = instructions to Ewok in `workspace/TOOLS.md` ("Stoic Journal") + `AGENTS.md`. Framework: `workspace/stoic/stoic_knowledge.md`. Journal prompts: `workspace/stoic/prompts/`.
- Health ingestion: `~/projects/fitbit-sync` → `biometrics` table (single OAuth token).
- **Drawing prompts don't exist anywhere** (code, skills, crons).

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

## Open questions for Mihajlo

1. Drawing prompts don't exist. Out of scope for now?
2. Morning Brief / Weekly Digest mix Ewok content with Stoic content. OK to move only the Stoic part to Telegram?
3. Parallel run: duplicate on both channels, or Telegram-only coaching with WhatsApp as fallback?
4. Fitbit sync-failure alerts: keep them on WhatsApp (system alert) or move them to the coach bot?

## Next step

Wait for Mihajlo's go-ahead on Phase 1, then draft the `coach` agent config + workspace and show the diff.
