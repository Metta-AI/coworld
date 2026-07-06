# When the league rolls its coworld version: the migration procedure

Reference for the one-time-per-roll migration that happens when the crewrift league bumps its
coworld package out from under you. Read this when a session starts and the live league's coworld
ID no longer matches what local manifests, harness defaults, or your built player images reference —
or whenever an upstream bot you carry patches against has been rewritten. It is not an always-on
checklist and not the crux loop: it runs once, end to end, when a roll is detected, and then you go
back to the loop.

The league rolls its coworld package **without notice**. The moment it does, every local artifact —
the vendored game repo's manifest, the harness's default version, your built player images — is
silently targeting a dead version. You can run commands that *look* like they work and get numbers
that mean nothing, because they're certifying against a game the league no longer runs. The whole
point of this procedure is to detect that mismatch before you trust a single local number, then
migrate your crown-jewel patches onto the new upstream without re-introducing a known-dead lever.

> The procedure below was derived from the `0.1.24 → 0.1.36` migration. The numbered outcomes from
> that specific roll live in the playbook; what's captured here is the **reusable procedure**.
> (Session-derived, unverified — needs human review against the next roll.)

---

## The seven steps, in order

The ordering is load-bearing. Detect before you trust numbers; back up before you touch the tree;
probe compatibility before you rebuild; grep symbols before you port. Do not reorder.

### 1. Detect the live-vs-local ID mismatch

At session start, ask the live league what coworld version it's running and compare against what
local state references:

```bash
uv run coworld leagues <league_id>
```

Compare the live coworld ID against the version your vendored manifest / harness defaults point at.
**If they differ, nothing local is trustworthy yet.** Pull the new package and run a baseline
episode before believing any local measurement:

```bash
coworld download crewrift
# then run one baseline episode against the NEW game before trusting local numbers
```

A version roll is exactly the kind of state that's stale by default: re-check the live ID at the
start of every session in this area, not just once.

### 2. Back up the crown jewels FIRST — before anything touches the tree

This is the step that prevents catastrophe. The highest-value local work — strategy patches, an
untracked `advisor.py`, a custom `Dockerfile.llm` — typically sits as **uncommitted and untracked**
changes inside the vendored game repo. A version roll's reconciliation can clobber the working tree.
Save everything before you go further:

```bash
git status                       # inventory what's tracked-dirty vs untracked
git diff > backup.patch          # save tracked changes
# copy every untracked crown-jewel file (advisor.py, Dockerfile.llm, etc.) OUT of the repo
git fetch                        # SAFE: does not touch the working tree
```

`git fetch` is safe — it doesn't modify the working tree — so fetch first to assess the delta
against the new upstream *while your local work is still intact*. Do the backup and the fetch before
any checkout, reset, or merge.

### 3. Triage old patches against the rewritten upstream — do not blindly reapply

The upstream isn't just bumped; it's frequently **rewritten**. Your patches fall into three
buckets, and you must classify each one before reapplying:

- **Absorbed** — upstream now does what your patch did. Drop it; reapplying would conflict or
  duplicate. In the `0.1.24 → 0.1.36` roll, the slot-aware self-ID patch (previously our
  single biggest measured win) had been **absorbed upstream** — it was already in the new source.
- **Known-dead** — a patch you already measured as a regression. Do not carry it forward. In that
  roll, a witness-aware-kill patch was a known regression and was dropped.
- **Carry** — still a real, un-absorbed win. In that roll, only the LLM-advisor integration was
  worth carrying.

Triage means reading the new upstream source and deciding per-patch — not running `git apply
backup.patch` and hoping. A blind reapply re-introduces measured-dead levers and fights changes
upstream already made for you.

### 4. Verify the scoring constants survive

Whether your entire strategic playbook still holds hinges on one question: **did the reward/scoring
constants change?** Check them across versions directly from git:

```bash
git show <old_ref>:src/crewrift/sim.nim | grep <reward/scoring consts>
git show <new_ref>:src/crewrift/sim.nim | grep <reward/scoring consts>
```

- **Unchanged** → every prior strategic conclusion survives. The migration is pure re-wiring: port
  the carried patches and move on.
- **Changed** → the playbook needs **re-derivation, not just re-wiring**. The measured win/loss
  conclusions that depended on the old reward structure are now suspect; the refuted-levers and
  crux conclusions may need re-checking against the new scoring.

