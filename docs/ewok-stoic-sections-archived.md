# Ewok's Stoic sections, archived at the coaching cutover (2026-10-06)

Verbatim copies of what Ewok's bootstrap files said before Phase 4 trimmed them to pointers. **Rollback:** paste each block back in place of its pointer (see OPERATIONS.md → Coaching channel rollback). Check the 20,000-char bootstrap limit after.

## workspace/TOOLS.md → `## Stoic Journal` (whole section, end of file)

````markdown
## Stoic Journal

(Full runbook — moved here from AGENTS.md to keep it lean; AGENTS.md keeps the short pointer.)

A daily Stoic journaling system. Mihajlo answers short prompts twice a day; answers are stored in SQLite and used as memory for a Stoic coach persona.

**Components:**
- **Morning prompt job (cron):** Sends a Stoic morning question (e.g. premeditatio malorum, intention setting).
- **Evening prompt job (cron):** Sends a Stoic evening review (e.g. what went well, what to improve, what was outside my control).
- **Answer handler → SQLite DB:** Captures the reply and writes it to `~/.openclaw/stoic/stoic_journal.db` (table `journal_entries`).
- **Stoic coach response (3-day memory window):** When responding, the coach loads the last 3 days of `journal_entries` for context and replies in a Stoic-aligned voice.
- **Query interface (natural language → SQL):** Lets Mihajlo ask questions like "what have I been worried about this week?" — translates the question into a SQL query against `journal_entries` / `biometrics` and summarizes the result.

**DB init:** `python3 ~/.openclaw/workspace/scripts/db_init.py` (idempotent).

**Keyword prefixes for journal entries:**
- Morning entry: message starts with "morning prep:" (case-insensitive)
- Evening entry: message starts with "evening review:" (case-insensitive)

**When sending a Stoic prompt (morning or evening):**
After sending the prompt, immediately update ~/.openclaw/stoic/state.json:
- awaiting_response: true
- session: "morning" or "evening" accordingly
- prompt_sent_at: current datetime as ISO 8601 timestamp

Also append this line to the bottom of the prompt when sending:
"↩️ Reply starting with *morning prep:* (or *evening review:*) to log your entry."

**When receiving a WhatsApp message from Mihajlo:**
1. Check if message starts with "morning prep:" or "evening review:" (case-insensitive)
2. If yes, also read ~/.openclaw/stoic/state.json and confirm awaiting_response is true
3. If both conditions met:
   - Strip the keyword prefix from the message before saving
   - Run: python3 /home/mihajlo/.openclaw/workspace/scripts/save_entry.py --session <morning|evening> --response "<message text without prefix>"
   - Reply to Mihajlo: "✅ Stoic entry saved."
4. If keyword present but awaiting_response is false — save anyway by adding the `--force` flag (this writes a warning to ~/.openclaw/stoic/stoic.log): `python3 /home/mihajlo/.openclaw/workspace/scripts/save_entry.py --session <morning|evening> --response "<message text without prefix>" --force`
5. If no keyword — handle as a normal message regardless of state.json

