# AARTH — Task Delegation (Cross-User Tasks) — Design Doc

Status: **Proposal / for review** · Owner: product · Last updated: 2026-07-03

Lets a user **assign a task to another person**, **track** it to completion, and
**receive** tasks others assign to them — all conversationally ("ask Priya to send
the deck by Friday") and through the Tasks screen.

This is the feature that makes AARTH *multiplayer*: every person you delegate to is
a reason for them to be on AARTH too (built-in growth), and it opens a clear
team/B2B upgrade path.

---

## 1. User stories

- **Delegate:** "Ask Priya to send the investor deck by Friday." → AARTH creates the
  task, assigns it to Priya, and I can see if she accepted, is on it, and finished.
- **Receive:** Priya opens AARTH, sees *"Mahesh assigned you 'Send investor deck',
  due Fri"*, taps **Accept**, and from then on it's a normal task in her list with
  reminders/follow-ups — tagged **"from Mahesh."**
- **Track:** I have a **"Delegated by me"** view with each task's status
  (Pending / Accepted / Done). I'm notified when Priya accepts, declines, or
  completes it — and nudged if it's slipping so I can follow up.
- **Decline:** If someone assigns me something I won't do, I can **decline** (they're
  told), so nobody can dump work on me silently.

---

## 2. Terminology

| Term | Meaning |
|---|---|
| **Delegator** | The user who assigns the task (a.k.a. assigner). |
| **Assignee** | The user who must do it (the owner of the actual task). |
| **Assignment** | The link + lifecycle between a delegator and an assignee for one task. |
| **Acceptance** | The assignee agreeing to take it on (Pending → Accepted). |

---

## 3. Design principle (why it stays simple)

**The assignee OWNS the task.** We keep AARTH's single-owner `Task` model: a
delegated task lives in the *assignee's* list, so **all existing machinery just
works for them** — reminders, the at-time ping, the accountability follow-up, the
evening review, the learned profile. We only add a back-link to the delegator
(`assigned_by_id`) and a small acceptance state.

