# Protocol Substitution: Modbus TCP in place of EtherNet/IP (ENIP/CIP)

## Why this document exists

The proposal and the primary reference paper (PA-NIDS, Gauthama Raman et al.,
2025) describe deep packet inspection of **EtherNet/IP (ENIP/CIP)** traffic,
decoding CIP `Write_Tag_Service` commands via their **Instance Identifier**,
**Member Identifier**, and **Command-Specific Data** fields. This implementation
performs the equivalent protocol-aware DPI on **Modbus TCP** instead. This is a
deliberate, defensible substitution — recorded here so it is a documented design
decision in the report rather than an unexplained gap.

## The substitution is sound because the security-relevant properties match

| Property exploited by data-manipulation attacks | ENIP/CIP | Modbus TCP |
|---|---|---|
| Runs over TCP/IP, capturable on a SPAN/bridge tap | yes | yes |
| No authentication of the master | yes | yes |
| No encryption / integrity of payload | yes | yes |
| Writes name a target object + a value | CIP Instance/Member ID + data | unit id + register address + value |
| Attack surface: spoofed set-point / actuator write | `Write_Tag_Service` | `Write Single/Multiple Register(s)` (fc 6/16), coils (fc 5/15) |
| Replay of a captured control frame works | yes | yes |

The PA-NIDS insight — *decode the write down to which device, what action, and
what value, then check it against a policy* — is protocol-independent. What CIP
expresses as (Instance ID → Member ID → Command-Specific Data), Modbus expresses
as (unit id → register address → written value). Our register map
(`sim/register_map.py`) is the direct analogue of PA-NIDS's manual
Instance/Member-ID mapping table: it names each addressable point, its safe band,
and whether it is a sensor or an actuator.

## Why Modbus is the better choice for a software-only testbed

1. **Real packets, real DPI.** pymodbus produces genuine, standards-conformant
   Modbus TCP frames over a Docker bridge. tshark captures them and the rule
   engine decodes them for real — no synthetic packet stream that would make the
   protocol-aware contribution hollow.
2. **Toolchain maturity.** Modbus has first-class support in pymodbus, Scapy,
   Wireshark/tshark, and OpenPLC, so every layer (simulation, capture, attack
   crafting, DPI) uses real tooling rather than hand-rolled ENIP.
3. **Same reference testbed lineage.** SWaT itself uses both CIP and Modbus at
   different stages; AFAD (the second reference paper) evaluates on a **Modbus
   dataset** explicitly. Modbus is squarely within the papers' scope.

## Mapping the proposal's attack table onto Modbus

| Proposal attack class | CIP form | Modbus form in this testbed |
|---|---|---|
| Single-point sensor spoofing (LIT101) | Write_Tag_Service to level tag | `write_register` to LIT101 address, value outside safe band |
| Multi-point coordinated (LIT101+MV101+P101) | multiple CIP writes | burst of `write_register`/coil writes across addresses |
| Stealthy process manip (AIT202 pH mask) | value-masking write | write that keeps registers plausible while physics diverges (LSTM layer) |
| Replay | replayed CIP frame | Scapy replay of captured Modbus write frames |
| Command injection / insider | unauthorized Write_Tag_Service | `write_register` from a source that is not the authorised HMI |
| Flooding / DoS | ENIP flood | Modbus request flood (NetFlow/DoS layer) |

## Optional extension

If Phase 4 finishes ahead of schedule, an ENIP field-layer emulation can be added
behind the same `Decoder` interface used for Modbus, so the DPI rule engine
consumes decoded writes identically regardless of wire protocol. This keeps the
door open to a direct ENIP demonstration without putting it on the critical path.

## What to write in the report

State plainly: *"We implement protocol-aware DPI on Modbus TCP, which shares the
authentication-free, unencrypted, write-by-address properties that
data-manipulation attacks exploit in ENIP/CIP. The PA-NIDS decode-and-check
methodology is reproduced field-for-field, with the Modbus register map serving
the role of PA-NIDS's Instance/Member-ID mapping."* This is accurate and
examiner-defensible.
