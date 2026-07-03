# AARTH — Task Delegation (Cross-User Tasks) — Design Doc

Status: **Decisions locked · Phase 1 ready to build** · Last updated: 2026-07-03

Lets a user **assign a task to a connected person**, **track** it to completion, and
**receive** tasks people they've connected with assign to them — conversationally
("ask Priya to send the deck by Friday") and via the Tasks screen.

This makes AARTH *multiplayer*: connections + shared accountability drive growth and
retention, and delegation is **subscription-gated on both sides**, so it directly
pulls people into paying.

---

## 0. Confirmed decisions (product)

1. **Connection-gated + auto-accept.** Only people you've **connected** with (one
   sends a request, the other accepts) can assign you tasks — never a stranger.
   Within an accepted connection, assignments **auto-accept** (no per-task approval).
   Escape hatch: you can **Return** a specific task if it's not for you.
2. **Reach:** connect registered users; if they're not on AARTH yet, **invite by
   link** → they join → you connect. *(Confirmed OK.)*
3. **Deadline control:** the **assignee can change the deadline**; the **delegator
   gets a notification** of the change.
4. **Both parties must be subscribed.** If the assignee isn't subscribed, assigned
   tasks **pile up in a locked state** with "Subscribe to accept your tasks" — a
   built-in conversion nudge. If the delegator isn't subscribed, they can't assign.

---

## 1. User stories

- **Connect:** I search/invite Priya → send a connection request → she accepts. Now
  we can assign each other tasks.
- **Delegate:** "Ask Priya to send the investor deck by Friday." → it lands in
  Priya's list automatically (we're connected), tagged **"from Mahesh."**
- **Receive:** As Priya, connected tasks just appear in my list with reminders; I can
  **Return** one if it's wrong. Tasks from non-connections never reach me.
- **Track:** I have a **"Delegated by me"** view with each task's status
  (In progress / Done / Returned). I'm notified when Priya finishes it, returns it,
  or moves its deadline; I'm nudged if it's slipping so I can follow up.
- **Paywall pull:** If Priya isn't subscribed, my assigned tasks stack up for her
  behind "Subscribe to accept" — nudging her to upgrade.

---

## 2. Terminology

| Term | Meaning |
|---|---|
| **Connection** | A mutual, accepted link between two users; the trust boundary. |
| **Delegator** | The user who assigns a task. |
| **Assignee** | The user who does it (owner of the actual task). |
| **Return** | Assignee handing a specific task back (declines that one task, stays connected). |
| **Locked / piled-up** | An assigned task waiting because the assignee isn't subscribed. |

---

## 3. Design principle

**The assignee owns the task** — a delegated task lives in the assignee's list, so
all existing machinery (at-time ping, 1-hour follow-up, evening review, learned
profile) works for them automatically. We add:
- `connections` — the trust boundary + auto-accept.
- `assigned_by_id` on the task — the back-link the delegator tracks by.
- a small `assignment_status` — mainly to model the **locked (unsubscribed)** case.

One source of truth for work status; the delegator sees a **read-only** tracking view
and never any of the assignee's other data.

---

## 4. Data model

### 4.1 New table `connections`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `requester_id` | UUID FK users | who sent the request |
| `addressee_id` | UUID FK users | who receives it |
| `status` | text | `pending` \| `accepted` \| `blocked` |
| `created_at` / `updated_at` | timestamptz | |

Unique on the unordered pair (no duplicate connections). "Are A and B connected?"
= a row with the pair and `status='accepted'`.

### 4.2 Changes to `tasks`
| Column | Type | Notes |
|---|---|---|
| `assigned_by_id` | UUID FK users, **null** | delegator; NULL = normal self task |
| `assignment_status` | text | `none` \| `active` \| `locked` \| `returned` |
| `assigned_at` | timestamptz null | when delegated |

- `active` = auto-accepted, live for the assignee (reminders on).
- `locked` = assignee not subscribed → piled up, **no reminders**, shows paywall.
- `returned` = assignee handed it back → delegator notified, task archived for assignee.
- `user_id` still = assignee/owner; `status`/`progress` still = work state.

