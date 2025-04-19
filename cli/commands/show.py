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

def print_tree(d, prefix="", with_descriptions=False):
    lines = []
    for key, value in d.items():
        if key == "" or key == "tree":
            continue  # Skip empty string keys and the 'tree' command itself
        if isinstance(value, dict):
            desc = value.get("", "")
            if with_descriptions:
                lines.append(f"{prefix}{key} - {desc}")
            else:
                lines.append(f"{prefix}{key}")
            lines.extend(print_tree(value, prefix + "  ", with_descriptions))
        else:
            if with_descriptions:
                lines.append(f"{prefix}{key} - {value}")
            else:
                lines.append(f"{prefix}{key}")
    return lines

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' or '?' for more information."
    if args[0] == 'tree':
        # Print all command trees or a specific one
        output = []
        with_descriptions = len(args) > 1 and args[1] == 'details'
        # Check if a specific tree is requested
        if (with_descriptions and len(args) > 2) or (not with_descriptions and len(args) > 1):
            tree_arg = args[2] if with_descriptions else args[1]
            if tree_arg == 'show':
                output.extend(print_tree(descriptions, with_descriptions=with_descriptions))
            elif tree_arg == 'config':
                output.extend(print_tree(config.descriptions, with_descriptions=with_descriptions))
            elif tree_arg == 'system':
                output.extend(print_tree(system.descriptions, with_descriptions=with_descriptions))
            else:
                return f"{prompt}Unknown tree '{tree_arg}'. Choose from: show, config, system."
        else:
            output.append("show:")
            output.extend(print_tree(descriptions, with_descriptions=with_descriptions))
            output.append("\nconfig:")
            output.extend(print_tree(config.descriptions, with_descriptions=with_descriptions))
            output.append("\nsystem:")
            output.extend(print_tree(system.descriptions, with_descriptions=with_descriptions))
        return "\n" + "\n".join(output) + "\n"
    if args[0] == 'interfaces':
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
        elif args[1] == 'ip':
            if len(args) == 2:
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
            elif args[2] == 'config':
                # Handle `show interfaces ip config`
                return f"{prompt}Detailed IP configuration not implemented yet."
            else:
                return f"{prompt}Unknown subcommand for 'interfaces ip': {args[2]}"
        elif args[1] == 'ipv4':
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
                return "\n" + "\n".join(ipv4_lines)+ "\n"
            except subprocess.CalledProcessError as e:
                return f"{prompt}Error executing command: {e}"
        else:
            return f"{prompt}Unknown subcommand for 'interfaces': {args[1]}"
    
    elif args[0] == 'routes':
        try:
            result = subprocess.run(
                ["ip", "route", "show"],
                capture_output=True,
                text=True,
                check=True
            )
            return f"""
{result.stdout}"""
        except subprocess.CalledProcessError as e:
            return f"{prompt}Error executing command: {e}"
    
    else:
        return f"{prompt}Unknown command {args[0]}"