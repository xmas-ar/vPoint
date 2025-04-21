import subprocess
from pyroute2 import IPDB
from cli.commands import config, system  # Import config and system modules

descriptions = {
    "tree": {
        "": "Display entire command tree",
        "show": "Display only the 'show' tree",
        "config": "Display only the 'config' tree",
        "system": "Display only the 'system' tree",
        "details": {
            "": "Display entire command tree with descriptions",
            "show": "Display only the 'show' tree with descriptions",
            "config": "Display only the 'config' tree with descriptions",
            "system": "Display only the 'system' tree with descriptions",
        },
    },
    "interfaces": {
        "": "Show interface-related information",
        "ip": {
            "": "Show interface IP address information",
            "config": "Show detailed IP configuration",
        },
        "ipv4": "Show IPv4 addresses only",
    },
    "routes": {
        "": "Show routing table information",
    },
}

def get_command_tree():
    """Build and return command tree based on descriptions"""
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

    # Build basic tree from descriptions
    command_tree = build_tree_from_descriptions(descriptions)
    
    # Add dynamic interface names to the "interfaces" subtree
    if "interfaces" in command_tree:
        interfaces_tree = {
            name: {} for name in interface_names
        }
        # Add static subcommands for "show interfaces"
        interfaces_tree.update({
            "ip": {
                "": None,
                "config": None,
            },
            "ipv4": None,
        })
        command_tree["interfaces"] = interfaces_tree
    
    return command_tree

def print_tree(d, prefix=""):
    lines = []
    if not d:
        return lines
        
    for key, value in d.items():
        if key == "_options":
            # Skip options in the tree output
            continue
            
        # Format the current line
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}")
            lines.extend(print_tree(value, prefix + "  "))
        else:
            lines.append(f"{prefix}{key}")
            
    return lines

