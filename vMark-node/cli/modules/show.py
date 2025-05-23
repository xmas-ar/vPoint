import subprocess
from pyroute2 import IPDB
from cli.modules import config, system, register, twamp, xdp_mef_switch  # Import config, system, and register modules

descriptions = {
    "tree": {
        "": "Display entire command tree",
        "show": "Display only the 'show' tree",
        "config": "Display only the 'config' tree",
        "system": "Display only the 'system' tree",
        "twamp": "Display only the 'twamp' tree",
        "register": "Display only the 'register' tree",
        "xdp-switch": "Display only the 'xdp-switch' tree",

        "details": {
            "": "Display entire command tree with descriptions",
            "show": "Display only the 'show' tree with descriptions",
            "config": "Display only the 'config' tree with descriptions",
            "system": "Display only the 'system' tree with descriptions",
            "twamp": "Display only the 'twamp' tree with descriptions",
            "register": "Display only the 'register' tree with descriptions",
            "xdp-switch" : "Display only the 'xdp-switch' tree with descriptions",
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

def get_descriptions():
    """Return the description dictionary."""
    return descriptions

# Fix the print_tree function to reduce excessive whitespace

def print_tree(d, prefix="", is_last=True, path=None, visited=None, max_depth=None, current_depth=0):
    """Print a tree structure with improved cycle detection and depth limiting"""
    if path is None:
        path = []
    
    # Initialize visited set for cycle detection
    if visited is None:
        visited = set()
    
    # Initialize max_depth if not provided
    if max_depth is None:
        max_depth = 5  # Default to a much lower value to prevent recursion issues
    
    # Depth limiting to prevent overly complex tree displays
    if current_depth > max_depth:
        return f"{prefix}... (max depth reached)"
    
    if not isinstance(d, dict) or not d:  # Check if d is a dict and not empty
        return ""
    
    # Create path-based node identifier for smarter cycle detection
    current_path_str = '.'.join(str(p) for p in path) if path else "root"
    current_node_id = (current_path_str, id(d))
    
    if current_node_id in visited:
        # Only show cyclic reference if it's not an empty parameter value
        if not path or not str(path[-1]).startswith("<"):
            return f"{prefix}⟲ [cyclic reference]"
        return ""
    
    # Mark this node as visited
    visited.add(current_node_id)
    
    lines = []  # Store lines instead of a single result string
    
    # Sort the keys for consistent output, filtering out None keys and internal keys like _options
    items = []
    if isinstance(d, dict):
        items = [(k, v) for k, v in d.items() if k is not None and isinstance(k, str) and not k.startswith('_')]
    items.sort(key=lambda x: str(x[0]))
    
    for i, (k, v) in enumerate(items):
        is_last_item = i == len(items) - 1
        
        # Skip empty keys
        if k == "":
            continue
        
        # Create the branch symbol
        if is_last_item:
            branch = "└── " if prefix else ""
            new_prefix = prefix + "    "
        else:
            branch = "├── " if prefix else ""
            new_prefix = prefix + "│   "
        
        # Build the full path for this node
        current_path = path + [k]
        
        # Skip parameter values that would create cycles - with strict depth control
        if str(k).startswith("<") and current_depth >= 2:
            lines.append(f"{prefix}{branch}{k}")
            continue
            
        # Add the current item
        lines.append(f"{prefix}{branch}{k}")
        
        # Recursively add subtrees, but only if they contain items and are not cycles
        # Limit the maximum depth for certain key patterns to avoid deep recursion
        local_max_depth = max_depth
        if 'out-if' in str(current_path_str) or 'cvlan' in str(current_path_str) or 'svlan' in str(current_path_str):
            local_max_depth = min(max_depth, current_depth + 2)  # Restrict depth for VLAN and interface paths
            
        if isinstance(v, dict) and v:
            # Pass a COPY of the visited set to avoid side effects between different branches
            subtree = print_tree(
                v, 
                new_prefix, 
                is_last_item, 
                current_path, 
                visited.copy(), 
                local_max_depth,
                current_depth + 1
            )
            if subtree:  # Only include non-empty subtrees
                lines.append(subtree)
    
    return "\n".join(lines)  # Join with newlines only at the end

def print_tree_with_descriptions(d, descs, prefix="", path=None, visited=None, max_depth=None, current_depth=0):
    """Print a tree structure with descriptions, improved cycle detection, and depth limiting"""
    if path is None:
        path = []
    
    # Initialize visited set for cycle detection
    if visited is None:
        visited = set()
    
    # Initialize max_depth if not provided
    if max_depth is None:
        max_depth = 4  # Even lower depth for the detailed tree
    
    # Depth limiting to prevent overly complex tree displays
    if current_depth > max_depth:
        return f"{prefix}... (max depth reached)"
    
    if not isinstance(d, dict) or not d:  # Check if d is a dict and not empty
        return ""
    
    # Create path-based node identifier for smarter cycle detection
    current_path_str = '.'.join(str(p) for p in path) if path else "root"
    current_node_id = (current_path_str, id(d))
    
    if current_node_id in visited:
        # Only show cyclic reference if it's not an empty parameter value
        if not path or not str(path[-1]).startswith("<"):
            return f"{prefix}⟲ [cyclic reference]"
        return ""
    
    # Mark this node as visited
    visited.add(current_node_id)
    
    lines = []  # Store lines instead of returning a list
    
    # Sort keys for consistent output, filtering out None keys and internal keys like _options
    items = []
    if isinstance(d, dict):
        items = [(k, v) for k, v in d.items() if k is not None and isinstance(k, str) and not k.startswith('_')]
    items.sort(key=lambda x: str(x[0]))
    
    for i, (key, value) in enumerate(items): # key will be a string here
        is_last_item = i == len(items) - 1
        
        # Skip empty keys
        if key == "":
            continue
        
        # Create the branch symbol
        if is_last_item:
            branch = "└── " if prefix else ""
            new_prefix = prefix + "    "
        else:
            branch = "├── " if prefix else ""
            new_prefix = prefix + "│   "
            
        # Get description for this item
        desc = ""
        current_path = path + [key]
        
        # Standard description lookup first
        if isinstance(descs, dict) and key in descs:
            if isinstance(descs[key], dict) and "" in descs[key]:
                desc = f" - {descs[key]['']}"
            elif isinstance(descs[key], str):
                desc = f" - {descs[key]}"
        
        # Skip parameter values that would create cycles with stricter depth control
        if str(key).startswith("<") and current_depth >= 2:
            lines.append(f"{prefix}{branch}{key}{desc}")
            continue
        
        # Format the current line with description
        lines.append(f"{prefix}{branch}{key}{desc}")
        
        # Limit the maximum depth for certain key patterns
        local_max_depth = max_depth
        if 'out-if' in str(current_path_str) or 'cvlan' in str(current_path_str) or 'svlan' in str(current_path_str):
            local_max_depth = min(max_depth, current_depth + 1)  # Restrict depth for VLAN and interface paths
            
        # Only recurse if this is a dictionary and if we should show children
        if isinstance(value, dict) and value and current_depth < local_max_depth:
            # Determine which description dictionary to pass to the recursive call
            sub_descs = descs.get(key, {}) if isinstance(descs, dict) else {}
            
            # Recursively add subtrees, with increased depth and a copy of visited set
            subtree = print_tree_with_descriptions(
                value, 
                sub_descs, 
                new_prefix, 
                current_path, 
                visited.copy(),
                local_max_depth,
                current_depth + 1
            )
            if subtree:  # Only include non-empty subtrees
                lines.append(subtree)
    
    return "\n".join(lines)  # Join with newlines only at the end


def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' or '?' for more information."

    if args[0] == "tree":
        # Import the full tree from shell
        from cli.shell import command_tree as full_tree, description_tree as full_desc_tree
        
        # Support for depth limiting with --depth option
        max_depth = 5  # Default depth - low enough to avoid recursion issues but still show structure
        depth_flag_idx = -1
        
        # Check for --depth flag
        for i, arg in enumerate(args):
            if arg == "--depth" and i + 1 < len(args) and args[i + 1].isdigit():
                max_depth = int(args[i + 1])
                depth_flag_idx = i
                break
                
        # Filter out the --depth flag and value if present
        if depth_flag_idx >= 0:
            args = args[:depth_flag_idx] + args[depth_flag_idx+2:]

        # Check for specific filter flags
        no_vlan_details = "--no-vlan-details" in args
        if no_vlan_details:
            args = [arg for arg in args if arg != "--no-vlan-details"]
        
        # Use the full tree instead of just the show command tree
        if len(args) == 1:
            return print_tree(full_tree, max_depth=max_depth)
        # show tree <subtree>
        elif len(args) == 2 and args[1] in full_tree:
            # For potentially deep trees like config, twamp, keep max_depth lower
            if args[1] in ["config", "twamp"]:
                if max_depth > 5:  # User explicitly asked for a deeper tree
                    return print_tree(full_tree[args[1]], max_depth=max_depth)
                else:
                    return print_tree(full_tree[args[1]], max_depth=3) # Lower default for problematic trees
            else:
                return print_tree(full_tree[args[1]], max_depth=max_depth)
        # show tree details
        elif len(args) > 1 and args[1] == "details":
            # show tree details
            if len(args) == 2:
                return print_tree_with_descriptions(full_tree, full_desc_tree, max_depth=3) # Lower default for details
            # show tree details <subtree>
            elif len(args) == 3 and args[2] in full_tree:
                # For potentially deep trees like config, twamp, keep max_depth lower
                if args[2] in ["config", "twamp"]:
                    if max_depth > 5:  # User explicitly asked for a deeper tree
                        return print_tree_with_descriptions(
                            full_tree[args[2]], 
                            full_desc_tree.get(args[2], {}),
                            path=[args[2]],
                            max_depth=max_depth
                        )
                    else:
                        return print_tree_with_descriptions(
                            full_tree[args[2]], 
                            full_desc_tree.get(args[2], {}),
                            path=[args[2]],
                            max_depth=2
                        )
                else:
                    return print_tree_with_descriptions(
                        full_tree[args[2]], 
                        full_desc_tree.get(args[2], {}),
                        path=[args[2]],
                        max_depth=max_depth
                    )
            else:
                return f"{prompt}Unknown subcommand for 'tree details': {' '.join(args[2:])}"
        else:
            return f"{prompt}Unknown subcommand for 'tree': {' '.join(args[1:])}"

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
                    # Gather interface details using `ip` command
                    ip_details = subprocess.run(
                        ["ip", "-br", "addr", "show", ifname],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    
                    # Get detailed link info to detect VLANs
                    ip_link_details = subprocess.run(
                        ["ip", "-d", "link", "show", ifname],
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

                    # Parse detailed link info for VLAN tags
                    vlan_info = {}
                    svlan_id = None
                    cvlan_id = None
                    
                    # Check if this is a VLAN interface
                    for line in ip_link_details.stdout.splitlines():
                        if "vlan" in line and "id" in line:
                            # Extract VLAN ID
                            vlan_parts = line.strip().split()
                            for i, part in enumerate(vlan_parts):
                                if part == "id":
                                    if i + 1 < len(vlan_parts):
                                        vlan_id = vlan_parts[i + 1]
                                        
                                        # Determine if this is a C-VLAN or S-VLAN based on interface name
                                        parent_interface = None
                                        for part in vlan_parts:
                                            if part.startswith("link"):
                                                parent_interface = part.split("/")[1]
                                                
                                        # If parent is also a VLAN interface, this is likely a C-VLAN
                                        if parent_interface and "." in parent_interface:
                                            cvlan_id = vlan_id
                                            # Try to find the S-VLAN ID from the parent
                                            parent_details = subprocess.run(
                                                ["ip", "-d", "link", "show", parent_interface],
                                                capture_output=True,
                                                text=True
                                            )
                                            if parent_details.returncode == 0:
                                                for parent_line in parent_details.stdout.splitlines():
                                                    if "vlan" in parent_line and "id" in parent_line:
                                                        parent_vlan_parts = parent_line.strip().split()
                                                        for j, parent_part in enumerate(parent_vlan_parts):
                                                            if parent_part == "id" and j + 1 < len(parent_vlan_parts):
                                                                svlan_id = parent_vlan_parts[j + 1]
                                        else:
                                            # This is a regular VLAN (S-VLAN)
                                            svlan_id = vlan_id

                    # Try to get ethtool info, but don't fail if it doesn't work
                    try:
                        ethtool_details = subprocess.run(
                            ["ethtool", ifname],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        ethtool_output = ethtool_details.stdout
                        speed = "N/A"
                        auto_nego = "N/A"
                        duplex = "N/A"

                        for line in ethtool_output.splitlines():
                            if "Speed:" in line:
                                speed = line.split(":")[1].strip()
                            elif "Duplex:" in line:
                                duplex = line.split(":")[1].strip()
                            elif "Auto-negotiation:" in line:
                                auto_nego = line.split(":")[1].strip()
                    except subprocess.CalledProcessError:
                        # ethtool doesn't work for virtual interfaces
                        speed = "N/A (virtual interface)"
                        auto_nego = "N/A (virtual interface)"
                        duplex = "N/A (virtual interface)"

                    # Parse `ip link show` output for MAC address, MTU, and status
                    ip_link_details = subprocess.run(
                        ["ip", "link", "show", ifname],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    mac_address = "N/A"
                    mtu = "N/A"
                    status = "N/A"
                    
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
  Duplex: {duplex}"""

                    # Add VLAN information if present
                    if svlan_id and cvlan_id:
                        output += f"\n  QinQ VLANs: S-VLAN {svlan_id}, C-VLAN {cvlan_id}"
                    elif svlan_id:
                        output += f"\n  VLAN ID: {svlan_id}"
                    elif cvlan_id:
                        output += f"\n  VLAN ID: {cvlan_id}"
                        
                    # Detect if interface is a virtual subinterface
                    if "@" in ifname:
                        parent = ifname.split("@")[1]
                        child = ifname.split("@")[0]
                        if "." in child:
                            parts = child.split(".")
                            if len(parts) > 1:
                                parent_if = parts[0]
                                vlan_id = parts[1]
                                if not svlan_id:
                                    output += f"\n  VLAN ID: {vlan_id} (on {parent_if})"

                    # Add extra newline at the end
                    output += "\n"
                    
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