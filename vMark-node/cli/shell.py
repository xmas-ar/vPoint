from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import print_formatted_text
from cli.dispatcher import dispatch
from cli.modules import show, config, system, twamp, register  # Add register import
from cli.modules.config import handle  # Change any direct imports
import os
import getpass
import platform

# Add to command_descriptions dictionary
command_descriptions = {
    "show": "Show system-related information",
    "config": "Configure system settings",
    "system": "Perform system operations",
    "twamp": "TWAMP testing commands",
    "register": "Register with vMark server"  # Add this line
}

# Create a custom completer that extends NestedCompleter but handles parameter sequences better
class VMarkCompleter(Completer):
    def __init__(self, command_tree, description_tree):
        self.command_tree = command_tree
        self.description_tree = description_tree
        # Define known parameter keywords across different commands
        self.param_commands = [
            # config interface/new-interface parameters
            "mtu", "speed", "status", "auto-nego", "duplex", "type",
            "cvlan-id", "svlan-id", "ipv4address", "netmask", "parent-interface",
            # twamp parameters
            "destination-ip", "port", "count", "interval", "padding", "ttl", "tos",
            "do-not-fragment",
            # register parameters
            "listen-ip", "port", "pin" # Added register parameters
        ]

    def get_available_interfaces(self):
        """Get list of available network interfaces using 'ip' command."""
        try:
            result = subprocess.run(
                ["ip", "-br", "link", "show"],
                capture_output=True,
                text=True,
                check=True
            )
            interfaces = []
            for line in result.stdout.splitlines():
                if_name = line.split()[0]
                # Basic filtering (can be adjusted)
                if (not if_name.startswith('lo') and
                    not if_name.startswith('vir') and
                    not if_name.startswith('docker') and
                    not if_name.startswith('br-') and # More specific bridge filter
                    not if_name.startswith('veth') and
                    not if_name.startswith('tun') and
                    not if_name.startswith('tap')):
                    interfaces.append(if_name)
            return interfaces
        except Exception:
            # Fallback or log error if needed
            return []

    def get_description(self, desc_node, key):
        """Helper to safely get description text."""
        if isinstance(desc_node, dict) and key in desc_node:
            entry = desc_node[key]
            if isinstance(entry, dict):
                # Prefer the "" key for the main description
                return entry.get("", "")
            elif isinstance(entry, str):
                # Handle cases where the description is just a string
                return entry
        return "" # Return empty string if no description found

    def create_completion(self, text, partial="", display=None, display_meta=""):
        """Helper to create consistent completions, replacing the partial word."""
        # Use -len(partial) to ensure the typed part is replaced
        return Completion(
            text, # The full word to complete with
            start_position=-len(partial),
            display=display if display is not None else text,
            display_meta=str(display_meta) # Ensure meta is string
        )

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        parts = text.strip().split()
        is_completing_command = text.endswith(' ') # True if the last char is a space

        # --- 1. Top Level Completion ---
        # ... (no changes needed here) ...
        if not parts or (len(parts) == 1 and not is_completing_command):
            partial = parts[0] if parts else ""
            for key in self.command_tree.keys():
                if key.startswith(partial):
                    yield self.create_completion(
                        key,
                        partial,
                        display_meta=command_descriptions.get(key, "")
                    )
            return

        # --- 2. Context Detection & Parameter Tracking ---
        current_command = parts[0]
        used_params = set()
        context = None
        param_level_subtree = None
        param_level_descsubtree = None
        start_index_for_params = 0





        # Determine context and parameter start index
        if current_command == "config":
            if len(parts) >= 2 and parts[1] == "new-interface":
                context = 'config_new_if'
                start_index_for_params = 3 # After config new-interface <name>
                if len(parts) >= start_index_for_params:
                    param_level_subtree = self.command_tree.get("config", {}).get("new-interface", {}).get("<ifname>", {})
                    param_level_descsubtree = self.description_tree.get("config", {}).get("new-interface", {}).get("<ifname>", {})
            elif len(parts) >= 2 and parts[1] == "interface":
                 context = 'config_if'
                 start_index_for_params = 3 # After config interface <name>
                 if len(parts) >= start_index_for_params:
                     param_level_subtree = self.command_tree.get("config", {}).get("interface", {}).get("<ifname>", {})
                     param_level_descsubtree = self.description_tree.get("config", {}).get("interface", {}).get("<ifname>", {})

        elif current_command == "twamp":
            if len(parts) >= 3: # Need twamp <ipver> <mode>
                ip_ver = parts[1] if len(parts) > 1 else None
                mode = parts[2] if len(parts) > 2 else None
                if ip_ver in ["ipv4", "ipv6"] and mode in ["sender", "responder"]:
                    context = f'twamp_{mode}'
                    start_index_for_params = 3
                    param_level_subtree = self.command_tree.get("twamp", {}).get(ip_ver, {}).get(mode, {})
                    param_level_descsubtree = self.description_tree.get("twamp", {}).get(ip_ver, {}).get(mode, {})

        elif current_command == "register": # Added register context
             if len(parts) >= 3 and parts[1] == "vmark" and parts[2] == "link-api":
                 context = 'register_link_api'
                 start_index_for_params = 3 # After register vmark link-api
                 param_level_subtree = self.command_tree.get("register", {}).get("vmark", {}).get("link-api", {})
                 param_level_descsubtree = self.description_tree.get("register", {}).get("vmark", {}).get("link-api", {})

        # Scan for used parameters if in a parameter context
        if context and param_level_subtree:
            i = start_index_for_params
            while i < len(parts):
                current_part = parts[i]
                # Check if it's a known parameter for the current context
                if current_part in param_level_subtree and current_part in self.param_commands:
                    used_params.add(current_part)
                    # Check if it's a flag (no value expected)
                    is_flag = current_part in ["pin", "do-not-fragment"] # Add other flags if any
                    if not is_flag:
                        if i + 1 < len(parts):
                            i += 2 # Skip parameter and its value
                        else:
                            # Parameter typed, but no value yet (or partial value)
                            i += 1
                            break # Stop scanning, user might be typing the value
                    else:
                        i += 1 # Skip flag parameter
                else:
                    # Not a parameter or value we track in this context, move on
                    # This could be a partially typed parameter or value
                    i += 1

        # --- 3. Navigate Tree & Generate Completions ---
        subtree = self.command_tree
        descsubtree = self.description_tree
        navigate_parts = parts if is_completing_command else parts[:-1]
        partial = "" if is_completing_command else parts[-1]
        reset_to_param_level = False # Flag to track if navigation reset

        for i, part in enumerate(navigate_parts):
            # ... (standard navigation logic) ...
            if not isinstance(subtree, dict): subtree = None; break
            if part in subtree:
                subtree = subtree[part]
                descsubtree = descsubtree.get(part, {}) if isinstance(descsubtree, dict) else {}
            # ... (dynamic interface name handling) ...
            elif i == 2 and context == 'config_if' and "<ifname>" in self.command_tree.get("config", {}).get("interface", {}):
                 subtree = self.command_tree["config"]["interface"]["<ifname>"]
                 descsubtree = self.description_tree["config"]["interface"]["<ifname>"]
            elif i == 2 and context == 'config_new_if' and "<ifname>" in self.command_tree.get("config", {}).get("new-interface", {}):
                 subtree = self.command_tree["config"]["new-interface"]["<ifname>"]
                 descsubtree = self.description_tree["config"]["new-interface"]["<ifname>"]
            # --- MODIFIED: Handle navigation after parameter value/flag ---
            elif i >= start_index_for_params and context and navigate_parts[i-1] in self.param_commands:
                 # Reset to parameter level for subsequent completions
                 subtree = param_level_subtree
                 descsubtree = param_level_descsubtree
                 reset_to_param_level = True # Set the flag
                 break # Stop navigation here
            else:
                subtree = None; break

        # --- 4. Determine Final Completions ---

        # Case A: Completing command after a parameter value/flag (space typed)
        # ... (no changes needed here, this part works) ...
        just_finished_param_value_or_flag = False
        if is_completing_command and context and len(navigate_parts) >= start_index_for_params:
             # ... (logic to set just_finished_param_value_or_flag) ...
             last_param_or_value = navigate_parts[-1]
             if len(navigate_parts) > start_index_for_params and navigate_parts[-2] in self.param_commands:
                  if navigate_parts[-2] in ["pin", "do-not-fragment"] or navigate_parts[-2] not in ["pin", "do-not-fragment"]:
                      just_finished_param_value_or_flag = True
             elif len(navigate_parts) == start_index_for_params and navigate_parts[-1] in ["pin", "do-not-fragment"]:
                  just_finished_param_value_or_flag = True

        if just_finished_param_value_or_flag and param_level_subtree:
            for key in param_level_subtree.keys():
                if key not in used_params and not key.startswith('_'):
                    desc = self.get_description(param_level_descsubtree, key)
                    yield self.create_completion(key, "", display_meta=desc)
            return

        # Case B: Standard completion OR Mid-word completion after parameter value/flag
        if isinstance(subtree, dict):
            # Special handling for dynamic interface names
            # ... (no changes needed here) ...
            if context == 'config_if' and len(navigate_parts) == 2:
                 interfaces = self.get_available_interfaces()
                 for if_name in interfaces:
                     if if_name.startswith(partial):
                         yield self.create_completion(if_name, partial, display_meta="Network Interface")
                 return
            elif context == 'config_new_if' and len(navigate_parts) == 3 and navigate_parts[2] == 'parent-interface':
                 interfaces = self.get_available_interfaces()
                 for if_name in interfaces:
                     if if_name.startswith(partial):
                         yield self.create_completion(if_name, partial, display_meta="Parent Interface")
                 return

            # General case: complete keys in the current subtree
            for key in subtree.keys():
                 # --- MODIFIED: Apply used_params filter if context was reset ---
                 if reset_to_param_level and key in used_params:
                     continue
                 # Skip internal keys
                 if key.startswith("_"):
                     continue

                 # Filter by partial word
                 if not partial or key.startswith(partial):
                     desc = self.get_description(descsubtree, key)
                     # Add hint for parameters expecting values
                     if key in self.param_commands and key not in ["pin", "do-not-fragment"]:
                         param_details = descsubtree.get(key, {})
                         options_hint = ""
                         if isinstance(param_details, dict):
                              options = param_details.get("_options")
                              if options: options_hint = f" ({options[0]})"
                         desc += options_hint

                     yield self.create_completion(key, partial, display_meta=desc)

