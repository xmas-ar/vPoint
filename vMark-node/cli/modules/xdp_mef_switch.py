import json
import subprocess
from typing import Optional
from pathlib import Path
import logging # Add logging import

from plugins.xdp_mef_switch.map_utils import get_network_interfaces, get_bpf_map_path_if_exists
from plugins.xdp_mef_switch.xdp_loader import get_parent_interface, ensure_xdp_program_attached # Import necessary functions
# Use the functions from the forwarding_table module
from plugins.xdp_mef_switch.forwarding_table import (
    load_rules, save_rules, detect_conflicts, rebuild_forwarding_map
)

logger = logging.getLogger(__name__) # Initialize logger for this module

create_rule_params = [
    "name", "in_interface", "svlan", "cvlan", "out_interface", "pop_tags", "push_svlan", "push_cvlan"
]

def get_command_tree():
    interfaces = get_network_interfaces()
    params = [
        "name", "in_interface", "svlan", "cvlan", "out_interface", "pop_tags", "push_svlan", "push_cvlan"
    ]

    def build_param_tree(remaining):
        if not remaining:
            return {}
        tree = {}
        for param in remaining:
            tree[param] = {f"<{param}>": build_param_tree([p for p in remaining if p != param])}
        return tree

    create_rule_tree = build_param_tree(params)

    # --- Agrega los nombres de reglas actuales a show-forwarding ---
    rules = load_rules()
    rule_names = sorted([rule["name"] for rule in rules if "name" in rule])

    show_forwarding_tree = {
        "": {},
        "json": {}
    }
    for name in rule_names:
        show_forwarding_tree[name] = {}

    tree = {
        "create-rule": create_rule_tree,
        "delete-rule": {
            "<name>": {}
        },
        "enable-rule": {
            "<name>": {}
        },
        "disable-rule": {
            "<name>": {}
        },
        "show-forwarding": show_forwarding_tree
    }
    return tree

def get_descriptions():
    interfaces = get_network_interfaces()
    rules = load_rules()
    rule_names = sorted([rule["name"] for rule in rules if "name" in rule])
    
    rule_names_help_suffix = "Available rules: " + ", ".join(rule_names) + "." if rule_names else "No rules configured."

    descriptions = {
        "create-rule": {
            "": "Create a new forwarding rule (inactive by default).",
            "name": {"": "Unique rule name (e.g., rule1)", "<name>": {"": "Enter the rule name"}},
            "in_interface": {"": "Input interface name (e.g., eth0)", 
                             "<in_interface>": {"": "Select the input interface", "_options": interfaces}},
            "svlan": {"": "Service VLAN ID (1-4094) or 'null'", "<svlan>": {"": "Enter SVLAN or 'null'"}},
            "cvlan": {"": "Customer VLAN ID (1-4094) or 'null'", "<cvlan>": {"": "Enter CVLAN or 'null'"}},
            "out_interface": {"": "Output interface name (e.g., eth1)", 
                              "<out_interface>": {"": "Select the output interface", "_options": interfaces}},
            "pop_tags": {
                "": "Number of VLAN tags to pop.",
                "<pop_tags>": {"": "0 (no pop), 1 (outermost), 2 (two outermost)."}
            },
            "push_svlan": {"": "SVLAN ID to push (1-4094) or 'null'", "<push_svlan>": {"": "Enter SVLAN to push or 'null'"}},
            "push_cvlan": {"": "CVLAN ID to push (1-4094) or 'null'", "<push_cvlan>": {"": "Enter CVLAN to push or 'null'"}},
        },
        "delete-rule": {
            "": "Delete a forwarding rule (must be inactive).",
            "<name>": {"": f"Name of the rule to delete. {rule_names_help_suffix}", "_options": rule_names}
        },
        "enable-rule": {
            "": "Enable a rule and its egress pair, then rebuild BPF map.",
            "<name>": {"": f"Name of the rule to enable. {rule_names_help_suffix}", "_options": rule_names}
        },
        "disable-rule": {
            "": "Disable a rule and its egress pair, then rebuild BPF map.",
            "<name>": {"": f"Name of the rule to disable. {rule_names_help_suffix}", "_options": rule_names}
        },
        "show-forwarding": {
            "": "Show all rules. Optionally specify a rule name or 'json'.",
            "json": {"": "Show table in JSON format."}
            # Descriptions for rule names will be added below
        }
    }

    # Dynamically add descriptions for individual rule names under 'show-forwarding'
    if rule_names:
        for name in rule_names:
            # Ensure not to overwrite existing keys like "" or "json"
            if name not in descriptions["show-forwarding"]: 
                 descriptions["show-forwarding"][name] = {"": f"Show details for rule '{name}'."}
    
    return descriptions

