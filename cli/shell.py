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
from cli.commands.config import handle

# Combine descriptions from all command modules
command_descriptions = {
    "show": "Show system-related information",
    "config": "Configure system settings",
    "system": "Perform system operations",
}

# Build the command tree from the modules
def build_command_tree_and_descs():
    # Generate the command tree from each module
    command_tree = {
        "config": config.get_command_tree(),
        "show": show.get_command_tree(),
        "system": system.get_command_tree(),
    }
    
    # Generate the description tree from module descriptions
    description_tree = {
        "config": config.descriptions,
        "show": show.descriptions,
        "system": system.descriptions,
    }
    
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

    # Create a key binding for '?' to display possible completions
    bindings = KeyBindings()

    @bindings.add('?')
    def _(event):
        buffer = event.app.current_buffer
        text = buffer.text.strip()
        output = []
        
        # Do not insert the ? character into the buffer
        # buffer.insert_text('?')  # This line should remain commented out
        
        if not text:
            # Top-level commands
            output.append(("class:completion-header", "\nPossible completions:\n"))
            for key in command_tree.keys():
                desc = command_descriptions.get(key, "")
                output.append(("", f"  {key:<20} {desc}\n"))
        else:
            parts = text.split()
            
            # Find the current command tree and description tree
            subtree = command_tree
            descsubtree = description_tree
            
            # Track if we're at a parameter level
            at_param_level = False
            param_name = None
            last_command = parts[-1] if parts else ""
            
            # Navigate to the current position in both trees
            for i, part in enumerate(parts):
                if subtree is None:
                    break  # Stop traversing if we've hit a leaf node
                    
                if part in subtree:
                    # Check if we're at a parameter command
                    if part in ["mtu", "speed", "status", "auto-nego", "duplex", "type", "cvlan-id", "svlan-id"]:
                        at_param_level = True
                        param_name = part
                    
                    subtree = subtree[part]
                    # Special handling for interface parameters
                    if i >= 2 and parts[0] == "config" and parts[1] == "interface" and i-1 == 2:
                        # We're at an interface level, use <ifname> in description tree
                        descsubtree = description_tree["config"]["interface"]["<ifname>"]
                    else:
                        descsubtree = descsubtree.get(part, {}) if isinstance(descsubtree, dict) else {}
                else:
                        # Handle dynamic interface names in config interface
                        if i == 2 and parts[0] == "config" and parts[1] == "interface":
                            # We're at a dynamic interface name
                            if part in command_tree["config"]["interface"]:
                                subtree = command_tree["config"]["interface"][part]
                                # Use <ifname> for descriptions
                                descsubtree = description_tree["config"]["interface"]["<ifname>"]
                            else:
                                subtree = None
                                descsubtree = None
                                break
                        else:
                            subtree = None
                            descsubtree = None
                            break
            
            # If we're at a parameter level, show options
            if at_param_level and param_name and param_name in descsubtree:
                param_desc = descsubtree[param_name]
                
                # Navigate to the parameter options
                if isinstance(param_desc, dict) and "_options" in param_desc:
                    output.append(("class:completion-header", f"\nPossible values for {param_name}:\n"))
                    for option in param_desc["_options"]:
                        output.append(("", f"  {option}\n"))
                    print_formatted_text(FormattedText(output), end="")
                    event.app.invalidate()
                    return
            
            # Default behavior for showing available commands
            if subtree is not None:
                output.append(("class:completion-header", f"\nPossible completions: {text} ?\n"))
                if isinstance(subtree, dict):
                    for key in subtree.keys():
                        desc_entry = descsubtree.get(key, {}) if isinstance(descsubtree, dict) else {}
                        desc = desc_entry.get("", "") if isinstance(desc_entry, dict) else desc_entry
                        output.append(("", f"  {key:<20} {desc}\n"))
                else:
                    output.append(("", f"\nNo further options available for: {text}\n"))
            else:
                output.append(("", f"\nNo further options available for: {text}\n"))

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