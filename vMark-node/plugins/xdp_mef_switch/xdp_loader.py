import os
import subprocess
import logging
import re
import json
from pathlib import Path
from typing import Optional
from .utils import get_parent_interface, run_with_sudo, get_interface_mac
from .map_utils import pack_key, pack_forwarding_value_with_mac, get_bpf_map_path_if_exists, get_interface_index, base_iface_name
## Version: 0.8.0

logger = logging.getLogger('ebpf')


def is_program_pinned_on_parent(parent_interface_name: str) -> bool:
    """Check if an XDP program and its map are pinned for this parent interface."""
    logger.debug(f"is_program_pinned_on_parent: Checking pins for {parent_interface_name}")
    bpf_base_path = get_real_bpf_path() # Should be /sys/fs/bpf
    prog_pin = f'{bpf_base_path}/vmark/xdp_prog_{parent_interface_name}'
    map_pin = f'{bpf_base_path}/vmark/fw_table_{parent_interface_name}'

    prog_exists = os.path.exists(prog_pin)
    map_exists = os.path.exists(map_pin)

    logger.debug(f"  Program pin '{prog_pin}': {'exists' if prog_exists else 'does not exist'}")
    logger.debug(f"  Map pin '{map_pin}': {'exists' if map_exists else 'does not exist'}")

    # For the program to be considered "pinned on parent", both program and map pins should ideally exist.
    # The original function also performed a cleanup if pins were found, which was problematic.
    # This version will only check.
    if prog_exists and map_exists:
        # Additionally, check if it's attached to the interface
        # bpftool net show dev <parent_interface_name>
        success, output = run_with_sudo(["bpftool", "net", "show", "dev", parent_interface_name])
        if success and "xdp/" in output: # "xdp/generic", "xdp/native", "xdp/offload"
            logger.debug(f"XDP program is pinned and attached to {parent_interface_name}.")
            return True
        else:
            logger.debug(f"Pins exist for {parent_interface_name}, but XDP program not actively attached or 'bpftool net show' failed. Output: {output}")
            # Pins might exist but program not loaded/attached. Consider this not "properly pinned and active".
            return False # Or True if just pin existence is enough, but active attachment is better.
    
    logger.debug(f"Program or map pins not found for {parent_interface_name}.")
    return False


def _ensure_bpf_fs() -> bool:
    """Ensure BPF filesystem is mounted."""
    if not os.path.ismount('/sys/fs/bpf'): # Corrected path
        try:
            logger.info("BPF filesystem not mounted. Attempting to mount.")
            success, output = run_with_sudo(['mount', '-t', 'bpf', 'bpf', '/sys/fs/bpf']) # Corrected path
            if not success:
                logger.error(f"Failed to mount BPF filesystem: {output}")
                return False
            logger.info("Mounted BPF filesystem at /sys/fs/bpf")
        except FileNotFoundError: # This might catch if 'mount' itself is not found, though run_with_sudo also handles this.
            logger.error("Failed to mount BPF filesystem: 'mount' command not found.")
            return False
        except Exception as e: # Catch any other unexpected errors during the mount attempt
            logger.error(f"An unexpected error occurred while trying to mount BPF filesystem: {e}")
            return False
    else:
        logger.debug("bpffs already mounted at /sys/fs/bpf") # Corrected path
    return True

def _ensure_pin_path(path: str) -> bool:
    """Ensure pin directory exists using sudo ls for accurate check."""
    try:
        # Use sudo ls to check existence, similar to check_bpf_state
        result = subprocess.run(
            ["sudo", "ls", path],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"Pin path {path} already exists.")
            return True
        else:
            logger.info(f"Pin path {path} does not exist. Attempting to create.")
            success_mkdir, out_mkdir = run_with_sudo(['mkdir', '-p', path])
            if not success_mkdir:
                logger.error(f"Failed to create directory {path}: {out_mkdir}")
                return False
            if os.geteuid() != 0:
                success_chmod, out_chmod = run_with_sudo(['chmod', '755', path])
                if not success_chmod:
                    logger.warning(f"Failed to chmod {path} after creation: {out_chmod}")
            return True
    except Exception as e:
        logger.error(f"Error ensuring pin path {path}: {e}")
        return False

