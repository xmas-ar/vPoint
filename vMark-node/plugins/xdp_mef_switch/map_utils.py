## Version: 0.8.0
import struct
import subprocess
import json
import logging
from pyroute2 import IPRoute
from typing import Optional, List, Dict, Any # Import List, Dict, Any
from .utils import get_parent_interface, run_with_sudo

logger = logging.getLogger('ebpf')

# Action types (for the 'type' field in struct action_step)
ACTION_TYPE_NONE = 0
ACTION_TYPE_FORWARD = 1
ACTION_TYPE_PUSH = 2
ACTION_TYPE_POP = 3

# Tag types (for the 'tag_type' field in struct action_step)
TAG_TYPE_NONE = 0
TAG_TYPE_CVLAN = 1
TAG_TYPE_SVLAN = 2


MAX_ACTIONS_PER_RULE = 5 # Iterations over the ebpf logic // Must match forwarding_maps.bpf.h // "num_actions"

def get_network_interfaces(exclude_virtual: bool = True) -> list[str]:
    """
    Get list of network interface names using IPRoute.
    Args:
        exclude_virtual: If True, common virtual/loopback interfaces are excluded.
    Returns:
        A sorted list of unique interface names.
    """
    try:
        ipr = IPRoute()
        # Get all links, then extract the IFLA_IFNAME attribute
        interfaces = []
        for link in ipr.get_links():
            ifname_attr = next((attr for attr in link.get('attrs', []) if attr[0] == 'IFLA_IFNAME'), None)
            if ifname_attr:
                interfaces.append(ifname_attr[1])
        ipr.close()
        
        if not exclude_virtual:
            return sorted(list(set(interfaces)))

        # Common prefixes for virtual, loopback, or special interfaces to exclude
        excluded_prefixes = (
            "lo", "docker", "veth", "br-", "virbr", "kube-", "dummy", 
            "ifb", "tun", "tap", "bond", "can", "ipoib", "wwan", "wg",
            "vxlan", "geneve", "gretap", "ip6tnl", "sit"
        )
        # Also exclude interfaces with '@' which often indicates a sub-interface already handled
        # or a virtual interface linked to a physical one (e.g. vlan sub-interfaces like eth0.100@eth0)
        # However, the primary goal here is to list base interfaces for selection.
        # The user might still want to see 'eth0.100' if it's configured,
        # but 'eth0.100@eth0' is less of a primary selectable interface.
        # For now, let's filter based on prefixes.
        
        filtered_interfaces = [
            iface for iface in interfaces 
            if not any(iface.startswith(prefix) for prefix in excluded_prefixes) and '@' not in iface
        ]
        return sorted(list(set(filtered_interfaces)))
    except Exception as e:
        logger.error(f"Error getting interfaces with IPRoute: {e}")
        return []

def base_iface_name(ifname: str) -> str:
    """Extracts the base interface name (e.g., 'if-a-cv90' from 'if-a-cv90@ens160')."""
    return ifname.split('@')[0] if '@' in ifname else ifname

def get_interface_index(ifname: str) -> Optional[int]:
    """Get the numerical index of a network interface."""
    ip = IPRoute()
    try:
        # Ensure we are looking up the base name if it's a sub-interface like 'if-a-cv90'
        # If 'ifname' is already a parent like 'ens160', this is fine.
        # If 'ifname' is 'if-a-cv90@ens160', we need 'if-a-cv90' for the index.
        # The base_iface_name helper should handle this.
        lookup_name = base_iface_name(ifname)
        indices = ip.link_lookup(ifname=lookup_name)
        if indices:
            return indices[0]
        else:
            logger.warning(f"Interface index not found for '{lookup_name}' (derived from '{ifname}').")
            return None
    except Exception as e:
        logger.error(f"Error looking up interface index for '{base_iface_name(ifname)}': {e}")
        return None
    finally:
        ip.close()

def pack_key(ifindex: int, vlan_id: int, svlan_id: int, bmac: bytes = b'\x00'*6) -> bytes:
    """
    Pack key into 16 bytes with proper byte ordering:
    - ifindex: 4 bytes (u32) - little endian
    - vlan_id: 2 bytes (u16) - little endian
    - svlan_id: 2 bytes (u16) - little endian
    - bmac: 6 bytes (default all zeros)
    - pad: 2 bytes of zeros for alignment
    """
    return struct.pack("<IHH6s2s", ifindex, vlan_id or 0, svlan_id or 0, bmac, b'\x00'*2)

