from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import print_formatted_text
from cli.dispatcher import dispatch
from cli.commands import show, config, system  # Import command modules
from cli.commands.config import handle
import os
import getpass
import platform

# Combine descriptions from all command modules
command_descriptions = {
    "show": "Show system-related information",
    "config": "Configure system settings",
    "system": "Perform system operations",
}

# Create a custom completer that extends NestedCompleter but handles parameter sequences better
class VMarkCompleter(Completer):
    def __init__(self, command_tree, description_tree):
        self.command_tree = command_tree
        self.description_tree = description_tree
        self.param_commands = ["mtu", "speed", "status", "auto-nego", "duplex", "type", 
                               "cvlan-id", "svlan-id", "ipv4address", "netmask", "parent-interface"]
        
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.strip():
            # Top level completions
            for key in self.command_tree.keys():
                yield Completion(key, start_position=0, display_meta=command_descriptions.get(key, ""))
            return
        
        # Split into command parts
        parts = text.strip().split()
        current_text = parts[-1] if parts else ""
        
        # Check if we're completing a command or a partial command
        is_completing_command = text[-1].isspace() if text else False
        
        # Start from the root of the tree
        subtree = self.command_tree
        descsubtree = self.description_tree
        
        # Track if we've encountered a new-interface command
        new_interface_command = False
        interface_name = None
        
        # Track already used parameters to exclude them from completions
        used_params = set()
        
        # SIMPLIFIED DETECTION LOGIC
        # First determine if we're in a new-interface command
        if len(parts) >= 2 and parts[0] == "config" and parts[1] == "new-interface":
            new_interface_command = True
            if len(parts) >= 3:
                interface_name = parts[2]
            
            # Track used parameters more reliably by scanning the entire command
            # This is the key to fixing the parameter tracking
            i = 3  # Start after "config new-interface <name>"
            while i < len(parts):
                if i < len(parts) and parts[i] in self.param_commands:
                    used_params.add(parts[i])
                    # Skip the parameter value too
                    i += 2
                else:
                    i += 1
        
        # SIMPLIFIED NAVIGATION LOGIC
        # Navigate through the command tree to reach the current position
        navigate_parts = parts if is_completing_command else parts[:-1]
        for i, part in enumerate(navigate_parts):
            if not isinstance(subtree, dict):
                break
            
            if part in subtree:
                subtree = subtree[part]
                descsubtree = descsubtree.get(part, {}) if isinstance(descsubtree, dict) else {}
            else:
                # Handle dynamic interface name in new-interface command
                if i == 2 and new_interface_command:
                    subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
                    descsubtree = self.description_tree["config"]["new-interface"]["<ifname>"]
                else:
                    subtree = None
                    break
        
        # SPECIAL CASE HANDLING
        # Case 1: We're right after a parameter name (ready to show parameter values)
        if new_interface_command and interface_name and len(parts) >= 4 and parts[-2] in self.param_commands and parts[-1] == "":
            param_name = parts[-2]
            param_desc = self.description_tree["config"]["new-interface"]["<ifname>"].get(param_name, {})
            
            # Special case for parent-interface
            if param_name == "parent-interface":
                parent_if_options = self.command_tree["config"]["new-interface"]["<ifname>"]["parent-interface"]
                for option in parent_if_options.keys():
                    if option.startswith("_"):
                        continue
                    yield Completion(option, start_position=0, display_meta="")
                return

            # For other parameters with _options
            elif isinstance(param_desc, dict) and "_options" in param_desc:
                for option in param_desc["_options"]:
                    desc = param_desc.get("format", "")
                    # Format hints don't auto-complete
                    if option.startswith("<") and option.endswith(">"):
                        yield Completion(
                            "",  # Don't actually insert text
                            start_position=0,
                            display=option,
                            display_meta=desc
                        )
                    else:
                        yield Completion(option, start_position=0, display_meta=desc)
                return
        
        # Case 2: After any parameter-value pair, show the next available parameters
        # This is the key case that ensures tab completion works after "cvlan-id 20 "
        elif new_interface_command and interface_name and is_completing_command:
            # If we're at a completion point (space at the end) after any parameter-value pair,
            # reset to the parameter level and show available parameters
            param_subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
            
            # Show all remaining parameters
            for key in param_subtree.keys():
                # Skip used parameters and special entries
                if key in used_params or key.startswith("_"):
                    continue
                
                desc = ""
                if key in self.description_tree["config"]["new-interface"]["<ifname>"]:
                    desc_entry = self.description_tree["config"]["new-interface"]["<ifname>"].get(key, {})
                    if isinstance(desc_entry, dict) and "" in desc_entry:
                        desc = desc_entry[""]
                        
                yield Completion(key, start_position=0, display_meta=desc)
            return
        
        # STANDARD COMPLETION LOGIC
        # Now handle standard completions if we're not in a special case
        if isinstance(subtree, dict):
            # If we're completing a command (space after last word)
            if is_completing_command:
                # Show all options from current subtree, excluding used parameters
                for key, value in subtree.items():
                    # Skip already used parameters
                    if new_interface_command and interface_name and key in used_params:
                        continue
                        
                    desc = ""
                    if isinstance(descsubtree, dict) and key in descsubtree:
                        if isinstance(descsubtree[key], dict) and "" in descsubtree[key]:
                            desc = descsubtree[key][""]
                        elif isinstance(descsubtree[key], str):
                            desc = descsubtree[key]
                    
                    yield Completion(key, start_position=0, display_meta=desc)
            else:
                # Completing partial command (the last word in parts)
                partial = parts[-1] if parts else ""
                
                # First try direct completion from the current subtree
                completions_found = False
                
                for key, value in subtree.items():
                    # Skip already used parameters
                    if new_interface_command and interface_name and key in used_params:
                        continue
                        
                    if key.startswith(partial):
                        completions_found = True
                        desc = ""
                        if isinstance(descsubtree, dict) and key in descsubtree:
                            if isinstance(descsubtree[key], dict) and "" in descsubtree[key]:
                                desc = descsubtree[key][""]
                            elif isinstance(descsubtree[key], str):
                                desc = descsubtree[key]
                        
                        # Only complete what's missing
                        completion_text = key[len(partial):]
                        yield Completion(
                            completion_text,
                            start_position=0,
                            display=key,
                            display_meta=desc
                        )
                
                # If we're in a config context, check for partial matches with top-level commands
                if not completions_found and len(parts) == 1 and parts[0].startswith("con"):
                    for key in self.command_tree.keys():
                        if key.startswith(partial):
                            yield Completion(
                                key[len(partial):],
                                start_position=0,
                                display=key,
                                display_meta=command_descriptions.get(key, "")
                            )
                
                # If we're in a new-interface context, check for partial matches with parameters
                elif not completions_found and new_interface_command:
                    # We're in a new-interface context, check parameter subtree
                    param_subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
                    param_descs = self.description_tree["config"]["new-interface"]["<ifname>"]
                    
                    for key, value in param_subtree.items():
                        # Skip already used parameters
                        if key in used_params:
                            continue
                            
                        if key.startswith(partial):
                            desc = ""
                            if isinstance(param_descs, dict) and key in param_descs:
                                if isinstance(param_descs[key], dict) and "" in param_descs[key]:
                                    desc = param_descs[key][""]
                            
                            completion_text = key[len(partial):]
                            yield Completion(
                                completion_text,
                                start_position=0,
                                display=key,
                                display_meta=desc
                            )

