import logging
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import print_formatted_text
from cli.dispatcher import dispatch
from cli.modules import show, config, system, twamp, register, xdp_mef_switch 
from cli.modules.config import handle
from .modules.register import initialize_api_on_startup
import subprocess
import os
import getpass
import platform
from pyroute2 import IPRoute
from pathlib import Path
from plugins.xdp_mef_switch.forwarding_table import load_rules, rebuild_forwarding_map
from plugins.xdp_mef_switch.map_utils import get_network_interfaces, get_bpf_map_path_if_exists, dump_bpf_map_keys, pack_key, get_interface_index
from plugins.xdp_mef_switch.xdp_loader import run_with_sudo
from plugins.xdp_mef_switch.xdp_loader import ensure_xdp_program_attached
from cli.utils import get_dynamic_interfaces

# Add to command_descriptions dictionary
command_descriptions = {
    "show": "Show system-related information",
    "config": "Configure system settings",
    "system": "Perform system operations",
    "twamp": "TWAMP testing commands",
    "register": "Register with vMark server",
    "xdp-switch": "Manage eBPF forwarding table",
}

def ensure_bpffs_mounted():
    """Checks if bpffs is mounted and mounts it if not."""
    logger = logging.getLogger('ebpf')
    mount_point = "/sys/fs/bpf"
    try:
        # Check if already mounted
        with open('/proc/mounts', 'r') as f:
            for line in f:
                if mount_point in line and 'bpf' in line:
                    logger.info(f"bpffs already mounted at {mount_point}")
                    return True

        # If not mounted, try to mount it
        logger.info(f"bpffs not mounted. Attempting to mount at {mount_point}...")
        if not os.path.exists(mount_point):
            try:
                os.makedirs(mount_point, exist_ok=True)
                logger.info(f"Created directory {mount_point}")
            except OSError as e:
                logger.error(f"Error creating directory {mount_point}: {e}")
                return False
        
        # Try to mount
        try:
            subprocess.run(["sudo", "mount", "-t", "bpf", "bpf", mount_point], 
                         check=True, capture_output=True, text=True)
            logger.info(f"Successfully mounted bpffs at {mount_point}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error mounting bpffs: {e.stderr.strip()}")
            return False
        except FileNotFoundError:
            logger.error(f"'mount' command not found")
            return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while checking/mounting bpffs: {e}")
        return False