def pack_action_step(action_detail: Dict[str, Any], endpoints: Dict[str, Any], current_endpoint_key: str) -> bytes:
    """Packs a single action_step structure.
    Format: type (u8), tag_type (u8), vlan_id (u16), target_ifindex (u32)
    """
    act_type_str = action_detail.get("type", "").lower()
    act_tag_str = action_detail.get("tag", "").lower()

    bpf_action_type = ACTION_TYPE_NONE
    bpf_tag_type = TAG_TYPE_NONE
    vlan_val = 0
    target_idx = 0

    if act_type_str == "push":
        bpf_action_type = ACTION_TYPE_PUSH
        vlan_val = action_detail.get("value", 0)
        if act_tag_str == "cvlan":
            bpf_tag_type = TAG_TYPE_CVLAN
        elif act_tag_str == "svlan":
            bpf_tag_type = TAG_TYPE_SVLAN
        else:
            logger.warning(f"Unknown tag type '{act_tag_str}' for push action. Defaulting to NONE.")
    elif act_type_str == "pop":
        bpf_action_type = ACTION_TYPE_POP
        if act_tag_str == "cvlan":
            bpf_tag_type = TAG_TYPE_CVLAN
        elif act_tag_str == "svlan":
            bpf_tag_type = TAG_TYPE_SVLAN
        else:
            logger.warning(f"Unknown tag type '{act_tag_str}' for pop action. Defaulting to NONE.")
    elif act_type_str == "forward":
        bpf_action_type = ACTION_TYPE_FORWARD
        bpf_tag_type = TAG_TYPE_NONE
        to_ep_key = action_detail.get("to")
        if to_ep_key and to_ep_key in endpoints:
            target_interface_name = endpoints[to_ep_key]["interface"]
            idx = get_interface_index(target_interface_name)
            if idx is not None:
                target_idx = idx
            else:
                logger.error(f"Could not get ifindex for forward target interface '{target_interface_name}'")
                raise ValueError(f"Invalid target interface for forward action: {target_interface_name}")
        else:
            logger.error(f"Invalid 'to' endpoint key '{to_ep_key}' in forward action.")
            raise ValueError(f"Invalid 'to' endpoint key for forward action: {to_ep_key}")
    else:
        logger.warning(f"Unknown action type: {act_type_str}")

    return struct.pack("<BBHI", bpf_action_type, bpf_tag_type, vlan_val, target_idx)

def hex_encode(b: bytes) -> str:
    """Convert bytes to exact hex string format required by bpftool."""
    return ' '.join([f"{b[i]:02x}" for i in range(len(b))])

def add_forwarding_rule(
    in_iface_service_point: str,
    match_cvlan: int,
    match_svlan: int,
    actions: List[Dict[str, Any]],
    all_endpoints_details: Dict[str, Any] = None,
    current_endpoint_key_for_actions: str = None
):
    """Add a rule to the map to forward traffic based on the specified actions"""
    
    from .xdp_loader import get_parent_interface, get_bpf_map_path_if_exists, get_interface_index, run_with_sudo, base_iface_name

    base_in_iface_for_key = base_iface_name(in_iface_service_point)
    if_idx = get_interface_index(base_in_iface_for_key)
    if if_idx is None:
        raise ValueError(f"Failed to get interface index for {base_in_iface_for_key}")

    parent_for_map = get_parent_interface(in_iface_service_point)
    map_path = get_bpf_map_path_if_exists(parent_for_map)
    if not map_path:
        raise RuntimeError(f"Map path for parent interface '{parent_for_map}' not found.")

    # Empaquetar la clave
    key_bytes = pack_key(if_idx, match_cvlan, match_svlan)

    # Convertir las acciones de alto nivel a la estructura numérica que espera el packing
    packed_actions = []
    for action in actions:
        packed = pack_action_step(action, all_endpoints_details, current_endpoint_key_for_actions)
        t, tag_type, vlan_id, target_ifindex = struct.unpack("<BBHI", packed)
        packed_actions.append({
            "type": t,
            "tag_type": tag_type,
            "vlan_id": vlan_id,
            "target_ifindex": target_ifindex
        })

    # Empaquetar el valor
    value_bytes = pack_forwarding_value_with_mac(packed_actions)

    # Actualizar el mapa
    update_cmd = ['bpftool', 'map', 'update', 'pinned', map_path, 'key', 'hex']
    update_cmd.extend([f"{b:02x}" for b in key_bytes])
    update_cmd.append('value')
    update_cmd.append('hex') # CORREGIDO: añadido "hex"
    update_cmd.extend([f"{b:02x}" for b in value_bytes])

    success, output = run_with_sudo(update_cmd)
    if not success:
        raise RuntimeError(f"Failed to insert rule: {output}")

    logger.info(f"Successfully added forwarding rule to map at {map_path}")
    
