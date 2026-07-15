# Case Study: Optimizing a Gate-All-Around Nanowire nFET

This is a real optimization campaign run with TCADOpt, including the mistakes. It is written honestly because the mistakes are the most useful part.

The task: optimize a 2D cylindrical gate-all-around silicon nanowire n-channel transistor. Many quantities were fixed by the problem (gate length 15 nm, wire diameter 6 nm, equivalent oxide thickness 0.9 nm, metal gate work function 4.4 eV, supply 0.7 V, 1 GPa tensile stress along transport, room temperature). The design freedom was the source and drain doping profile and the doping under the inner spacer. The metrics were on-current, off-current, peak transconductance, and maximum electron velocity.

---

## How the search space grew

The first attempt used **three parameters**: the source/drain peak doping, the junction reach, and the junction abruptness. The engine converged quickly and cleanly, and the result was disappointing: on-current improved about twofold and off-current barely moved.

This was not an engine failure. It was a **parameterization failure**. Three symmetric knobs cannot express the physics that actually controls leakage.

The space was rebuilt with **seven parameters**, splitting the doping into three zones (deep source/drain, an independent source-side extension, and an independent drain-side extension) and making the source and drain **asymmetric**: an aggressive source (low series resistance, more drive) and a conservative, pulled-back drain (a wider junction, less leakage).

That change alone moved the results substantially. It grew further to **ten parameters** by adding a raised (epitaxial) source and drain radius, a free interfacial-layer thickness with the high-k thickness derived so the equivalent oxide thickness stayed pinned exactly at its required value, and a source-side pocket doping.

**Lesson one: when an optimizer converges quickly to a mediocre answer, suspect the parameterization before you suspect the optimizer.** The engine can only search the space you give it.

---

## What the physics actually allowed

With the work function fixed, the threshold voltage was effectively pinned, which meant on-current and off-current were chained together on a single exponential curve set by the subthreshold slope. Moving along that curve trades one for the other; it does not break the trade-off.

The Pareto tracer made this concrete. Roughly 1500 simulations mapped the entire achievable front, from a low-leakage end to a high-drive end. That map was the single most valuable artifact of the whole campaign, because it turned a vague hope ("can we get both high drive and very low leakage?") into a measured fact ("here is exactly what is achievable, and the combination you want lies outside it").

**Lesson two: a measured trade-off front is worth more than a single champion.** It tells you what is possible, and it tells you when to stop searching.

---

## The mistake that cost the most

Early on, the inner spacers were modeled with a high-k dielectric (hafnium oxide) instead of the industry-standard silicon nitride. It improved the numbers, because a high-k spacer fringe-couples the gate field into the underlap region and helps control it.

It was also **not manufacturable**. A high-k dielectric placed directly against silicon as a spacer is a research curiosity, not something a modern high-volume fab does.

A long campaign ran on that structure. When the spacer was reverted to silicon nitride for realism, the champion's metrics degraded: the designs that had won relied on the very fringe-coupling that the unrealistic spacer provided. The reported champion metrics had been correct for the structure that was simulated; the structure had simply changed afterward.

**Lesson three: enforce manufacturability from the first line of the deck, not at the end.** An optimizer will exploit every affordance you give it, including the ones you did not mean to give. If a structure choice cannot be fabricated, it must never enter the search space at all, because the engine will build its champion on top of it.

---

## Options that were correctly rejected

- **Using band-to-band tunneling to boost drive current** (a tunnel-FET approach). Rejected with proof: in silicon, with its indirect 1.12 eV bandgap, at a 0.7 V supply, tunneling current is far below the thermionic drive current already achieved. It would have reduced on-current, not increased it, and it would have changed the device into something other than what was asked for.
- **A narrow-bandgap source and drain material.** Rejected: a smaller bandgap increases band-to-band leakage at the drain junction, making off-current worse.

**Lesson four: write down why you rejected something, with the physics.** It protects you from re-litigating it under deadline pressure, and it is exactly the reasoning a reviewer wants to see.

---

## What the engine did well

- The **physics guard** quarantined results with impossible subthreshold slopes during the campaign, keeping solver artifacts out of the surrogate.
- The **trust-region restarts** kept the search moving after it plateaued instead of stopping early.
- The **champion defense** flagged a champion as fragile under manufacturing-tolerance perturbations, which is exactly the warning a device engineer needs before committing to a design.
- The **convergence evidence** (the gap to the runner-up, the spread of top designs) made it possible to judge how much to trust a champion rather than accepting it blindly.

---

## What would be done differently

1. **Fix manufacturability constraints before the first campaign, not after.**
2. **Question every unstated assumption about the design space.** The problem fixed many things, but it did not fix everything; assumptions made silently are opportunities left on the table.
3. **Optimize the metrics that are actually scored.** It is easy to become attached to a diagnostic quantity that is informative but is not what you are being judged on.
4. **Run multiple independent seeds from the start** and use their agreement as the confidence signal, rather than trusting a single run.

---

## The engineering takeaway

The optimizer was never the bottleneck. The bottleneck was the quality of the problem definition: the parameterization, the realism of the structure, and the choice of objective. TCADOpt makes the search efficient and honest. It cannot make a badly-posed problem into a good one. Spend your effort there first.