class VMarkCompleter(Completer):
    def __init__(self, command_tree, description_tree):
        self.command_tree = command_tree
        self.description_tree = description_tree
        # No need for self.dynamic_options here if _options are in description_tree
        # self.dynamic_options = {
        #     "<in_interface>": get_network_interfaces,
        #     "<out_interface>": get_network_interfaces,
        # }

    def get_description(self, desc_node, key):
        """Helper to safely get description text from the description tree."""
        if isinstance(desc_node, dict):
            # Direct description for the key itself
            if "" in desc_node and key in desc_node: # Check if key itself has a description object
                desc_entry = desc_node[key]
                if isinstance(desc_entry, dict) and "" in desc_entry:
                    return desc_entry[""]
                elif isinstance(desc_entry, str): # Should not happen if "" is for description object
                    return desc_entry 
            # Description for the current level (e.g. help for "create-rule" itself)
            elif key == "" and "" in desc_node:
                 return desc_node[""]
        return "" # No description found

    def create_completion(self, text, partial="", display=None, display_meta=""):
        """Helper to create Completion objects."""
        if display is None:
            display = text
        return Completion(
            text,
            start_position=-len(partial),
            display=display,
            display_meta=FormattedText([("class:completion-meta", display_meta)]) if display_meta else None,
        )

    def get_completions(self, document, complete_event):
        text_before_cursor = document.text_before_cursor
        words = text_before_cursor.split()

        completing_word = ""
        current_path_words = words
        if text_before_cursor and not text_before_cursor.endswith(" "):
            completing_word = words[-1]
            current_path_words = words[:-1]

        current_command_node = self.command_tree
        current_desc_node = self.description_tree
        
        path_processed_placeholders = 0

        for i, word in enumerate(current_path_words):
            if isinstance(current_command_node, dict) and word in current_command_node:
                current_command_node = current_command_node[word]
                current_desc_node = current_desc_node.get(word, {})
            elif isinstance(current_command_node, dict):
                placeholder = get_placeholder_key(current_command_node)
                if placeholder:
                    # Consumimos una palabra como valor para el placeholder
                    current_command_node = current_command_node[placeholder]
                    current_desc_node = current_desc_node.get(placeholder, {})
                    path_processed_placeholders +=1
                else:
                    return # Palabra no reconocida y no es un placeholder
            else:
                return # Camino inválido

        # Generar completaciones para el nodo actual
        if isinstance(current_command_node, dict):
            for key_option in current_command_node.keys():
                if key_option.startswith("<") and key_option.endswith(">"):
                    param_desc_node = current_desc_node.get(key_option, {})
                    options_list = param_desc_node.get("_options")

                    if key_option in ["<in_interface>", "<out_interface>", "<parent-interface>"] and not options_list:
                        options_list = get_dynamic_interfaces()

                    if options_list:
                        for opt_val in options_list:
                            if isinstance(opt_val, str) and opt_val.startswith(completing_word):
                                meta_desc = param_desc_node.get("", f"Value for {key_option}")
                                yield self.create_completion(opt_val, partial=completing_word, display_meta=meta_desc)
                    # else: No hay _options, no se sugieren valores específicos para este placeholder con Tab
                elif key_option.startswith(completing_word): # Standard command/option
                    description = self.get_description(current_desc_node, key_option) # Usa el helper mejorado
                    yield self.create_completion(key_option, partial=completing_word, display_meta=description)
