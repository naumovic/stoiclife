#!/usr/bin/env python3
"""FEAT-07 Phase 6 — ux_metrics.py against a seeded scratch DB (and read-only on it).
Run: python3 tests/test_feat07_phase6.py
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(Path.home() / ".openclaw" / "workspace" / "scripts"))

import checkins  # noqa: E402
import ux_metrics  # noqa: E402

failures = 0
total = 0


def check(label, ok, detail=""):
    global failures, total
    total += 1
    if not ok:
        failures += 1
        print(f"FAIL  {label}  {detail}")
    else:
        print(f"ok    {label}")


TMP = Path(tempfile.mkdtemp(prefix="feat07p6-"))
schema = subprocess.run(["sqlite3", "-readonly", str(checkins.DEFAULT_DB), ".schema"],
                        capture_output=True, text=True, check=True).stdout
schema = "\n".join(l for l in schema.splitlines() if not l.startswith("CREATE TABLE sqlite_sequence"))
DB = TMP / "m.db"
with sqlite3.connect(DB) as c:
    c.executescript(schema)
subprocess.run([sys.executable, str(REPO / "migrate.py"), "--db", str(DB), "--no-backup"], check=True, capture_output=True)
C = "8917837483"
T = "+10:00"
with sqlite3.connect(DB) as c:
    # prompts: 3 mornings (2 answered after 30 / 90 min, 1 skipped), 2 evenings (1 answered, 1 open)
    P = [("2026-10-08", "morning", "07:30", "08:00", None, 1), ("2026-10-09", "morning", "07:30", "09:00", None, 2),
         ("2026-10-10", "morning", "07:30", None, "08:10", None), ("2026-10-08", "evening", "20:30", "21:00", None, 3),
         ("2026-10-09", "evening", "20:30", None, None, None)]
    for d, s, sent, ans, skip, eid in P:
        c.execute("INSERT INTO prompt_events (chat_id, local_date, session, message_id, sent_at, window_ends_at, "
                  "skipped_at, entry_id, answered_at) VALUES (?, ?, ?, 'm', ?, ?, ?, ?, ?)",
                  (C, d, s, f"{d}T{sent}:00{T}", f"{d}T11:00:00{T}", f"{d}T{skip}:00{T}" if skip else None,
                   eid, f"{d}T{ans}:00{T}" if ans else None))
    for i, (d, s) in enumerate((("2026-10-08", "morning"), ("2026-10-09", "morning"), ("2026-10-08", "evening"),
                                ("2026-10-09", "morning")), 1):
        c.execute("INSERT INTO journal_entries (id, date, session, raw_response, created_at) VALUES (?, ?, ?, 'x', 'x')",
                  (i, d, s))
    for src, n in (("window", 1), ("hold", 1), ("prefix", 1)):
        for _ in range(n):
            c.execute("INSERT INTO route_events (chat_id, at, route, session, source) VALUES (?, '2026-10-09T08:00:00+10:00', "
                      "'entry', 'morning', ?)", (C, src))
    c.execute("INSERT INTO route_events (chat_id, at, route, session, source) VALUES (?, '2026-10-09T13:00:00+10:00', 'hold', 'morning', 'late')", (C,))
    for d, t, v, src in (("2026-10-08", "mood", "7", "button"), ("2026-10-09", "mood", "5", "legacy_prefix"),
                         ("2026-10-08", "module", "creativity", "button")):
        c.execute("INSERT INTO checkin_events (chat_id, local_date, type, value, source, created_at, updated_at) "
                  "VALUES (?, ?, ?, ?, ?, 'x', 'x')", (C, d, t, v, src))
    # feedback: 3 replies (neutral day, flagged day, no flags) + 1 push
    for rid, sess, flags in ((1, "morning", {"fired": 0, "state": "neutral"}), (2, "evening", {"fired": 1, "state": "system_drain"}),
                             (3, "morning", None)):
        c.execute("INSERT INTO coaching_responses (id, chat_id, session, data_flags_json, created_at) VALUES (?, ?, ?, ?, 'x')",
                  (rid, C, sess, json.dumps(flags) if flags else None))
        c.execute("INSERT INTO ui_messages (message_id, chat_id, kind, ref_id, session, local_date, created_at) "
                  "VALUES (?, ?, 'coaching_r', ?, ?, '2026-10-09', 'x')", (f"r{rid}", C, rid, sess))
    ev = c.execute("INSERT INTO trigger_events (eval_datetime, date, session, state) VALUES ('x', '2026-10-09', 'safety-net', 'system_drain')").lastrowid
    c.execute("INSERT INTO trigger_coaching (id, event_id, generated_at, state, coaching_text, valid) VALUES (9, ?, 'x', 'system_drain', 'x', 1)", (ev,))
    c.execute("INSERT INTO ui_messages (message_id, chat_id, kind, ref_id, local_date, created_at) VALUES ('t9', ?, 'coaching_t', 9, '2026-10-09', 'x')", (C,))
    for kind, tid, rating, reason in (("r", 1, "up", None), ("r", 2, "down", "generic"), ("t", 9, "up", None)):
        c.execute("INSERT INTO response_feedback (target_kind, target_id, rating, reason, created_at) VALUES (?, ?, ?, ?, 'x')",
                  (kind, tid, rating, reason))
    for d, st, esc in (("2026-10-08", "complete", "none"), ("2026-10-09", "complete", "send_full"), ("2026-10-10", "not_synced", "none")):
        c.execute("INSERT INTO daily_updates (chat_id, local_date, status, escalation, created_at, updated_at) VALUES (?, ?, ?, ?, 'x', 'x')",
                  (C, d, st, esc))

before = DB.read_bytes()
m = ux_metrics.collect(ux_metrics.connect(DB), "2026-10-08", "2026-10-10")
check("read-only: DB bytes unchanged", DB.read_bytes() == before)
pm, pe = m["prompts"]["morning"], m["prompts"]["evening"]
check("morning: 3 sent, 2 answered (66.7%), 1 skipped", (pm["sent"], pm["answered"], pm["skipped"], pm["completion_pct"]) == (3, 2, 1, 66.7), pm)
check("median prompt → entry = 60 min (30, 90)", pm["median_minutes_to_entry"] == 60.0, pm)
check("evening: 2 sent, 1 answered (50%), skip 0%", (pe["sent"], pe["answered"], pe["completion_pct"], pe["skip_pct"]) == (2, 1, 50.0, 0.0), pe)
mo = m["checkins"]["mood"]
check("mood logged 2/3 days, by source", mo["days_logged"] == 2 and mo["rate_pct"] == 66.7
      and mo["by_source"] == {"button": 1, "legacy_prefix": 1}, mo)
f = m["feedback"]
check("feedback: 4 sent, 3 rated (75%), 👍 2/3", (f["all"]["sent"], f["all"]["rated"], f["all"]["feedback_rate_pct"],
      f["all"]["thumbs_up_share_pct"]) == (4, 3, 75.0, 66.7), f["all"])
check("by kind: r 3 sent / 2 rated; t 1 / 1", f["by_kind"]["r"]["rated"] == 2 and f["by_kind"]["t"]["sent"] == 1
      and f["by_kind"]["t"]["thumbs_up_share_pct"] == 100.0, f["by_kind"])
check("by flagged: push + drain reply flagged, neutral reply unflagged, no-flags unknown",
      f["by_flagged"]["flagged"]["sent"] == 2 and f["by_flagged"]["unflagged"]["sent"] == 1
      and f["by_flagged"]["unknown"]["sent"] == 1, f["by_flagged"])
check("by session: push counted under safety-net", f["by_session"]["safety-net"]["sent"] == 1, f["by_session"])
check("👎 reasons", f["down_reasons_all_time"] == {"generic": 1})
e = m["entries"]
check("entries by method incl. legacy + not routed", e["entries"] == 4 and e["by_method"] == {
      "typed after a prompt": 1, "confirmed via hold buttons": 1, "legacy prefix": 1, "before routing / not routed": 1}, e)
check("holds offered counted", e["holds_offered"] == {"late": 1})
d = m["daily_updates"]
check("daily updates", d["days"] == 3 and d["status"] == {"complete": 2, "not_synced": 1}
      and d["escalation"] == {"none": 2, "send_full": 1}, d)
out = subprocess.run([sys.executable, str(REPO / "ux_metrics.py"), "2026-10-08", "2026-10-10", "--db", str(DB)],
                     capture_output=True, text=True)
check("text report renders", out.returncode == 0 and "66.7%" in out.stdout and "🧭 push (t)" in out.stdout, out.stdout + out.stderr)
out = subprocess.run([sys.executable, str(REPO / "ux_metrics.py"), "2026-10-08", "2026-10-10", "--db", str(DB), "--json"],
                     capture_output=True, text=True)
check("--json parses", json.loads(out.stdout)["days"] == 3)

print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