def check_xdp_requirements() -> bool:
    """Check if system meets XDP requirements."""
    try:
        # Check kernel version
        kernel_version = subprocess.run(['uname', '-r'], capture_output=True, text=True, check=True).stdout.strip()
        major, minor = map(int, kernel_version.split('.')[:2])
        if major < 4 or (major == 4 and minor < 18):
            logger.warning(f"Kernel {kernel_version} may have limited XDP support. Recommend 4.18+")
        logger.info(f"Kernel version check passed: {kernel_version}")

        # Check bpftool availability
        subprocess.run(['bpftool', 'version'], capture_output=True, text=True, check=True)
        logger.info("bpftool is installed")

        # Check XDP object file
        xdp_obj_path = Path(__file__).parent / "xdp_forwarding.o"
        if not xdp_obj_path.exists():
            logger.error(f"XDP object file not found: {xdp_obj_path}")
            return False
        logger.info(f"XDP object file found: {xdp_obj_path}")

        return True
    except Exception as e:
        logger.error(f"XDP requirements check failed: {e}")
        return False

def check_xdp_mode_support(interface: str) -> str:
    """Check supported XDP modes for interface."""
    actual_parent_interface = get_parent_interface(interface)
    if not actual_parent_interface:
        logger.warning(f"Could not determine parent interface for {interface}, defaulting to generic XDP mode.")
        return 'generic'

    try:
        # Check for hardware offload support
        offload_success, offload_output = run_with_sudo(
            ['bpftool', 'feature', 'probe', 'dev', actual_parent_interface, 'xdpoffload']
        )
        if offload_success and 'is supported' in offload_output:
            logger.info(f"{actual_parent_interface} supports XDP offload")
            return 'offload'
        elif not offload_success:
            logger.debug(f"xdpoffload check failed for {actual_parent_interface}: {offload_output}")

        # Check for native XDP support
        native_success, native_output = run_with_sudo(
            ['bpftool', 'feature', 'probe', 'dev', actual_parent_interface, 'xdpdrv']
        )
        if native_success and 'is supported' in native_output:
            logger.info(f"{actual_parent_interface} supports native XDP (xdpdrv)")
            return 'native'
        elif not native_success:
            logger.debug(f"xdpdrv check failed for {actual_parent_interface}: {native_output}")

        logger.info(f"{actual_parent_interface} using generic XDP mode")
        return 'generic'

    except Exception as e:
        logger.warning(f"XDP mode check encountered an exception for {actual_parent_interface}: {e}")
        return 'generic'

