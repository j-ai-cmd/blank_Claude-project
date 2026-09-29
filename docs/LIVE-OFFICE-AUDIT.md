# Live Office audit

Checked against your original request, then hunted for bugs. Every item below was reproduced first, then fixed and re-checked.

## Your original request, point by point

| You asked for | Status | How it was checked |
|---|---|---|
| An office with every department and little Minecraft-style employees | ✅ | Built from `/api/office`, so the new org (Studio, Sales, Talent, Engineering, Ops + 4 at the head table) drew with no layout code changes. Headless screenshot. |
| When the backend works, that department is shown working | ✅ | `employee.state` events drive poses. Test: only the employees on a task wake; everyone else stays asleep (`tests/test_live.py`). |
| Click a desk to give a prompt (Atlas + Leads) | ✅ | End-to-end: clicked Sam's desk in the browser, typed a task, and the backend created it. Specialist desks are refused (403) and open a profile card instead. |
| On handover, they walk and deliver the note, so you know where the work is at every point | ✅ | End-to-end run: You → Sam → Script → Sam → Proof → Sam → You, each as a walk. After every backend test, an automatic check confirms every open task has exactly one holder and closed tasks have none. |
| Live, real time | ✅ | Server-Sent Events. Walks speed up when they fall behind the backend (was ~40 s behind, now a few seconds). |
| Backend details + a Stitch prompt | ✅ | `docs/STITCH-HANDOFF.md`, updated for the new org, Proof, and standing-rule approvals. |

## Flags found and fixed

| # | Flag | Effect | Fix |
|---|---|---|---|
| 1 | Opening any employee card crashed the page (React infinite re-render in the card header) | You couldn't open employee cards | Header reads the office once instead of building a new list every render. Browser test: 35 of 36 cards open (the miss was someone mid-walk). |
| 2 | Your new org lived on another branch | Office showed the old departments | Merged org v2; kept the office hooks on top of the new dispatcher. |
| 3 | Proof (fact checker) ran without any walk | The note seemed to sit with the Lead during fact-checking | `for_factcheck` / `factcheck_result` walks added (backend + demo). |
| 4 | "Part done" walk after a sub-task closed revived its note | A finished task's note stayed on Atlas's desk | Closed/cancelled notes can't be picked up again. |
| 5 | Standing-rule approvals (GM) never reached the office inbox | "Always/never" instructions could only be answered in Slack | GM now appears in the inbox. |
| 6 | Approvals that expired (parked after 72 h, or replaced by a new contract version) never left the inbox | Stale cards that fail when clicked | Expiry now removes the card. |
| 7 | R3 actions (approve, then confirm) were refused by the office | Irreversible actions could only be confirmed in Slack | The office accepts the confirm step; the card re-appears as "CONFIRM …". |
| 8 | Wrong status reported when an approval was decided | Inbox could keep a decided card | Reports the new status. |
| 9 | Live deliveries had no "save to memory" checkboxes | Nothing you accepted in the office was ever remembered | Memory candidates are sent with the delivery. |
| 10 | After a page reload, inbox cards had no summary and no memory checkboxes | Decisions made blind after a reload | Snapshot approvals now read the same as live ones. |
| 11 | If creating a task failed, "Hand over the note" hung forever | Frozen dialog | Returns an error within 30 s. |
| 12 | The decision card appeared before the note arrived | Inbox and office disagreed | Cards land when the note does. |

## Still open

- **Not tried with real Claude agents.** All runs use scripted agents; the Agent SDK path needs your token.
- **Event history is in memory.** After a server restart the office reloads correctly from the database, but walks that were mid-way aren't replayed.
- **The preview link runs the demo only.** Artifacts can't reach outside servers; deploy `frontend/` to use your real office.
