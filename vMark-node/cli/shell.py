from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import print_formatted_text
from cli.dispatcher import dispatch
from cli.modules import show, config, system, twamp  # Changed from commands to modules
from cli.modules.config import handle  # Change any direct imports
import os
import getpass
import platform

# Combine descriptions from all command modules
command_descriptions = {
    "show": "Show system-related information",
    "config": "Configure system settings",
    "system": "Perform system operations",
    "twamp": "TWAMP testing commands",
}

# Create a custom completer that extends NestedCompleter but handles parameter sequences better
class VMarkCompleter(Completer):
    def __init__(self, command_tree, description_tree):
        self.command_tree = command_tree
        self.description_tree = description_tree
        self.param_commands = [
            # Existing parameters
            "mtu", "speed", "status", "auto-nego", "duplex", "type", 
            "cvlan-id", "svlan-id", "ipv4address", "netmask", "parent-interface",
            # Add TWAMP parameters
            "destination-ip", "port", "count", "interval", "padding", "ttl", "tos", 
            "do-not-fragment"
        ]
        
    def create_completion(self, text, partial="", display=None, display_meta=""):
        """Helper to create consistent completions"""
        completion_text = text[len(partial):] if partial else text
        return Completion(
            completion_text,
            start_position=0,  # Changed from -len(partial) to 0
            display=text,  # Show full command in menu
            display_meta=display_meta
        )

    def get_available_interfaces(self):
        """Get list of available network interfaces"""
        try:
            import subprocess
            result = subprocess.run(
                ["ip", "-br", "link", "show"],
                capture_output=True,
                text=True,
                check=True
            )
            interfaces = []
            for line in result.stdout.splitlines():
                if_name = line.split()[0]
                # Filter out virtual and special interfaces
                if (not if_name.startswith('lo') and 
                    not if_name.startswith('vir') and 
                    not if_name.startswith('docker') and
                    not if_name.startswith('br') and
                    not if_name.startswith('tun') and
                    not if_name.startswith('tap') and
                    not if_name.startswith('veth')):
                    interfaces.append(if_name)
            return interfaces
        except Exception:
            return []

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        parts = text.strip().split()
        current_command = parts[0] if parts else ""
        used_params = set()

        # Handle TWAMP commands
        if current_command == "twamp" and len(parts) >= 4:
            mode = parts[2]  # sender or responder
            twamp_desc = self.description_tree.get("twamp", {})
            version_desc = twamp_desc.get(parts[1], {})
            mode_desc = version_desc.get(mode, {})

            # Track used parameters
            for i in range(3, len(parts) - 1, 2):
                if parts[i] in mode_desc:
                    used_params.add(parts[i])

        if not text.strip():
            # Top level completions
            for key in self.command_tree.keys():
                yield Completion(
                    key,
                    start_position=0,  # Keep 0 for empty input
                    display=key,
                    display_meta=command_descriptions.get(key, "")
                )
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
        
        # Track used parameters for both new-interface and TWAMP
        used_params = set()
        
        # Track if we're in a TWAMP command
        twamp_command = len(parts) >= 2 and parts[0] == "twamp"
        twamp_mode = None
        if twamp_command:
            if "sender" in parts:
                twamp_mode = "sender"
            elif "responder" in parts:
                twamp_mode = "responder"
        
        # First determine if we're in a new-interface command or TWAMP command
        if len(parts) >= 2:
            if parts[0] == "config" and parts[1] == "new-interface":
                new_interface_command = True
                if len(parts) >= 3:
                    interface_name = parts[2]
                
                # Track used parameters
                i = 3
                while i < len(parts):
                    if i < len(parts) and parts[i] in self.param_commands:
                        used_params.add(parts[i])
                        if i + 1 < len(parts):
                            i += 2
                        else:
                            break
                    else:
                        i += 1
            elif parts[0] == "twamp":
                # Track used TWAMP parameters
                i = 2  # Start after "twamp ipv4"
                while i < len(parts):
                    if i < len(parts) and parts[i] in self.param_commands:
                        used_params.add(parts[i])
                        if i + 1 < len(parts):
                            i += 2
                        else:
                            break
                    else:
                        i += 1
        
        # SIMPLIFIED DETECTION LOGIC
        # First determine if we're in a new-interface command
        if len(parts) >= 2 and parts[0] == "config" and parts[1] == "new-interface":
            new_interface_command = True
            if len(parts) >= 3:
                interface_name = parts[2]
            
            # Track used parameters by scanning the entire command
            i = 3  # Start after "config new-interface <name>"
            while i < len(parts):  
                if i < len(parts) and parts[i] in self.param_commands:
                    used_params.add(parts[i])
                    # Skip the parameter's value and reset subtree
                    if i + 1 < len(parts):
                        i += 2
                    else:
                        break
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
                # Handle TWAMP parameter values
                elif len(parts) >= 2 and parts[0] == "twamp":
                    # After a TWAMP parameter value, reset to show remaining options
                    if parts[-2] in self.param_commands:
                        # Track parameter-value pairs for both sender and responder
                        param_pairs = {}
                        used_params = set()
                        
                        # Scan for used parameters
                        for i in range(len(parts)-1):
                            if parts[i] in self.param_commands and i+1 < len(parts):
                                param_pairs[parts[i]] = parts[i+1]
                                used_params.add(parts[i])
                        
                        if "sender" in parts:
                            subtree = self.command_tree["twamp"]["ipv4"]["sender"]
                            descsubtree = self.description_tree["twamp"]["ipv4"]["sender"]
                            
                            # Reset navigation to show remaining options
                            if is_completing_command:
                                # Show all remaining parameters that haven't been used
                                for key in subtree.keys():
                                    if key not in used_params and not key.startswith('_'):
                                        desc = ""
                                        if isinstance(descsubtree, dict):
                                            desc_entry = descsubtree.get(key, {})
                                            if isinstance(desc_entry, dict):
                                                desc = desc_entry.get("", "")
                                            elif isinstance(desc_entry, str):
                                                desc = desc_entry
                                        yield self.create_completion(key, "", display_meta=desc)
                                
                        elif "responder" in parts:
                            subtree = self.command_tree["twamp"]["ipv4"]["responder"]
                            descsubtree = self.description_tree["twamp"]["ipv4"]["responder"]
                            
                            # Reset navigation to show remaining options
                            if is_completing_command:
                                # Show all remaining parameters that haven't been used
                                for key in subtree.keys():
                                    if key not in used_params and not key.startswith('_'):
                                        desc = ""
                                        if isinstance(descsubtree, dict):
                                            desc_entry = descsubtree.get(key, {})
                                            if isinstance(desc_entry, dict):
                                                desc = desc_entry.get("", "")
                                            elif isinstance(desc_entry, str):
                                                desc = desc_entry
                                        yield self.create_completion(key, "", display_meta=desc)
                # Reset to parameter level after any parameter value
                elif new_interface_command and i > 2 and len(parts) > i:
                    subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
                    descsubtree = self.description_tree["config"]["new-interface"]["<ifname>"]
                else:
                    subtree = None
                    break
        
        # SPECIAL CASE HANDLING
        # Case 1: We're right after a parameter name (ready to show parameter values)
        if new_interface_command and interface_name and len(parts) >= 4 and parts[-2] in self.param_commands:
            param_name = parts[-2]
            param_desc = self.description_tree["config"]["new-interface"]["<ifname>"].get(param_name, {})
            partial = parts[-1] if parts else ""
            
            # Special case for parent-interface
            if param_name == "parent-interface":
                # Get actual network interfaces from the system
                interfaces = self.get_available_interfaces()
                
                # Show interfaces only if we haven't selected one yet
                if not partial or (partial and not partial == interfaces[0]):
                    for if_name in interfaces:
                        if if_name.startswith(partial):
                            yield self.create_completion(
                                if_name,
                                partial,
                                display=if_name,
                                display_meta="Available interface"
                            )
                return

            # For other parameters with _options
            elif isinstance(param_desc, dict) and "_options" in param_desc:
                format_hint = param_desc.get("format", "")
                
                # Always show format hint when no partial input
                if not partial:
                    yield Completion(
                        "",  # Don't insert text
                        start_position=0,
                        display=param_desc["_options"][0],
                        display_meta=format_hint
                    )

                # Show format hint for ipv4address parameter
                if param_name == "ipv4address":
                    yield Completion(
                        "",
                        start_position=0,
                        display="<x.x.x.x>",
                        display_meta="Enter IPv4 address in dotted decimal format (e.g., 192.168.1.1)"
                    )
                return
        
        # Case 2: After any parameter-value pair, show the next available parameters
        elif new_interface_command and interface_name:
            # Check if we're after a parameter value or parameter-value pair
            if len(parts) >= 4:
                # We're right after a parameter value or parameter-value pair
                partial = parts[-1] if parts else ""
                
                # Reset to parameter level and show available parameters
                param_subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
                
                # Show all remaining parameters
                for key in param_subtree.keys():
                    # Skip used parameters and special entries
                    if key in used_params or key.startswith("_"):
                        continue
                    
                    if not partial or key.startswith(partial):
                        desc = ""
                        if key in self.description_tree["config"]["new-interface"]["<ifname>"]:
                            desc_entry = self.description_tree["config"]["new-interface"]["<ifname>"].get(key, {})
                            if isinstance(desc_entry, dict) and "" in desc_entry:
                                desc = desc_entry[""]
                    
                        # Only complete what's missing if there's a partial match
                        yield self.create_completion(key, partial, display_meta=desc)
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
                        
                yield self.create_completion(key, "", display_meta=desc)
            return
        
        # Add TWAMP command handling after a parameter value
        elif len(parts) >= 2 and parts[0] == "twamp":
            # After a parameter value, show remaining options
            if len(parts) > 4:  # We have at least command + mode + param + value
                partial = parts[-1] if not is_completing_command else ""
                
                # Reset to appropriate command tree
                if "sender" in parts:
                    subtree = self.command_tree["twamp"]["ipv4"]["sender"]
                    descsubtree = self.description_tree["twamp"]["ipv4"]["sender"]
                elif "responder" in parts:
                    subtree = self.command_tree["twamp"]["ipv4"]["responder"]
                    descsubtree = self.description_tree["twamp"]["ipv4"]["responder"]
                    
                # Show remaining parameters that match partial
                for key in subtree.keys():
                    if key not in used_params and not key.startswith('_'):
                        if not partial or key.startswith(partial):
                            desc = ""
                            desc_entry = descsubtree.get(key, {})
                            if isinstance(desc_entry, dict):
                                desc = desc_entry.get("", "")
                            elif isinstance(desc_entry, str):
                                desc = desc_entry
                            yield self.create_completion(key, partial, display_meta=desc)

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
                    
                    yield self.create_completion(key, "", display_meta=desc)
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
                            desc_entry = descsubtree.get(key, {})
                            if isinstance(desc_entry, dict):
                                if "" in desc_entry:
                                    desc = desc_entry[""]
                                elif "_options" in desc_entry:
                                    desc = f"Options: {', '.join(desc_entry['_options'])}"
                            else:
                                desc = desc_entry
                        
                        # Only complete what's missing
                        yield self.create_completion(key, partial, display_meta=desc)
                
                # If we're in a config context, check for partial matches with top-level commands
                if not completions_found and len(parts) == 1 and parts[0].startswith("con"):
                    for key in self.command_tree.keys():
                        if key.startswith(partial):
                            completion_text = key[len(partial):]  # Only complete what's missing
                            yield Completion(
                                completion_text,
                                start_position=0,  # Changed from -len(partial) to 0
                                display=key,
                                display_meta=command_descriptions.get(key, "")
                            )
                
                # In the parameter completion section:
                elif not completions_found and new_interface_command:
                    # We're in a new-interface context, check parameter subtree
                    param_subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
                    param_descs = self.description_tree["config"]["new-interface"]["<ifname>"]
                    
                    # Get the current partial word
                    partial = parts[-1] if parts else ""
                    
                    for key in param_subtree.keys():
                        # Skip already used parameters and special entries
                        if key in used_params or key.startswith("_"):
                            continue
                            
                        if key.startswith(partial):
                            desc = ""
                            if isinstance(param_descs, dict) and key in param_descs:
                                desc_entry = param_descs.get(key, {})
                                if isinstance(desc_entry, dict) and "" in desc_entry:
                                    desc = desc_entry[""]
                                    
                            # Calculate what needs to be completed
                            yield self.create_completion(key, partial, display_meta=desc)

    def get_description(self, desc_node, key):
        """Helper to safely get description text."""
        if isinstance(desc_node, dict) and key in desc_node:
            entry = desc_node[key]
            if isinstance(entry, dict):
                return entry.get("", "") # Get main description if available
            elif isinstance(entry, str):
                return entry
        return ""

    # Ensure create_completion is defined correctly
    def create_completion(self, text, partial="", display=None, display_meta=""):
        completion_text = text[len(partial):] if partial else text
        # Use -len(partial) for replacing the partial word
        return Completion(
            text, # Use the full word for replacement
            start_position=-len(partial),
            display=display if display is not None else text,
            display_meta=display_meta
        )

