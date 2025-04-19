
# Release Notes

Version 0.1.1: Project Creation
-------------------------
- Repository created.
- CLI created mimicking junOS cli, with nested autocompletions, commands descriptions and help.
- Architecture:
  Shell: Auto-completion and tree creation based of descriptions.
  Distpacher: recognizing the command and what to do with it (which module to call). modules/plugins, distpacher is the one , some modules are: ).
  Modules: 'show', 'config', 'system', basically any command tree structure.
  Plugins: use of external libraries, like OpenBFDD.
- Additional commands added (accesible from help).
- Added commands:
  'show interface'
  'show interface ip'
  'show interface ipv4'
  'show tree' & 'show tree details'
