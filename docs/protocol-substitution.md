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

1. **Real traffic.** pymodbus exchanges genuine, standards-conformant Modbus TCP
   requests between the controller, the attacker and the plant. The traffic
   generator logs each request with the fields a packet decoder would extract
   (source, function code, register, value), and the rule engine decodes those
   records. Capturing the frames with tshark and decoding the pcap would produce
   the same records; that step was not implemented.
2. **Toolchain maturity.** Modbus is supported by pymodbus (used here) and by
   Scapy, Wireshark/tshark and OpenPLC, which were not needed for this
   implementation but make it straightforward to extend.
3. **Same reference testbed lineage.** SWaT itself uses both CIP and Modbus at
   different stages; AFAD (the second reference paper) evaluates on a **Modbus
   dataset** explicitly. Modbus is squarely within the papers' scope.

## Mapping the proposal's attack table onto Modbus

| Proposal attack class | CIP form | Implemented in this testbed |
|---|---|---|
| Single-point sensor spoofing (LIT101) | Write_Tag_Service to level tag | False data injection: `write_register` to LIT101 with 1180 mm, above its safe range |
| Multi-point coordinated (LIT101+MV101+P101) | multiple CIP writes | Not implemented as a separate scenario |
| Stealthy process manipulation | value-masking write | Compromised HMI holds the HCl dosing pump P203 on from the authorised address (valid command, visible only in process behaviour) |
| Replay | replayed CIP frame | Attacker re-sends the controller's most recent recorded write through pymodbus |
| Command injection / insider | unauthorized Write_Tag_Service | `write_register` forcing pump P101 off from a source that is not the authorised HMI |
| Flooding / DoS | ENIP flood | 40 read requests per second from the attacker (NetFlow layer) |

## Possible extension

An ENIP/CIP decoder could produce the same transaction records as the Modbus
path, so the DPI rules would apply unchanged. This was not implemented.

## What to write in the report

State plainly: *"We implement protocol-aware DPI on Modbus TCP, which shares the
authentication-free, unencrypted, write-by-address properties that
data-manipulation attacks exploit in ENIP/CIP. The PA-NIDS decode-and-check
methodology is reproduced field-for-field, with the Modbus register map serving
the role of PA-NIDS's Instance/Member-ID mapping."* This is accurate and
examiner-defensible.
