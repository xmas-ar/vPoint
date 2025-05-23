# xdp-mef-switch Plugin

Low-latency eBPF forwarding for transparent MEF service delivery, integrated into vMark-node.

Latest version: 0.2.0

## Features

- Transparent Ethernet frame forwarding based on:
  - Ingress interface
  - VLAN ID (802.1Q)
  - QinQ (dual-tag, 802.1ad)
  - PBB (MAC-in-MAC, 802.1ah / B-MAC) (Not fully implemented)
- High-rate switching using XDP (runs in kernel space)
- Automatic inverted-rule logic: The plugin will automatically create inverted rules for each rule added, allowing for traffic to be forwarded in both directions, this rule can also be modified.
- No modification of client traffic (MEF-compliant transparent frame transport, L2 protocols un-touched)
- Dynamic rule management via CLI/API or vMark GUI.
- Safe rule conflict detection and map rebuilds
- Automatic XDP rules restoration on vmark-node start
- Automatic XDP program detachment when no rules are active for an interface (automatic promiscuous mode activation too)
- Forwarding table persistence through start-up consistency checks.

## Directory Contents

- `xdp_forwarding.c` – XDP program that parses L2 headers and performs forwarding/vlan actions based on a match key
- `forwarding_maps.bpf.h` – Shared key/value struct definitions for the BPF maps (used in both C and Python)
- `xdp_loader.py` – Python manager to manage XDP program life-cycle and update forwarding rules dynamically
- `map_utils.py` – Utility functions and classes for managing and interacting with eBPF maps
- `forwarding_table.py` – Python logic related to the forwarding data structure and rebuild mechanisms
- `Makefile` – Compiles the `xdp_forwarding.c` into `xdp_forwarding.o`
- `README.md` – This documentation file
- `~/.vmark/forwarding_table.json` – JSON file that stores the forwarding table and rules

## Related files

- `cli/modules/xdp_mef_switch.py` – Python module that provides the CLI interface for the plugin
- `start_cli in shell.py` – Performs eBPF check and fw table consistency check on startup
- `main.py` - Initializes and configures logging for eBPF-related events

## CLI Usage (within vMark-node)

The plugin exposes a CLI command `xdp-switch` within the vMark-node shell:

```sh
test/r86s1@vMark-node> show tree xdp-switch
create-rule
│   ├── cvlan
│   │   └── <cvlan>
│   ├── in_interface
│   │   └── <in_interface>
│   ├── name
│   │   └── <name>
│   ├── out_interface
│   │   └── <out_interface>
│   ├── pop_tags
│   │   └── <pop_tags>
│   ├── push_cvlan
│   │   └── <push_cvlan>
│   ├── push_svlan
│   │   └── <push_svlan>
│   └── svlan
│       └── <svlan>
delete-rule
│   └── <name>
disable-rule
│   └── <name>
enable-rule
│   └── <name>
show-forwarding
    ├── 1po1pu
    ├── asd
    ├── egress-1po1pu
    ├── egress-asd
    ├── egress-simple
    ├── json
    └── simple

```

### Commands

- `show-forwarding`  
  Show the current forwarding table and rule status.

- `create-rule name <NAME> in_interface <IFACE> svlan <S-VLAN> cvlan <C-VLAN> out_interface <IFACE> [pop_tags <N>] [push_svlan <S-VLAN>] [push_cvlan <C-VLAN>]`  
  Create a new forwarding rule. All parameters are passed as key-value pairs.

- `enable-rule <NAME>`  
  Enable a rule and apply it to the BPF map.

- `disable-rule <NAME>`  
  Disable a rule and remove it from the BPF map. If no rules remain for an interface, the XDP program is detached and promiscuous mode disabled.

- `delete-rule <NAME>`  
  Delete a rule from the configuration (must be disabled first).

### Parameters

- `name <NAME>`: Unique rule name
- `in_interface <IFACE>`: Input interface (e.g., `enp1s0`)
- `svlan <S-VLAN>`: S-VLAN ID to match at ingress (or `None`)
- `cvlan <C-VLAN>`: C-VLAN ID to match at ingress (or `None`)
- `out_interface <IFACE>`: Output interface for forwarding
- `[pop_tags <N>]`: Number of VLAN tags to pop (default: 0) (pops outermost tag first, then inner)
- `[push_svlan <S-VLAN>]`: S-VLAN ID to push at exit (optional)
- `[push_cvlan <C-VLAN>]`: C-VLAN ID to push at exit (optional)

### Example

```sh
test/r86s1@vMark-node> xdp-switch create-rule name test1 in_interface enp1s0 svlan 100 cvlan 10 out_interface enp2s0 pop_tags 1 push_cvlan 11
test/r86s1@vMark-node> xdp-switch create-rule name test2 in_interface enp3s0 svlan 200 cvlan 20 out_interface enp4s0 pop_tags 1 push_svlan 201 push_cvlan 20
test/r86s1@vMark-node> xdp-switch create-rule name test3 in_interface enp1s0 svlan 300 cvlan 10 out_interface enp3s0 pop_tags 2 push_svlan 301 push_cvlan 31
```

```sh
test/r86s1@vMark-node> xdp-switch show-forwarding
+----------+--------------+----------+----------+--------------+----------+------------+------------+--------+
|   name   | in_interface | svlan    | cvlan    | out_interface| pop_tags | push_svlan | push_cvlan | active |
+----------+--------------+----------+----------+--------------+----------+------------+------------+--------+
| simple   | enp1s0       | None     | None     | enp2s0       | 0        | None       | None       | no     |
| egress-s | enp2s0       | None     | None     | enp1s0       | 0        | None       | None       | no     |
| 1po1pu   | enp1s0       | None     | 90       | enp2s0       | 1        | None       | 37         | yes    |
| egress-1 | enp2s0       | None     | 37       | enp1s0       | 1        | None       | 90         | yes    |
| asd      | enp4s0d1     | 30       | 230      | enp4s0       | 0        | None       | None       | no     |
| egress-a | enp4s0       | 30       | 230      | enp4s0d1     | 0        | None       | None       | no     |
+------------------------------------------------------------------------------------------------------------+

```

```sh
test/r86s1@vMark-node> xdp-switch enable-rule test3
test/r86s1@vMark-node> xdp-switch disable-rule test2
test/r86s1@vMark-node> xdp-switch delete-rule test2
```

## Technical Notes

- Most eBPF operations will prompt for sudo.
- On start, vmark-node will check the consistency of the file ~/.vmark/forwarding_table.json against running xdp programs.
- The plugin uses a shared BPF map (`fw_table_<iface>`) for each physical interface.
- Rule changes trigger a full map rebuild for consistency check with present active rules.
- The Python code and C code share struct layouts via `forwarding_maps.bpf.h`.
- XDP program is automatically detached from an interface when no rules remain active for it.
- All map and program management is performed using `bpftool` and `pyroute2`.
- All xdp-switch operations can be performed remotely via /api/execute from vmark.

## License

This plugin is part of the vMark-node project and is released under the same license.