- **One source of truth** for status (the assignee's task).
- The delegator gets a **read-only tracking view** (`Task WHERE assigned_by_id = me`)
  — they never see any of the assignee's *other* data.

This avoids a parallel "shared task" engine and reuses everything we've built.

---

## 4. Data model

### 4.1 Changes to `tasks`
| Column | Type | Notes |
|---|---|---|
| `assigned_by_id` | UUID FK users, **null** | The delegator. NULL = normal self-created task. |
| `assignment_status` | text | `none` \| `pending` \| `accepted` \| `declined` (default `none`). |
| `assigned_at` | timestamptz null | When it was delegated. |

`user_id` continues to mean **the owner/assignee**. `status`/`progress` continue to
mean the *doing* state (pending → completed). Assignment state is separate from work
state on purpose (you can have `assignment_status=accepted` + `status=pending`).

### 4.2 New table `connections` (Phase 2 — optional but recommended)
Builds your network of people you delegate to / from. Enables name autocomplete,
trust (auto-accept), and "only people I know can assign to me."
| Column | Notes |
|---|---|
| `user_id`, `contact_id` | the two people |
| `status` | `pending` \| `accepted` \| `blocked` |
| `created_at` | |

### 4.3 New table `pending_invites` (Phase 2 — assign to non-users)
When you assign to an email that isn't on AARTH yet, park it here; when they sign
up with that email, materialize the task + send them into onboarding.
| Column | Notes |
|---|---|
| `email`, `delegator_id`, `title`, `reason`, `deadline`, `created_at` | |

### 4.4 Notifications
Reuse the existing `notifications` table; add kinds:
`assignment_new`, `assignment_accepted`, `assignment_declined`, `assignment_done`,
`delegated_overdue`. Add optional `actor_id` (who triggered it) for "Priya accepted…".

---

## 5. Assignment lifecycle (state machine)

```
                 assign
   (delegator) ──────────▶  PENDING ──accept──▶ ACCEPTED ──(assignee does work)──▶ DONE
                              │  │                  │                                 │
                              │  └── decline ──▶ DECLINED                             │
                              │                    (delegator notified)              │
                              └── (auto-accept if connection + setting) ─────────────┘
   revoke (delegator, while PENDING/ACCEPTED) ──▶ removed from assignee (+ notice)
```

- **PENDING**: task exists in assignee's list but greyed/"needs your OK"; not yet
  reminding. Delegator sees "Pending Priya's acceptance."
- **ACCEPTED**: becomes a live task for the assignee → reminders/follow-ups start;
  delegator notified.
- **DECLINED**: task archived; delegator notified with optional reason.
- **DONE**: assignee completes it (normal flow) → delegator notified.
- **Revoke/cancel**: delegator can pull it back while pending or accepted.

Optional **auto-accept**: if the assignee has a connection with the delegator and
"auto-accept from people I know" enabled, skip PENDING → straight to ACCEPTED.

---

## 6. API (Phase 1)

| Method / path | Who | Does |
|---|---|---|
| `POST /assignments` `{title, to_email, when?, reason?, priority?}` | delegator | Create + assign a task in one shot. |
| `POST /tasks/{id}/assign` `{to_email}` | delegator | Delegate an existing task. |
| `POST /tasks/{id}/revoke` | delegator | Cancel a delegation (pending/accepted). |
| `GET /assignments/incoming` | assignee | Tasks assigned to me awaiting Accept/Decline. |
| `POST /assignments/{taskId}/accept` | assignee | Accept → live task. |
| `POST /assignments/{taskId}/decline` `{reason?}` | assignee | Decline → delegator notified. |
| `GET /tasks?filter=delegated` | delegator | "Delegated by me" + assignee + live status. |
| `GET /tasks?filter=assigned_to_me` | assignee | Incoming + accepted-from-others. |

Completion uses the **existing** `POST /tasks/{id}/complete` (assignee) — the
backend fires an `assignment_done` notification to the delegator.

**Resolution of `to_email`:** if it's a registered user → assign; else (Phase 2)
create a `pending_invite`. Phase 1 can restrict to registered users with a clear
"they're not on AARTH yet — invite?" message.

---

## 7. Chat / agent integration (the magic)

New agent tools so delegation is natural language:

- `assign_task(title, to, when?, reason?)` — "ask Priya to send the report by Fri",
  "get Rahul to book the venue tomorrow."
- `list_delegated()` — "what did I assign to others?", "did Priya send the deck?"
- Incoming handled conversationally — AARTH can say *"Priya asked you to send the
  report by Friday — want me to accept it?"* and on "yes" call `accept`.

**Resolving `to`:** match the name against the user's connections / recently-used
assignees; if ambiguous or unknown, AARTH asks ("Which Priya — priya@…?"). Never
guess an email.

This rides on the intent-first + duplicate-guard rules already in place, so it won't
mis-assign from old context.

---

## 8. Notifications & accountability

| Event | Who gets it | Example |
|---|---|---|
| New assignment | assignee | "Mahesh assigned you 'Send deck', due Fri. Accept?" (call-style) |
| Accepted / Declined | delegator | "Priya accepted 'Send deck'." / "Priya declined 'Send deck'." |
| Completed | delegator | "Priya finished 'Send deck'." |
| Assignee reminders | assignee | Normal at-time ping + 1h follow-up, phrased "Mahesh is counting on this." |
| Delegated slipping | delegator | "Your delegated task 'Send deck' (Priya) is overdue — want to nudge her?" |

The **assertive collective follow-up** already built simply widens to include
delegated items on both sides ("you owe Priya X; Rahul owes you Y").

---

## 9. UI / UX

**Tasks tab → three light sections:**
1. **My tasks** — self-created + accepted-from-others (chip: *"from Mahesh"*).
2. **Assigned to me** — incoming requests with **Accept / Decline** buttons.
3. **Delegated by me** — each with assignee name + a status chip
   (Pending / Accepted / Done) + a **Nudge** button.

**Ways to assign:**
- **Chat:** "ask Priya to …" (primary, on-brand).
- **Task menu:** "Assign to…" → pick a connection or type an email.

**Small identity needs:** show assignee/delegator **display names** (we have them);
Phase 2 adds avatars/initials.

---

## 10. Privacy, permissions, anti-abuse

- A delegated task is visible to **exactly two people**: delegator + assignee.
- The delegator sees **only that task**, never the assignee's other tasks/profile.
- **Accept/decline** means no one can silently pile work on you.
- **Block/mute** a user; setting: *"Only people I've connected with can assign to me."*
- **Rate-limit** assignments per user/day; add a **Report** action (Phase 2).
- Assignee can **decline** anytime before accepting, and **return** after accepting.

---

## 11. Edge cases to handle

- **Assignee not on AARTH** → invite-by-email flow (Phase 2); Phase 1 blocks with a
  friendly "invite them" prompt.
- **Delegator revokes/deletes** → task removed from assignee with a notice.
- **Assignee changes the deadline** → delegator sees the update (decision: silent
  update vs. "requested a new time, approve?" — recommend silent + a note for MVP).
- **Assignee account deleted** → delegated tasks marked "assignee left"; delegator
  can reclaim/reassign.
- **Onward delegation** (Priya re-assigns to someone) → Phase 3.
- **Duplicate assignment** of the same thing → reuse the existing duplicate-guard,
  scoped per assignee.

---

## 12. Phasing

**Phase 1 — MVP (delegation that works):**
registered-users-only; assign new/existing task by email; accept/decline; "Delegated
by me" + "Assigned to me" views; notifications on assign/accept/decline/complete;
`assign_task` + `list_delegated` agent tools.

**Phase 2 — Network & reach:**
connections/contacts + auto-accept from people you know; invite non-users by email;
delegator accountability nudges; a lightweight **comment/update thread** on a shared
task ("any update?"); block/report.

**Phase 3 — Teams / B2B:**
groups & shared projects, multi-assignee, roles, onward delegation, org/workspace
accounts — the paid **team plan** upsell.

---

## 13. Decisions needed from you

1. **Acceptance:** require Accept/Decline (recommended, prevents dumping) — or
   auto-accept so it just appears? (Could be a per-user setting.)
2. **Reach:** Phase 1 = registered users only (fast) — or build invite-by-email now
   so a friend gets pulled in even before they've joined?
3. **Deadline control:** can the assignee change the time, or is it delegator-owned?
4. **Billing:** do delegated tasks count against the assignee's plan limits, the
   delegator's, or neither? (Ties into the subscription model.)

---

## 14. Why this is worth it (business)

- **Growth loop:** each delegation invites a new user (the assignee). Delegation is
  inherently viral.
- **Stickiness:** shared accountability across people is far harder to leave than a
  solo to-do list.
- **Upsell:** teams/orgs → a paid **Team plan**, the natural B2B path beyond ₹499
  individual.
</content>
