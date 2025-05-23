## Version: 0.8.0
import json
import os
import ctypes
from .utils import get_interface_mac
import logging  # Make sure this is at the top
from pathlib import Path
from .map_utils import (
    clear_map_with_bpftool,  # or clear_all_entries_from_map if that's your function name
    add_forwarding_rule
)
import subprocess

# Add this line near the top of the file
logger = logging.getLogger('ebpf')

# Define the path to the rules file
RULES_FILE_PATH = Path.home() / ".vmark" / "forwarding_table.json"


def load_rules():
    """Loads forwarding rules from the JSON file."""
    if not RULES_FILE_PATH.exists():
        return []
    try:
        with open(RULES_FILE_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading rules from {RULES_FILE_PATH}: {e}")
        return []

def save_rules(rules):
    """Saves forwarding rules to the JSON file."""
    try:
        RULES_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(RULES_FILE_PATH, 'w') as f:
            json.dump(rules, f, indent=4)
    except IOError as e:
        logger.error(f"Error saving rules to {RULES_FILE_PATH}: {e}")

def detect_conflicts(rules, new_rule=None):
    """
    Detects if a new rule conflicts with existing rules.
    Checks for name uniqueness and duplicate (in_interface, match_cvlan, match_svlan).
    """
    # Helper to get the tuple for comparison
    def rule_key(rule):
        return (
            rule.get("in_interface"),
            int(rule.get("match_cvlan")) if rule.get("match_cvlan") is not None else None,
            int(rule.get("match_svlan")) if rule.get("match_svlan") is not None else None,
        )

    # If no new_rule provided, check for conflicts among existing rules
    if new_rule is None:
        # Check for duplicate names
        names = [rule["name"] for rule in rules]
        if len(names) != len(set(names)):
            for name in set(names):
                if names.count(name) > 1:
                    return f"Multiple rules with name '{name}' exist."
        # Check for duplicate (in_interface, match_cvlan, match_svlan)
        keys = [rule_key(rule) for rule in rules]
        if len(keys) != len(set(keys)):
            for key in set(keys):
                if keys.count(key) > 1:
                    return f"Multiple rules for in_interface={key[0]}, cvlan={key[1]}, svlan={key[2]} exist."
        return None

    # Check if new rule conflicts with existing rules
    for rule in rules:
        if rule["name"] == new_rule["name"]:
            return f"Rule name '{new_rule['name']}' already exists."
        if rule_key(rule) == rule_key(new_rule):
            return (
                f"Rule for in_interface={rule_key(new_rule)[0]}, "
                f"cvlan={rule_key(new_rule)[1]}, svlan={rule_key(new_rule)[2]} already exists."
            )
    return None

def rebuild_forwarding_map(map_pin_path: str):
    """
    Rebuilds the BPF forwarding map from the active rules in rules.json.
    Clears the existing map and re-adds all active rules using bpftool.
    """
    logger.info(f"Rebuilding BPF forwarding map using pinned map: {map_pin_path}")

    if not map_pin_path:
        logger.error("Invalid BPF map pin path provided. Cannot rebuild map.")
        return

    # Clear all existing entries in the map using bpftool
    try:
        clear_map_with_bpftool(map_pin_path)
        logger.info(f"Successfully cleared map {map_pin_path}.")
    except Exception as e:
        logger.error(f"Failed to clear map {map_pin_path} during rebuild: {e}")
        raise

    rules = load_rules()
    active_rules = [rule for rule in rules if rule.get("active", False)]
    
    if not active_rules:
        logger.info("No active rules to apply to BPF map. Map remains clear.")
        return

    logger.info(f"Applying {len(active_rules)} active rules to map {map_pin_path}.")
    
    for rule in active_rules:
        try:
            logger.debug(f"Processing rule for rebuild: {rule}")
            
            # Extract parameters from the rule
            in_interface = rule.get("in_interface")
            out_interface = rule.get("out_interface")
            match_cvlan = rule.get("match_cvlan")
            match_svlan = rule.get("match_svlan") 
            pop_tags = rule.get("pop_tags", 0)
            push_svlan = rule.get("push_svlan")
            push_cvlan = rule.get("push_cvlan")
            
            # Ensure numeric values are integers
            if isinstance(match_cvlan, str) and match_cvlan.lower() == 'null':
                match_cvlan = None
            if match_cvlan is not None:
                match_cvlan = int(match_cvlan)
                
            if isinstance(match_svlan, str) and match_svlan.lower() == 'null':
                match_svlan = None
            if match_svlan is not None:
                match_svlan = int(match_svlan)
                
            if isinstance(pop_tags, str):
                pop_tags = int(pop_tags)
                
            if isinstance(push_svlan, str) and push_svlan.lower() == 'null':
                push_svlan = None
            if push_svlan is not None:
                push_svlan = int(push_svlan)
                
            if isinstance(push_cvlan, str) and push_cvlan.lower() == 'null':
                push_cvlan = None
            if push_cvlan is not None:
                push_cvlan = int(push_cvlan)
            
            # Build actions list from the rule properties
            actions_list = []

            # Add pop actions if needed (these should come first)
            if pop_tags > 0:
                if pop_tags == 2:
                    actions_list.append({"type": "pop", "tag": "svlan"})
                    actions_list.append({"type": "pop", "tag": "cvlan"})
                elif pop_tags == 1:
                    actions_list.append({"type": "pop", "tag": "cvlan"})

            # Add push actions if needed (these should come after pop)
            if push_svlan is not None:
                actions_list.append({
                    "type": "push", 
                    "tag": "svlan",
                    "value": push_svlan
                })

            if push_cvlan is not None:
                actions_list.append({
                    "type": "push", 
                    "tag": "cvlan",
                    "value": push_cvlan
                })

            # Add the forward action last
            if out_interface:
                all_endpoints_details = {
                    "a": {"interface": out_interface}
                }
                current_endpoint_key = "a"
                actions_list.append({
                    "type": "forward",
                    "to": "a"
                })
            else:
                all_endpoints_details = {}
                current_endpoint_key = None
            
            # Skip if no input interface or actions
            if not in_interface or not actions_list:
                logger.error(f"Skipping rule '{rule.get('name', 'Unnamed')}' due to missing 'in_interface' or actions.")
                continue

            logger.info(f"Rule '{rule.get('name')}': Preparing to add to BPF. In-interface: {in_interface}, Match CVLAN: {match_cvlan}, Match SVLAN: {match_svlan}")
            logger.info(f"Generated actions_list for rule '{rule.get('name')}': {actions_list}") # CRITICAL LOG
            logger.info(f"All endpoints details for rule '{rule.get('name')}': {all_endpoints_details}")
            logger.info(f"Current endpoint key for rule '{rule.get('name')}': {current_endpoint_key}")

            # Habilitar promisc antes de agregar la regla
            if in_interface:
                set_promisc_mode(in_interface, enable=True)

            # Add the rule to the BPF map
            add_forwarding_rule(
                in_iface_service_point=in_interface,
                match_cvlan=match_cvlan,
                match_svlan=match_svlan,
                actions=actions_list,
                all_endpoints_details=all_endpoints_details,
                current_endpoint_key_for_actions=current_endpoint_key
            )
            logger.info(f"Successfully applied rule '{rule.get('name', 'Unnamed')}' to map {map_pin_path}.")
        except Exception as e:
            logger.error(f"Failed to apply rule '{rule.get('name', 'Unnamed')}' during rebuild: {e}", exc_info=True)
            # Continue with other rules
    
    logger.info(f"BPF map rebuild completed for {map_pin_path}.")

def set_promisc_mode(interface, enable=True):
    """Set or unset promiscuous mode on an interface."""
    mode = "on" if enable else "off"
    try:
        subprocess.run(["sudo", "ip", "link", "set", interface, "promisc", mode], check=True)
    except Exception as e:
        logger.warning(f"Failed to set promisc {mode} on {interface}: {e}")