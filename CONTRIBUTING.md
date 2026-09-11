# Contributing to TCADOpt

Contributions are welcome. This project is young, and there is a lot of room
for improvement.

## Ways to help

- **Report a bug.** Open an issue describing what you ran, what you expected,
  and what happened. Include the problem YAML if you can share it.
- **Connect a new simulator.** Adapters for simulators other than the ones this
  was developed against would make the engine far more useful -- both TCAD
  simulators for the design path and circuit simulators for the extraction
  path. See `docs/CONNECTING_A_SIMULATOR.md`.
- **Add a compact model.** The card generator currently targets BSIM-CMG.
  Another standard model is a new template in `tcadopt/l2_decks/cardgen.py` and
  nothing else. See `docs/PARAMETER_EXTRACTION.md`.
- **Extend the physics knowledge base.** New invariants and lever maps for
  device families not yet covered. See `docs/PHYSICS_KNOWLEDGE.md`.
- **Improve the optimizer.** Better acquisition functions, better surrogate
  models, smarter restart policies.
- **Improve the docs.** If something confused you, it will confuse the next
  person. Say so.

## Ground rules

- **Never commit vendor-copyrighted material.** No simulator decks, input
  files, output files, or vendor documentation. The `.gitignore` blocks the
  common extensions, but check before you commit.
- **Do not commit run artifacts.** Campaign outputs, databases, and result
  JSON files are personal to a run and do not belong in the repository.
- **Keep physics claims honest.** If you add an invariant or a lever map,
  be able to justify it from device physics. An incorrect invariant will
  silently discard valid results.
- **Report a measurement, not an impression.** If you claim a change improves
  something, say what you measured and on what. Every performance claim in this
  repository names the configuration it was measured on, and a claim that
  cannot be reproduced from what is written down is worse than no claim.

## Submitting a change

1. Fork the repository.
2. Create a branch for your change.
3. Make the change, keeping the existing style.
4. Open a pull request describing what it does and why.

## Questions

Open an issue. Questions are useful; they usually reveal a gap in the docs.