def remove_forwarding_rule(iface_service_point: str, match_cvlan: int, match_svlan: int):
    parent_interface = get_parent_interface(iface_service_point)
    map_path = get_bpf_map_path_if_exists(parent_interface)
    if not map_path:
        return True  # Considerar como éxito si el mapa no existe

    base_iface_for_key = base_iface_name(iface_service_point)
    if_idx = get_interface_index(base_iface_for_key)
    if if_idx is None:
        raise ValueError(f"Failed to get interface index for {base_iface_for_key}")

    key_bytes = pack_key(if_idx, match_cvlan, match_svlan)
    key_hex = ' '.join(f"0x{b:02x}" for b in key_bytes)

    cmd = ["bpftool", "map", "delete", "pinned", map_path, "key hex", key_hex]
    success, output = run_with_sudo(cmd)
    if not success:
        logger.warning(f"Failed to delete rule: {output}")

def set_promisc_mode(interface, enable=True):
    mode = "on" if enable else "off"
    try:
        subprocess.run(["sudo", "ip", "link", "set", interface, "promisc", mode], check=True)
    except Exception as e:
        logger.warning(f"Failed to set promisc {mode} on {interface}: {e}")

def clear_forwarding_rules_for_interface(interface: str, vlan_id: int = 0, svlan_id: int = 0) -> bool:
    """
    Clear specific forwarding rules for an interface and its VLANs.
    
    Args:
        interface: Interface name (can be in sub@parent format)
        vlan_id: C-VLAN ID to clear (0 for any)
        svlan_id: S-VLAN ID to clear (0 for any)
        
    Returns:
        bool: True if successful, False otherwise
    """
    logger = logging.getLogger('ebpf')
    logger.debug(f"clear_forwarding_rules_for_interface: Clearing rules for {interface} VLAN {vlan_id}/{svlan_id}")
    
    try:
        # Get the parent interface name for the map path
        parent_interface = get_parent_interface(interface)
        if not parent_interface:
            logger.error(f"Could not determine parent interface for {interface}")
            return False
            
        # Get the interface index for the key
        if_idx = get_interface_index(interface.split('@')[0] if '@' in interface else interface)
        if if_idx is None:
            logger.error(f"Could not get interface index for {interface}")
            return False
            
        # Get the map path using the correct function
        map_path = get_bpf_map_path_if_exists(parent_interface)
        if not map_path:
            logger.debug(f"Map not found for parent interface {parent_interface} - no rules to clear")
            return True  # No map means no rules, so technically "cleared"
            
        # If both VLAN IDs are 0, delete all rules for this interface
        if vlan_id == 0 and svlan_id == 0:
            # List all keys in the map
            success, output = run_with_sudo(["bpftool", "map", "dump", "pinned", map_path])
            if not success:
                logger.error(f"Failed to dump map keys: {output}")
                return False
                
            # Parse the output to find keys for this interface
            # Example line: key: 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00  value: ...
            for line in output.split('\n'):
                if not line.startswith('key:'):
                    continue
                    
                # Extract the key as hex bytes
                key_part = line.split("value:")[0].strip()
                if not key_part.startswith('key:'):
                    continue
                    
                key_bytes_str = key_part[4:].strip()
                key_bytes = [int(b, 16) for b in key_bytes_str.split()]
                
                # Parse the interface index from the key
                # Key format: [if_idx(4), cvlan_id(2), svlan_id(2), pad(8)]
                if len(key_bytes) < 4:
                    continue
                    
                key_if_idx = key_bytes[0] | (key_bytes[1] << 8) | (key_bytes[2] << 16) | (key_bytes[3] << 24)
                
                # If the key matches our interface index, delete it
                if key_if_idx == if_idx:
                    # Convert key bytes to hex format for bpftool
                    key_hex = ' '.join(f"{b:02x}" for b in key_bytes)
                    logger.debug(f"Deleting rule for if_idx {if_idx}, key: {key_hex}")
                    delete_success, delete_output = run_with_sudo(["bpftool", "map", "delete", "pinned", map_path, "key hex", "hex", key_hex])
                    if not delete_success:
                        logger.warning(f"Failed to delete key {key_hex}: {delete_output}")
            
            return True
        else:
            # Delete a specific rule based on VLAN IDs
            key_bytes = pack_key(if_idx, vlan_id, svlan_id)
            key_hex = ' '.join(f"{b:02x}" for b in key_bytes)
            
            logger.debug(f"Deleting specific rule for if_idx {if_idx}, C-VLAN {vlan_id}, S-VLAN {svlan_id}")
            success, output = run_with_sudo(["bpftool", "map", "delete", "pinned", map_path, "key", "hex", key_hex])
            
            if not success:
                if "key not found" in output:
                    logger.debug(f"Key not found in map - rule already cleared")
                    return True
                else:
                    logger.warning(f"Failed to delete key: {output}")
                    return False
            
            return True
    except Exception as e:
        logger.error(f"Error clearing forwarding rules: {e}")
        return False