This check is cheap and decides the scope of the entire migration, so do it before investing in any
port.

### 5. Run the cheap compat probe before any rebuild

Before rebuilding a single image, find out whether you even need to. Run **one OLD player image**
against the **NEW** game's cert fixture:

- A clean connect / run / replay means the wire protocol is backward-compatible and your existing
  built images are still usable as-is. You've just avoided a full rebuild cycle.
- A failure tells you the protocol moved and a rebuild is mandatory — but you learned that from one
  cheap probe instead of a full build-upload-eval round trip.

This probe is the difference between a 5-minute migration and an hour of unnecessary rebuilds.

### 6. Port carried patches by symbol-grep

When step 5 says you must rebuild, port the **carried** patches (from step 3) mechanically, not by
merge guesswork. Before editing the new source, grep it for **every** proc, field, and const the
patch references — plus a name-collision check:

```bash
# for each symbol the patch calls:
rg '<proc_or_field_or_const_name>' src/
# and a collision check for any new name the patch introduces
```

If every symbol the patch depends on still exists with the same signature, the port is mechanical.
If a symbol was renamed, moved, or had its signature changed, the grep surfaces it before you
compile, turning a risky merge into a deterministic edit. In the reference roll, the symbol-grep
port **compiled clean on the first build** — that's the signal that this step works.

### 7. Trust the manifest player id, not the binary's logging name

The reference bot's **binary logging name and its manifest/binary id can disagree**, and the
manifest is authoritative. In `0.1.36`, the reference bot logs itself as `truecrew`, but the
manifest id and the binary are still `notsus`. If you key any roster entry, comparator, or seat
assignment off the name the binary prints in its logs, you will mis-identify players. Always resolve
identity from the manifest player id.

This compounds the seat-verification rule from the crux loop: opponents land in **list order**, and
a binary's self-reported name is not its identity. Verify seat assignment from
`participants[].position` and player identity from the manifest id — never from log output.

---

## Trigger

Run this procedure when **either** holds:

- the live league's coworld ID (from `coworld leagues <league_id>`) differs from what local
  manifests / harness defaults / built images reference; **or**
- an upstream bot you carry patches against has been rewritten.

Until you've completed it, treat every local measurement as certifying against a dead version.

---

## Why each guard exists (the evidence)

From the `0.1.24 → 0.1.36` migration (session-derived, unverified):

- The **symbol-grep port compiled clean on the first build** — mechanical port instead of a merge
  gamble (step 6).
- The **compat probe avoided an unnecessary rebuild** — one old image against the new fixture
  certified the protocol was backward-compatible (step 5).
- The **absorbed-patch triage avoided re-introducing a measured regression** — the slot-aware
  self-ID patch was already upstream, and the witness-aware-kill regression was correctly dropped
  rather than reapplied (step 3).

---

## Quick reference

| Step | Action | Guards against |
|---|---|---|
| 1 detect | `coworld leagues <id>`; compare live ID vs local; `coworld download` + baseline if differ | trusting numbers certified against a dead version |
| 2 back up | `git status`; `git diff > backup.patch`; copy untracked files out; `git fetch` (safe) | the roll clobbering untracked crown-jewel patches |
| 3 triage | classify each patch absorbed / known-dead / carry against the rewritten upstream | re-introducing absorbed or measured-dead levers |
| 4 constants | `git show <ref>:src/crewrift/sim.nim \| grep` rewards across versions | a silently-changed reward structure invalidating the playbook |
| 5 compat probe | one OLD image vs the NEW game's cert fixture | an unnecessary rebuild (or a missed mandatory one) |
| 6 port | symbol-grep every proc/field/const + collision check before editing | a risky blind merge against rewritten source |
| 7 identity | trust manifest player id, not the binary's logging name | mis-identifying players by their self-reported log name |

---

## Related

See `crux-loop-and-asana-state.md` for the resumable improvement loop you return to after a roll
(and for the `participants[].position` seat-verification rule referenced in step 7); the
refuted-levers guide for the measured-dead patches that step 3 must keep classified as known-dead;
and `LOOP.md` for the operational narrative around all of this. Use current
`coworld upload-policy` during post-roll rebuilds; reserve the manual
`authorization_token` path for older pinned installs that still fail before
parsing the server response.