# Build the command tree from the modules
def build_command_tree_and_descs():
    """Build command tree and descriptions from modules"""
    # Ensure all necessary modules are imported
    from cli.modules import show, config, system, twamp, register

    # Import tree and descriptions from each module
    command_tree = {
        "show": show.get_command_tree(),
        "config": config.get_command_tree(),
        "system": system.get_command_tree(),
        "twamp": twamp.get_command_tree(),
        "register": register.get_command_tree() # Added register
    }

    description_tree = {
        "show": show.get_descriptions(),         # Call get_descriptions()
        "config": config.get_descriptions(),       # Call get_descriptions()
        "system": system.get_descriptions(),       # Call get_descriptions()
        "twamp": twamp.get_descriptions(),        # Call get_descriptions()
        "register": register.get_descriptions()    # Already calling get_descriptions()
    }

    # Add top-level commands not covered by modules if needed
    # e.g., command_tree['exit'] = None; description_tree['exit'] = "Exit the CLI"

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
    VERSION = "0.3.6"  # Project version
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
def get_question_mark_help(text_before_question_mark, command_tree, description_tree, param_commands_list, command_descriptions_map):
    """Determines the help text for the '?' handler."""
    text = text_before_question_mark.strip()
    parts = text.split()
    is_partial_word = not text_before_question_mark.endswith(' ') and text
    partial = parts[-1] if is_partial_word else ""
    # Use all parts for context detection and param tracking
    context_parts = parts
    # Use parts before partial/space for navigation
    navigate_parts = parts if not is_partial_word else parts[:-1]

    current_node = command_tree
    current_desc_node = description_tree
    help_items = []
    used_params = set()
    context = None
    param_level_subtree = None
    param_level_descsubtree = None
    start_index_for_params = 0

    # --- 1. Handle Empty Input ---
    if not context_parts: # Check context_parts here
        for key in command_tree.keys():
            if not key.startswith('_'):
                # Filter by partial if present at top level
                if not partial or key.startswith(partial):
                    help_items.append({
                        'type': 'option',
                        'display': key,
                        'meta': command_descriptions_map.get(key, description_tree.get(key, {}).get("", ""))
                    })
        return help_items

    # --- 2. Determine Context & Parameter Tracking (using context_parts) ---
    current_command = context_parts[0] if context_parts else ""

    # Determine context, parameter start index, and parameter-level nodes
    if current_command == "config":
        if len(context_parts) >= 2 and context_parts[1] == "new-interface":
            context = 'config_new_if'
            start_index_for_params = 3
            param_level_subtree = command_tree.get("config", {}).get("new-interface", {}).get("<ifname>", {})
            param_level_descsubtree = description_tree.get("config", {}).get("new-interface", {}).get("<ifname>", {})
        elif len(context_parts) >= 2 and context_parts[1] == "interface":
             context = 'config_if'
             start_index_for_params = 3
             param_level_subtree = command_tree.get("config", {}).get("interface", {}).get("<ifname>", {})
             param_level_descsubtree = description_tree.get("config", {}).get("interface", {}).get("<ifname>", {})

    elif current_command == "twamp":
        if len(context_parts) >= 3:
            ip_ver = context_parts[1] if len(context_parts) > 1 else None
            mode = context_parts[2] if len(context_parts) > 2 else None
            if ip_ver in ["ipv4", "ipv6"] and mode in ["sender", "responder"]:
                context = f'twamp_{mode}'
                start_index_for_params = 3
                param_level_subtree = command_tree.get("twamp", {}).get(ip_ver, {}).get(mode, {})
                param_level_descsubtree = description_tree.get("twamp", {}).get(ip_ver, {}).get(mode, {})

    elif current_command == "register": # Added register context
         if len(context_parts) >= 3 and context_parts[1] == "vmark" and context_parts[2] == "link-api":
             context = 'register_link_api'
             start_index_for_params = 3
             param_level_subtree = command_tree.get("register", {}).get("vmark", {}).get("link-api", {})
             param_level_descsubtree = description_tree.get("register", {}).get("vmark", {}).get("link-api", {})

    # Scan for used parameters based on *all* context parts
    if context and param_level_subtree:
        i = start_index_for_params
        while i < len(context_parts):
            current_part = context_parts[i]
            if current_part in param_level_subtree and current_part in param_commands_list:
                used_params.add(current_part)
                is_flag = current_part in ["pin", "do-not-fragment"]
                if not is_flag:
                    if i + 1 < len(context_parts):
                        i += 2 # Skip parameter and its value
                    else:
                        i += 1 # Incomplete pair
                        break
                else:
                    i += 1 # Skip flag parameter
            else:
                i += 1

    # --- 3. Navigate Tree (using navigate_parts) ---
    final_nav_node = command_tree
    final_nav_desc_node = description_tree
    reset_to_param_level = False

    for i, part in enumerate(navigate_parts):
        if not isinstance(final_nav_node, dict):
            final_nav_node = None # Invalid path
            break

        if part in final_nav_node:
            final_nav_node = final_nav_node[part]
            final_nav_desc_node = final_nav_desc_node.get(part, {}) if isinstance(final_nav_desc_node, dict) else {}
        # Handle dynamic interface names during navigation
        elif i == 2 and context == 'config_if' and "<ifname>" in command_tree.get("config", {}).get("interface", {}):
             final_nav_node = command_tree["config"]["interface"]["<ifname>"]
             final_nav_desc_node = description_tree["config"]["interface"]["<ifname>"]
        elif i == 2 and context == 'config_new_if' and "<ifname>" in command_tree.get("config", {}).get("new-interface", {}):
             final_nav_node = command_tree["config"]["new-interface"]["<ifname>"]
             final_nav_desc_node = description_tree["config"]["new-interface"]["<ifname>"]
        # Check if we just navigated past a parameter value or flag
        elif i >= start_index_for_params and context and navigate_parts[i-1] in param_commands_list:
             # We are after a parameter value/flag. Reset to parameter level for next suggestions.
             final_nav_node = param_level_subtree
             final_nav_desc_node = param_level_descsubtree
             reset_to_param_level = True # Mark that we reset
             break # Stop navigation here, we want options at the parameter level
        else:
            final_nav_node = None # Invalid path element
            break

    # --- 4. Generate Help Items ---

    # Determine if the last *full* part entered was a parameter value or flag
    # This helps decide if we should show remaining params even if typing partially
    last_full_part_was_value_or_flag = False
    if context and len(navigate_parts) >= start_index_for_params:
        last_nav_part = navigate_parts[-1]
        # Check if the second to last part was a parameter
        if len(navigate_parts) > start_index_for_params and navigate_parts[-2] in param_commands_list:
             # If it was a flag, or if it wasn't a flag (implying a value was just entered)
             if navigate_parts[-2] in ["pin", "do-not-fragment"] or navigate_parts[-2] not in ["pin", "do-not-fragment"]:
                 last_full_part_was_value_or_flag = True
        # Handle case where only a flag was typed
        elif len(navigate_parts) == start_index_for_params and navigate_parts[-1] in ["pin", "do-not-fragment"]:
             last_full_part_was_value_or_flag = True

    # If we reset to param level OR the last full part was a value/flag, use param_level_subtree
    current_node_for_help = final_nav_node
    current_desc_node_for_help = final_nav_desc_node
    use_param_filtering = False

    if reset_to_param_level or last_full_part_was_value_or_flag:
         if param_level_subtree:
             current_node_for_help = param_level_subtree
             current_desc_node_for_help = param_level_descsubtree
             use_param_filtering = True # Apply used_params filter

    # Generate help from the determined node
    if isinstance(current_node_for_help, dict):
        # Special handling for dynamic interface names if appropriate
        if context == 'config_if' and len(navigate_parts) == 2: # Right after 'config interface'
             temp_completer = VMarkCompleter(command_tree, description_tree)
             interfaces = temp_completer.get_available_interfaces()
             for if_name in interfaces:
                 if if_name.startswith(partial):
                     help_items.append({'type': 'option', 'display': if_name, 'meta': "Network Interface"})
             return help_items
        elif context == 'config_new_if' and len(navigate_parts) == 3 and navigate_parts[2] == 'parent-interface': # After 'parent-interface' param name
             temp_completer = VMarkCompleter(command_tree, description_tree)
             interfaces = temp_completer.get_available_interfaces()
             for if_name in interfaces:
                 if if_name.startswith(partial):
                     help_items.append({'type': 'option', 'display': if_name, 'meta': "Parent Interface"})
             return help_items

        # General case: Iterate through keys
        for key in current_node_for_help.keys():
            # Skip internal keys
            if key.startswith('_'):
                continue
            # Apply used_params filter if required
            if use_param_filtering and key in used_params:
                continue

            # Filter based on partial word
            if not partial or key.startswith(partial):
                # Get description
                desc = ""
                if isinstance(current_desc_node_for_help, dict) and key in current_desc_node_for_help:
                    entry = current_desc_node_for_help[key]
                    if isinstance(entry, dict):
                        desc = entry.get("", "") # Prefer "" key
                        options = entry.get("_options")
                        if options:
                            desc += f" ({options[0]})"
                    elif isinstance(entry, str):
                        desc = entry

                help_items.append({'type': 'option', 'display': key, 'meta': desc})

    return help_items