# Build the command tree from the modules
def build_command_tree_and_descs():
    """Build command tree and descriptions from modules"""
    # Ensure all necessary modules are imported
    from cli.modules import show, config, system, twamp, register, xdp_mef_switch

    # Import tree and descriptions from each module
    command_tree = {
        "show": show.get_command_tree(),
        "config": config.get_command_tree(),
        "system": system.get_command_tree(),
        "twamp": twamp.get_command_tree(),
        "register": register.get_command_tree(), # Added register
        "xdp-switch": xdp_mef_switch.get_command_tree() # Call new function
    }

    description_tree = {
        "show": show.get_descriptions(),         # Call get_descriptions()
        "config": config.get_descriptions(),       # Call get_descriptions()
        "system": system.get_descriptions(),       # Call get_descriptions()
        "twamp": twamp.get_descriptions(),        # Call get_descriptions()
        "register": register.get_descriptions(),    # Already calling get_descriptions()
        "xdp-switch": xdp_mef_switch.get_descriptions() # Call new function
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
    VERSION = "0.3.9"  # Project version
    print(f"vMark-node version: {VERSION}")

# Additional feature: Display hardware and OS information
def af_info():
    print("\n  -- System Information --")
    print(f"OS: {platform.system()}")
    print(f"OS Release: {platform.release()}")
    print(f"Hostname: {platform.node()}")
    print(f"Architecture: {platform.processor()}")
    print("\n")

# Add this helper function before get_question_mark_help
def get_description_helper(desc_node, key):
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

# Helper to find a placeholder key (e.g., <name-of-mef-service>)
def get_placeholder_key(node):
    if isinstance(node, dict):
        for k in node.keys():
            # Ensure k is a string before calling startswith/endswith
            if isinstance(k, str) and k.startswith('<') and k.endswith('>'):
                return k
    return None

def get_question_mark_help(text_before_question_mark, command_tree, description_tree, command_descriptions_map):
    text = text_before_question_mark.strip()
    context_parts = text.split()
    
    current_command_node = command_tree
    current_desc_node = description_tree
    help_items = []

    for word in context_parts:
        if isinstance(current_command_node, dict) and word in current_command_node:
            current_command_node = current_command_node[word]
            current_desc_node = current_desc_node.get(word, {})
        elif isinstance(current_command_node, dict):
            placeholder = get_placeholder_key(current_command_node)
            if placeholder:
                # Se ha ingresado un valor para el placeholder, avanzar al siguiente nivel de estructura
                current_command_node = current_command_node[placeholder]
                current_desc_node = current_desc_node.get(placeholder, {})
            else:
                # No es un comando conocido ni un placeholder esperado en este punto
                help_items.append({'type': 'error', 'display': f"Unknown command or parameter: '{word}'", 'meta': ''})
                return help_items # Detener si hay un error
        else:
            # Se esperaba un diccionario (más comandos/parámetros) pero no se encontró
            help_items.append({'type': 'info', 'display': f"No further specific options available after '{word}'", 'meta': ''})
            return help_items

    # Si llegamos aquí, current_command_node y current_desc_node apuntan al nivel correcto
    # para el cual queremos mostrar ayuda.

    if isinstance(current_command_node, dict) and current_command_node:
        # Primero, verificar si hay una descripción general para el comando actual
        general_desc_for_current_level = current_desc_node.get("", "")
        if general_desc_for_current_level:
             help_items.append({'type': 'header', 'display': general_desc_for_current_level, 'meta': ''})


        for key_option in sorted(current_command_node.keys()): # Ordenar para consistencia
            if key_option == "_options": # No mostrar _options directamente
                continue

            desc_entry_for_key = current_desc_node.get(key_option, {})
            meta_text = ""
            if isinstance(desc_entry_for_key, dict):
                meta_text = desc_entry_for_key.get("", f"Option {key_option}")
            elif isinstance(desc_entry_for_key, str): # Menos común, pero posible
                meta_text = desc_entry_for_key
            
            display_text = key_option

            if key_option.startswith("<") and key_option.endswith(">"):
                # Es un placeholder, como <name> o <in_interface>
                help_items.append({'type': 'parameter', 'display': display_text, 'meta': meta_text})
                
                # Si el placeholder tiene _options, listarlas
                options_list = desc_entry_for_key.get("_options")
                if key_option in ["<in_interface>", "<out_interface>", "<parent-interface>"] and not options_list:
                    options_list = get_dynamic_interfaces() # Cargar dinámicas si no hay explícitas

                if options_list:
                    help_items.append({'type': 'subheader', 'display': "  Possible values:", 'meta': ''})
                    for opt_val in options_list:
                        help_items.append({'type': 'value_suggestion', 'display': f"    {opt_val}", 'meta': ''}) # Indentar valores
            else:
                # Es un subcomando o una opción fija
                help_items.append({'type': 'option', 'display': display_text, 'meta': meta_text})
    
    if not help_items and text_before_question_mark: # Si después de todo no hay items y se escribió algo
         help_items.append({'type': 'info', 'display': f"No further specific options available for: '{text_before_question_mark.strip()}'", 'meta': ''})
    elif not help_items and not text_before_question_mark: # Si no hay nada escrito y no hay opciones (comando raíz vacío)
         help_items.append({'type': 'info', 'display': "Type a command. Use Tab for completion.", 'meta': ''})


    return help_items
def set_promisc_mode(interface, enable=True):
    import subprocess
    mode = "on" if enable else "off"
    try:
        subprocess.run(["sudo", "ip", "link", "set", interface, "promisc", mode], check=True)
    except Exception as e:
        print(f"Failed to set promisc {mode} on {interface}: {e}")

def restore_active_xdp_rules():
    ebpf_logger = setup_ebpf_logging()
    ebpf_logger.info("Checking if restoration needed for active XDP rules...")
    rules = load_rules()
    for rule in rules:
        if not rule.get("active"):
            continue
        in_if = rule.get("in_interface")
        match_cvlan = rule.get("match_cvlan")
        match_svlan = rule.get("match_svlan")
        if not in_if:
            continue
        if_idx = get_interface_index(in_if)
        if if_idx is None:
            continue
        key_bytes = pack_key(if_idx, match_cvlan, match_svlan)
        map_pin_path = get_bpf_map_path_if_exists(in_if)
        if not map_pin_path:
            ebpf_logger.info(f"BPF map for {in_if} not found. Attempting to re-attach XDP program and create map.")
            # Aquí deberías pasar el path al objeto .o de tu XDP program
            xdp_obj_path = Path(__file__).parent.parent / "plugins" / "xdp_mef_switch" / "xdp_forwarding.o"
            if ensure_xdp_program_attached(in_if, xdp_obj_path):
                map_pin_path = get_bpf_map_path_if_exists(in_if)
            else:
                ebpf_logger.error(f"Failed to attach XDP program to {in_if}, cannot restore rule.")
                continue
        if map_pin_path:
            keys_in_map = dump_bpf_map_keys(map_pin_path)
            if key_bytes not in keys_in_map:
                try:
                    ebpf_logger.info("Restoring missing XDP rule...")
                    rebuild_forwarding_map(map_pin_path)
                    ebpf_logger.info(f"Restored missing XDP rule for {in_if} (cvlan={match_cvlan}, svlan={match_svlan})")
                except Exception as e:
                    ebpf_logger.info(f"Failed to restore rule for {in_if}: {e}")
        else:
            ebpf_logger.info(f"No restoration possible for {in_if} (cvlan={match_cvlan}, svlan={match_svlan})")
        set_promisc_mode(in_if, enable=True)

def start_cli():
    """Initialize and start the command-line interface."""
    restore_active_xdp_rules()
    ebpf_logger = setup_ebpf_logging()
    ebpf_logger.info("CLI Starting - Testing log file creation")

    if ensure_bpffs_mounted():
        ebpf_logger.info("BPF filesystem mounted successfully")
    else:
        ebpf_logger.error("Failed to mount BPF filesystem. Some XDP/BPF operations may fail.")

    initialize_api_on_startup() 

    command_tree, description_tree = build_command_tree_and_descs()
    global command_descriptions

    bindings = KeyBindings()

    @bindings.add('?')
    def _(event):
        buffer = event.app.current_buffer
        original_text = buffer.text
        text_before_question_mark = original_text.rstrip('?')

        # --- Get Help Items ---
        try:
            help_items = get_question_mark_help(
                text_before_question_mark,
                command_tree,
                description_tree,
                command_descriptions # Pass the map here
            )
        except Exception as e:
            print_formatted_text(FormattedText([('fg:red', f"\nError getting help items: {e}\n")]))
            help_items = []

        # --- Prepare FormattedText fragments for ALL output ---
        output_fragments = []

        # 1. The prompt line + '?'
        prompt_string = f"{getpass.getuser()}/{os.uname().nodename}@vMark-node> "
        output_fragments.append(('', f"{prompt_string}{text_before_question_mark} ?\n"))

        # 2. Help content (with spacing)
        if help_items:
            output_fragments.append(('', "\n")) # Blank line before help

            # --- REVISED HELP FORMATTING ---
            # Find max display length for alignment among 'option' and 'value_suggestion' types
            max_len = 0
            # has_options = False # This flag is no longer needed for adding the header here
            for item in help_items:
                if isinstance(item, dict) and item.get('type') in ['option', 'value_suggestion']:
                    max_len = max(max_len, len(item.get('display', '')))
                    # if item.get('type') == 'option':
                        # has_options = True

            # REMOVE/COMMENT OUT THE DUPLICATE HEADER ADDITION:
            # # Add standard header if only options are present
            # if has_options and isinstance(help_items[0], dict) and help_items[0].get('type') == 'option':
            #      output_fragments.append(('', "Possible completions:\n"))
            # The get_question_mark_help function is now responsible for adding this header.

            # Iterate and format each item
            for item in help_items:
                if isinstance(item, dict):
                    item_type = item.get('type')
                    display_text = item.get('display', '')
                    meta_text = str(item.get('meta', ''))
                    text_content = item.get('text', '') # For headers

                    if item_type == 'option':
                        output_fragments.append(('', f"  {display_text:<{max_len + 2}} {meta_text}\n"))
                    elif item_type == 'header':
                        # Headers from get_question_mark_help already include newlines where intended
                        output_fragments.append(('', f"{text_content}")) 
                    elif item_type == 'value_hint':
                        output_fragments.append(('', f"  Format: {display_text}\n"))
                        if meta_text:
                            output_fragments.append(('', f"  Description: {meta_text}\n"))
                    elif item_type == 'value_suggestion':
                        output_fragments.append(('', f"  {display_text:<{max_len + 2}} {meta_text}\n"))
        else:
            output_fragments.append(('', "\n")) # Blank line before message
            output_fragments.append(('', f"No further options available for: '{text_before_question_mark.strip()}'\n"))

        # Add a final blank line for spacing before the prompt redraws
        output_fragments.append(('', "\n"))

        # --- Print all collected text above the prompt ---
        print_formatted_text(FormattedText(output_fragments), end='')

        # --- Restore buffer ---
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

            # --- Add this block to detect rule changes and refresh completer ---
            should_refresh_completer = False
            if cmd.startswith('xdp-switch '):
                subcmd = cmd.split()[1] if len(cmd.split()) > 1 else ""
                if subcmd in ("create-rule", "delete-rule", "enable-rule", "disable-rule"):
                    should_refresh_completer = True

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
                # Refresh completer after rule-changing commands
                if should_refresh_completer:
                    rebuild_completer()
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

def setup_ebpf_logging():
    """Get the eBPF logger."""
    return logging.getLogger('ebpf')

def check_bpf_state():
    """
    Chequea el estado real de los programas XDP y mapas BPF,
    y asegura que el JSON de reglas refleje el estado real del datapath.
    Nunca reactiva reglas desde el JSON, solo desactiva si ya no están en el mapa.
    """
    logger = logging.getLogger('ebpf')
    rules_modified = False
    try:
        logger.info("=== BPF State Check at Startup ===")
        from plugins.xdp_mef_switch.forwarding_table import save_rules
        rules = load_rules()
        logger.info(f"Loaded {len(rules)} rules from forwarding_table.json for consistency check.")

        # Validar y desactivar reglas activas que no estén en el mapa
        map_keys_cache = {}
        for i, rule in enumerate(rules):
            if not rule.get("active", False):
                continue
            in_if = rule.get("in_interface")
            match_cvlan = rule.get("match_cvlan")
            match_svlan = rule.get("match_svlan")
            if not in_if:
                logger.error(f"Rule '{rule.get('name', f'index {i}')}' active but missing in_interface. Disabling.")
                rules[i]["active"] = False
                rules_modified = True
                continue
            if_idx = get_interface_index(in_if)
            if if_idx is None:
                logger.warning(f"Rule '{rule.get('name', 'unnamed')}' (in_interface: {in_if}) active in JSON, but its interface index not found. Disabling.")
                rules[i]["active"] = False
                rules_modified = True
                continue
            key_bytes = pack_key(if_idx, match_cvlan, match_svlan)
            map_path = get_bpf_map_path_if_exists(in_if)
            if map_path:
                if map_path not in map_keys_cache:
                    map_keys_cache[map_path] = dump_bpf_map_keys(map_path)
                keys_in_map = map_keys_cache[map_path]
                if key_bytes not in keys_in_map:
                    logger.warning(f"Rule '{rule.get('name', 'unnamed')}' marked as active in JSON but not present in its BPF map (expected at {map_path}). Disabling.")
                    rules[i]["active"] = False
                    rules_modified = True
            else:
                logger.info(f"No BPF map found for interface {in_if} (or its parent). Rule '{rule.get('name', 'unnamed')}' cannot be active in datapath.")
                rules[i]["active"] = False
                rules_modified = True

        if rules_modified:
            save_rules(rules)
            logger.info("forwarding_table.json updated to reflect actual BPF state.")
        else:
            logger.info("No changes needed in forwarding_table.json based on BPF state check.")
        logger.info("=== End BPF State Check ===")
    except Exception as e:
        logger.error(f"Critical error during BPF state check: {e}", exc_info=True)