def get_parent_interface(interface_name: str) -> str:
    """Find actual parent physical interface.
    Handles interface_name in 'sub@parent' format or queries 'ip link show' for sub-interfaces.
    """
    logger.debug(f"get_parent_interface: Finding parent for '{interface_name}'")
    if not interface_name:
        return ""

    # If interface_name itself is in "sub@parent" format
    if '@' in interface_name:
        parts = interface_name.split('@', 1)
        if len(parts) == 2 and parts[1]:
            logger.debug(f"Parent directly parsed from '{interface_name}' as '{parts[1]}'")
            return parts[1]
        else:
            logger.warning(f"Malformed interface name with '@': {interface_name}. Will attempt to query using the part before '@' or the full name.")
            # Use the part before '@' if it exists, otherwise the original malformed name for the query
            query_name = parts[0] if parts[0] else interface_name
    else:
        query_name = interface_name

    try:
        # Query the system for the base/sub-interface name
        # Example 'ip -o link show dev if-a-cv90' output:
        # "2: if-a-cv90@ens160: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 xdp ..."
        result = subprocess.run(
            ['ip', '-o', 'link', 'show', 'dev', query_name],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            logger.warning(f"Could not get interface info for '{query_name}' using 'ip link show'. Assuming it's a base interface or does not exist.")
            return query_name # Return the name we queried

        output = result.stdout.strip()
        # Regex to find "sub@parent" in "idx: sub@parent:"
        match = re.search(r'^\d+:\s*[^@\s]+@([^:\s]+)', output)
        if match:
            parent = match.group(1)
            logger.debug(f"Found parent '{parent}' for '{query_name}' from 'ip link show' output")
            return parent
        
        logger.debug(f"No '@' in 'ip link show' output for '{query_name}', assuming it's a base physical interface.")
        return query_name # Return the name we queried, likely a base physical interface

    except Exception as e:
        logger.error(f"Error finding parent for '{interface_name}' (queried as '{query_name}'): {e}")
        return query_name # Fallback

def attach_xdp_program(interface_name: str, program_path: str) -> bool:
    """Attach XDP program to interface."""
    # ... (initial checks remain the same) ...
    logger.info(f"attach_xdp_program called with interface_name={interface_name}, program_path={program_path}")
    if not os.path.exists(program_path):
        logger.error(f"XDP object file does not exist at {program_path}")
        return False
        
    if not check_kernel_version(): # This function itself logs
        return False
    
    if not check_bpftool_installed(): # This function itself logs
        return False
    
    if not check_program_file(program_path): # This function itself logs
        return False
    
    actual_parent_interface = get_parent_interface(interface_name)
    if not actual_parent_interface:
        logger.error(f"Could not determine parent interface for '{interface_name}'")
        return False
    
    logger.info(f"Determined parent interface: {actual_parent_interface} for requested interface: {interface_name}")

    logger.info(f"Attempting to detach any existing XDP program and pins from parent interface '{actual_parent_interface}' before attaching new one.")
    if not detach_xdp_program(actual_parent_interface, force=True):
        logger.warning(f"detach_xdp_program (force=True) reported issues for {actual_parent_interface}, but proceeding with attach attempt.")

    bpf_mount_point = get_real_bpf_path()
    prog_pin_path = f'{bpf_mount_point}/vmark/xdp_prog_{actual_parent_interface}'
    map_pin_path = f'{bpf_mount_point}/vmark/fw_table_{actual_parent_interface}'
    pin_dir = os.path.dirname(prog_pin_path)
    
    if not _ensure_pin_path(pin_dir):
        logger.error(f"Failed to ensure pin directory {pin_dir}")
        return False

    logger.debug(f"map_pin_path type: {type(map_pin_path)}, value: {map_pin_path}")
    logger.debug(f"prog_pin_path type: {type(prog_pin_path)}, value: {prog_pin_path}")
    logger.debug(f"program_path (object file) type: {type(program_path)}, value: {program_path}")

    # Step 1: Load XDP program and pin the program itself
    load_prog_cmd = [
        "bpftool", "prog", "load", program_path, prog_pin_path,
        "type", "xdp",
    ]
    logger.info(f"Loading and pinning XDP program: sudo {' '.join(map(str,load_prog_cmd))}")
    success_prog_load, output_prog_load = run_with_sudo(load_prog_cmd)

    if not success_prog_load:
        logger.error(f"Failed to load XDP program to '{prog_pin_path}': {output_prog_load}")
        if os.path.exists(prog_pin_path):
            run_with_sudo(["rm", "-f", prog_pin_path])
        return False
    logger.info(f"Successfully loaded XDP program to '{prog_pin_path}'")

    # Step 2: Pin the 'fw_table' map.
    map_id_to_pin = None
    map_pinned_successfully = False

    show_prog_cmd = ["bpftool", "prog", "show", "pinned", prog_pin_path, "--json"]
    logger.info(f"Getting map ID(s) for program '{prog_pin_path}': sudo {' '.join(show_prog_cmd)}")
    success_show_prog, output_show_prog = run_with_sudo(show_prog_cmd)

    if success_show_prog:
        try:
            prog_details = json.loads(output_show_prog)
            if isinstance(prog_details, dict):
                map_ids = prog_details.get("map_ids", [])
                logger.info(f"Found map IDs: {map_ids}")
                
                # Inspect each map to find fw_table
                for mid in map_ids:
                    show_map_cmd = ["bpftool", "map", "show", "id", str(mid), "--json"]
                    success_show_map, output_show_map = run_with_sudo(show_map_cmd)
                    if success_show_map:
                        try:
                            map_details = json.loads(output_show_map)
                            if map_details.get("name") == "fw_table" and map_details.get("type") == "hash":
                                map_id_to_pin = mid
                                logger.info(f"Found fw_table (hash map) with ID {map_id_to_pin}")
                                break
                        except json.JSONDecodeError:
                            continue
                
                if not map_id_to_pin:
                    logger.error("Could not find fw_table hash map among program maps")
                    return False
            else:
                logger.error(f"Unexpected program details format: {prog_details}")
                return False
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from program show command: {output_show_prog}")
            return False
        except Exception as e:
            logger.error(f"Error processing program details: {e}")
            return False
    else:
        logger.error(f"Failed to get program details: {output_show_prog}")
        return False

    # Pin the map using the found ID
    if map_id_to_pin:
        pin_map_cmd = ["bpftool", "map", "pin", "id", str(map_id_to_pin), map_pin_path]
        logger.info(f"Pinning fw_table map (ID {map_id_to_pin}): sudo {' '.join(pin_map_cmd)}")
        success_map_pin, output_map_pin = run_with_sudo(pin_map_cmd)
        if not success_map_pin:
            logger.error(f"Failed to pin fw_table map: {output_map_pin}")
            run_with_sudo(["rm", "-f", prog_pin_path])
            return False
        logger.info(f"Successfully pinned fw_table map to {map_pin_path}")
    else:
        logger.error("No valid map ID found for fw_table")
        run_with_sudo(["rm", "-f", prog_pin_path])
        return False


    # Actualizar el mapa de forwarding con una entrada de ejemplo
    key = pack_key(ifindex=1, vlan_id=0, svlan_id=0)  # Ejemplo de clave

    # Define una lista de acciones vacía para la entrada de ejemplo/inicialización
    example_actions = []
    
    # Llama a la función con out_mac_bytes_for_init y example_actions
    value = pack_forwarding_value_with_mac(example_actions)
    
    update_cmd = [
        "bpftool", "map", "update", "pinned", map_pin_path,
        "key", "hex", *[f"{b:02x}" for b in key],
        "value", "hex", *[f"{b:02x}" for b in value]
    ]
    success_update, output_update = run_with_sudo(update_cmd)
    if not success_update:
        logger.error(f"Error actualizando el mapa de forwarding: {output_update}")
        return False
    logger.info(f"Mapa de forwarding inicializado correctamente.")

    # Determine XDP mode (native, generic, offload)
    # Using ethtool for a hint, but bpftool feature probe is more direct for xdpdrv/xdpoffload
    xdp_mode_to_try = "xdpdrv" # Default to driver/native mode
    
    probe_offload_success, probe_offload_output = run_with_sudo(['bpftool', 'feature', 'probe', 'dev', actual_parent_interface, 'xdpoffload'])
    if probe_offload_success and 'is supported' in probe_offload_output.lower():
        xdp_mode_to_try = "xdpoffload"
        logger.info(f"Interface {actual_parent_interface} supports XDP offload.")
    else:
        probe_drv_success, probe_drv_output = run_with_sudo(['bpftool', 'feature', 'probe', 'dev', actual_parent_interface, 'xdpdrv'])
        if probe_drv_success and 'is supported' in probe_drv_output.lower():
            xdp_mode_to_try = "xdpdrv"
            logger.info(f"Interface {actual_parent_interface} supports XDP driver mode (xdpdrv).")
        else:
            xdp_mode_to_try = "xdpgeneric" # bpftool uses xdpgeneric
            logger.info(f"Interface {actual_parent_interface} does not appear to support xdpoffload or xdpdrv, defaulting to xdpgeneric. Offload probe: '{probe_offload_output}'. Drv probe: '{probe_drv_output}'.")

    logger.info(f"Attempting to attach XDP to {actual_parent_interface} in '{xdp_mode_to_try}' mode.")
    attach_cmd = [
        "bpftool", "net", "attach", "xdp", "pinned", prog_pin_path,
        "dev", actual_parent_interface, "overwrite"  # Add overwrite before mode
    ]
    
    # Add mode after overwrite
    attach_cmd.append(xdp_mode_to_try)

    logger.info(f"Attaching XDP program: sudo {' '.join(attach_cmd)}")
    success, output = run_with_sudo(attach_cmd)
    if not success:
        logger.error(f"Failed to attach XDP program to interface {actual_parent_interface} using mode {xdp_mode_to_try}: {output}")
        run_with_sudo(["rm", "-f", map_pin_path])
        run_with_sudo(["rm", "-f", prog_pin_path])
        return False
    
    logger.info(f"Successfully loaded, pinned, and attached XDP to {actual_parent_interface} in {xdp_mode_to_try} mode")
    return True

def detach_xdp_program(interface_name: str, force: bool = False) -> bool:
    """
    Detach XDP program and clean up resources.

    If force is True:
        - Detaches XDP program from the parent interface using 'bpftool net detach' and 'ip link set xdp off'.
        - Removes BPF program pin for the parent interface.
        - Removes BPF map pin for the parent interface.
    If force is False (default):
        - This mode is intended for scenarios where you only want to clear rules
          related to a sub-interface without detaching the main XDP program from the parent.
        - Currently, this function does not implement rule clearing.
          Rule clearing should be handled by map_utils.clear_forwarding_rules_for_interface directly.
          If `force=False` is called, it will log a warning and do nothing to XDP attachments/pins.

    Args:
        interface_name: The interface name (can be sub-interface like eth0.100 or parent like eth0).
                        The parent interface will be determined for actual XDP operations.
        force: If True, performs a full detach and cleanup. 
               If False, does nothing to XDP attachments/pins (rule clearing should be separate).

    Returns:
        True if operations were successful or not needed, False on failure.
    """
    logger.info(f"detach_xdp_program called for interface '{interface_name}' with force={force}")
    actual_parent_interface = get_parent_interface(interface_name)
    if not actual_parent_interface:
        logger.error(f"detach_xdp_program: Could not determine parent for '{interface_name}'")
        return False

    if not force:
        logger.warning(f"detach_xdp_program called with force=False for interface '{interface_name}'. "
                       "This function, when force=False, does not modify XDP attachments or pins. "
                       "For rule clearing, call 'clear_forwarding_rules_for_interface' from map_utils directly.")
        # Previously, this branch tried to call clear_forwarding_rules_for_interface.
        # However, that function takes vlan_id and svlan_id, which are not parameters here.
        # Making this a no-op for force=False simplifies its contract: it's about XDP program/pin lifecycle.
        return True # No operation performed, considered successful in this context.

    # Force is True: Full cleanup for the parent interface
    logger.info(f"Forced detach: Removing XDP program and pins for parent interface '{actual_parent_interface}'")
    
    all_successful = True

    # 1. Detach XDP from the network interface
    logger.debug(f"Attempting to detach XDP from '{actual_parent_interface}' using 'bpftool net detach'")
    detach_bpftool_success, detach_bpftool_out = run_with_sudo(
        ['bpftool', 'net', 'detach', 'xdp', 'dev', actual_parent_interface]
    )
    if not detach_bpftool_success:
        # Log warning but continue, as 'ip link' might also work or pins might still need removal
        logger.warning(f"Failed to detach XDP from '{actual_parent_interface}' using 'bpftool net detach' (continuing): {detach_bpftool_out}")
        # all_successful = False # Don't mark as failure yet, ip link might succeed or pins are more critical

    logger.debug(f"Attempting to detach XDP from '{actual_parent_interface}' using 'ip link set xdp off'")
    detach_ip_success, detach_ip_out = run_with_sudo(
        ['ip', 'link', 'set', 'dev', actual_parent_interface, 'xdp', 'off']
    )
    if not detach_ip_success:
        logger.warning(f"Failed to detach XDP from '{actual_parent_interface}' using 'ip link set xdp off' (continuing): {detach_ip_out}")
        # all_successful = False # Don't mark as failure yet

    # 2. Remove BPF program and map pins
    bpf_base_path = get_real_bpf_path() # Should be /sys/fs/bpf
    prog_pin_path = f'{bpf_base_path}/vmark/xdp_prog_{actual_parent_interface}'
    map_pin_path = f'{bpf_base_path}/vmark/fw_table_{actual_parent_interface}'

    for pin_path in [prog_pin_path, map_pin_path]:
        # Always attempt to remove the pin using sudo. 'rm -f' will not error if the file doesn't exist.
        logger.debug(f"Attempting to remove pin (if it exists): {pin_path}")
        rm_success, rm_out = run_with_sudo(['rm', '-f', pin_path])
        if not rm_success:
            # This indicates 'sudo rm -f' itself failed, which is a more serious issue
            # (e.g., pin_path is a non-empty directory, or a critical permission error).
            logger.warning(f"Command 'sudo rm -f {pin_path}' failed: {rm_out}")
            all_successful = False # Failure to remove a pin is a problem
        else:
            # 'sudo rm -f' command executed successfully.
            # This means the file is now gone, or it was not there to begin with.
            logger.info(f"Ensured pin is removed (or was not present): {pin_path}")
            
    if all_successful:
        logger.info(f"Successfully detached XDP and cleaned pins for parent interface '{actual_parent_interface}'")
    else:
        logger.warning(f"Completed detach_xdp_program for parent '{actual_parent_interface}' with some issues.")
        
    return all_successful

def ensure_xdp_program_attached(interface_name: str, program_path: str) -> bool:
    """Ensure XDP program is attached to the parent of interface_name."""
    logger.debug(f"ensure_xdp_program_attached: Starting for interface '{interface_name}' using program {program_path}")
    
    if not check_xdp_requirements(): # This function logs its own errors
        return False

    actual_parent_interface = get_parent_interface(interface_name)
    if not actual_parent_interface:
        logger.error(f"ensure_xdp_program_attached: Could not determine parent for '{interface_name}'")
        return False
    logger.debug(f"ensure_xdp_program_attached: Using parent interface '{actual_parent_interface}'")

    # Check if program is already pinned AND attached to the parent interface
    if is_program_pinned_on_parent(actual_parent_interface): # This now also checks for active attachment
        logger.info(f"XDP program already pinned and attached on parent '{actual_parent_interface}'. No action needed.")
        return True

    logger.info(f"XDP program not active on '{actual_parent_interface}'. Proceeding with attach_xdp_program.")
    
    # _ensure_bpf_fs() is important before any bpftool operations if not already guaranteed.
    # attach_xdp_program should ideally handle this, or it should be called here.
    # Let's assume _ensure_bpf_fs() is called at a higher level (e.g. CLI start) or implicitly by bpftool.
    # For safety, can add:
    if not _ensure_bpf_fs():
        logger.error("ensure_xdp_program_attached: BPF filesystem not available.")
        return False

    return attach_xdp_program(interface_name, program_path) # interface_name is fine, attach_xdp_program gets parent



def check_kernel_version() -> bool:
    """Check if kernel version supports XDP."""
    try:
        kernel_version = subprocess.run(['uname', '-r'], capture_output=True, text=True, check=True).stdout.strip()
        logger.debug(f"Kernel version: {kernel_version}")
        
        # Parse kernel version
        version_parts = kernel_version.split('.')
        if len(version_parts) >= 2:
            major, minor = int(version_parts[0]), int(version_parts[1])
            if major < 4 or (major == 4 and minor < 18):
                logger.warning(f"Kernel {kernel_version} may have limited XDP support. Recommend 4.18+")
                # Don't fail here, just warn
            logger.debug(f"Kernel version check passed: {kernel_version}")
            return True
        else:
            logger.error(f"Could not parse kernel version: {kernel_version}")
            return False
    except Exception as e:
        logger.error(f"Error checking kernel version: {e}")
        return False

def check_bpftool_installed() -> bool:
    """Check if bpftool is installed."""
    try:
        result = subprocess.run(['which', 'bpftool'], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("bpftool not found in PATH. Install with: sudo apt install linux-tools-common linux-tools-generic")
            return False
        logger.debug("bpftool is installed")
        return True
    except Exception as e:
        logger.error(f"Error checking for bpftool: {e}")
        return False

def check_program_file(program_path: str) -> bool:
    """Check if XDP program file exists."""
    if not os.path.exists(program_path):
        logger.error(f"XDP program file not found: {program_path}")
        return False
    logger.debug(f"XDP object file found: {program_path}")
    return True

def get_real_bpf_path() -> str:
    """Always use the canonical BPF filesystem path."""
    return '/sys/fs/bpf'
    
    # The path that bpftool expects for pins is always /sys/fs/bpf
    # regardless of any symlinks or other mount points, so we should return this
    expected_path = '/sys/fs/bpf'
    logger.debug(f"Using bpftool expected BPF path {expected_path}")
    return expected_path