def start_cli():
    command_tree, description_tree = build_command_tree_and_descs()
    # Get the list of known parameter commands (needed for the helper)
    temp_completer_for_params = VMarkCompleter(command_tree, description_tree)
    param_commands_list = temp_completer_for_params.param_commands
    # Make sure the global command_descriptions map is accessible
    global command_descriptions

    # Create key bindings
    bindings = KeyBindings()

    @bindings.add('?')
    def _(event):
        buffer = event.app.current_buffer
        original_text = buffer.text
        text_before_question_mark = original_text.rstrip('?') # Corrected rstrip

        # --- Get Help Items ---
        try:
            help_items = get_question_mark_help(
                text_before_question_mark,
                command_tree,
                description_tree,
                param_commands_list,
                command_descriptions # Pass the map here
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
            # Check if the first item indicates a format hint (adjust if needed)
            is_format_hint = False # Default
            if help_items[0].get('type') == 'format': # Safer check
                 is_format_hint = True

            output_fragments.append(('', "\n")) # Blank line before help

            if is_format_hint:
                item = help_items[0]
                output_fragments.append(('', f"Help for '{item.get('param', '')}']:\n")) # Safer get
                output_fragments.append(('', f"  Format: {item.get('hint', '')}\n"))
                if item.get('meta'):
                     output_fragments.append(('', f"  Description: {item['meta']}\n"))
            else:
                output_fragments.append(('', "Possible completions:\n"))
                # Find max display length for alignment
                max_len = 0
                for item in help_items:
                    if item.get('type') == 'option':
                        max_len = max(max_len, len(item.get('display', '')))

                for item in help_items:
                    if item.get('type') == 'option':
                        display_text = item.get('display', '')
                        meta_text = str(item.get('meta', ''))
                        # Simple alignment
                        output_fragments.append(('', f"  {display_text:<{max_len + 2}} {meta_text}\n"))
        else:
            output_fragments.append(('', "\n")) # Blank line before message
            # Use text_before_question_mark.strip() for a cleaner message
            output_fragments.append(('', f"No further options available for: '{text_before_question_mark.strip()}'\n"))

        # Add a final blank line for spacing before the prompt redraws
        output_fragments.append(('', "\n"))

        # --- Print all collected text above the prompt ---
        print_formatted_text(FormattedText(output_fragments), end='')

        # --- Restore buffer ---
        # Restore text *before* the '?' without adding extra space automatically
        buffer.text = text_before_question_mark
        buffer.cursor_position = len(buffer.text)

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