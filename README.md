<h1 align="center">vMark-node by Pathgate</h1>
<h2 align="center">An effort towards the first Ethernet software-based open source demarcation NID.</h2>

Latest version: **0.2.1** / Release notes: [Link](https://github.com/xmas-ar/vMark-node/blob/public/docs/base/release_notes.md) 

**Features:**
- Modular tree-style CLI with autocompletions.
- Shell/Dispatcher/Modules/Plugins architecture.
- Network interfaces manipulation. (v0.1.5)
- Add & delete sub.interfaces (QinQ / dual-tags supported) (v0.2.0)

**Feature roadmap:**
 - Complete Interface management.
 - web GUI (flask).
 - Docker & pip installations.
 - Loopback testing with automatic timeout.
 - In-band management through QinQ (dualtags).
 - RFC2544 reflector.
 - TWAMP implementation for ad-hoc testing.
 - open-BFDD implementation for service assurance (p2p session).
___

<h1 align="center"># Introduction</h1>

<p align="center">
vMark-node is a software-based open-source Ethernet demarcation NID designed for flexibility and democratization in the Carrier industry.
The "-node" refers to this repo being the client-side of <a href="https://github.com/xmas-ar/vMark">vMark</a> system.
</p>


<p align="center">
  <img src="https://github.com/user-attachments/assets/ed3e07e1-9320-4fbb-a715-5a4fbe24c977" alt="xxx">
</p>


<h1 align="center"># Architecture</h1>

**Shell**:
Provides command-line auto-completion, some help-related features and dynamically builds the command tree based on the modules and installed plugins. This enables a modular, scalable and re-usable interactive CLI experience.

**Dispatcher**:
Interprets user commands, determines the appropriate module to handle each command, and routes execution accordingly. The dispatcher acts as the central coordinator between the shell and the available modules/plugins.

**Modules**:
Shell modules encapsulate core command logic and define the command tree structure. Examples: 'show', 'config', and 'system', each representing a set of related commands and subcommands with item descriptions.

**Plugins**:
Integrate external libraries or tools to extend functionality. For example, plugins can provide access to third-party systems such as OpenBFDD, allowing seamless integration with external services.


___

## Quick Install

```
gh repo clone https://github.com/xmas-ar/vMark-node.git
cd vMark-node
pip3 install -r requirements.txt
python3 main.py
