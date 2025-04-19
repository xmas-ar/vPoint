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
    def build_subtree(subcommands, descs, path=()):
        tree = {}
        desc_lookup = {}
        for key, value in subcommands.items():
            if isinstance(value, dict):
                tree[key], desc_lookup[key] = build_subtree(value, value)
                desc_lookup[key][""] = value.get("", "")
            else:
                tree[key] = {}
                desc_lookup[key] = {"": value}
        return tree, desc_lookup

    tree = {}
    desc_lookup = {}
    for group, subcommands in group_descriptions.items():
        tree[group], desc_lookup[group] = build_subtree(subcommands, subcommands)
    return tree, desc_lookup

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
    VERSION = "0.1.1"  # Project version
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

            # If only one word and it's a top-level command, treat as 'show ?'
            if len(parts) == 1 and parts[0] in command_tree:
                subtree = command_tree[parts[0]]
                descsubtree = description_tree[parts[0]]
                output.append(("class:completion-header", f"\nPossible completions: {parts[0]} ?\n"))
                for key in subtree.keys():
                    desc_entry = descsubtree[key]
                    desc = desc_entry.get("", "") if isinstance(desc_entry, dict) else desc_entry
                    output.append(("", f"  {key:<20} {desc}\n"))
            else:
                for part in parts:
                    if part in subtree:
                        subtree = subtree[part]
                        descsubtree = descsubtree[part]
                    else:
                        subtree = None
                        descsubtree = None
                        break

                # Only show completions if at the end of a valid command path
                if subtree is not None and (not parts or buffer.text.endswith(' ')):
                    output.append(("class:completion-header", f"\nPossible completions: {text} ?\n"))
                    for key in subtree.keys():
                        desc_entry = descsubtree[key]
                        desc = desc_entry.get("", "") if isinstance(desc_entry, dict) else desc_entry
                        output.append(("", f"  {key:<20} {desc}\n"))
                else:
                    output.append(("", f"\nNo further options available for: {text} ?\n"))

        print_formatted_text(FormattedText(output), end="")
        event.app.invalidate()

    session = PromptSession(
        completer=NestedCompleter.from_nested_dict(command_tree),
        key_bindings=bindings
    )

    help_message = """

-- vMark-node CLI Help --

  - Tab for autocomplete, see possible options with ? or 'show tree'.
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