<h1 align="center">vMark-node by Pathgate</h1>
<h2 align="center">World's first open source Ethernet software-based demarcation NID.</h2>

<p align="center">Latest version: 0.3.9 / Release notes: <a href="https://github.com/xmas-ar/vMark-node/blob/public/docs/base/release_notes.md">Link</a> / News at: <a href="https://www.linkedin.com/company/pathgate">LinkedIn</a> </p></p>

**🚀 Features:**
- Modular tree-style CLI with tab autocompletions and '?' helper.
- Shell/Dispatcher/Modules/Plugins architecture.
- Complete **Interface management**.
- GPLv3 License.
- Add & delete sub.interfaces (**QinQ** / dual-tags supported) (v0.2)
- **TWAMP** (RFC5357) implementation for End-to-End L3 tests. (**ipv4 & ipv6, sender/responder modes**). (v0.3)
- Pypi (pip) packaging. (v0.3.1)
- Remote Management via vMark. (v0.3.4)
- **XDP-Switch** (eBPF) based MEF-compliant <a href="https://github.com/xmas-ar/vMark-node/blob/plugins/xdp_mef_switch/README.md">transparent Ethernet switching</a> (v0.3.9)


**🔧 Feature roadmap:**
 - Ethernet OAM. (IEEE 802.1ag / Y.1731)
 - Timing protocols support (ITU-T G.8262 Sync-E and IEEE 1588v2)
 - Automated MEF3 Service WAN failover.
 - Remote loop testing with automatic timeout.
 - RFC2544 Service Activation testing and reflector.
 - open-BFDD implementation for service session assurance.
 - fiber-interface management and optic levels monitoring.
 - SNMP Support.
 - Multi-vendor IPSec Tunnel support.
 - VXLAN Tunneling.

<img src="https://github.com/user-attachments/assets/f03e03f7-961f-4c25-8ed4-d95991735c05" alt="xxx">
<h2 align="center"></h2>
<h1 align="center"># Overview</h1>

<p align="center">vMark-node is a software-based open-source Ethernet demarcation NID designed for flexibility and democratization in the Carrier industry.</p>

<p align="center">The "-node"** refers to this being the client-side of <a href="https://github.com/xmas-ar/vMark">vMark</a> server. (vMark-node doenst need vMark to work). </p>



<p align="center">
  <img src="https://github.com/user-attachments/assets/86b990c2-bbf9-472b-b2ef-cd1b0842d8c97" alt="xxx">
</p>

<h1 align="center"># Architecture</h1>

**Shell**:
Provides command-line auto-completion, some help-related features and dynamically builds the command tree based on the modules and installed plugins. This enables a modular, scalable and re-usable interactive CLI experience.

**Dispatcher**:
Interprets user commands, determines the appropriate module to handle each command, and routes execution accordingly. The dispatcher acts as the central coordinator between the shell and the available modules/plugins, Web-UI and API interactions talk directly with the Dispatcher.

**Modules**:
Shell modules encapsulate core command logic and define the command tree structure. Examples: 'show', 'config', and 'system', each representing a set of related commands and subcommands with item descriptions.

**Plugins**:
Integrate external libraries or tools to extend functionality. For example, plugins can provide access to third-party systems such as OpenBFDD, allowing seamless integration with external services.


___

<h1 align="center">📎 Installation methods</h1>

## System Requirements

- Python 3.9+
- bpftool
- pkg-config
- libnl-3-dev and libnl-route-3-dev (Debian/Ubuntu)
- libnl3-devel (Fedora/RHEL/CentOS)

- Ubuntu/Debian:
```
sudo apt update
sudo apt install -y python3.9 python3.9-venv python3-pip build-essential pkg-config libnl-3-dev libnl-route-3-dev python3-dev ethtool
```

- Fedora/RHEL/CentOS:
```
sudo dnf install -y python3.9 python3-pip gcc pkgconfig libnl3-devel python3-devel ethtool
```

## Quick Install

```
git clone https://github.com/xmas-ar/vMark-node
cd vMark-node/vMark-node
pip3 install -r requirements.txt
python3 main.py
```
___
## PIP Install (recommended)
(Might need one of these two lines previous to install pip:)
```
sudo dnf install -y pkgconfig libnl3-devel gcc python3-devel
sudo apt install -y pkg-config libnl-3-dev python3-dev build-essential
```
**Then do:**
```
pip install vmark-node
~/.local/bin/vmark-node
```
___

### 🔄 Running as a Background Service (Production)

To ensure `vmark-node` stays running in the background (e.g., to keep the API server accessible by `vMark`), you can use **`systemd`** or **`tmux`**.

___


### ✅ Option 1: `systemd` Service (Recommended for Linux)

1. **Create a service file:**

```
bash
sudo nano /etc/systemd/system/vmark-node.service
```
Paste this configuration:
```
[Unit]
Description=vMark-node Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/vmark-node
WorkingDirectory=/opt/vmark-node
Restart=always
RestartSec=3
User=nobody

[Install]
WantedBy=multi-user.target
```
⚠️ Replace /usr/local/bin/vmark-node and /opt/vmark-node with your actual install path (check with which vmark-node if installed via pip).

2. **Enable and start the service:**
```
sudo systemctl daemon-reload
sudo systemctl enable vmark-node
sudo systemctl start vmark-node
```
2. **Useful commands:**
```
sudo systemctl status vmark-node
sudo journalctl -u vmark-node -f
```

---

### ✅ Option 2: TMUX (Simpler option)

1. **Install tmux and launch vmark (after installed with pip):**

```
sudo apt install tmux
tmux
vmark-node
```

2. **Then press:**

```
Ctrl + B, then D
```

👉 That detaches the session, leaving vmark-node running.

3. **To resume later:**
```
tmux attach
```