def ifname_to_index(ifname: str) -> int:
    """Return the interface index for a given interface name, or raise if not found."""
    idx = get_interface_index(ifname)
    if idx is None:
        raise ValueError(f"Could not get index for interface '{ifname}'")
    return idx

BPF_FS_ROOT = "/sys/fs/bpf"  # Adjust this if your BPF filesystem is mounted elsewhere

def get_bpf_map_path_if_exists(interface_name: Optional[str]) -> Optional[str]:
    """
    Checks if a pinned BPF map exists for the parent of the given interface and returns its path.
    Args:
        interface_name: The interface name (e.g., eth0, eth0.100). The parent will be determined.
    Returns:
        The map_pin_path (str) on success, or None on failure or if not found.
    """
    if not interface_name:
        logger.error("get_bpf_map_path_if_exists: interface_name must be specified.")
        return None

    parent_iface = get_parent_interface(interface_name)
    if not parent_iface:
        logger.error(f"get_bpf_map_path_if_exists: Could not determine parent interface for '{interface_name}'.")
        return None
    
    # The map is always pinned against the parent interface name
    map_pin_path = f"{BPF_FS_ROOT}/vmark/fw_table_{parent_iface}"
    logger.debug(f"Attempting to check BPF map for parent '{parent_iface}' (from interface '{interface_name}') at: {map_pin_path}")

    check_cmd = ["bpftool", "map", "show", "pinned", map_pin_path]
    exists_success, bpftool_output = run_with_sudo(check_cmd)

    if not exists_success:
        logger.warning(f"BPF map pin path does not exist or is not accessible (checked with bpftool): {map_pin_path}. Output: {bpftool_output}")
        return None
    
    logger.debug(f"BPF map confirmed at {map_pin_path} for parent '{parent_iface}'.")
    return map_pin_path

def clear_map_with_bpftool(map_pin_path: str) -> bool:
    """
    Remove all entries from the BPF map by dumping keys and deleting them one by one.
    Compatible with older bpftool (sin 'map flush').
    """
    logger.debug(f"Attempting to clear map {map_pin_path} using bpftool map dump/delete.")

    # Dump all keys
    dump_cmd = ["bpftool", "map", "dump", "pinned", map_pin_path]
    success, output = run_with_sudo(dump_cmd)
    if not success:
        if "No such file or directory" in output or "map not found" in output or "Error: bpf obj get" in output:
            logger.debug(f"Map {map_pin_path} not found or error accessing, nothing to clear. Output: {output}")
            return True # Considered cleared if map doesn't exist
        logger.error(f"Failed to dump map {map_pin_path} to clear it: {output}")
        return False

    # Parse keys from output
    keys_to_delete = []
    for line in output.splitlines():
        line = line.strip()
        if line.lower().startswith("key:"):
            key_hex = line[4:].split("value:")[0].strip()
            if key_hex:
                keys_to_delete.append(key_hex)

    if not keys_to_delete:
        logger.debug(f"Map {map_pin_path} is empty or no keys found.")
        return True

    # Delete each key
    all_deleted = True
    for key_hex in keys_to_delete:
        del_cmd = ["bpftool", "map", "delete", "pinned", map_pin_path, "key hex", key_hex]
        success, del_output = run_with_sudo(del_cmd)
        if not success:
            logger.warning(f"Failed to delete key {key_hex} from {map_pin_path}: {del_output}")
            all_deleted = False

    return all_deleted

