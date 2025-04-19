import subprocess

descriptions = {
    "tree": {
        "": "Show command tree",
        "details": "Show command tree with descriptions",
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
        if len(args) > 1 and args[1] == 'details':
            tree_lines = print_tree(descriptions, with_descriptions=True)
            return "\n" + "\n".join(tree_lines) + "\n"
        else:
            tree_lines = print_tree(descriptions, with_descriptions=False)
            return "\n" + "\n".join(tree_lines) + "\n"
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