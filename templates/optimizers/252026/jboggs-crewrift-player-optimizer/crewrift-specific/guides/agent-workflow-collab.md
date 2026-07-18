# Agent workflow & collaboration — guide (crewrift tier)

Reference notes, design rationale, and negative results (1).

#### 1. Build asymmetric crewmate/imposter policies over one shared perception stack
`crewrift`

For a social-deduction game (e.g. Among Them), keep two distinct policies (crewmate vs imposter) sharing one perception stack and build deliberate asymmetry: the crewmate is principled and quiet (pure task throughput, reports only stumbled-on bodies, votes only on firsthand evidence) while the imposter is a theatrical social engineer. The asymmetry is the point -- it makes the crewmate a hard target and the imposter a manipulator. Treat a perception/navigation reference written in another language (e.g. a Nim bot for a Go player) as a behavioral reference to re-derive idiomatically, not as source to port line-for-line.
  <sub>sources: bitworld/among_them/players/evidencebot_strategy.md, bitworld/among_them/players/lively_lecun/ROADMAP.md</sub>
