# Datasets

Labelled data produced by the Phase-3 generator and used to train/evaluate the
detection layers. Generated files are git-ignored; regenerate with:

```bash
python -m net.generate_dataset --out-dir data/run1 --speedup 0
```

Each run directory (`data/run1/`, ...) contains two CSVs sharing a `label`
column of ground truth (`normal` or one of the five attack classes).

## `network_log.csv` — decoded Modbus transactions (for the DPI engine)

One row per Modbus TCP request that crossed the simulated wire.

| column | meaning |
|---|---|
| `ts` | epoch seconds when the request was issued |
| `src_ip`, `src_port` | logical source on the OT segment (HMI `10.0.0.5`, SCADA `10.0.0.10`, **attacker `10.0.0.66`**) |
| `dst_ip`, `dst_port` | the PLC endpoint (`10.0.0.2:502`) |
| `unit_id` | Modbus unit/slave id |
| `func_code`, `func_name` | 3/4 = read, 6/16 = write |
| `register` | first register address touched |
| `value_raw` | raw 16-bit value written (0 for reads) |
| `count` | number of registers in the request |
| `is_write` | 1 for write function codes |
| `tag` | SWaT-style tag for `register` (e.g. `LIT101`), if mapped |
| `value_phys` | `value_raw` converted to engineering units |
| `label` | ground truth for this transaction |

The DPI engine (Phase 4) decides legitimacy from `src_ip` + `func_code` +
`register` against the write-authorisation policy in `net/config.py` — it does
**not** see the `label` column, which exists only for scoring.

## `device_log.csv` — per-second historian record (for the LSTM)

One row per simulated second: every sensor's **reported** value (what the
historian/HMI recorded — already spoofed during sensor-manipulation attacks) and
every actuator state, plus the ground-truth `label`.

| column | meaning |
|---|---|
| `ts`, `tick` | wall time, and the 0-based sim-second index |
| one column per sensor tag | reported physical value (e.g. `LIT101`, `AIT202`) |
| one column per actuator tag | state (0/1/2, e.g. `P101`, `MV101`) |
| `label` | ground truth for this second |

## Attack classes

| label | what the attacker does | intended detector |
|---|---|---|
| `false_data_injection` | holds `LIT101` at 1180 mm (out of band) | DPI (unauthorised write) + band check |
| `command_injection` | unauthorised write forcing `P101` OFF | DPI (unauthorised source) |
| `flooding_dos` | burst of read requests each second | NetFlow/volume monitor |
| `replay` | re-sends a captured legitimate actuator command out of order | DPI (unauthorised source) + LSTM (temporal) |
| `stealth_manipulation` | masks `AIT202` pH at a constant in-band 7.30 while forcing the acid pump ON | **LSTM only** (evades band + rule checks) |

## Public dataset (cross-validation) — TODO

To validate the LSTM on data we did not generate ourselves, drop a public ICS
dataset under `data/public/`. Neither requires the SWaT access application:

- **HAI** (HIL-based Augmented ICS): https://github.com/icsdataset/hai
- **Morris SCADA** (gas pipeline / water tank): https://sites.google.com/a/uah.edu/tommy-morris-uah/ics-data-sets

A loader that maps these to the `device_log.csv` schema will live in
`detect/lstm/` (Phase 5).