# Build the command tree from the modules
def build_command_tree_and_descs():
    """Build command tree and descriptions from modules"""
    from cli.commands import show, config, system
    
    # Import tree and descriptions from each module
    command_tree = {
        "show": show.get_command_tree(),
        "config": config.get_command_tree(),
        "system": system.get_command_tree(),
    }
    
    description_tree = {
        "show": show.descriptions,
        "config": config.descriptions,
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
    VERSION = "0.2.0"  # Project version
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

    # Create key bindings
    bindings = KeyBindings()

    @bindings.add('?')
    def _(event):
        buffer = event.app.current_buffer
        text = buffer.text.strip()
        output = []
        
        # Do not insert the ? character into the buffer
        
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
            last_param = None
            last_param_index = -1
            
            # Track if we're in a new-interface command
            new_interface_command = False
            interface_name = None
            
            # Track already used parameters
            used_params = set()
            
            # First, detect if we're in a new-interface command context
            if len(parts) >= 2 and parts[0] == "config" and parts[1] == "new-interface":
                new_interface_command = True
                if len(parts) >= 3:
                    interface_name = parts[2]
                    
                    # Collect used parameters for new-interface command
                    param_list = ["mtu", "speed", "status", "auto-nego", "duplex", "type", 
                                  "cvlan-id", "svlan-id", "ipv4address", "netmask", "parent-interface"]
                    for i in range(3, len(parts), 2):
                        if i < len(parts) and parts[i] in param_list:
                            used_params.add(parts[i])
            
            # Navigate to the current position in both trees
            for i, part in enumerate(parts):
                if subtree is None:
                    break
                    
                if isinstance(subtree, dict):
                    # First check for exact matches
                    if part in subtree:
                        # Check if we're at a parameter command
                        if part in ["mtu", "speed", "status", "auto-nego", "duplex", "type", "cvlan-id", "svlan-id", "ipv4address", "netmask", "parent-interface"]:
                            at_param_level = True
                            param_name = part
                            last_param = part
                            last_param_index = i
                        
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
                        # Handle new-interface command with dynamic interface name
                        elif i == 2 and parts[0] == "config" and parts[1] == "new-interface":
                            # We're handling a new interface name input
                            # Use the parameters defined for <ifname> in new-interface
                            if "<ifname>" in command_tree["config"]["new-interface"]:
                                subtree = command_tree["config"]["new-interface"]["<ifname>"]
                                descsubtree = description_tree["config"]["new-interface"]["<ifname>"]
                            else:
                                subtree = None
                                descsubtree = None
                                break
                        # Handle parameter values (similar to the VMarkCompleter)
                        elif last_param_index == i - 1:
                            # This is a value for the last parameter
                            # We should skip it and continue with the parameter options
                            # For new-interface commands, reset to parameter options
                            if new_interface_command and interface_name:
                                subtree = command_tree["config"]["new-interface"]["<ifname>"]
                                descsubtree = description_tree["config"]["new-interface"]["<ifname>"]
                                # Mark parameter as used
                                if last_param in used_params:
                                    used_params.add(last_param)
                            continue
                        else:
                            subtree = None
                            descsubtree = None
                            break
            
            # Special handling for new-interface command with parameters
            if new_interface_command and interface_name:
                # Always reset for completions after a parameter value or interface name
                should_reset = False
                
                # Check if we're after a parameter-value pair
                if last_param_index >= 0 and last_param_index < len(parts) - 2:
                    should_reset = True
                
                # Check if we're just after the interface name
                if len(parts) == 3:
                    should_reset = True
                
                # If we're at a parameter value, also reset
                if len(parts) >= 4 and last_param_index == len(parts) - 2:
                    should_reset = True
                    
                if should_reset:
                    subtree = command_tree["config"]["new-interface"]["<ifname>"]
                    descsubtree = description_tree["config"]["new-interface"]["<ifname>"]
                    at_param_level = False
                    param_name = None
            
            # If we're at a parameter level, show options
            if at_param_level and param_name and param_name in descsubtree:
                param_desc = descsubtree[param_name]
                
                # Navigate to the parameter options
                if isinstance(param_desc, dict) and "_options" in param_desc:
                    output.append(("class:completion-header", f"\nFormat for {param_name}:\n"))
                    
                    # If we have a format description, show it
                    if isinstance(param_desc, dict) and "format" in param_desc:
                        output.append(("", f"  {param_desc['format']}\n"))
                    else:
                        # Otherwise show the options
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
                        # Skip already used parameters for new-interface command
                        if new_interface_command and interface_name and key in used_params:
                            continue
                            
                        desc_entry = descsubtree.get(key, {}) if isinstance(descsubtree, dict) else {}
                        desc = desc_entry.get("", "") if isinstance(desc_entry, dict) else desc_entry
                        output.append(("", f"  {key:<20} {desc}\n"))
                else:
                    output.append(("", f"\nNo further options available for: {text}\n"))
            else:
                output.append(("", f"\nNo further options available for: {text}\n"))

        # In the ? handler, update the parameter level detection

        # Check if we're at a parameter level requesting a value
        is_param_value_query = False
        param_for_value = None

        # Case 1: Last word is a parameter name
        if parts and parts[-1] in ["mtu", "speed", "status", "auto-nego", "duplex", "type", 
                                 "cvlan-id", "svlan-id", "ipv4address", "netmask", "parent-interface"]:
            is_param_value_query = True
            param_for_value = parts[-1]

        if is_param_value_query and param_for_value:
            # Get parameter description
            param_desc = None
            
            # Find the parameter in the appropriate context
            if new_interface_command and interface_name:
                param_desc = description_tree["config"]["new-interface"]["<ifname>"].get(param_for_value, {})
            elif len(parts) >= 3 and parts[0] == "config" and parts[1] == "interface":
                param_desc = description_tree["config"]["interface"]["<ifname>"].get(param_for_value, {})
            
            if param_desc and isinstance(param_desc, dict):
                output.append(("class:completion-header", f"\nFormat for {param_for_value}:\n"))
                
                # Show format hint if available
                if "format" in param_desc:
                    output.append(("", f"  {param_desc['format']}\n"))
                
                # Otherwise show available options
                elif "_options" in param_desc:
                    for option in param_desc["_options"]:
                        output.append(("", f"  {option}\n"))
                
                print_formatted_text(FormattedText(output), end="")
                event.app.invalidate()
                return

        print_formatted_text(FormattedText(output), end="")
        event.app.invalidate()

    # Create the PromptSession with our custom completer
    session = PromptSession(
        completer=VMarkCompleter(command_tree, description_tree),
        key_bindings=bindings
    )
    
    # Then define the rebuild function that uses the session
    def rebuild_completer():
        """Rebuild the command completer"""
        nonlocal command_tree, description_tree
        temp_tree, temp_desc = build_command_tree_and_descs()
        command_tree = temp_tree
        description_tree = temp_desc
        
        # Rebuild the session completer with the updated custom completer
        session.completer = VMarkCompleter(command_tree, description_tree)

    # Now it's safe to call rebuild_completer
    rebuild_completer()

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