### 4.3 Subscription flag (depends on billing work)
Needs a per-user subscription state, e.g. `users.plan` (`free` | `pro`) or a
`subscriptions` table. Delegation reads it on both sides. *(Coordinate with the
billing/₹499 work — this is the shared dependency.)*

### 4.4 Notifications
Reuse `notifications`; add kinds + an optional `actor_id`:
`connect_request`, `connect_accepted`, `assignment_new`, `assignment_returned`,
`assignment_deadline_changed`, `assignment_done`, `delegated_overdue`,
`assignment_locked_waiting`.

---

## 5. Lifecycle (state machine)

```
CONNECT
  A → request ─▶ (B) pending ─ accept ─▶ CONNECTED (both directions)
                              └ decline/block ─▶ none/blocked

ASSIGN  (A → B). Preconditions: A and B CONNECTED, and A is subscribed.
  ├─ B subscribed     → task ACTIVE in B's list (auto-accept). Reminders start.
  │                     A tracks it; no action needed from B.
  └─ B NOT subscribed → task LOCKED (piled up) for B. No reminders.
                        B sees "N tasks waiting — Subscribe to accept."
                        A sees "Priya isn't subscribed yet."
                        (On B subscribing, all her locked tasks flip to ACTIVE.)

WHILE ACTIVE
  • B changes deadline  → task updates; A notified ("Priya moved 'X' to Sat 2pm").
  • B returns the task  → RETURNED; archived for B; A notified.
  • B completes         → DONE; A notified ("Priya finished 'X'").
  • A revokes           → removed from B (+ notice).
```

---

## 6. API (Phase 1)

**Connections**
| Method / path | Does |
|---|---|
| `POST /connections/request` `{email}` | Send a request (or invite link if not a user). |
| `GET /connections` | My connections + pending requests (in/out). |
| `POST /connections/{id}/accept` / `decline` / `block` | Manage a request. |
| `DELETE /connections/{id}` | Remove a connection. |

**Assignment**
| Method / path | Who | Does |
|---|---|---|
| `POST /assignments` `{title, to, when?, reason?, priority?}` | delegator | Create + assign (checks connection + both subscribed). |
| `POST /tasks/{id}/assign` `{to}` | delegator | Delegate an existing task. |
| `POST /tasks/{id}/revoke` | delegator | Pull back a delegation. |
| `POST /tasks/{id}/return` `{reason?}` | assignee | Hand a task back. |
| `GET /tasks?filter=delegated` | delegator | "Delegated by me" + assignee + status. |
| `GET /tasks?filter=assigned_to_me` | assignee | Active-from-others. |
| `GET /tasks?filter=locked` | assignee | Piled-up tasks (subscribe to accept). |

Completion + deadline edits use the **existing** task endpoints; the backend fires
the delegator notifications. Assigning to a non-subscriber returns a clear state so
the UI can show the paywall pile-up (not an error).

---

## 7. Chat / agent integration

New agent tools (all enforce connection + subscription server-side):
- `connect_person(name_or_email)` — "connect me with Priya."
- `assign_task(title, to, when?, reason?)` — "ask Priya to send the report by Fri."
- `list_delegated()` — "did Priya send the deck?", "what have I handed off?"

Resolution of `to`: match against **connections** first; if not connected → AARTH
offers to send a connection request; if not on AARTH → offer an invite link. Never
guesses an email. Rides on the existing intent-first + duplicate guards.

---

## 8. Notifications & accountability

| Event | Who | Example |
|---|---|---|
| Connection request | addressee | "Mahesh wants to connect on AARTH. Accept?" |
| Assigned (active) | assignee | "Mahesh assigned you 'Send deck', due Fri." |
| Assigned but locked | assignee | "Mahesh assigned you a task — subscribe to accept it." |
| Deadline changed | delegator | "Priya moved 'Send deck' to Sat 2pm." |
| Returned | delegator | "Priya returned 'Send deck'." |
| Completed | delegator | "Priya finished 'Send deck'." |
| Delegated slipping | delegator | "'Send deck' (Priya) is overdue — nudge her?" |

