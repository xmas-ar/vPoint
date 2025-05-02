# Release Notes

Version 0.3.5/6/7: Bug fixing.
---------------------------------

- Bug fixes in the description tree.
- Adding requirements.

Version 0.3.4: vMark Integration + logging.
---------------------------------

- **Remote Management via vMark:** Introduced the ability to register vMark-node with a central vMark server, enabling remote management and orchestration capabilities.
    *   *Note:* vMark-node can still operate in standalone mode. The vMark server project is also intended to be open-source (Apache 2.0).
- **New Registration Commands:** Added CLI commands under `register vmark` to manage the registration process:
```
xmas/rocky-dw1@vMark-node> show tree register
vmark
    └── link-api
        ├── listen-ip
        ├── pin
        └── port
```
- **Registration State:** Once registered (refer to vMark documentation for the procedure), vMark-node stores connection details in `~/.vmark/register.json`. The vMark-node API server requires this file to be present on startup to listen for connections from the vMark server. Deleting this file unlinks the node.
- Error handling for vMark-id mismatch.
- Added logging functionality, file saved in `~/.vmark/api.log` .

Version 0.3.2/3: workflow update.
-------------------------

- Fixes to pip package.

Version 0.3.1: workflow update.
-------------------------

- Packaging to pip.

Version 0.3.0: onyx-Twamp implementation.
-------------------------

- New **TWAMP Light** feature for ad-hoc performance E2E L3 testing.
- Twamp supports both **ipv4 and ipv6** standards.
- commands folders renamed to modules.
- Improved overall '?' helper functionality and tab completion hints.
- List of commands added:

```
xmas/rocky01@vMark-node> show tree details twamp
dscptable - Display DSCP mapping table
ipv4 - IPv4 TWAMP commands
│   ├── responder - Start TWAMP responder session
│   │   ├── do-not-fragment - Set Do Not Fragment flag
│   │   ├── padding - Set packet padding
│   │   ├── port - Set local port (REQUIRED)
│   │   ├── tos - Set Type of Service
│   │   └── ttl - Set Time to Live
│   └── sender - Start TWAMP sender session
│       ├── count - Set number of packets
│       ├── destination-ip - Destination IP address (REQUIRED)
│       ├── do-not-fragment - Set Do Not Fragment flag
│       ├── interval - Set packet interval
│       ├── padding - Set packet padding
│       ├── port - Set destination port (REQUIRED)
│       ├── tos - Set Type of Service
│       └── ttl - Set Time to Live
ipv6 - IPv6 TWAMP commands
    ├── responder - Start TWAMP responder session
    │   ├── do-not-fragment - Set Do Not Fragment flag
    │   ├── padding - Set packet padding
    │   ├── port - Set local port (REQUIRED)
    │   ├── tos - Set Type of Service
    │   └── ttl - Set Time to Live
    └── sender - Start TWAMP sender session
        ├── count - Set number of packets
        ├── destination-ip - Destination IPv6 address (REQUIRED)
        ├── do-not-fragment - Set Do Not Fragment flag
        ├── interval - Set packet interval
        ├── padding - Set packet padding
        ├── port - Set destination port (REQUIRED)
        ├── tos - Set Type of Service
        └── ttl - Set Time to Live
```


Version 0.2.1: bug fixes.
-------------------------

- Bug fixing when only '?' is typed.
- Fixed autocompletion for _options in config commands.
- Fixed bug with some autocompletions when inputing values for _options.
- Added mid-word autocompletion.

Version 0.2.0: new-interface & delete interface + tree improvements.
-------------------------

- Improvement to the whole 'show tree' function for more clarity.
- Added following commands for creating and deleting interfaces:

```
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
```

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
