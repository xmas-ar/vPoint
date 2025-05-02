import subprocess
from pyroute2 import IPDB
from cli.modules import config, system, register  # Import config, system, and register modules

descriptions = {
    "tree": {
        "": "Display entire command tree",
        "show": "Display only the 'show' tree",
        "config": "Display only the 'config' tree",
        "system": "Display only the 'system' tree",
        "twamp": "Display only the 'twamp' tree",
        "register": "Display only the 'register' tree",  # Added register
        "details": {
            "": "Display entire command tree with descriptions",
            "show": "Display only the 'show' tree with descriptions",
            "config": "Display only the 'config' tree with descriptions",
            "system": "Display only the 'system' tree with descriptions",
            "twamp": "Display only the 'twamp' tree with descriptions",
            "register": "Display only the 'register' tree with descriptions", # Added register
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

def print_tree(d, prefix="", is_last=True, path=None):
    """Print a tree structure in a more compact format"""
    if path is None:
        path = []
    
    if not d:  # Empty dictionary
        return ""
    
    lines = []  # Store lines instead of a single result string
    
    # Sort the keys for consistent output
    items = sorted(d.items())
    
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
        
        # Add the current item
        lines.append(f"{prefix}{branch}{k}")
        
        # Recursively add subtrees, but only if they contain items
        if isinstance(v, dict) and v:
            subtree = print_tree(v, new_prefix, is_last_item, current_path)
            if subtree:  # Only include non-empty subtrees
                lines.append(subtree)
    
    return "\n".join(lines)  # Join with newlines only at the end

def print_tree_with_descriptions(d, descs, prefix="", path=None):
    """Print a tree structure with descriptions"""
    if path is None:
        path = []
    
    if not d:  # Empty dictionary
        return ""
    
    lines = []  # Store lines instead of returning a list
    
    # Sort keys for consistent output
    items = sorted(d.items())
    
    for i, (key, value) in enumerate(items):
        is_last_item = i == len(items) - 1
        
        # Skip empty keys and option entries
        if key == "" or key == "_options":
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
        
        # Special case for interface parameters (existing code)
        # ...
        
        # Format the current line with description
        if isinstance(value, dict):
            lines.append(f"{prefix}{branch}{key}{desc}")
            
            # Determine which description dictionary to pass to the recursive call
            sub_descs = descs.get(key, {}) if isinstance(descs, dict) else {}
            
            # (Rest of your special case handling for descriptions)
            # ...
            
            # Recursively add subtrees
            subtree = print_tree_with_descriptions(value, sub_descs, new_prefix, current_path)
            if subtree:  # Only include non-empty subtrees
                lines.append(subtree)
        else:
            lines.append(f"{prefix}{branch}{key}{desc}")
    
    return "\n".join(lines)  # Join with newlines only at the end

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' or '?' for more information."

    if args[0] == "tree":
        # Import the full tree from shell
        from cli.shell import command_tree as full_tree, description_tree as full_desc_tree
        
        # Use the full tree instead of just the show command tree
        if len(args) == 1:
            return print_tree(full_tree)  # Already joined with newlines
        # show tree <subtree>
        elif len(args) == 2 and args[1] in full_tree:
            return print_tree(full_tree[args[1]])
        # show tree details
        elif len(args) > 1 and args[1] == "details":
            # show tree details
            if len(args) == 2:
                return print_tree_with_descriptions(full_tree, full_desc_tree)
            # show tree details <subtree>
            elif len(args) == 3 and args[2] in full_tree:
                return print_tree_with_descriptions(
                    full_tree[args[2]], 
                    full_desc_tree.get(args[2], {}),
                    path=[args[2]]  # Pass the path for better context
                )
            else:
                return f"{prompt}Unknown subcommand for 'tree details': {' '.join(args[2:])}"
        else:
            return f"{prompt}Unknown subcommand for 'tree': {' '.join(args[1:])}"
            
    elif args[0] == "tree":
        if len(args) == 1:
            # Show the entire command tree
            return print_tree(command_tree)
        elif len(args) == 2 and args[1] == "details":
            # Show the command tree with descriptions
            return print_tree_with_descriptions(command_tree, description_tree)
        else:
            # Show specific subtree
            subtree = command_tree
            for part in args[1:]:
                if part in subtree:
                    subtree = subtree[part]
                else:
                    return f"{prompt}Invalid path: {' '.join(args[1:])}"
            
            # Only print if we have a valid subtree
            if isinstance(subtree, dict):
                return print_tree(subtree, path=args[1:])
            else:
                return f"{prompt}No subtree available for: {' '.join(args[1:])}"

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