The existing assertive follow-up widens to cover both sides ("you owe Priya X; Rahul
owes you Y").

---

## 9. UI / UX

**Tasks tab — sections:**
1. **My tasks** — self-created + active-from-connections (chip: *"from Mahesh"*).
2. **Delegated by me** — assignee name + status chip (In progress / Done / Returned /
   Waiting-not-subscribed) + **Nudge** button.
3. **Waiting to accept** (only if you have locked tasks) — "Subscribe to accept N
   tasks people assigned you."

**Connections screen** (new, small): connections list, pending requests, "Add /
invite" (email or share link).

**Assign entry points:** chat ("ask Priya to…") primary; task menu "Assign to…" →
pick a connection.

---

## 10. Privacy, permissions, anti-abuse

- Only **connected** users can assign — no global/stranger assignments.
- A delegated task is visible to exactly the two parties; the delegator sees **only
  that task**, nothing else of the assignee's.
- **Block** a connection; blocked users can't request or assign.
- **Return** any single task without breaking the connection.
- Rate-limit requests/assignments; **Report** action (Phase 2).

---

## 11. Billing coupling (important)

Delegation is a **paid, both-sides** feature:
- **Delegator must be subscribed** to assign (upsell at the "Assign" action).
- **Assignee must be subscribed** for tasks to go **active**; otherwise they **pile
  up locked** → "Subscribe to accept the tasks people gave you" (conversion lever).
- On subscribing, a user's locked tasks flip to active in one sweep.

➡️ **Dependency:** needs the subscription state from the ₹499 billing work. Recommend
building **billing first (or in parallel)**, since delegation gates on it.

---

## 12. Phasing

**Phase 1 — MVP:** connections (request/accept/block) · auto-accept within a
connection · assign new/existing task · return / revoke · deadline-change +
completion notifications · locked pile-up for non-subscribers · "Delegated by me" +
"Assigned to me" views · `connect_person` / `assign_task` / `list_delegated` tools.

**Phase 2 — Reach & richness:** invite-by-link onboarding for non-users · comment /
"any update?" thread on a shared task · block/report · delegator accountability
nudges baked into the follow-up.

**Phase 3 — Teams / B2B:** groups & shared projects, multi-assignee, roles, onward
delegation, workspace accounts — the paid **Team plan**.

---

## 13. Phase 1 build checklist

1. **Billing dependency:** confirm the subscription flag (`users.plan` or
   `subscriptions`) exists or is being added.
2. **Migrations:** `connections` table; `tasks.assigned_by_id`,
   `assignment_status`, `assigned_at`; notification `actor_id`.
3. **Models:** `Connection`; extend `Task`.
4. **Services:** `connections_service` (request/accept/are_connected);
   `delegation_service` (assign → check connection + subscription → active|locked;
   revoke; return; on-complete/on-deadline-change → notify delegator; on-subscribe →
   unlock).
5. **API routes:** connections + assignment endpoints (§6); task filters.
6. **Agent tools:** `connect_person`, `assign_task`, `list_delegated` (+ prompt
   rules: only assign to connections; offer connect/invite otherwise).
7. **Nudges:** new kinds; widen the follow-up to delegated items.
8. **UI:** Connections screen; Tasks-tab sections + "from X" chips + status chips +
   Nudge; locked/paywall banner; chat flows.
9. **Tests:** connect→assign→active; assign-to-unsubscribed→locked→subscribe→active;
   return/revoke/deadline-change notifications; non-connection assignment blocked.

---

## 14. Why it's worth it

- **Growth loop:** every connection/assignment invites another user.
- **Retention:** shared accountability is far stickier than a solo list.
- **Revenue:** both-sides-subscription + the locked pile-up convert testers to payers,
  and Phase 3 opens the **Team plan** B2B tier.
</content>
