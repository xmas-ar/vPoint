<h1 align="center">vMark-node by Pathgate</h1>
<h2 align="center">An effort towards the first Ethernet software-based open source demarcation NID.</h2>

<p align="center">Latest version: 0.3.2 / Release notes: <a href="https://github.com/xmas-ar/vMark-node/blob/public/docs/base/release_notes.md">Link</a> </p>

**Features:**
- Modular tree-style CLI with tab autocompletions and '?' helper.
- Shell/Dispatcher/Modules/Plugins architecture.
- Complete **Interface management**.
- GPLv3 License.
- Add & delete sub.interfaces (**QinQ** / dual-tags supported) (v0.2)
- **TWAMP** Light implementation for End-to-End L3 tests. (**ipv4 & ipv6, sender/responder modes**). (v0.3)
- Pypy packaging. (v0.3.1)

**Feature roadmap:**
 - web GUI (flask).
 - Docker & pip installations.
 - Loopback testing with automatic timeout.
 - RFC2544 reflector.
 - open-BFDD implementation for service assurance (p2p session).
 - fiber-interface management and optic levels monitoring.
 - Enable API-operated dispatcher.
 - SNMP Support.
 - Multi-vendor IPSec Tunnel support.

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

## Quick Install

```
gh repo clone https://github.com/xmas-ar/vMark-node.git
cd vMark-node/vMark-node
pip3 install -r requirements.txt
python3 main.py
