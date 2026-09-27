# External Validation on the Public HAI Dataset

Our LSTM detector was developed and evaluated on data from our own simulator
(see [results.md](results.md)). To test whether the approach generalises beyond
data we generated ourselves, we validated it on **HAI 22.04** (HIL-based Augmented
ICS dataset, National Security Research Institute, South Korea) — a real
hardware-in-the-loop testbed with boiler, turbine, water-treatment and HIL
processes, sampled at 1 Hz.

**Bottom line:** the approach transfers only weakly. The LSTM ranks real attacks
above normal operation clearly better than chance (ROC-AUC 0.74), but it does not
reach usable alarm performance on HAI. Even with an ideally calibrated threshold,
F1 is at most ~0.10. The strong simulator results should therefore be read as
optimistic, and this is reported as a limitation.

## Setup

| | |
|---|---|
| Training data | `hai-22.04/train1.csv` — 93,601 s (~26 h), normal operation only |
| Test data | `hai-22.04/test1.csv` — 86,400 s (24 h), 885 s of labelled attacks (~1%), 7 attack episodes |
| Features | 60 informative sensors/actuators (26 constant columns dropped) |
| Model | Same LSTM autoencoder as our detector (window 10 s, hidden 64, latent 32, 15 epochs) |
| Protocol | Unsupervised: train on normal only; threshold = 99.9th percentile of training scores |

Reproduce (after downloading the two CSVs into `data/public/hai/`):

```bash
python -m eval.hai_validate
```

## Results

Window-level, contamination-aware labels (a window is an attack window if any of
its seconds is an attack). Random-guess PR-AUC equals the attack base rate, 0.011.

| Metric | Per-feature std score (ours) | Plain mean MSE |
|---|---|---|
| ROC-AUC | 0.742 | 0.742 |
| PR-AUC | 0.044 (4× random) | 0.081 (7× random) |
| **At the train-derived threshold** | | |
| Precision / Recall | 0.012 / 0.998 | 0.012 / 0.978 |
| False-positive rate | 0.940 | 0.914 |
| **At the oracle-best threshold** *(upper bound, uses test labels)* | | |
| Precision / Recall | 0.031 / 0.369 | 0.430 / 0.058 |
| F1 | 0.057 | 0.102 |
| Attack episodes detected | 5 / 7 | 2 / 7 |

At the deployable (train-derived) threshold the detector flags ~94% of the test
day, so its "7/7 episodes detected" is not meaningful and is not claimed as a
result. The oracle rows are **not** achievable in practice — they show the best
the score could do if the threshold were perfectly calibrated, i.e. an upper
bound on the score's separating power.

![HAI timeline](../eval/results/hai_timeline.png)

## Diagnosis

1. **A near-constant sensor broke the first run.** Without safeguards, ROC-AUC
   was 0.47 (worse than random). `P1_PCV02Z` has a training std of 0.0037, but on
   the test day its normal values sit a median of ~127σ from the training mean;
   standardisation turned this small drift into an enormous error that dominated
   every window. Clipping standardised inputs to ±5σ — a conventional outlier
   bound, fixed before re-running and not tuned on test labels — raised ROC-AUC
   to 0.74.
2. **Operating-mode drift dominates the score.** The timeline shows the score
   moving in large steps (e.g. hours 7.5–9.5) that contain no attacks: the plant
   runs in operating regimes on the test day that never appeared in the single
   training day. The alarm threshold, learned on training data, sits below almost
   the entire test day.
3. **HAI attacks are short and subtle.** Most attack episodes are brief blips on
   top of this drifting baseline; a few produce clear spikes (e.g. ~16.7 h), most
   do not stand out.
4. **Scoring choice is data-dependent.** Our per-feature "worst-signal" score was
   what let the LSTM catch the single-signal stealth attack in our simulator, but
   on HAI's 60 noisy real sensors it is more sensitive to noise, and plain MSE has
   the better PR-AUC (0.081 vs 0.044).

## Methodological note

We stopped after diagnosing the failure rather than continuing to adjust the model
and re-checking against `test1`. Repeatedly tuning against the labelled test file
would fit the model to that file and invalidate the external validation. The
results above come from one model configuration; the only change between runs was
the input clipping described in point 1, which was motivated by the feature
distributions, set in advance, and applied once.

## What would improve it (future work)

These are principled next steps that do not use test labels for tuning:

- **Train on more operating conditions.** HAI provides six training files from
  different days. Training on several of them exposes the model to the operating
  regimes it currently mistakes for attacks.
- **Calibrate the threshold on a held-out normal day** (e.g. `train2`), not on
  the training data itself, so the threshold reflects day-to-day variation.
- **Longer windows / trend removal.** HAI attacks and regime changes unfold over
  minutes; a 10 s window cannot tell a slow regime shift from a fault. Scoring
  deviations relative to a rolling baseline would target sudden changes.
- **HAI's official metric (eTaPR).** Reporting it alongside ROC/PR-AUC would allow
  direct comparison with published HAI results.

## Implication for the project

The simulator evaluation shows the detection-in-depth architecture works as
designed when the attacks and operating conditions match what the models were
built for. The HAI validation shows that the LSTM layer, as currently trained,
does not generalise to a real testbed with non-stationary operation and subtle
attacks. The DPI rule engine and NetFlow monitor were not evaluated on HAI
because HAI provides process data only, not network packets.
