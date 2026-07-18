# Suspicion & belief modeling — guide (generic tier)

Reference notes, design rationale, and negative results (1).

#### 1. Before changing a shared threshold or parameter, enumerate its consumers and ask whose objective each serves
`generic` · _see related: U0791 (other tier)_

A single tuned threshold or shared parameter often feeds multiple consumers whose objectives oppose each other, so changing it for one consumer silently distorts the other. Before editing a shared decision threshold, grep for every consumer and ask what each one's goal is: raising a bar that restrains one path can simultaneously suppress a path that WANTS lower-confidence triggering. The fix is to scope the change to the consumer it was meant for (e.g. apply the raised value conditionally) rather than mutate the shared value globally. Evaluate the change against held-out PAYOFF (a decision simulation tied to the real outcome), not just a fit metric like AUC, since opposing consumers can both look fine on a global metric while one regresses on its actual objective.
  <sub>sources: personal_labs/crewrift_lab/WORKING_CONTEXT.md, personal_labs/crewrift_lab/lessons_archive/TENTATIVE_LESSONS-20260612-</sub>
