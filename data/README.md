# Datasets

Labelled data produced by the Phase-3 generator and used to train/evaluate the
detection layers. Generated files are git-ignored; regenerate with:

```bash
python -m net.generate_dataset --out-dir data/run1 --speedup 0 --seed 42
```

Each run directory (`data/run1/`, ...) contains two CSVs sharing a `label`
column of ground truth (`normal` or one of the five attack classes). The default
run is 510 s: 60 s of normal operation, then each attack for 45 s separated by
45 s of normal operation.

## `network_log.csv` — decoded Modbus transactions (for the DPI engine)

One row per Modbus TCP request sent by the controller (HMI) or the attacker. The
generator records each request as it sends it, with the fields a packet decoder
would extract; it is not a packet capture.

| column | meaning |
|---|---|
| `ts` | epoch seconds when the request was issued |
| `src_ip`, `src_port` | logical source on the simulated OT segment (HMI `10.0.0.5`, **attacker `10.0.0.66`**) |
| `dst_ip`, `dst_port` | the PLC endpoint (`10.0.0.2:502`) |
| `unit_id` | Modbus unit/slave id |
| `func_code`, `func_name` | 3/4 = read, 6/16 = write |
| `register` | first register address touched |
| `value_raw` | raw 16-bit value written (0 for reads) |
| `count` | number of registers in the request |
| `tick` | the simulated second the request belongs to (used for windowing) |
| `is_write` | 1 for write function codes |
| `tag` | SWaT-style tag for `register` (e.g. `LIT101`), if mapped |
| `value_phys` | `value_raw` converted to engineering units |
| `label` | ground truth for this transaction |

The DPI engine decides legitimacy from `src_ip` + `func_code` + `register`
against the write-authorisation policy in `net/config.py`. It does **not** see
the `label` column, which exists only for scoring.

## `device_log.csv` — per-second historian record (for the LSTM)

One row per simulated second: every sensor's **reported** value (what the
historian/HMI recorded — already spoofed during false data injection) and every
actuator state, plus the ground-truth `label`.

| column | meaning |
|---|---|
| `ts`, `tick` | wall time, and the 0-based sim-second index |
| one column per sensor tag | reported physical value (e.g. `LIT101`, `AIT202`) |
| one column per actuator tag | state (0/1/2, e.g. `P101`, `MV101`) |
| `label` | ground truth for this second |

The controller re-applies its actuator outputs every second (as a PLC does each
scan), so once an attack window ends the plant returns to normal operation and
seconds labelled `normal` really are normal.

## Attack classes

| label | what the attacker does | layer that detects it |
|---|---|---|
| `false_data_injection` | writes `LIT101` = 1180 mm (above its 1100 mm limit) from `10.0.0.66` each second | DPI (sensor-register write) + LSTM |
| `command_injection` | writes `P101` = off from `10.0.0.66` each second | DPI (unauthorised source) + LSTM |
| `flooding_dos` | sends 40 read requests per second | NetFlow volume monitor |
| `replay` | re-sends the controller's most recent recorded write from `10.0.0.66` | DPI (unauthorised source) |
| `stealth_manipulation` | compromised HMI holds the HCl pump `P203` on from the authorised address `10.0.0.5` | LSTM only |

## Public dataset (HAI 22.04)

The LSTM was also validated on the public HAI 22.04 dataset
(https://github.com/icsdataset/hai). The CSVs used (`train1`–`train4`, `test1`)
are downloaded into `data/public/hai/` and are git-ignored. See
[`docs/hai_validation.md`](../docs/hai_validation.md) and `eval/hai_validate.py`.