# Build the command tree from the modules
def build_command_tree_and_descs():
    """Build command tree and descriptions from modules"""
    from cli.modules import show, config, system, twamp  # Add twamp import
    
    # Import tree and descriptions from each module
    command_tree = {
        "show": show.get_command_tree(),
        "config": config.get_command_tree(),
        "system": system.get_command_tree(),
        "twamp": twamp.get_command_tree(),  # Add twamp command tree
    }
    
    description_tree = {
        "show": show.descriptions,
        "config": config.descriptions,
        "system": system.descriptions,
        "twamp": twamp.descriptions,  # Add twamp descriptions
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
    VERSION = "0.3.3"  # Project version
    print(f"vMark-node version: {VERSION}")

# Additional feature: Display hardware and OS information
def af_info():
    print("\n  -- System Information --")
    print(f"OS: {platform.system()}")
    print(f"OS Release: {platform.release()}")
    print(f"Hostname: {platform.node()}")
    print(f"Architecture: {platform.processor()}")
    print("\n")

# --- NEW HELPER FUNCTION for '?' ---
def get_question_mark_help(text_before_question_mark, command_tree, description_tree, param_commands_list):
    """Determines the help text for the '?' handler."""
    parts = text_before_question_mark.strip().split()
    current_node = command_tree
    current_desc_node = description_tree
    help_items = []
    used_params = set()

    # For empty input, show top-level commands
    if not parts:
        for key in command_tree.keys():
            if not key.startswith('_'):
                help_items.append({
                    'type': 'option',
                    'display': key,
                    'meta': command_descriptions.get(key, "")
                })
        return help_items

    # Special case for config new-interface without name
    if parts == ["config", "new-interface"]:
        help_items.append({
            'type': 'option',
            'display': '',  # Empty to just show description
            'meta': 'New interface name'
        })
        return help_items

    # Track if we're in a parameter context
    is_twamp = parts[0] == "twamp" if parts else False
    is_config_iface = len(parts) >= 3 and parts[0] == "config" and parts[1] == "new-interface"
    is_config_if = len(parts) >= 2 and parts[0] == "config" and parts[1] == "interface"

    # Collect ALL parameter-value pairs in the entire command
    if is_twamp or is_config_iface:
        # Scan the entire command to find all parameter-value pairs
        i = 0
        while i < len(parts):
            if parts[i] in param_commands_list and i + 1 < len(parts):
                used_params.add(parts[i])
                i += 2  # Skip both parameter and value
            else:
                i += 1

    # Navigate through command tree for basic commands
    for part in parts:
        if isinstance(current_node, dict) and part in current_node:
            current_node = current_node[part]
            current_desc_node = current_desc_node.get(part, {})
        else:
            break

    # Reset to appropriate command level for TWAMP
    if is_twamp and len(parts) >= 4:
        mode = "sender" if "sender" in parts else "responder"
        current_node = command_tree["twamp"]["ipv4"][mode]
        current_desc_node = description_tree["twamp"]["ipv4"][mode]
    # Reset for config new-interface with name
    elif is_config_iface and len(parts) >= 3:
        current_node = command_tree["config"]["new-interface"]["<ifname>"]
        current_desc_node = description_tree["config"]["new-interface"]["<ifname>"]

    # Generate help items for current node
    if isinstance(current_node, dict):
        for key, value in current_node.items():
            if key not in used_params and not key.startswith('_'):
                desc = ""
                if isinstance(current_desc_node, dict) and key in current_desc_node:
                    entry = current_desc_node[key]
                    if isinstance(entry, dict):
                        desc = entry.get("", "")
                    elif isinstance(entry, str):
                        desc = entry
                help_items.append({'type': 'option', 'display': key, 'meta': desc})

    return help_items

def start_cli():
    command_tree, description_tree = build_command_tree_and_descs()
    # Get the list of known parameter commands (needed for the helper)
    # You might need to instantiate VMarkCompleter once to get this list,
    # or define the list globally/pass it differently.
    temp_completer_for_params = VMarkCompleter(command_tree, description_tree)
    param_commands_list = temp_completer_for_params.param_commands

    # Create key bindings
    bindings = KeyBindings()

    @bindings.add('?')
    def _(event):
        buffer = event.app.current_buffer
        original_text = buffer.text
        text_before_question_mark = original_text.rstrip(' ?')

        # --- Get Help Items ---
        try:
            help_items = get_question_mark_help(
                text_before_question_mark,
                command_tree,
                description_tree,
                param_commands_list
            )
        except Exception as e:
            # Using print_formatted_text for errors too, to avoid interfering
            print_formatted_text(FormattedText([('fg:red', f"\nError getting help items: {e}\n")]))
            help_items = []

        # --- Prepare FormattedText fragments for ALL output ---
        output_fragments = []

        # 1. The prompt line + '?'
        prompt_string = f"{getpass.getuser()}/{os.uname().nodename}@vMark-node> "
        # Add a newline *after* the prompt line
        output_fragments.append(('', f"{prompt_string}{text_before_question_mark} ?\n"))

        # 2. Help content (with spacing)
        if help_items:
            is_format_hint = help_items[0]['type'] == 'format'
            output_fragments.append(('', "\n")) # Blank line before help

            if is_format_hint:
                item = help_items[0]
                output_fragments.append(('', f"Help for '{item['param']}']:\n"))
                output_fragments.append(('', f"  Format: {item['hint']}\n"))
                if item['meta']:
                     output_fragments.append(('', f"  Description: {item['meta']}\n"))
            else:
                output_fragments.append(('', "Possible completions:\n"))
                for item in help_items:
                    if item['type'] == 'option':
                        display_text = item['display']
                        meta_text = str(item['meta'])
                        output_fragments.append(('', f"  {display_text:<20} {meta_text}\n"))
        else:
            output_fragments.append(('', "\n")) # Blank line before message
            output_fragments.append(('', f"No further options available for: {text_before_question_mark}\n"))

        # Add a final blank line for spacing before the prompt redraws
        output_fragments.append(('', "\n"))

        # --- Print all collected text above the prompt ---
        # This function handles clearing space, printing, and redrawing the prompt below
        print_formatted_text(FormattedText(output_fragments), end='')

        # --- Restore buffer ---
        # Add a space after the command when restoring the buffer
        buffer.text = text_before_question_mark + " "  # Add space here
        buffer.cursor_position = len(buffer.text)  # Move cursor after the space
        # No invalidate needed, print_formatted_text handles the redraw.

    # Create the PromptSession - STILL USES VMarkCompleter FOR TAB
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