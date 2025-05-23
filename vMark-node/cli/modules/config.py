from pyroute2 import IPDB
import subprocess
import re
import ipaddress  # Ensure this is imported once at the top
from cli.utils import get_dynamic_interfaces
import sys
import termios
import tty
from contextlib import contextmanager

# Define descriptions with proper _options for parameters
def get_descriptions():
    """Return the description dictionary."""
    interfaces = get_dynamic_interfaces()  # Obtener interfaces dinámicamente

    desc = {
        "interface": {
            "": "Configure network interfaces",
            "<ifname>": {
                "": "Interface name",
                "_options": interfaces,  # Usar la variable correcta
                "mtu": {
                    "": "Set MTU size",
                    "_options": ["<1-10000>"],
                },
                "speed": {
                    "": "Set interface speed",
                    "_options": ["10M", "100M", "1G", "10G"],
                },
                "status": {
                    "": "Set interface status",
                    "_options": ["up", "down"],
                },
                "auto-nego": {
                    "": "Enable or disable auto-negotiation",
                    "_options": ["on", "off"],
                },
                "duplex": {
                    "": "Set duplex mode",
                    "_options": ["half", "full"],
                },
            }
        },
        "new-interface": {
            "": "Create a new interface",
            "<ifname>": {
                "": "New interface name",
                "parent-interface": {
                    "": "Parent interface name (REQUIRED)",
                    "_options": interfaces  # Agregar interfaces dinámicas
                },
                "cvlan-id": {
                    "": "Customer VLAN ID (C-TAG)",
                    "_options": ["<1-4000>"],
                },
                "svlan-id": {
                    "": "Service VLAN ID (S-TAG)",
                    "_options": ["<1-4000>"],
                },
                "mtu": {
                    "": "Set MTU size",
                    "_options": ["<1000-10000>"],
                },
                "status": {
                    "": "Set interface status",
                    "_options": ["up", "down"],
                },
                "ipv4address": {
                    "": "Set IPv4 address (REQUIRED)",
                    "_options": ["<x.x.x.x>"],
                },
                "netmask": {
                    "": "Set network mask (REQUIRED)",
                    "_options": ["</xx>", "<x.x.x.x>"],
                },
            }
        },
        "delete-interface": {
            "": "Delete a network interface",
            "<ifname>": {
                "": "Name of interface to delete",
                "_options": interfaces  # Usar la variable correcta
            }
        }
    }
    return desc

