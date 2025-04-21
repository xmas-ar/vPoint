import os
import getpass
import platform
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import print_formatted_text
from cli.dispatcher import dispatch
from cli.commands import show, config, system  # Import command modules
from pyroute2 import IPDB
from cli.commands.config import handle

# Combine descriptions from all command modules
command_descriptions = {
    "show": "Show system-related information",
    "config": "Configure system settings",
    "system": "Perform system operations",
}

# Centralized descriptions
group_descriptions = {
    "show": show.descriptions,
    "config": config.descriptions,
    "system": system.descriptions,
}

# Dynamically build the command tree and descriptions
def build_command_tree_and_descs():
    # Dynamically fetch interface names
    with IPDB() as ipdb:
        interface_names = [
            str(name) for name in ipdb.interfaces.keys()
            if isinstance(name, str) and not name.isdigit()  # Exclude numeric keys
        ]

    # Helper function to recursively build the command tree
    def build_tree_from_descriptions(desc_tree):
        tree = {}
        for key, value in desc_tree.items():
            if key == "_options":
                # Add options as leaf nodes for autocompletion
                for option in value:
                    tree[option] = None
            elif isinstance(value, dict):
                # Recursively build subtrees
                tree[key] = build_tree_from_descriptions(value)
            else:
                # Leaf nodes (commands without subcommands)
                tree[key] = None
        return tree

    # Generate the command tree from the description tree
    description_tree = {
        "config": config.descriptions,
        "show": show.descriptions,
        "system": system.descriptions,
    }
    command_tree = build_tree_from_descriptions(description_tree)

    # Add dynamic interface names to the "config interface" subtree
    if "config" in command_tree and "interface" in command_tree["config"]:
        command_tree["config"]["interface"] = {
            name: {
                "mtu": None,
                "speed": None,
                "status": None,
                "auto-nego": None,
                "duplex": None,
            }
            for name in interface_names
        }

    # Add dynamic interface names to the "show interfaces" subtree
    if "show" in command_tree and "interfaces" in command_tree["show"]:
        command_tree["show"]["interfaces"] = {
            name: {} for name in interface_names
        }
        # Add static subcommands for "show interfaces"
        command_tree["show"]["interfaces"].update({
            "ip": {
                "": None,
                "config": None,
            },
            "ipv4": None,
        })

    return command_tree, description_tree

command_tree, description_tree = build_command_tree_and_descs()

# Additional feature: Clear the screen
def af_clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

# Additional feature: View command history
def af_view_history(history, count=None):
    if count is None:
        count = len(history)
    try:
        count = int(count)
        print("\nCommand History:")
        for i, cmd in enumerate(history[-count:], start=1):
            print(f"{i}: {cmd}")
    except ValueError:
        print("Invalid count. Please provide a valid number.")

# Additional feature: Check the version
def af_check_version():
    VERSION = "0.1.5"  # Project version
    print(f"vMark-node version: {VERSION}")

# Additional feature: Display hardware and OS information
def af_info():
    print("\n  -- System Information --")
    print(f"OS: {platform.system()}")
    print(f"OS Release: {platform.release()}")
    print(f"Hostname: {platform.node()}")
    print(f"Architecture: {platform.processor()}")
    print("\n")

def start_cli():
    command_tree, description_tree = build_command_tree_and_descs()

    # Create the PromptSession first
    session = PromptSession()

    def rebuild_completer():
        # Rebuild the NestedCompleter with the updated command_tree
        session.completer = NestedCompleter.from_nested_dict(command_tree)

    # Call rebuild_completer after building the command tree
    rebuild_completer()

    # Replace placeholders with dynamic handlers
    def update_new_interface_tree(interface_name):
        command_tree["config"]["new-interface"][interface_name] = {
            "type": {"vlan": {}, "vlan-in-vlan": {}},
            "cvlan-id": {},
            "svlan-id": {},
        }
        rebuild_completer()

    # Create a key binding for '?' to display possible completions
    bindings = KeyBindings()

    @bindings.add('?')
    def _(event):
        buffer = event.app.current_buffer
        text = buffer.text.strip()
        output = []

        if not text:
            # Top-level commands
            output.append(("class:completion-header", "\nPossible completions:\n"))
            for key in command_tree.keys():
                desc = description_tree[key].get("", "") if isinstance(description_tree[key], dict) else description_tree[key]
                output.append(("", f"  {key:<20} {desc}\n"))
        else:
            parts = text.split()
            subtree = command_tree
            descsubtree = description_tree

            for part in parts:
                if part in subtree:
                    subtree = subtree[part]
                    descsubtree = descsubtree.get(part, {})  # Safely get the next level
                else:
                    # Handle dynamic new-interface name
                    if len(parts) > 2 and parts[0] == "config" and parts[1] == "new-interface":
                        update_new_interface_tree(parts[2])
                        subtree = command_tree["config"]["new-interface"][parts[2]]
                        descsubtree = description_tree["config"]["new-interface"]
                    else:
                        subtree = None
                        descsubtree = None
                        break

            if subtree is not None and (not parts or buffer.text.endswith(' ')):
                output.append(("class:completion-header", f"\nPossible completions: {text} ?\n"))
                for key in subtree.keys():
                    desc_entry = descsubtree.get(key, {})  # Safely get the description
                    desc = desc_entry.get("", "") if isinstance(desc_entry, dict) else desc_entry
                    output.append(("", f"  {key:<20} {desc}\n"))
            else:
                output.append(("", f"\nNo further options available for: {text} ?\n"))

        print_formatted_text(FormattedText(output), end="")
        event.app.invalidate()

    # Initialize the PromptSession with the initial completer
    session = PromptSession(
        completer=NestedCompleter.from_nested_dict(command_tree),
        key_bindings=bindings
    )

    help_message = """

-- vMark-node CLI Help --

  - Tab for autocomplete, see completions with ? or 'show tree/show tree details/show tree show'.
  - Type 'clear' to clear the screen.
  - Type 'history count <number>' to view the last commands.
  - Type 'version' to check the vMark-node version.
  - Type 'debug' to enable debug mode.
  - Type 'info' to check hardware and OS information.
  - Type 'status' to check the general status of the system.

Type 'exit' or 'quit' to exit.

"""

    print("\n" + "vMark-node Initialized. Type 'help' or '?' for more information." + "\n")

    # Get the current username and hostname
    username = getpass.getuser()
    hostname = os.uname().nodename

    # Command history
    history = []

    while True:
        try:
            # Use the username and hostname in the prompt
            cmd = session.prompt(f'{username}/{hostname}@vMark-node> ').strip()
            if not cmd:
                continue  # Skip processing if no command is entered

            history.append(cmd)  # Add command to history

            if cmd in ['exit', 'quit']:
                break
            elif cmd == 'help':
                print(help_message)
            elif cmd == 'clear':
                af_clear_screen()
            elif cmd.startswith('history'):
                # Parse the history command
                parts = cmd.split()
                count = None
                if len(parts) > 1:
                    # Handle cases like "history count 10" or "history -count 10"
                    if parts[1].isdigit():
                        count = parts[1]
                    elif len(parts) > 2 and parts[2].isdigit():
                        count = parts[2]
                af_view_history(history, count)
            elif cmd == 'version':
                af_check_version()
            elif cmd == 'info':
                af_info()
            else:
                # Pass username and hostname to the handle function
                output = dispatch(cmd, username, hostname)
                if output:
                    print(output)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

def handle_config_interface_action(action, args, ifname, prompt):
    # Delegate the logic to config.py
    return handle(args, getpass.getuser(), os.uname().nodename)