**After saving a journal entry** (the save in step 3 or step 4 above succeeded):
1. Capture the row ID printed by save_entry.py (it prints only the integer ID to stdout).
2. Run: `python3 /home/mihajlo/.openclaw/workspace/scripts/coach_context.py --entry-id <row_id>`
3. Read ~/.openclaw/stoic/stoic_knowledge.md for Stoic principles and personal context. If the file is empty or contains only comments/whitespace, skip it and coach from general Stoic principles alone — do not error.
4. Using the journal context and knowledge file, generate a coaching response yourself (no separate API call) with:
   - **coaching_text:** 3-5 sentences of Stoic coaching to Mihajlo, in the voice/principles of ~/.openclaw/stoic/stoic_knowledge.md (Ken Mogi's *Think Like a Stoic* + classical Stoicism). Keep it authentic, calm, grounded — candor over flattery. Name any patterns across the 3-day window. End with one short, practical question or next step.
   - **mood_score:** integer 1-10 inferred from the tone of today's entry only (1 = distressed, 10 = thriving). But if mood_source is already 'manual' (an inline `mood N`), skip this — keep the stored score; update_entry.py won't overwrite it. Still infer themes.
   - **processed_themes:** 2-5 single-word themes present in today's entry, chosen from or similar to: control, patience, resilience, distraction, gratitude, memento-mori, virtue, family, work, health, clarity, frustration, acceptance.
5. Run: `python3 /home/mihajlo/.openclaw/workspace/scripts/update_entry.py --entry-id <row_id> --mood-score <score> --themes "<comma-separated themes>"`
6. **stoiclife check:** run `python3 ~/projects/stoiclife/stoiclife_run.py --session <morning|evening> --entry-id <row_id>` and follow its `# AGENT:` lines. **Always pass `--entry-id`** (the same row id from step 1): save_entry.py back-dates a late reply, so the row's own date is the day to evaluate. Without it stoiclife_run falls back to the wall clock and an after-midnight or morning-after reply evaluates the *wrong* day, finds no entry, and emits a false ⚠️ "heads up". `SEND_FULL` → the stoiclife message replaces coaching_text (skip step 7); `CLARIFY` → send coaching_text then the printed 🧭 line; `SILENT`/`HOLD_QUIET` → send coaching_text + append any printed `STOICLIFE_STATUS:` line last. (No biometrics → SILENT.)
7. Send coaching_text to Mihajlo via WhatsApp — no preamble, just the text. (Skip if step 6 was SEND_FULL.)
````

## workspace/TOOLS.md → `## Morning Brief` + `## Weekly Digest` bullets

````markdown
## Weekly Digest

- **Script:** `bash scripts/weekly-digest.sh`
- **Cron:** gateway job "Weekly Digest", `0 8 * * 0` in the active timezone.
- **Requires:** `jq`, `curl`
- **What it does:** Compiles weekly status from `ewok-audit.md` + Obsidian changes:
  - Actions logged in the audit trail this week
  - Obsidian files modified this week
  - The stoiclife weekly review block
- **Output:** WhatsApp-formatted digest to stdout (framework delivers)
- **Consumes:** `scripts/audit-log.sh` (reads ewok-audit.md)


## Morning Brief

- **Script:** `scripts/morning-brief.sh`
- **Cron:** Daily at 7:30 AM AEST → WhatsApp
- **Contents:** System health, calendar, Health Snapshot (sleep/HRV/resting HR/steps — built by the script from the `biometrics` table), Stoic morning prep. Weather and news blocks exist in the script but are **commented out**.
- **Job ID:** 01c20347-9c8a-4497-8bf4-5f82c6f0a3ef
````

## workspace/AGENTS.md → stoiclife feedback line (under `### 😊 Reactions`)

````markdown
**stoiclife feedback:** when Mihajlo *replies* to a 🧭 push (typed 👍/👎, a word, or comment — WhatsApp tap-reactions aren't delivered), record it: `python3 ~/projects/stoiclife/record_reaction.py --usefulness <+1|0|-1> --reaction "<his reply>"` — targets the latest unrated push (18h).
````

## workspace/AGENTS.md → `## Stoic Journal`

````markdown
## Stoic Journal

Twice-daily Stoic journaling: Mihajlo replies `morning prep:` / `evening review:` → entries saved to `~/.openclaw/stoic/stoic_journal.db`, then a Stoic coach replies (3-day memory window); stoiclife may append a status line.

- **When a `morning prep:` / `evening review:` message arrives**, run the full save → coach → stoiclife flow documented in `TOOLS.md → Stoic Journal` (scripts: `save_entry.py`, `coach_context.py`, `update_entry.py`, `~/projects/stoiclife/stoiclife_run.py`; DB init `scripts/db_init.py`). Inline `mood N` sets a manual mood that always wins.
````