def try_get_map_path_silent(interface_name: Optional[str]) -> Optional[str]:
    """Helper function to get map path silently using the consolidated function."""
    if not interface_name: # Guard against None or empty interface_name
        logger.warning("try_get_map_path_silent called with no interface_name.")
        return None
    try:
        return get_bpf_map_path_if_exists(interface_name)
    except Exception as e:
        logger.error(f"Unexpected error in try_get_map_path_silent for '{interface_name}': {e}")
        return None

def build_egress_rule_from(rule):
    """
    Genera la regla egress- a partir de la regla original.
    La regla de egreso debe coincidir con el estado del paquete después de las operaciones
    de pop y push de la regla de ingreso.
    La regla de egreso popeará las tags pusheadas por la regla de ingreso
    y pusheará las tags matcheadas originalmente por la regla de ingreso.
    """
    # Normalización: si solo hay svlan y no cvlan, tratar svlan como cvlan (MEF/Ethernet estándar)
    orig_match_svlan = rule.get("match_svlan")
    orig_match_cvlan = rule.get("match_cvlan")
    if orig_match_svlan is not None and orig_match_cvlan is None:
        orig_match_cvlan = orig_match_svlan
        orig_match_svlan = None

    pop_tags_ingress = rule.get("pop_tags", 0)
    orig_push_svlan = rule.get("push_svlan")
    orig_push_cvlan = rule.get("push_cvlan")

    # 1. Estado después del POP de la regla de ingreso
    s_after_ingress_pop = None
    c_after_ingress_pop = None

    if pop_tags_ingress == 0:
        s_after_ingress_pop = orig_match_svlan
        c_after_ingress_pop = orig_match_cvlan
    elif pop_tags_ingress == 1:
        if orig_match_svlan is not None:
            s_after_ingress_pop = None
            c_after_ingress_pop = orig_match_cvlan
        elif orig_match_cvlan is not None:
            s_after_ingress_pop = None
            c_after_ingress_pop = None
        else:
            s_after_ingress_pop = None
            c_after_ingress_pop = None
    elif pop_tags_ingress == 2:
        s_after_ingress_pop = None
        c_after_ingress_pop = None

    # 2. Estado después del PUSH de la regla de ingreso (esto es lo que debe matchear la egress)
    if orig_push_svlan is not None:
        egress_match_svlan_final = orig_push_svlan
        if orig_push_cvlan is not None:
            egress_match_cvlan_final = orig_push_cvlan
        else:
            if pop_tags_ingress == 0:
                egress_match_cvlan_final = orig_match_cvlan
            elif pop_tags_ingress == 1 and orig_match_svlan is not None:
                egress_match_cvlan_final = orig_match_svlan
            else:
                egress_match_cvlan_final = None
    elif orig_push_cvlan is not None:
        # CORREGIDO: Si solo había una CVLAN y se pushea una CVLAN, el resultado es solo una CVLAN
        if orig_match_svlan is not None:
            egress_match_svlan_final = orig_push_cvlan
            egress_match_cvlan_final = orig_match_svlan
        elif orig_match_cvlan is not None:
            egress_match_svlan_final = None
            egress_match_cvlan_final = orig_push_cvlan
        else:
            egress_match_svlan_final = None
            egress_match_cvlan_final = orig_push_cvlan
    else:
        egress_match_svlan_final = s_after_ingress_pop
        egress_match_cvlan_final = c_after_ingress_pop

    # 3. POP de la egress: debe popear lo que la regla de ingreso pusheó
    egress_pop_tags_final = 0
    if orig_push_svlan is not None:
        egress_pop_tags_final += 1
    if orig_push_cvlan is not None:
        egress_pop_tags_final += 1

    # 4. PUSH de la egress: solo pushear si el valor original es distinto al que queda tras el pop de la egress
    s_after_egress_pop = egress_match_svlan_final
    c_after_egress_pop = egress_match_cvlan_final
    if egress_pop_tags_final == 1:
        if s_after_egress_pop is not None and c_after_egress_pop is not None:
            s_after_egress_pop = None
        elif s_after_egress_pop is not None:
            s_after_egress_pop = None
            c_after_egress_pop = None
        elif c_after_egress_pop is not None:
            s_after_egress_pop = None
            c_after_egress_pop = None
    elif egress_pop_tags_final == 2:
        s_after_egress_pop = None
        c_after_egress_pop = None

    egress_push_svlan_final = orig_match_svlan if orig_match_svlan != s_after_egress_pop else None
    egress_push_cvlan_final = orig_match_cvlan if orig_match_cvlan != c_after_egress_pop else None

    # --- Normalización final: si solo queda svlan y no cvlan, tratarlo como cvlan ---
    if egress_match_svlan_final is not None and egress_match_cvlan_final is None:
        egress_match_cvlan_final = egress_match_svlan_final
        egress_match_svlan_final = None

    return {
        "name": f"egress-{rule['name']}",
        "in_interface": rule["out_interface"],
        "out_interface": rule["in_interface"],
        "match_svlan": egress_match_svlan_final,
        "match_cvlan": egress_match_cvlan_final,
        "pop_tags": egress_pop_tags_final,
        "push_svlan": egress_push_svlan_final,
        "push_cvlan": egress_push_cvlan_final,
        "active": rule.get("active", False)
    }

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Usage: create-rule|delete-rule|enable-rule|disable-rule|show-forwarding [...]"
    cmd = args[0]

    if cmd == "create-rule":
        # ... (create-rule logic seems mostly fine, ensure all params are handled) ...
        params = {}
        i = 1
        while i < len(args):
            if i + 1 < len(args):
                key = args[i]
                value = args[i+1]
                if key in create_rule_params:
                    params[key] = value
                else:
                    return f"{prompt}Unknown parameter for create-rule: {key}"
                i += 2
            else:
                return f"{prompt}Missing value for parameter: {args[i]}"
        
        required = ["name", "in_interface", "svlan", "cvlan", "out_interface", "pop_tags", "push_svlan", "push_cvlan"]
        missing = [k for k in required if k not in params]
        if missing:
            return f"{prompt}Missing parameters for create-rule: {', '.join(missing)}"
        
        try:
            rule = {
                "name": params["name"],
                "in_interface": params["in_interface"],
                "match_svlan": int(params["svlan"]) if params["svlan"].lower() != "null" else None,
                "match_cvlan": int(params["cvlan"]) if params["cvlan"].lower() != "null" else None,
                "out_interface": params["out_interface"],
                "pop_tags": int(params["pop_tags"]),
                "push_svlan": int(params["push_svlan"]) if params["push_svlan"].lower() != "null" else None,
                "push_cvlan": int(params["push_cvlan"]) if params["push_cvlan"].lower() != "null" else None,
                "active": False
            }
            if rule["match_svlan"] is not None and not (1 <= rule["match_svlan"] <= 4094):
                return f"{prompt}Invalid svlan: {rule['match_svlan']}. Must be 1-4094 or null."
            if rule["match_cvlan"] is not None and not (1 <= rule["match_cvlan"] <= 4094):
                return f"{prompt}Invalid cvlan: {rule['match_cvlan']}. Must be 1-4094 or null."
            if not (0 <= rule["pop_tags"] <= 2):
                return f"{prompt}Invalid pop_tags: {rule['pop_tags']}. Must be 0, 1, or 2."
            if rule["push_svlan"] is not None and not (1 <= rule["push_svlan"] <= 4094):
                return f"{prompt}Invalid push_svlan: {rule['push_svlan']}. Must be 1-4094 or null."
            if rule["push_cvlan"] is not None and not (1 <= rule["push_cvlan"] <= 4094):
                return f"{prompt}Invalid push_cvlan: {rule['push_cvlan']}. Must be 1-4094 or null."

        except ValueError:
            return f"{prompt}Invalid value for a numeric parameter (svlan, cvlan, pop_tags, push_svlan, push_cvlan)."

        rules = load_rules()
        # Check for duplicate rule name
        if any(r["name"] == rule["name"] for r in rules):
            return f"{prompt}Error: Rule with name '{rule['name']}' already exists."
            
        conflict = detect_conflicts(rules, rule) # detect_conflicts might need adjustment if it checks name
        if conflict: # Assuming detect_conflicts checks for operational conflicts, not just name
            return f"{prompt}{conflict}"
        
        rules.append(rule)
        # --- Crear también la egress-rule ---
        egress_rule = build_egress_rule_from(rule)
        if not any(r["name"] == egress_rule["name"] for r in rules):
            rules.append(egress_rule)
        save_rules(rules)
        return f"{prompt}Rule '{rule['name']}' and its egress pair '{egress_rule['name']}' created (inactive)."

    elif cmd == "delete-rule":
        if len(args) != 2:
            return f"{prompt}Usage: delete-rule <name>"
        name_to_delete = args[1]
        egress_name = f"egress-{name_to_delete}"
        rules = load_rules()
        original_rule_count = len(rules)
        rule_to_delete = next((r for r in rules if r["name"] == name_to_delete), None)
        egress_rule_to_delete = next((r for r in rules if r["name"] == egress_name), None)

        if not rule_to_delete:
            return f"{prompt}Rule '{name_to_delete}' not found."
        if rule_to_delete.get("active", False):
            return f"{prompt}Rule '{name_to_delete}' is active. Disable it before deletion."

        interface_of_deleted_rule = rule_to_delete.get("in_interface") if rule_to_delete else None
        interface_of_egress_rule = egress_rule_to_delete.get("in_interface") if egress_rule_to_delete else None
        rules = [r for r in rules if r["name"] not in [name_to_delete, egress_name]]

        if len(rules) < original_rule_count:
            save_rules(rules)
            # Rebuild maps for both interfaces if needed
            msgs = []
            for iface in {interface_of_deleted_rule, interface_of_egress_rule}:
                if iface:
                    map_pin_path = try_get_map_path_silent(iface)
                    if map_pin_path:
                        try:
                            rebuild_forwarding_map(map_pin_path)
                            msgs.append(f"BPF map rebuilt for {iface}.")
                        except Exception as e:
                            msgs.append(f"Error rebuilding BPF map for {iface}: {e}")
            return f"{prompt}Rule '{name_to_delete}' and its egress pair '{egress_name}' deleted. " + " ".join(msgs)
        else:
            return f"{prompt}Error deleting rule '{name_to_delete}' (rule found but not removed)."

    elif cmd == "enable-rule":
        if len(args) != 2:            
            return f"{prompt}Usage: enable-rule <name>"
        name_to_enable = args[1]
        egress_name = f"egress-{name_to_enable}"
        rules = load_rules()
        names_to_enable = [name_to_enable, egress_name]
        enabled = []
        for name in names_to_enable:
            rule_to_enable = None
            for r_idx, r_val in enumerate(rules):
                if r_val["name"] == name:
                    if r_val.get("active", False):
                        continue
                    rules[r_idx]["active"] = True
                    rule_to_enable = rules[r_idx]
                    break
            if rule_to_enable:
                save_rules(rules)
                in_interface = rule_to_enable["in_interface"]
                program_path = str(Path(__file__).parent.parent.parent / "plugins" / "xdp_mef_switch" / "xdp_forwarding.o")
                if ensure_xdp_program_attached(in_interface, program_path):
                    map_pin_path = try_get_map_path_silent(in_interface)
                    if map_pin_path:
                        try:
                            rebuild_forwarding_map(map_pin_path)
                            enabled.append(name)
                        except Exception as e:
                            return f"{prompt}Rule '{name}' enabled but error rebuilding BPF map: {e}"
            # Si no existe la egress, la ignora silenciosamente
        return f"{prompt}Rule '{name_to_enable}' and its egress pair enabled and BPF maps rebuilt."

    elif cmd == "disable-rule":
        if len(args) != 2 :
            return f"{prompt}Usage: disable-rule <rule_name>"
        name_to_disable = args[1]
        egress_name = f"egress-{name_to_disable}"
        rules = load_rules()
        names_to_disable = [name_to_disable, egress_name]
        disabled = []
        for name in names_to_disable:
            rule_found = False
            in_interface_of_disabled_rule = None 
            for r_idx, r_val in enumerate(rules):
                if r_val["name"] == name:
                    if not r_val.get("active", False):
                        continue
                    rules[r_idx]["active"] = False
                    in_interface_of_disabled_rule = r_val.get("in_interface")
                    rule_found = True
                    break
            if rule_found:
                save_rules(rules)
                if in_interface_of_disabled_rule:
                    map_pin_path = try_get_map_path_silent(in_interface_of_disabled_rule)
                    if map_pin_path:
                        try:
                            rebuild_forwarding_map(map_pin_path)
                            # Detach XDP si no quedan reglas activas
                            still_active = any(
                                r.get("active", False) and r.get("in_interface") == in_interface_of_disabled_rule
                                for r in rules
                            )
                            if not still_active:
                                from plugins.xdp_mef_switch.xdp_loader import detach_xdp_program
                                detach_xdp_program(in_interface_of_disabled_rule, force=True)
                                # Deshabilitar promiscuous mode si no quedan reglas activas
                                try:
                                    subprocess.run(
                                        ["sudo", "ip", "link", "set", in_interface_of_disabled_rule, "promisc", "off"],
                                        check=True
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to disable promisc mode on {in_interface_of_disabled_rule}: {e}")
                        except Exception as e:
                            return f"{prompt}Rule '{name}' disabled but error rebuilding BPF map: {e}"
                disabled.append(name)
        return f"{prompt}Rule '{name_to_disable}' and its egress pair disabled and BPF maps rebuilt."

    elif cmd == "show-forwarding":
        all_rules_list = load_rules() # Use a different variable name to avoid conflict if 'rules' module is imported
        rules_to_display = []
        output_format_json = False
        specific_rule_name_provided = None

        if len(args) > 1:
            second_arg = args[1]
            if second_arg == "json":
                output_format_json = True
                # For JSON output, typically all rules are returned, or filtered if a name was also given
                # For simplicity here, if 'json' is present, we show all.
                # If you want 'show-forwarding <name> json', you'd need more complex arg parsing.
                rules_to_display = all_rules_list
            else:
                # Assume second_arg is a rule name based on new command tree
                specific_rule_name_provided = second_arg
                for r_val in all_rules_list: # Iterate through all loaded rules
                    if r_val.get("name") == specific_rule_name_provided:
                        rules_to_display.append(r_val)
                        # If you want to automatically include the egress pair:
                        # egress_pair_name = f"egress-{specific_rule_name_provided}"
                        # for er_val in all_rules_list:
                        #    if er_val.get("name") == egress_pair_name:
                        #        rules_to_display.append(er_val)
                        #        break
                        break # Found the primary rule
        else: # No second argument, show all rules
            rules_to_display = all_rules_list

        if output_format_json:
            # If a specific rule was requested for JSON, rules_to_display is already filtered
            return json.dumps(rules_to_display, indent=4)

        # Table display part
        table_header_str = (
            "+----------+--------------+----------+----------+--------------+----------+------------+------------+--------+\n"
            "|   name   | in_interface | svlan    | cvlan    | out_interface| pop_tags | push_svlan | push_cvlan | active |\n"
            "+----------+--------------+----------+----------+--------------+----------+------------+------------+--------+"
        )
        # Adjust footer width if your column widths changed. Max 8+12+8+8+12+8+10+10+6 + (9*2 separators) = 82 + 18 = 100.
        # Current footer is 108, which allows for some padding.
        table_footer_str = "+" + "-"*108 + "+" 

        if not rules_to_display:
            no_rules_msg_text = ""
            if specific_rule_name_provided:
                 no_rules_msg_text = f"Rule '{specific_rule_name_provided}' not found"
            else:
                 no_rules_msg_text = "no rules configured"
            # Pad the message to fit the table width
            # Max content width is 108 - 2 for the side pipes = 106
            no_rules_msg_display = f"| {f'({no_rules_msg_text})':<106} |"
            return f"{table_header_str}\n{no_rules_msg_display}\n{table_footer_str}"

        output_lines = [table_header_str]
        for r_val in rules_to_display: # Changed r to r_val
            row = "| {name:<8} | {in_if:<12} | {svlan:<8} | {cvlan:<8} | {out_if:<12} | {pop:<8} | {p_svlan:<10} | {p_cvlan:<10} | {active:<6} |".format(
                name=str(r_val.get("name", "N/A"))[:8], 
                in_if=str(r_val.get("in_interface", "N/A"))[:12],
                svlan=str(r_val.get("match_svlan", "null"))[:8],
                cvlan=str(r_val.get("match_cvlan", "null"))[:8],
                out_if=str(r_val.get("out_interface", "N/A"))[:12],
                pop=str(r_val.get("pop_tags", "N/A"))[:8],
                p_svlan=str(r_val.get("push_svlan", "null"))[:10],
                p_cvlan=str(r_val.get("push_cvlan", "null"))[:10],
                active="yes" if r_val.get("active") else "no"
            )
            output_lines.append(row)
        
        output_lines.append(table_footer_str)
        return "\n".join(output_lines)
    else:
        return f"{prompt}Unknown xdp-switch command: {cmd}. Supported: create-rule, delete-rule, enable-rule, disable-rule, show-forwarding."