def dump_bpf_map_keys(map_path):
    logger = logging.getLogger('ebpf')
    keys = set()
    try:
        logger.debug(f"Dumping map keys for: {map_path}")
        success, output = run_with_sudo(["bpftool", "map", "dump", "pinned", map_path])
        
        logger.debug(f"bpftool dump success: {success}")
        # Uncomment for verbose output debugging if issues persist:
        # logger.debug(f"bpftool dump output:\n{output}")

        if not success:
            logger.warning(f"dump_bpf_map_keys: Could not dump map {map_path}. bpftool output: {output}")
            return keys

        if not output.strip():
            logger.warning(f"dump_bpf_map_keys: bpftool dump output is empty for {map_path}.")
            return keys

        # Attempt to parse as JSON first, as indicated by bpftool's typical output
        try:
            map_entries = json.loads(output)
            logger.debug(f"Successfully parsed bpftool output as JSON. Found {len(map_entries)} entries.")
            for entry in map_entries:
                if 'key' not in entry:
                    logger.warning("JSON entry missing 'key' field. Skipping.")
                    continue
                
                key_data = entry['key']
                
                ifindex = key_data.get('ingress_ifindex')
                vlan_id = key_data.get('vlan_id') # Corresponds to match_cvlan
                svlan_id = key_data.get('svlan_id') # Corresponds to match_svlan
                bmac_list = key_data.get('bmac')

                if ifindex is None or vlan_id is None or svlan_id is None:
                    logger.warning(f"JSON key data missing required fields (ingress_ifindex, vlan_id, svlan_id): {key_data}. Skipping.")
                    continue

                # Convert bmac list to bytes, default to all zeros if not present or None
                bmac_bytes = bytes(bmac_list) if bmac_list is not None else b'\x00\x00\x00\x00\x00\x00'
                
                try:
                    # Use the existing pack_key to ensure consistency.
                    # pack_key expects integer VLAN IDs.
                    packed_key_from_json = pack_key(int(ifindex), int(vlan_id), int(svlan_id), bmac_bytes)
                    logger.debug(f"Re-packed key from JSON: {packed_key_from_json.hex()} (len={len(packed_key_from_json)})")
                    
                    # pack_key should always produce a 16-byte key as per its definition.
                    if len(packed_key_from_json) == 16:
                        keys.add(packed_key_from_json)
                    else:
                        # This case should ideally not be reached if pack_key is consistent.
                        logger.error(f"pack_key produced unexpected length {len(packed_key_from_json)} from JSON data. Key not added.")
                except ValueError as ve:
                    logger.error(f"ValueError using pack_key with data from JSON entry {key_data} (likely type issue for VLAN IDs): {ve}")
                except Exception as e:
                    logger.error(f"Error using pack_key with data from JSON entry {key_data}: {e}")

        except json.JSONDecodeError:
            logger.warning("Failed to parse bpftool output as JSON. Falling back to line-by-line plain text parsing.")
            # Fallback to original line-by-line parsing
            for line_num, line_content in enumerate(output.splitlines()):
                line = line_content.strip()
                if line.lower().startswith("key:"):
                    key_part = line.split("value:")[0].replace("key:", "").strip()
                    if key_part:
                        try:
                            key_bytes_list = key_part.split()
                            key_bytes = bytes(int(b, 16) for b in key_bytes_list)
                            logger.debug(f"Fallback: Parsed map key: {key_bytes.hex()} (len={len(key_bytes)})")
                            if len(key_bytes) == 16:
                                keys.add(key_bytes)
                            else:
                                logger.warning(f"Fallback: Key from map is {len(key_bytes)} bytes, expected 16: {key_bytes.hex()}. Key not added.")
                        except Exception as e:
                            logger.warning(f"Fallback: Generic error parsing key '{key_part}': {e}")
        
        logger.debug(f"All parsed map keys (count: {len(keys)}): {[k.hex() for k in keys if isinstance(k, bytes)]}")
        return keys
            
    except Exception as e:
        logger.error(f"dump_bpf_map_keys: Unhandled exception during bpftool execution or processing for {map_path}: {e}", exc_info=True)
        return keys

def pack_forwarding_value_with_mac(actions: list) -> bytes:
    """
    Empaqueta el valor para el mapa de forwarding.
    DEBE COINCIDIR EXACTAMENTE CON struct forwarding_value en C (50 bytes).
    - actions: lista de diccionarios con los campos type, tag_type, vlan_id, target_ifindex
    """
    num_actions = len(actions)
    result = struct.pack("<B", num_actions) # 1 byte

    # Empaqueta las acciones (MAX_ACTIONS_PER_RULE = 5)
    # Cada acción es <BBHI (type, tag_type, vlan_id, target_ifindex) = 8 bytes
    for i in range(5):
        if i < len(actions):
            act = actions[i]
            result += struct.pack("<BBHI", act['type'], act['tag_type'], act['vlan_id'], act['target_ifindex'])
        else:
            result += struct.pack("<BBHI", 0, 0, 0, 0)
    # Hasta aquí: 1 + 5*8 = 41 bytes

    # Padding final: 9 bytes para llegar a 50
    result += b"\x00" * 9

    if len(result) != 50:
        logger.error(f"INTERNAL PACKING ERROR: pack_forwarding_value_with_mac generated {len(result)} bytes, but expected 50 bytes to match C struct.")
        raise ValueError(f"Packed forwarding_value is {len(result)} bytes, expected 50")
    return result