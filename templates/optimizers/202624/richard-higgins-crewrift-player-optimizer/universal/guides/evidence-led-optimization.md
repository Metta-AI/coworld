# Evidence-Led Optimization

The direct CrewRift packages converged on the same failure mode: it is easy to confuse
creating a candidate with validating a candidate. A build, upload, policy
version, request body, or pending XP request is only an opportunity to learn.
The learning comes from completed artifacts and the inspection that follows.

Use the candidate record as the optimizer's memory. It should answer:

- What behavior failed?
- Which source owner changed?
- Which tests or diagnostics covered the change?
- Which hosted comparison was requested?
- Which artifacts were inspected?
- Was the candidate promoted, held, or rejected?

This is why negative results matter. They constrain future search better than
another plausible variant name.
