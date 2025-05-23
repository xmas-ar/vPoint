import subprocess
import logging
from typing import Optional
import os
import re

logger = logging.getLogger('ebpf')

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
            query_name = parts[0] if parts[0] else interface_name
    else:
        query_name = interface_name

    try:
        result = subprocess.run(
            ['ip', '-o', 'link', 'show', 'dev', query_name],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            logger.warning(f"Could not get interface info for '{query_name}' using 'ip link show'. Assuming it's a base interface or does not exist.")
            return query_name

        output = result.stdout.strip()
        match = re.search(r'^\d+:\s*[^@\s]+@([^:\s]+)', output)
        if match:
            parent = match.group(1)
            logger.debug(f"Found parent '{parent}' for '{query_name}' from 'ip link show' output")
            return parent
        
        logger.debug(f"No '@' in 'ip link show' output for '{query_name}', assuming it's a base physical interface.")
        return query_name

    except Exception as e:
        logger.error(f"Error finding parent for '{interface_name}' (queried as '{query_name}'): {e}")
        return query_name

def run_with_sudo(command: list):
    """
    Runs a command, prepending 'sudo' if the current user is not root and sudo -n works.
    Returns a tuple: (bool_success, output_string).
    """
    try:
        # Convert all elements to str (important for Path objects)
        cmd_to_run = [str(x) for x in command]

        if os.geteuid() != 0:
            cmd_to_run.insert(0, 'sudo')

        result = subprocess.run(cmd_to_run, capture_output=True, text=True, check=False)

        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            error_output = f"Error (code {result.returncode})"
            if result.stdout:
                error_output += f"\nSTDOUT: {result.stdout.strip()}"
            if result.stderr:
                error_output += f"\nSTDERR: {result.stderr.strip()}"
            logger.debug(f"Command failed: {' '.join(cmd_to_run)}\nOutput:\n{error_output}")
            return False, error_output.strip()

    except FileNotFoundError:
        logger.error(f"Command not found: {cmd_to_run[0] if cmd_to_run else 'empty command'}")
        return False, f"Command not found: {cmd_to_run[0] if cmd_to_run else 'empty command'}"
    except Exception as e:
        logger.error(f"Exception running command {' '.join([str(x) for x in cmd_to_run])}: {e}")
        return False, str(e)

def get_interface_mac(interface_name: str) -> Optional[str]:
    """
    Obtiene la dirección MAC de una interfaz.
    """
    try:
        result = subprocess.run(
            ["ip", "link", "show", interface_name],
            capture_output=True,
            text=True,
            check=True
        )
        for line in result.stdout.splitlines():
            if "link/ether" in line:
                return line.split()[1]  # La dirección MAC está en la segunda columna
    except Exception as e:
        logger.error(f"Error obteniendo la dirección MAC de '{interface_name}': {e}")
    return None