def print_tree_with_descriptions(d, descs, prefix="", path=None):
    """
    Prints tree with descriptions, handling special cases for interface parameters.
    
    Args:
        d: Current subtree of command tree
        descs: Current subtree of description tree
        prefix: Prefix for indentation
        path: Current path in the tree (list of keys)
    """
    lines = []
    if not d:
        return lines
    
    # Initialize path if None
    if path is None:
        path = []
        
    for key, value in d.items():
        if key == "_options":
            continue
            
        # Get description for this item
        desc = ""
        current_path = path + [key]
        
        # Standard description lookup first
        if isinstance(descs, dict) and key in descs:
            if isinstance(descs[key], dict) and "" in descs[key]:
                desc = f" - {descs[key]['']}"
            elif isinstance(descs[key], str):
                desc = f" - {descs[key]}"
        
        # Special case for interface parameters
        if not desc and key in ["mtu", "speed", "status", "auto-nego", "duplex"]:
            # Check if we're in a config->interface->ifname path
            in_interface_path = False
            
            # Full tree path: ["config", "interface", "ifname", param]
            if len(path) == 0 and len(current_path) >= 3 and current_path[0] == "config" and current_path[1] == "interface":
                in_interface_path = True
                # Get descriptions from the full tree's config section
                config_desc = descs.get("config", {})
                interface_desc = config_desc.get("interface", {})
                ifname_desc = interface_desc.get("<ifname>", {})
                if key in ifname_desc:
                    param_desc = ifname_desc[key]
                    if isinstance(param_desc, dict) and "" in param_desc:
                        desc = f" - {param_desc['']}"
                    elif isinstance(param_desc, str):
                        desc = f" - {param_desc}"
            # Config subtree view - path starts with "config"
            elif len(path) >= 1 and path[0] == "config" and len(current_path) >= 2 and current_path[0] == "interface":
                in_interface_path = True
                # Get descriptions directly from the config subtree
                interface_desc = descs.get("interface", {})
                ifname_desc = interface_desc.get("<ifname>", {})
                # Rest of the lookup is similar...
        
        # Format the current line with description
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}{desc}")
            
            # Determine which description dictionary to pass to the recursive call
            sub_descs = descs.get(key, {}) if isinstance(descs, dict) else {}
            
            # Identify if we're at interfaces section in 'show' to handle it properly
            is_show_interfaces = False
            if (len(path) == 0 and len(current_path) >= 2 and 
                current_path[0] == "show" and current_path[1] == "interfaces"):
                is_show_interfaces = True
            elif (len(path) >= 1 and path[0] == "show" and len(current_path) >= 1 and
                  current_path[0] == "interfaces"):
                is_show_interfaces = True
                
            # Special case for interface names in config->interface path
            is_config_if = False
            if len(path) == 0 and len(current_path) >= 2:
                # Full tree view: ["config", "interface"]
                if current_path[0] == "config" and current_path[1] == "interface":
                    is_config_if = True
            elif len(path) >= 1 and path[0] == "config" and len(current_path) >= 1:
                # Config subtree view: path=["config"], current_path=["interface"]
                if current_path[0] == "interface":
                    is_config_if = True
            
            # Apply the appropriate description context based on path
            if is_config_if:
                # For actual interface names like "lo", "ens33", etc.
                # Get interface parameters from <ifname> template
                config_desc = descs.get("config", {}) if len(path) == 0 else descs
                if_desc = config_desc.get("interface", {})
                ifname_desc = if_desc.get("<ifname>", {})
                
                # Use the <ifname> descriptions for the next level
                if ifname_desc:
                    sub_descs = ifname_desc
            elif is_show_interfaces:
                # Make sure interface commands in 'show' tree get proper descriptions
                show_desc = descs.get("show", {}) if len(path) == 0 else descs
                interfaces_desc = show_desc.get("interfaces", {})
                if isinstance(interfaces_desc, dict):
                    sub_descs = interfaces_desc
            
            lines.extend(print_tree_with_descriptions(value, sub_descs, prefix + "  ", current_path))
        else:
            lines.append(f"{prefix}{key}{desc}")
            
    return lines

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' or '?' for more information."

    if args[0] == "tree":
        # Import the full tree from shell
        from cli.shell import command_tree as full_tree, description_tree as full_desc_tree
        
        # Use the full tree instead of just the show command tree
        if len(args) == 1:
            return "\n" + "\n".join(print_tree(full_tree))
        # show tree <subtree>
        elif len(args) == 2 and args[1] in full_tree:
            return "\n" + "\n".join(print_tree(full_tree[args[1]]))
        # show tree details
        elif len(args) > 1 and args[1] == "details":
            # show tree details
            if len(args) == 2:
                return "\n" + "\n".join(print_tree_with_descriptions(full_tree, full_desc_tree))
            # show tree details <subtree>
            elif len(args) == 3 and args[2] in full_tree:
                return "\n" + "\n".join(
                    print_tree_with_descriptions(
                        full_tree[args[2]], 
                        full_desc_tree.get(args[2], {}),
                        path=[args[2]]  # Pass the path for better context
                    )
                )
            else:
                return f"{prompt}Unknown subcommand for 'tree details': {' '.join(args[2:])}"
        else:
            return f"{prompt}Unknown subcommand for 'tree': {' '.join(args[1:])}"
            
    # Rest of the handle function

    if args[0] == "interfaces":
        if len(args) == 1:
            # Handle `show interfaces`
            try:
                result = subprocess.run(
                    ["ip", "-br", "-c", "link", "show"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return f"""
{result.stdout}"""
            except subprocess.CalledProcessError as e:
                return f"{prompt}Error executing command: {e}"
        elif len(args) == 2:
            if args[1] == "ip":
                # Handle `show interfaces ip`
                try:
                    result = subprocess.run(
                        ["ip", "-br", "addr", "show"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    return f"""
{result.stdout}"""
                except subprocess.CalledProcessError as e:
                    return f"{prompt}Error executing command: {e}"
            elif args[1] == "ipv4":
                # Handle `show interfaces ipv4`
                try:
                    result = subprocess.run(
                        ["ip", "-br", "addr", "show"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    # Filter out lines containing IPv6 addresses
                    ipv4_lines = []
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if len(parts) > 2:
                            ipv4_only = "\n".join([part for part in parts[2:] if "." in part])
                            if ipv4_only:
                                ipv4_lines.append(f"{parts[0]:<15} {parts[1]:<10} {ipv4_only}")
                    return "\n" + "\n".join(ipv4_lines) + "\n"
                except subprocess.CalledProcessError as e:
                    return f"{prompt}Error executing command: {e}"
            else:
                # Handle `show interfaces <ifname>`
                ifname = args[1]
                try:
                    # Gather interface details using `ip` and `ethtool`
                    ip_details = subprocess.run(
                        ["ip", "-br", "addr", "show", ifname],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    ethtool_details = subprocess.run(
                        ["ethtool", ifname],
                        capture_output=True,
                        text=True,
                        check=True
                    )

                    # Parse `ip` output for IP address and mask
                    ip_info = "N/A"
                    for line in ip_details.stdout.splitlines():
                        parts = line.split()
                        if len(parts) > 2:
                            ip_info = parts[2]

                    # Parse `ethtool` output for other details
                    ethtool_output = ethtool_details.stdout
                    mtu = "N/A"
                    speed = "N/A"
                    status = "N/A"
                    auto_nego = "N/A"
                    duplex = "N/A"

                    for line in ethtool_output.splitlines():
                        if "Speed:" in line:
                            speed = line.split(":")[1].strip()
                        elif "Duplex:" in line:
                            duplex = line.split(":")[1].strip()
                        elif "Auto-negotiation:" in line:
                            auto_nego = line.split(":")[1].strip()

                    # Parse `ip link show` output for MAC address, MTU, and status
                    ip_link_details = subprocess.run(
                        ["ip", "link", "show", ifname],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    mac_address = "N/A"
                    for line in ip_link_details.stdout.splitlines():
                        if "link/ether" in line:
                            mac_address = line.split()[1]
                        if "mtu" in line:
                            mtu = line.split("mtu")[1].split()[0]
                        if "state" in line:
                            status = line.split("state")[1].split()[0]

                    # Format the output
                    output = f"""
Interface: {ifname}
  IP Address/Mask: {ip_info}
  MAC Address: {mac_address}
  MTU: {mtu}
  Speed: {speed}
  Status: {status}
  Auto-Negotiation: {auto_nego}
  Duplex: {duplex}
"""
                    return output
                except subprocess.CalledProcessError as e:
                    return f"{prompt}Error fetching details for interface {ifname}: {e}"
    elif args[0] == "routes":
        try:
            result = subprocess.run(
                ["ip", "route", "show"],
                capture_output=True,
                text=True,
                check=True
            )
            return f"\n{result.stdout}"
        except subprocess.CalledProcessError as e:
            return f"{prompt}Error executing command: {e}"
    else:
        return f"{prompt}Unknown command '{args[0]}'."