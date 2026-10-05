# Task: Move life-coach agent from WhatsApp to Telegram, multi-user ready

> Saved verbatim from Mihajlo's brief on 2026-10-05. Progress lives in `docs/PROGRESS.md`.

## ⚠️ Scope change 2026-10-05 (after Phase 0)

Phase 0 showed nearly all risk sits in the multi-user half. Mihajlo descoped to **WhatsApp → Telegram, single user (Mihajlo only)**. Multi-user is **deferred**, not dropped.

Active phases now (details and checkboxes in `PROGRESS.md`):
1. Dedicated `coach` agent (own workspace). Single user, so it keeps `exec` for the existing scripts.
2. Its own Telegram bot/account, bound to `coach`, allowlist = Mihajlo only. Travelboard untouched.
3. Re-wire coaching delivery and formatting to Telegram.
4. Parallel run, then retire coaching on WhatsApp.

**Deferred** (kept below for later): the multi-user parts of Phases 2–6. That covers pairing, the global `dmScope` change, the `user_id` data layer and trusted-identity plugin, per-user scheduling and caps, the isolation test, /export and /delete, beta onboarding and the privacy note.

The brief below is the original, kept verbatim.

## Context
I run OpenClaw on my Beelink server. The life coach (Stoic frameworks, health-tracker stats, drawing prompts, coaching advice) currently runs on WhatsApp. A separate feature, Travelboard, already uses Telegram on the same OpenClaw install. I want to:
1. Move coaching to Telegram on its OWN bot and its OWN dedicated agent, isolated from the rest of OpenClaw.
2. Make it multi-user ready, so trusted friends / beta testers can use it on my server and my API key, each with separate sessions and data.
3. Keep the coaching core channel-agnostic so I can later build a standalone app.

## Rules
- Phase 0 is read-only. Report findings and wait for my go-ahead before changing anything.
- Work on a git branch. Show me diffs before applying config changes.
- Do NOT restart the gateway, touch the WhatsApp setup, or change Travelboard without asking first.
- No secrets in the repo. Bot tokens go in the existing secrets/env mechanism.
- Verify every OpenClaw config key against the installed version (`openclaw --help`, local docs) rather than assuming. Some features I read about (e.g. dynamic per-user agents) were only documented for Feishu, not Telegram.

## Progress tracking (do this first)
- Save this whole plan into the repo as `docs/coaching-plan.md` so it survives context compaction and new sessions.
- Create `docs/PROGRESS.md` with a checkbox per phase and sub-step, plus these sections: Findings, Decisions (with reasons), Open questions for me, Next step.
- Update `PROGRESS.md` after every completed step, before moving on, and commit it with the code changes.
- Add this to the project's `CLAUDE.md`: "Active work: coaching migration. At the start of every session read `docs/coaching-plan.md` and `docs/PROGRESS.md`, resume from 'Next step', and keep PROGRESS.md updated."
- Stop at the end of each phase, summarise, and wait for my approval before starting the next.

## Phase 0: Recon (read-only)
- Where does the coaching code, prompts, Stoic framework files and health-stat ingestion live?
- How tightly is it coupled to WhatsApp (channel-specific code, formatting, session assumptions)?
- Where is data stored today, and what are the cron/scheduled jobs?
- How is Travelboard wired to Telegram (account, bindings, config)?
- Summarise, then propose a concrete step list.

## Phase 1: Dedicated coach agent
- Create a separate agent (e.g. `coach`) with its own workspace.
- Move identity files, Stoic frameworks and prompt templates into that workspace (shared, read-only content).
- Restrict its tools to coaching tools only: no shell, no general file access.

## Phase 2: Telegram bot for coaching
- I will create a NEW bot via @BotFather myself. Tell me where to put the token.
- Configure it as its own Telegram account and bind it to the `coach` agent only. Travelboard stays on its own bot.
- Access control: pairing or allowlist only, never open DMs.
- Set `session.dmScope: "per-channel-peer"`. Note this setting is global, so check the effect on Travelboard and tell me.
- Run `openclaw security audit` and fix anything it flags.

## Phase 3: Multi-user data layer
- One SQLite database, `user_id` on every table (users, health_stats, checkins, journal, prompt_log, settings).
- A single data-access module is the only code that touches the DB.
- `user_id` must come from the trusted sender identity (numeric Telegram user ID, not @username) supplied by the runtime. It must never be a parameter the model can set.
- Migrate my existing data in as user 1.
- Keep coaching logic in channel-agnostic functions. The Telegram layer should stay thin.

## Phase 4: Scheduling and cost controls
- Rework scheduled prompts and health-triggered nudges to loop over users, with per-user timezone and preferences. Deliver via Telegram.
- Add per-user daily message/token caps.
- Use a cheaper model for routine check-ins, and the better model for deeper coaching.
- Confirm we are using a proper API key (not a consumer subscription login).

## Phase 5: Verify
- Run WhatsApp and Telegram in parallel for 1-2 weeks, then retire WhatsApp.
- Isolation test with a second Telegram account: it must not see my history or data, including when asking the coach about other users.
- Add basic /export and /delete commands for user data.

## Phase 6: Beta onboarding
- Document the flow: friend opens the bot link, sends a message, gets a pairing code, I run `openclaw pairing approve telegram <code>`.
- Draft a short plain-language privacy note for testers (Telegram bot chats are not end-to-end encrypted; I can technically access data on my server).