def get_command_tree():
    """Build and return command tree based on descriptions."""
    descriptions_data = get_descriptions()
    interfaces = get_dynamic_interfaces() # Asegurarse de tener las interfaces para _options

    def build_tree_from_desc(desc_node, current_path_for_options=None):
        tree_node = {}
        if not isinstance(desc_node, dict):
            return {} # O None, dependiendo de cómo se manejen las hojas

        for key, value_desc in desc_node.items():
            if key == "_options": # No incluir _options directamente en el command_tree
                continue
            if key == "": # La descripción general no es un comando
                continue

            if isinstance(value_desc, dict):
                # Si es un placeholder, el siguiente nivel es el contenido del placeholder
                if key.startswith("<") and key.endswith(">"):
                    # El command_tree para un placeholder es lo que sigue DESPUÉS de él.
                    # Lo que está DENTRO del placeholder en descriptions es la estructura de sus parámetros.
                    # Ejemplo: "<ifname>": { "parent-interface": ..., "cvlan-id": ... }
                    # El command_tree debe ser: "<ifname>": { lo que sigue a ifname }
                    
                    # Para los placeholders que esperan un valor (como <ifname>, <parent-interface>),
                    # el command_tree debe reflejar los siguientes parámetros *después* de que se provee el valor.
                    # La estructura de `_create_rule_structure` en xdp_mef_switch es un buen ejemplo.
                    # Aquí, el `value_desc` es el diccionario de parámetros que siguen al placeholder.
                    tree_node[key] = build_tree_from_desc(value_desc, current_path_for_options=key)

                else: # Es un subcomando normal
                    tree_node[key] = build_tree_from_desc(value_desc, current_path_for_options=key)
            else:
                # Es una hoja en descriptions (solo una cadena de descripción), en command_tree es un comando final.
                tree_node[key] = {} # O None si así se prefiere para comandos finales
        
        # Manejo especial para _options que definen valores aceptables para un placeholder
        # Esto es más para la ayuda contextual que para la estructura de comandos anidados.
        # Sin embargo, si un placeholder tiene opciones fijas (no otros comandos anidados),
        # se podrían listar aquí.
        if current_path_for_options and isinstance(desc_node.get("_options"), list):
            # Si el nodo actual (identificado por current_path_for_options) tiene _options,
            # y esas opciones son valores (no subcomandos), se pueden agregar.
            # Ejemplo: status: {"_options": ["up", "down"]} -> status: {"up":{}, "down":{}}
            options_for_placeholder = desc_node.get("_options")
            # Solo agregar si no son placeholders ellos mismos (como <1-4000>)
            # y si no son las interfaces dinámicas que ya se manejan.
            if all(not opt.startswith("<") for opt in options_for_placeholder if isinstance(opt, str)) \
               and options_for_placeholder != interfaces:
                for opt_val in options_for_placeholder:
                    if isinstance(opt_val, str): # Asegurar que es una cadena
                         tree_node[opt_val] = {}


        return tree_node

    # Construir el árbol principal
    final_tree = build_tree_from_desc(descriptions_data)
    
    # Ajuste específico para `config interface <ifname> status up/down` etc.
    # El `get_descriptions` ya tiene la estructura correcta para esto.
    # El `build_tree_from_desc` debería manejarlo.

    # Asegurar que los placeholders como <ifname> en `config interface <ifname>`
    # lleven a la estructura de sus subcomandos (mtu, speed, etc.)
    if "interface" in final_tree and "<ifname>" in final_tree["interface"]:
        # El contenido de final_tree["interface"]["<ifname>"] ya debería tener mtu, speed, etc.
        # debido a la recursión de build_tree_from_desc.
        pass # Ya debería estar correcto por la lógica recursiva.

    if "new-interface" in final_tree and "<ifname>" in final_tree["new-interface"]:
        # Similarmente, el contenido de final_tree["new-interface"]["<ifname>"]
        # debería tener parent-interface, cvlan-id, etc.
        pass


    # El command_tree para `delete-interface <ifname>` es solo `delete-interface: {"<ifname>": {}}`
    # porque después del nombre de la interfaz no hay más parámetros.
    if "delete-interface" in final_tree and "<ifname>" in final_tree["delete-interface"]:
        final_tree["delete-interface"]["<ifname>"] = {}


    return final_tree

