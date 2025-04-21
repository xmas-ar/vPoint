from pyroute2 import IPDB
import subprocess

# Define descriptions with proper _options for parameters
descriptions = {
    "interface": {
        "": "Configure network interfaces",
        "<ifname>": {
            "": "Interface name",
            "mtu": {
                "": "Set MTU size",
                "_options": ["<1-10000>"],  # Common MTU values
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
    #"new-interface": {
    #    "": "Create a new interface",
    #    "<ifnamenewif>": {
    #        "": "New interface name",
    #        "type": {
    #            "": "Set interface type",
    #            "_options": ["vlan", "vlan-in-vlan"],
    #        },
    #        "cvlan-id": {
    #            "": "Set CVLAN ID",
    #            "_options": ["1-4094"],
    #        },
    #        "svlan-id": {
    #            "": "Set SVLAN ID",
    #            "_options": ["1-4094"],
    #        },
    #    }
    #},
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
    
    # Add dynamic interface names to the "interface" subtree
    if "interface" in command_tree:
        interface_subtree = {
            name: {
                "mtu": None,
                "speed": None,
                "status": None,
                "auto-nego": None,
                "duplex": None,
            }
            for name in interface_names
        }
        command_tree["interface"] = interface_subtree
    
    # Setup new-interface placeholder if it exists
    if "new-interface" in command_tree:
        command_tree["new-interface"] = {}  # Will be populated dynamically
    
    return command_tree

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
        new_ifname = args[1]
        if len(args) < 3:
            return f"{prompt}Incomplete command. Type 'help' or '?' for more information."
        action = args[2]

        if action == "type":
            if len(args) < 4:
                return f"{prompt}Please specify a type (vlan/vlan-in-vlan)."
            interface_type = args[3]
            if interface_type not in ["vlan", "vlan-in-vlan"]:
                return f"{prompt}Invalid type '{interface_type}'. Choose from: vlan, vlan-in-vlan."
            return f"{prompt}New interface {new_ifname} of type {interface_type} created (simulation)."
        elif action == "cvlan-id":
            if len(args) < 4:
                return f"{prompt}Please specify a customer VLAN ID."
            cvlan_id = args[3]
            return f"{prompt}Customer VLAN ID for {new_ifname} set to {cvlan_id} (simulation)."
        elif action == "svlan-id":
            if len(args) < 4:
                return f"{prompt}Please specify a service VLAN ID."
            svlan_id = args[3]
            return f"{prompt}Service VLAN ID for {new_ifname} set to {svlan_id} (simulation)."
        else:
            return f"{prompt}Unknown action '{action}' for new-interface."

    else:
        return f"{prompt}Unknown command '{args[0]}'."