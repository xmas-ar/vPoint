<h1 align="center">vMark-node by Pathgate</h1>
<h2 align="center">An effort towards the first Ethernet software-based open source demarcation NID.</h2>

Latest version: **0.1.1** / Release notes: [Link](https://github.com/xmas-ar/vMark-node/blob/public/docs/base/release_notes.md) 

**Features:**
- Modern tree-style CLI with autocompletions.
- Shell/Dispatcher/Modules architecture.

**vMark-node roadmap 2025:**
 - Feature-list.
 - Basic interface management.
 - Loopback testing and automatic timeout.
 - In-band management through QinQ.
___

<h1 align="center"># Introduction</h1>

<p align="center">
vMark-node is a software-based open-source Ethernet demarcation NID designed for flexibility and democratization in the Carrier industry.
The "-node" refers to this repo being the client-side of <a href="https://github.com/xmas-ar/vMark">vMark</a> system.
</p>


<p align="center">
  <img src="https://github.com/user-attachments/assets/e08cc38e-dac9-4554-846d-2ac7effc18a2" alt="xxx">
</p>

<h1 align="center"># Architecture</h1>


___

## Quick Install

```
gh clone https://github.com/xmas-ar/vMark-node.git
cd vMark-node
pip3 install -r requirements.txt
python3 main.py
