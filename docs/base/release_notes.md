
# Release Notes

Version 0.2.0: new-interface & delete interface + tree improvements.
-------------------------

- Improvement to the whole 'show tree' function for more clarity.
- Added following commands for creating and deleting interfaces:

config
│   ├── delete-interface

new-interface
    └── <ifname>
        ├── cvlan-id
        ├── ipv4address
        ├── mtu
        ├── netmask
        ├── parent-interface
        ├── status
        └── svlan-id

Version 0.1.6: bug fixes.
-------------------------

- Moving all tree-like details to command modules to keep scalability.
- Fixing help for config interface commands.

Version 0.1.5: show/config commands.
-------------------------
- Added 'config interface' commands:
	- config interface ifname mtu
	- config interface ifname speed
	- config interface ifname status
	- config interface ifname auto-nego
	- config interface ifname duplex
	
- Added 'show interface' commands:
	- show interfaces
	- show interfaces ifname
	- show interfaces ip
	- show interfaces ipv4

Version 0.1.1: Project Creation
-------------------------
- Repository created.
- CLI created mimicking junOS cli, with nested autocompletions, commands descriptions and help.
- Architecture:

  **Shell**:
  Auto-completion and tree creation based of descriptions.
  
  **Distpacher**: recognizing the command and what to do with it (which module to call). modules/plugins, distpacher is the one , some modules are: ).
  
  **Modules**: 'show', 'config', 'system', basically any command tree structure.
  
  **Plugins**: use of external libraries, like OpenBFDD.
  
- Additional commands added (accesible from help).
- Added commands:
  'show interface'
  'show interface ip'
  'show interface ipv4'
  'show tree' & 'show tree details'
