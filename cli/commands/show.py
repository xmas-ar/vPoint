import subprocess
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

def print_tree(d, prefix=""):
    lines = []
    for key, value in d.items():
        if key == "_options":
            # Skip options in the tree output
            continue
        if isinstance(value, dict):
            # Replace dynamic interface names with a placeholder
            if key in ["lo", "ens33", "docker0"]:  # Replace with dynamic detection if needed
                key = "<ifname>"
            lines.append(f"{prefix}{key}")
            lines.extend(print_tree(value, prefix + "  "))
        elif value is None or isinstance(value, str):
            # Include leaf nodes that are commands or descriptions
            lines.append(f"{prefix}{key}")
    # Remove duplicate <ifname> entries
    return list(dict.fromkeys(lines))

def print_tree_with_descriptions(d, descs, prefix=""):
    lines = []
    for key, value in d.items():
        if key == "_options":
            continue
        desc = ""
        # Try to get the description for this key
        if isinstance(descs, dict) and key in descs:
            if isinstance(descs[key], str):
                desc = f"  # {descs[key]}"
            elif isinstance(descs[key], dict) and "" in descs[key]:
                desc = f"  # {descs[key]['']}"
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}{desc}")
            # Recurse with the sub-dictionary and sub-descriptions
            sub_descs = descs.get(key, {}) if isinstance(descs, dict) else {}
            lines.extend(print_tree_with_descriptions(value, sub_descs, prefix + "  "))
        else:
            lines.append(f"{prefix}{key}{desc}")
    # Remove duplicate <ifname> entries
    return list(dict.fromkeys(lines))

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' or '?' for more information."

    if args[0] == "tree":
        from cli.shell import command_tree, description_tree
        from cli.commands.show import print_tree, print_tree_with_descriptions

        # show tree
        if len(args) == 1:
            return "\n" + "\n".join(print_tree(command_tree))
        # show tree <subtree>
        elif len(args) == 2 and args[1] in command_tree:
            return "\n" + "\n".join(print_tree(command_tree[args[1]]))
        # show tree details
        elif len(args) > 1 and args[1] == "details":
            # show tree details
            if len(args) == 2:
                return "\n" + "\n".join(print_tree_with_descriptions(command_tree, description_tree))
            # show tree details <subtree>
            elif len(args) == 3 and args[2] in command_tree:
                return "\n" + "\n".join(
                    print_tree_with_descriptions(command_tree[args[2]], description_tree.get(args[2], {}))
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