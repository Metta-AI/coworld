# eval.py — note

**What it does.** The CLI front door to the league-realistic A/B eval. Given a
`--candidate` and `--baseline` (both must be *uploaded, owned* policies) and a
`--role` (crew or imposter), it runs each policy as its own server-side
Observatory experience request — the tested policy occupies one forced-role seat,
the league's top players fill the other seven — and prints a win-rate verdict with
Wilson confidence intervals, plus mean score, kills, and vote-timeouts per arm.

**Key entry points.** `main()` parses args into a `queue_models.ExperienceRequest`,
builds a `CoworldApiClient.from_login`, then delegates: `--dry-run` calls
`league_eval.resolve_roster` + `requester_slot_for_role` to print the seat plan
without submitting; otherwise `league_eval.run_league_ab(client, req, headers=...)`
runs both arms and returns the verdict dict that `main()` formats. The `--backend`
flag picks `k8s` (league runner, any league policy) vs `antfarm` (staging fleet,
antfarm-registered policies only). All real logic lives in `league_eval.py`; this
file is the thin argument-parsing/printing shell.

**Why it matters to the loop.** This is the canonical "did my change help?" command —
the single-change A/B that the working loop runs to judge a candidate against a
baseline in a league-faithful field before deciding whether to keep an edit.

**Status: CURRENT.** Part of the current server-side eval stack. Hardcodes the
Crewrift league id and imports the live `league_eval` harness; it follows the
post-2026-06-12 request shape via `league_eval.build_request_body`.
