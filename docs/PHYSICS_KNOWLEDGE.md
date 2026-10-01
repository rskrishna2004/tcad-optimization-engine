# The Physics Knowledge Base

One thing that sets TCADOpt apart from a generic optimizer is that it knows device physics. It uses this knowledge in two places: to **seed** the search in promising directions, and to **guard** against results that break physical laws. This document explains both, and how to extend the knowledge base for your own devices.

---

## Why physics knowledge helps

A generic Bayesian optimizer starts by sampling the design space at random. That works, but it wastes early simulations exploring regions that any device engineer would know are poor. It can also be fooled: if a simulation returns a garbage number because of a meshing artifact or a parsing glitch, a naive optimizer will happily chase that garbage.

TCADOpt fixes both problems with a small, human-readable knowledge base of device-physics rules.

---

## Physics seeding

Before the engine draws its space-filling initial sample, it generates a few **knowledge-guided** designs. It does this by starting from the middle of the design space and pushing each parameter in the direction that physics says improves the objective.

For example, if the objective is to maximize on-current, physics says: raise source and drain doping (lower series resistance), shorten the effective channel where allowed, and so on. The seeder applies these directional pushes to produce a handful of designs that are already in good regions, and hands them to the surrogate as early anchors. This does not replace the search; it gives the search a head start.

The seeding is **device-agnostic**. The knowledge base is written in terms of physical roles (a channel doping, a source/drain doping, an oxide thickness), and the seeder maps those roles onto whatever your device actually calls them. So a rule about oxide thickness applies whether your parameter is named for a planar oxide or an equivalent oxide thickness in a gate-all-around device.

An important safety property: physics seeds can only help or be neutral. If a seeded direction turns out to be wrong for your specific device, those few designs simply score poorly and the surrogate ignores them. The rest of the search proceeds normally. Seeding never makes the final result worse.

---

## The physics guard

After every simulation, the result passes through the guard before it is allowed to influence the surrogate. The guard checks the metrics against physical invariants. Examples of the kind of laws it enforces:

- **Subthreshold slope limit.** At a given temperature there is a hard lower bound on how sharply a conventional transistor can switch (about 60 mV per decade at room temperature). A reported slope steeper than this limit is physically impossible and signals a numerical or extraction error. The result is quarantined.
- **On-off ordering.** The on-current must exceed the off-current. A result that violates this is not a real operating point.
- **Sign and consistency checks.** Transconductance must be positive; derived ratios must be self-consistent.

A result that fails any invariant is flagged and excluded from the surrogate model, so the optimizer never learns from a physically impossible point. This is what stops a single solver artifact from derailing an entire campaign.

The guard is also used during champion defense, where the winning design is re-checked against the same invariants and the whole campaign's trend is audited for physical plausibility.

---

## The knowledge file

The rules live in `tcadopt/l4_knowledge/physics_rules.yaml`, beside the module
that reads them. It contains two kinds of entries:

- **Invariants**: the physical laws the guard enforces, such as the subthreshold slope limit and the on-off ordering.
- **Lever maps**: for each metric, which parameters move it and in which direction. This is what the seeder uses to push designs in good directions.

Because it is plain text, you can read it, understand exactly what the engine believes about device physics, and edit it.

**A note on a bug fixed in v1.1.0.** Up to and including v1.0.1 the guard was
looking for this file at a path that did not exist, and `load_kb()` treats a
missing file as an empty knowledge base rather than an error. The result was
silent and complete: no invariant ever fired, no result was ever quarantined,
and physics seeding returned nothing on every campaign, so the
`[physics-seed]` line described above never appeared. If you ran v1.0.0 or
v1.0.1 and never saw that line, this is why. Nothing about your results was
wrong - the engine simply was not applying the guard it advertised. Both
features work from v1.1.0 onward, and the lookup now tries the shipped location
first and the old one second, so a repository that really does keep a top-level
`knowledge/` folder still works.

---

## Extending it for your device

To teach the engine about a new device or a new metric:

1. **Add or adjust lever maps.** For your objective metric, list the parameters that improve it and the direction of improvement. The seeder will then push those parameters correctly for your device.
2. **Add role aliases if your parameter names are new.** If your device uses a parameter name the knowledge base does not recognize, add it to the appropriate physical role so the existing rules apply.
3. **Add invariants if your device has extra physical limits.** If there is a physical bound specific to your device that a valid result must satisfy, add it as an invariant so the guard enforces it.

Keep invariants conservative: they should encode laws that are genuinely impossible to violate physically, not merely designs you consider undesirable. Undesirable-but-possible regions are the optimizer's job to avoid through scoring, not the guard's job to forbid.

---

## Physics knowledge in an extraction

The guard and the seeder both apply to the design path, where each trial
produces figures of merit that an invariant can judge. An extraction trial
produces a curve, so the same invariants do not apply directly - a fit that
matches the reference curve is by construction as physical as the reference.

Extraction gets its equivalent protection somewhere else, and it is worth
knowing which is which:

- **Bounds in the stage's `parameters:` block** play the role the guard plays.
  A mobility that cannot be negative and a work function that cannot be 8 eV
  are enforced by the parameter space itself rather than caught afterward.
- **Fixed structural parameters** play the role manufacturability constraints
  play in a design problem. The optimizer cannot resize the transistor to
  explain a current error, because those dimensions are not in the search space
  at all.
- **The identifiability check** plays the role the physics guard plays for
  trustworthiness, but it catches a different failure. The guard catches a
  result that is impossible. Identifiability catches a result that is
  *arbitrary* - a number the data could never have determined. Neither shows up
  in the score, which is why both are separate measurements.