def run_with_sudo(command):
    try:
        result = subprocess.run(
            ["sudo"] + command,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' or '?' for more information."

    if args[0] == "interface":
        if len(args) < 2:
            return f"{prompt}Please specify an interface name."
        ifname = args[1]
        if len(args) < 3:
            return f"{prompt}Incomplete command. Type 'help' or '?' for more information."
        action = args[2]

        if action == "duplex":
            if len(args) < 4:
                return f"{prompt}Please specify duplex mode (half/full)."
            duplex_mode = args[3].lower()
            if duplex_mode not in ["half", "full"]:
                return f"{prompt}Invalid duplex mode '{duplex_mode}'. Choose from: half, full."
            try:
                # Use ethtool to set the duplex mode
                result = run_with_sudo([
                    "ethtool", "-s", ifname, "duplex", duplex_mode, "autoneg", "off"
                ])
                if result[0]:
                    return f"{prompt}Duplex mode for {ifname} set to {duplex_mode}."
                else:
                    return f"{prompt}Error setting duplex mode: {result[1]}"
            except Exception as e:
                return f"{prompt}Error setting duplex mode: {e}"

        elif action == "auto-nego":
            if len(args) < 4:
                return f"{prompt}Please specify auto-negotiation state (on/off)."
            auto_nego = args[3].lower()
            if auto_nego not in ["on", "off"]:
                return f"{prompt}Invalid auto-negotiation state '{auto_nego}'. Choose from: on, off."
            try:
                # Check driver information
                driver_check = subprocess.run(
                    ["ethtool", "-i", ifname],
                    capture_output=True,
                    text=True,
                )
                if "e1000" in driver_check.stdout:
                    return f"{prompt}The e1000 driver does not support disabling auto-negotiation."

                # Attempt to set auto-negotiation
                result = run_with_sudo([
                    "ethtool", "-s", ifname, "autoneg", "on" if auto_nego == "on" else "off"
                ])
                if result[0]:
                    # Verify the change
                    verify_result = subprocess.run(
                        ["ethtool", ifname],
                        capture_output=True,
                        text=True,
                    )
                    if verify_result.returncode == 0:
                        # Parse the output to check the auto-negotiation state
                        for line in verify_result.stdout.splitlines():
                            if "Auto-negotiation" in line:
                                current_state = line.split(":")[1].strip().lower()
                                if current_state == auto_nego:
                                    return f"{prompt}Auto-negotiation for {ifname} set to {auto_nego}."
                                else:
                                    return f"{prompt}Failed to set auto-negotiation to {auto_nego}. Current state: {current_state}."
                    else:
                        return f"{prompt}Failed to verify auto-negotiation state. Please check manually."
                else:
                    return f"{prompt}Error setting auto-negotiation: {result[1]}"
            except Exception as e:
                return f"{prompt}Error setting auto-negotiation: {e}"

        elif action == "mtu":
            if len(args) < 4:
                return f"{prompt}Please specify an MTU value."
            mtu = args[3]
            success, output = run_with_sudo(["ip", "link", "set", "dev", ifname, "mtu", mtu])
            if success:
                return f"{prompt}MTU for {ifname} set to {mtu}."
            else:
                return f"{prompt}Error setting MTU: {output}"

        elif action == "speed":
            if len(args) < 4:
                return f"{prompt}Please specify a speed (10M/100M/1G/10G)."
            speed = args[3]
            speed_map = {
                "10M": "10",
                "100M": "100",
                "1G": "1000",
                "10G": "10000",
            }
            if speed not in speed_map:
                return f"{prompt}Invalid speed '{speed}'. Choose from: 10M, 100M, 1G, 10G."
            try:
                result = run_with_sudo([
                    "ethtool", "-s", ifname, "speed", speed_map[speed], "duplex", "full", "autoneg", "off"
                ])
                if result[0]:
                    return f"{prompt}Speed for {ifname} set to {speed}."
                else:
                    return f"{prompt}Error setting speed: {result[1]}"
            except Exception as e:
                return f"{prompt}Error setting speed: {e}"

        elif action == "status":
            if len(args) < 4:
                return f"{prompt}Please specify a status (up/down)."
            status = args[3]
            if status not in ["up", "down"]:
                return f"{prompt}Invalid status '{status}'. Choose from: up, down."
            success, output = run_with_sudo(["ip", "link", "set", "dev", ifname, status])
            if success:
                return f"{prompt}Status for {ifname} set to {status}."
            else:
                return f"{prompt}Error setting status: {output}"

        else:
            return f"{prompt}Unknown action '{action}' for interface."

    elif args[0] == "new-interface":
        if len(args) < 2:
            return f"{prompt}Please specify a name for the new interface."
        
        ifname = args[1]
        
        # Initialize parameters with default values
        params = {
            "parent_if": None,
            "cvlan_id": None,
            "svlan_id": None,
            "mtu": None,
            "status": "up",  # Default to up
            "ipv4address": None,
            "netmask": None
        }
        
        # Parse all arguments to collect parameters
        i = 2
        while i < len(args):
            param = args[i]
            
            if param == "parent-interface" and i + 1 < len(args):
                parent_if = args[i + 1]
                # Validate parent interface exists
                try:
                    subprocess.run(
                        ["ip", "link", "show", parent_if],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    params["parent_if"] = parent_if
                except subprocess.CalledProcessError:
                    return f"{prompt}Parent interface '{parent_if}' does not exist."
                i += 2
            
            elif param == "cvlan-id" and i + 1 < len(args):
                vlan_id = args[i + 1]
                try:
                    vlan_id_int = int(vlan_id)
                    if 1 <= vlan_id_int <= 4000:
                        params["cvlan_id"] = vlan_id
                    else:
                        return f"{prompt}Invalid VLAN ID '{vlan_id}'. Must be between 1 and 4000."
                except ValueError:
                    return f"{prompt}Invalid VLAN ID '{vlan_id}'. Must be an integer."
                i += 2
                
            elif param == "svlan-id" and i + 1 < len(args):
                vlan_id = args[i + 1]
                try:
                    vlan_id_int = int(vlan_id)
                    if 1 <= vlan_id_int <= 4000:
                        params["svlan_id"] = vlan_id
                    else:
                        return f"{prompt}Invalid VLAN ID '{vlan_id}'. Must be between 1 and 4000."
                except ValueError:
                    return f"{prompt}Invalid VLAN ID '{vlan_id}'. Must be an integer."
                i += 2
                
            elif param == "mtu" and i + 1 < len(args):
                mtu = args[i + 1]
                try:
                    mtu_int = int(mtu)
                    if 1000 <= mtu_int <= 10000:
                        params["mtu"] = mtu
                    else:
                        return f"{prompt}Invalid MTU '{mtu}'. Must be between 1000 and 10000."
                except ValueError:
                    return f"{prompt}Invalid MTU '{mtu}'. Must be an integer."
                i += 2
                
            elif param == "status" and i + 1 < len(args):
                status = args[i + 1].lower()
                if status in ["up", "down"]:
                    params["status"] = status
                else:
                    return f"{prompt}Invalid status '{status}'. Choose from: up, down."
                i += 2
                
            elif param == "ipv4address" and i + 1 < len(args):
                ip_address = args[i + 1]
                try:
                    # Validate IP address format
                    ipaddress.IPv4Address(ip_address)
                    params["ipv4address"] = ip_address
                except ValueError:
                    return f"{prompt}Invalid IPv4 address '{ip_address}'."
                i += 2
                
            elif param == "netmask" and i + 1 < len(args):
                netmask = args[i + 1]
                # Check for CIDR format like /24
                if netmask.startswith('/'):
                    try:
                        prefix_len = int(netmask[1:])
                        if 0 <= prefix_len <= 32:
                            params["netmask"] = netmask
                        else:
                            return f"{prompt}Invalid CIDR prefix '{netmask}'. Must be between /0 and /32."
                    except ValueError:
                        return f"{prompt}Invalid CIDR prefix '{netmask}'."
                else:
                    # Check for dotted decimal format like 255.255.255.0
                    try:
                        # Validate netmask format using proper approach
                        parts = netmask.split('.')
                        if len(parts) != 4:
                            return f"{prompt}Invalid netmask format. Must be four octets (x.x.x.x)."
                        
                        # Convert to binary and check for contiguity
                        binary = ''.join([bin(int(p))[2:].zfill(8) for p in parts])
                        if '01' in binary:  # Valid netmasks don't have 1s after 0s
                            return f"{prompt}Invalid netmask '{netmask}'. Not a valid subnet mask pattern."
                        
                        # If we get here, it's a valid netmask
                        params["netmask"] = netmask
                    except ValueError:
                        return f"{prompt}Invalid netmask '{netmask}'. Must contain numbers 0-255."
                i += 2
                
            else:
                return f"{prompt}Unknown parameter '{param}' or missing value."
        
        # Check for all required parameters
        missing_params = []
        if not params["parent_if"]:
            missing_params.append("parent-interface")
        if not params["ipv4address"]:
            missing_params.append("ipv4address")
        if not params["netmask"]:
            missing_params.append("netmask")
            
        if missing_params:
            return f"{prompt}Missing required parameters: {', '.join(missing_params)}"
        
        # Find a parent interface if not specified
        if not params["parent_if"]:
            try:
                # Get all network interfaces
                ip_link_output = subprocess.run(
                    ["ip", "-o", "link", "show"],
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout
                
                # Parse output to find physical interfaces
                for line in ip_link_output.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        # Extract interface name without number
                        if_name = parts[1].split(':')[0]
                        # Skip loopback, virtual, and already used interfaces
                        if (not if_name.startswith('lo') and 
                            not if_name.startswith('vir') and 
                            not if_name.startswith('docker') and
                            not if_name.startswith('br') and
                            not if_name.startswith('tun') and
                            not if_name.startswith('tap') and
                            not if_name.startswith('veth')):
                            # Check if it's up
                            state_check = subprocess.run(
                                ["ip", "link", "show", if_name],
                                capture_output=True,
                                text=True
                            )
                            if "state UP" in state_check.stdout:
                                params["parent_if"] = if_name
                                break
                
                # If no UP interface is found, try to find any physical interface
                if not params["parent_if"]:
                    for line in ip_link_output.splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            if_name = parts[1].split(':')[0]
                            if (not if_name.startswith('lo') and 
                                not if_name.startswith('vir') and 
                                not if_name.startswith('docker') and
                                not if_name.startswith('br') and
                                not if_name.startswith('tun') and
                                not if_name.startswith('tap') and
                                not if_name.startswith('veth')):
                                params["parent_if"] = if_name
                                break
            except Exception as e:
                return f"{prompt}Error detecting network interfaces: {str(e)}"
            
            if not params["parent_if"]:
                # If still no parent interface found, try to use a dummy interface
                try:
                    # Check if dummy module is loaded
                    lsmod_output = subprocess.run(
                        ["lsmod"],
                        capture_output=True,
                        text=True
                    ).stdout
                    
                    dummy_loaded = "dummy" in lsmod_output
                    
                    if not dummy_loaded:
                        # Load dummy module
                        subprocess.run(["sudo", "modprobe", "dummy"], check=True)
                    
                    # Create dummy0 if it doesn't exist
                    dummy_check = subprocess.run(
                        ["ip", "link", "show", "dummy0"],
                        capture_output=True,
                        text=True
                    )
                    
                    if dummy_check.returncode != 0:
                        subprocess.run(
                            ["sudo", "ip", "link", "add", "dummy0", "type", "dummy"],
                            check=True
                        )
                        subprocess.run(
                            ["sudo", "ip", "link", "set", "dummy0", "up"],
                            check=True
                        )
                    
                    params["parent_if"] = "dummy0"
                    
                except Exception as e:
                    return f"{prompt}Error creating dummy interface: {str(e)}"
        
        # Create the interface
        try:
            parent_if = params["parent_if"]
            
            if params["svlan_id"] and params["cvlan_id"]:
                # Create double-tagged interface (QinQ)
                # First create the outer VLAN (S-TAG)
                s_vlan_name = f"{parent_if}.{params['svlan_id']}"
                
                # Check if s_vlan already exists
                s_vlan_check = subprocess.run(
                    ["ip", "link", "show", s_vlan_name],
                    capture_output=True,
                    text=True
                )
                
                if s_vlan_check.returncode != 0:
                    # S-VLAN doesn't exist, create it
                    subprocess.run(
                        ["sudo", "ip", "link", "add", "link", parent_if, "name", s_vlan_name, 
                         "type", "vlan", "id", params["svlan_id"]],
                        check=True
                    )
                    subprocess.run(
                        ["sudo", "ip", "link", "set", s_vlan_name, "up"],
                        check=True
                    )
                
                # Then create the inner VLAN (C-TAG) on top of the S-VLAN
                subprocess.run(
                    ["sudo", "ip", "link", "add", "link", s_vlan_name, "name", ifname, 
                     "type", "vlan", "id", params["cvlan_id"]],
                    check=True
                )
                
            elif params["cvlan_id"]:
                # Create single-tagged interface
                subprocess.run(
                    ["sudo", "ip", "link", "add", "link", parent_if, "name", ifname, 
                     "type", "vlan", "id", params["cvlan_id"]],
                    check=True
                )
                
            else:
                # Create untagged interface as a subinterface (using alias)
                subprocess.run(
                    ["sudo", "ip", "link", "add", "link", parent_if, "name", ifname, 
                     "type", "dummy"],
                    check=True
                )
            
            # Set MTU if specified
            if params["mtu"]:
                subprocess.run(
                    ["sudo", "ip", "link", "set", "dev", ifname, "mtu", params["mtu"]],
                    check=True
                )
            
            # Set IP address with netmask
            netmask_param = params["netmask"]
            if not netmask_param.startswith('/'):
                # Convert dotted decimal to CIDR if needed
                try:
                    # More reliable conversion from dotted decimal to CIDR
                    parts = netmask_param.split('.')
                    if len(parts) != 4:
                        return f"{prompt}Invalid netmask format."
                    
                    # Calculate prefix length from the binary representation
                    binary = ''.join([bin(int(p))[2:].zfill(8) for p in parts])
                    prefix_len = binary.count('1')
                    netmask_param = f"/{prefix_len}"
                except Exception as e:
                    return f"{prompt}Error converting netmask format: {str(e)}"
            
            subprocess.run(
                ["sudo", "ip", "addr", "add", f"{params['ipv4address']}{netmask_param}", "dev", ifname],
                check=True
            )
            
            # Set interface status
            subprocess.run(
                ["sudo", "ip", "link", "set", "dev", ifname, params["status"]],
                check=True
            )
            
            return f"{prompt}Successfully created interface {ifname} on parent {parent_if} with IP {params['ipv4address']}{netmask_param}."
            
        except subprocess.CalledProcessError as e:
            # Clean up if any step fails
            subprocess.run(["sudo", "ip", "link", "delete", ifname], capture_output=True, text=True)
            if params["svlan_id"] and params["cvlan_id"]:
                subprocess.run(["sudo", "ip", "link", "delete", f"{parent_if}.{params['svlan_id']}"], 
                               capture_output=True, text=True)
            
            # Add detailed error information
            error_msg = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
            return f"{prompt}Error creating interface: {error_msg}"
        except Exception as e:
            # Generic exception handling with more details
            import traceback
            error_details = traceback.format_exc()
            return f"{prompt}Error creating interface: {str(e)}\nDetails: {error_details}"

    elif args[0] == "delete-interface":
        if len(args) < 2:
            return f"{prompt}Please specify the name of the interface to delete."
        
        ifname = args[1]
        
        # Check if this is a direct confirmation with "confirm" parameter (keep for backward compatibility)
        if len(args) >= 3 and args[2] == "confirm":
            # Process deletion (existing code)
            try:
                # Check if the interface exists
                check_result = subprocess.run(
                    ["ip", "link", "show", ifname],
                    capture_output=True,
                    text=True
                )
                
                if check_result.returncode != 0:
                    return f"{prompt}Interface '{ifname}' does not exist."
                
                # Determine if this is a VLAN interface and if it has a parent
                ip_link_details = subprocess.run(
                    ["ip", "-d", "link", "show", ifname],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                # Initialize variables for parent interfaces
                parent_if = None
                is_svlan = False
                svlan_if = None
                
                # Check if this is a VLAN interface with a parent
                for line in ip_link_details.stdout.splitlines():
                    if "vlan" in line and "id" in line:
                        # This is a VLAN interface
                        for part in line.split():
                            if part.startswith("link/"):
                                parent_if = part.split("/")[1]
                                break
                
                # Check if this is a C-VLAN (in QinQ setup)
                if "@" in ifname and "." in ifname.split("@")[1]:
                    # This interface is likely a C-VLAN with an S-VLAN parent
                    svlan_if = ifname.split("@")[1]
                    is_svlan = True
                
                # Delete the interface
                result = subprocess.run(
                    ["sudo", "ip", "link", "delete", ifname],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    return f"{prompt}Error deleting interface: {result.stderr}"
                
                # If this was the only C-VLAN on an S-VLAN, also delete the S-VLAN
                if is_svlan and svlan_if:
                    # Check if there are other C-VLANs using this S-VLAN
                    other_cvlans = subprocess.run(
                        ["ip", "-br", "link", "show"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    
                    # Count interfaces using this S-VLAN as parent
                    has_other_cvlans = False
                    for line in other_cvlans.stdout.splitlines():
                        if f"@{svlan_if}" in line.split()[0]:
                            has_other_cvlans = True
                            break
                    
                    # If no other C-VLANs are using this S-VLAN, delete it too
                    if not has_other_cvlans:
                        subprocess.run(
                            ["sudo", "ip", "link", "delete", svlan_if],
                            capture_output=True,
                            text=True
                        )
                        return f"{prompt}Successfully deleted interface '{ifname}' and its parent S-VLAN interface '{svlan_if}'."
                
                return f"{prompt}Successfully deleted interface '{ifname}'."
                
            except subprocess.CalledProcessError as e:
                return f"{prompt}Error deleting interface: {e}"
        else:
            # Show confirmation message and wait for input
            
            @contextmanager
            def raw_mode():
                # Save terminal settings
                old_attrs = termios.tcgetattr(sys.stdin)
                try:
                    # Set terminal to raw mode
                    tty.setraw(sys.stdin)
                    yield
                finally:
                    # Restore terminal settings
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_attrs)
            
            # Return a special message that will be interpreted by the shell to request confirmation
            confirmation_message = f"{prompt}Are you sure you want to delete interface '{ifname}'?\nPlease type LGTM and press Enter to confirm, or Ctrl+C to cancel: "
            
            # Print the confirmation message
            print(confirmation_message, end='', flush=True)
            
            # Read user input
            confirmation = ""
            with raw_mode():
                while True:
                    char = sys.stdin.read(1)
                    
                    # Handle Enter key
                    if char == '\r' or char == '\n':
                        print()  # Move to next line
                        break
                    
                    # Handle backspace
                    elif char == '\x7f':  # Backspace
                        if confirmation:
                            confirmation = confirmation[:-1]
                            print('\b \b', end='', flush=True)  # Erase last character
                    
                    # Handle Ctrl+C
                    elif char == '\x03':  # Ctrl+C
                        print('^C')  # Show Ctrl+C
                        return f"{prompt}Interface deletion cancelled."
                    
                    # Handle normal characters
                    else:
                        confirmation += char
                        print(char, end='', flush=True)
            
            if confirmation.strip() == "LGTM":
                # User confirmed, proceed with deletion
                print("\r", end="")  # Move cursor to beginning of line
                print(f"{' ' * 100}\r", end="")  # Clear the line
                
                try:
                    # Check if the interface exists
                    check_result = subprocess.run(
                        ["ip", "link", "show", ifname],
                        capture_output=True,
                        text=True
                    )
                    
                    if check_result.returncode != 0:
                        return f"{prompt}Interface '{ifname}' does not exist."
                    
                    # Determine if this is a VLAN interface and if it has a parent
                    ip_link_details = subprocess.run(
                        ["ip", "-d", "link", "show", ifname],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    
                    # Initialize variables for parent interfaces
                    parent_if = None
                    is_svlan = False
                    svlan_if = None
                    
                    # Check if this is a VLAN interface with a parent
                    for line in ip_link_details.stdout.splitlines():
                        if "vlan" in line and "id" in line:
                            # This is a VLAN interface
                            for part in line.split():
                                if part.startswith("link/"):
                                    parent_if = part.split("/")[1]
                                    break
                    
                    # Check if this is a C-VLAN (in QinQ setup)
                    if "@" in ifname and "." in ifname.split("@")[1]:
                        # This interface is likely a C-VLAN with an S-VLAN parent
                        svlan_if = ifname.split("@")[1]
                        is_svlan = True
                    
                    # Delete the interface
                    result = subprocess.run(
                        ["sudo", "ip", "link", "delete", ifname],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode != 0:
                        return f"{prompt}Error deleting interface: {result.stderr}"
                    
                    # If this was the only C-VLAN on an S-VLAN, also delete the S-VLAN
                    if is_svlan and svlan_if:
                        # Check if there are other C-VLANs using this S-VLAN
                        other_cvlans = subprocess.run(
                            ["ip", "-br", "link", "show"],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        
                        # Count interfaces using this S-VLAN as parent
                        has_other_cvlans = False
                        for line in other_cvlans.stdout.splitlines():
                            if f"@{svlan_if}" in line.split()[0]:
                                has_other_cvlans = True
                                break
                        
                        # If no other C-VLANs are using this S-VLAN, delete it too
                        if not has_other_cvlans:
                            subprocess.run(
                                ["sudo", "ip", "link", "delete", svlan_if],
                                capture_output=True,
                                text=True
                            )
                            return f"{prompt}Successfully deleted interface '{ifname}' and its parent S-VLAN interface '{svlan_if}'."
                    
                    return f"{prompt}Successfully deleted interface '{ifname}'."
                    
                except subprocess.CalledProcessError as e:
                    return f"{prompt}Error deleting interface: {e}"
            else:
                return f"{prompt}Interface deletion cancelled. You typed '{confirmation}' instead of 'LGTM'."

    else:
        return f"{prompt}Unknown command '{args[0]}'."