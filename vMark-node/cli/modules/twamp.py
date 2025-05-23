import logging
import io          # Import io
import contextlib  # Import contextlib
import sys
import time
import struct
import socket
import binascii
import threading
import random
import argparse
import select
from pathlib import Path # Import Path
import os # Import os
import signal # Import signal
import subprocess # If needed to launch/manage processes

# --- Add Global Dictionaries for Tracking ---
# Store PIDs or thread objects. Key format depends on identification needs.
# Example: (ip_version, port) for responders
# Example: (ip_version, dest_ip, port) for senders (if tracking needed)
_active_responders = {} # key: (ip_version, port), value: PID or Thread object
_active_senders = {}    # key: (ip_version, dest_ip, port), value: PID or Thread object
_sender_results = {}    # key: (ip_version, dest_ip, port), value: { "timestamp": float, "results": dict }
_process_lock = threading.Lock() # To safely access the dictionaries
# --- End State Tracking ---

# Set up logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Configure the twamp logger
log = logging.getLogger('twamp')
log.setLevel(logging.DEBUG) # Or DEBUG for more details DESHABILTIAR ACA
log_file_path = Path.home() / ".vmark" / "api.log"
handler_exists = any(isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file_path) for h in log.handlers)
if not handler_exists:
    log_dir = log_file_path.parent
    log_dir.mkdir(exist_ok=True)
    log.propagate = False
    # Create file handler
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG) # Log everything to the file

    # Create formatter and add it to the handler
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Add the handler to the logger
    log.addHandler(file_handler)
    log.info("File handler added for twamp logger to api.log") # Confirm handler addition

    # Optional: Prevent logging to console if already handled by root logger or api_server
else:
    log.info("File handler for twamp logger to api.log already exists.")
# --- End Logging Modification ---

# Also silence pyroute2 debug messages if it's used elsewhere
# logging.getLogger('pyroute2').setLevel(logging.WARNING)

# Import the plugin after logging is configured
ONYX_PLUGIN_LOADED = False # Initialize flag
try:
    # --- FIX: Move imports and flag setting into the try block ---
    from plugins.twamp.onyx import (
        dscpTable,
        twl_sender,
        twl_responder,
        parse_addr, # Import helper if needed
        dp, # Import helper if needed
        onyxTimestamp # Ensure this is imported if used elsewhere
    )
    log.debug("Onyx plugin imported successfully.")
    ONYX_PLUGIN_LOADED = True # Set flag on successful import
# except Exception as e: # --- FIX: Remove this incorrect except block ---
#    log.error(f"An error occurred: {e}")
except ImportError as e:
    # This block is correct - handles the case where the plugin cannot be found/imported
    log.error(f"CRITICAL: Failed to import onyx plugin: {e}. TWAMP functionality will be unavailable.")
    # ONYX_PLUGIN_LOADED remains False (set during initialization)

# --- Command Tree and Descriptions ---

command_tree = {
    "twamp": {
        "dscptable": None,
        "ipv4": {
            "sender": {
                "destination-ip": { "_options": ["<ip-address>"] },
                "port": { "_options": ["<1024-65535>"] },
                "count": { "_options": ["<1-10000>"] },
                "interval": { "_options": ["<10-1000>"] },
                "padding": { "_options": ["<0-9000>"] },
                "ttl": { "_options": ["<1-255>"] },
                "tos": { "_options": ["<0-255>"] },
                "do-not-fragment": None
            },
            "responder": {
                "port": { "_options": ["<1024-65535>"] },
                "padding": { "_options": ["<0-9000>"] },
                "ttl": { "_options": ["<1-255>"] },
                "tos": { "_options": ["<0-255>"] },
                "do-not-fragment": None
            },
            "stop": { # --- Add Stop Command ---
                "responder": {
                    "port": { "_options": ["<1024-65535>"] }
                },
                "sender": { # Optional: If stopping senders is needed
                     "destination-ip": { "_options": ["<ip-address>"] },
                     "port": { "_options": ["<1024-65535>"] }
                }
            } # --- End Stop Command ---
        },
        "ipv6": {
            "sender": {
                "destination-ip": { "_options": ["<ipv6-address>"] },
                "port": { "_options": ["<1024-65535>"] },
                "count": { "_options": ["<1-10000>"] },
                "interval": { "_options": ["<10-1000>"] },
                "padding": { "_options": ["<0-9000>"] },
                "ttl": { "_options": ["<1-255>"] },
                "tos": { "_options": ["<0-255>"] },
                # "do-not-fragment": None # Typically not used/settable in IPv6
            },
            "responder": {
                "port": { "_options": ["<1024-65535>"] },
                "padding": { "_options": ["<0-9000>"] },
                "ttl": { "_options": ["<1-255>"] },
                "tos": { "_options": ["<0-255>"] },
                # "do-not-fragment": None # Typically not used/settable in IPv6
            },
            "stop": { # --- Add Stop Command ---
                 "responder": {
                     "port": { "_options": ["<1024-65535>"] }
                 },
                 "sender": { # Optional
                      "destination-ip": { "_options": ["<ipv6-address>"] },
                      "port": { "_options": ["<1024-65535>"] }
                 }
            } # --- End Stop Command ---
        }
    }
}

descriptions = {
    "twamp": {
        "": "TWAMP (Two-Way Active Measurement Protocol) commands",
        "dscptable": "Show DSCP value table",
        "ipv4": {
            "": "IPv4 TWAMP commands",
            "sender": {
                "": "Start TWAMP sender session",
                "destination-ip": {
                    "": "Destination IPv4 address (REQUIRED)",
                    "format": "Enter destination IPv4 address (REQUIRED)"
                },
                "port": {
                    "": "Set destination port (REQUIRED)",
                    "format": "Enter port number (1024-65535) (REQUIRED)"
                },
                "count": {
                    "": "Set number of packets",
                    "format": "Enter number of packets to send"
                },
                "interval": {
                    "": "Set packet interval",
                    "format": "Enter packet interval in milliseconds"
                },
                "padding": {
                    "": "Set packet padding",
                    "format": "Enter padding size in bytes"
                },
                "ttl": {
                    "": "Set Time to Live",
                    "format": "Enter TTL value"
                },
                "tos": {
                    "": "Set Type of Service",
                    "format": "Enter ToS value"
                },
                "do-not-fragment": "Set Do Not Fragment flag"
            },
            "responder": {
                "": "Start TWAMP responder session",
                "port": {
                    "": "Set local port (REQUIRED)",
                    "format": "Enter port number (1024-65535) (REQUIRED)"
                },
                "padding": {
                    "": "Set packet padding",
                    "format": "Enter padding size in bytes"
                },
                "ttl": {
                    "": "Set Time to Live",
                    "format": "Enter TTL value"
                },
                "tos": {
                    "": "Set Type of Service",
                    "format": "Enter ToS value"
                },
                "do-not-fragment": "Set Do Not Fragment flag"
            },
            "stop": { # --- Add Stop Descriptions ---
                "": "Stop an active TWAMP process",
                "responder": {
                    "": "Stop a TWAMP responder",
                    "port": {
                        "": "Specify the port the responder is listening on (REQUIRED)",
                        "format": "Enter port number (1024-65535)"
                    }
                },
                "sender": { # Optional
                     "": "Stop a TWAMP sender (if applicable)",
                     "destination-ip": { ... },
                     "port": { ... }
                }
            } # --- End Stop Descriptions ---
        },
        "ipv6": {
            "": "IPv6 TWAMP commands",
            "sender": {
                "": "Start TWAMP sender session",
                "destination-ip": {
                    "": "Destination IPv6 address (REQUIRED)",
                    "format": "Enter destination IPv6 address (REQUIRED)"
                },
                "port": {
                    "": "Set destination port (REQUIRED)",
                    "format": "Enter port number (1024-65535) (REQUIRED)"
                },
                "count": {
                    "": "Set number of packets",
                    "format": "Enter number of packets to send"
                },
                "interval": {
                    "": "Set packet interval",
                    "format": "Enter packet interval in milliseconds"
                },
                "padding": {
                    "": "Set packet padding",
                    "format": "Enter padding size in bytes"
                },
                "ttl": {
                    "": "Set Time to Live",
                    "format": "Enter TTL value"
                },
                "tos": {
                    "": "Set Type of Service",
                    "format": "Enter ToS value"
                },
                # "do-not-fragment": "Set Do Not Fragment flag (N/A for IPv6)"
            },
            "responder": {
                "": "Start TWAMP responder session",
                "port": {
                    "": "Set local port (REQUIRED)",
                    "format": "Enter port number (1024-65535) (REQUIRED)"
                },
                "padding": {
                    "": "Set packet padding",
                    "format": "Enter padding size in bytes"
                },
                "ttl": {
                    "": "Set Time to Live",
                    "format": "Enter TTL value"
                },
                "tos": {
                    "": "Set Type of Service",
                    "format": "Enter ToS value"
                },
                # "do-not-fragment": "Set Do Not Fragment flag (N/A for IPv6)"
            },
            "stop": { # --- Add Stop Descriptions ---
                "": "Stop an active TWAMP process",
                "responder": {
                    "": "Stop a TWAMP responder",
                    "port": {
                        "": "Specify the port the responder is listening on (REQUIRED)",
                        "format": "Enter port number (1024-65535)"
                    }
                },
                "sender": { # Optional
                     "": "Stop a TWAMP sender (if applicable)",
                     "destination-ip": { ... },
                     "port": { ... }
                }
            } # --- End Stop Descriptions ---
        }
    }
}

def get_command_tree():
    """Build and return command tree based on descriptions"""
    def build_tree(source, target):
        for key, value in source.items():
            if key in ["_options", "format", ""]:  # Skip metadata and description key
                continue

            if isinstance(value, dict):
                target[key] = {}
                build_tree(value, target[key])
            else:
                target[key] = {}  # Change from None to {} for proper nesting
    
    # Make sure each parameter has an empty dictionary as child
    # This ensures parameters like destination-ip have {} rather than None
    # which allows the shell.py tab completion to find sibling parameters
    
    result = {}
    build_tree(command_tree['twamp'], result)  # Start from 'twamp' level

    # Fix for ipv4/ipv6 sender parameters
    for ip_version in ['ipv4', 'ipv6']:
        if ip_version in result and 'sender' in result[ip_version]:
            sender = result[ip_version]['sender']
            
            # Make sure all parameters can be followed by their siblings
            param_parent = sender
            
            # Create proper sibling connections
            params = ["destination-ip", "port", "count", "interval", "padding", "ttl", "tos", "do-not-fragment"]
            
            # Initialize empty dictionaries for any None values
            for param in params:
                if param in param_parent and param_parent[param] is None:
                    param_parent[param] = {}
            
            # Create mapping for each parameter to contain all its siblings
            for param in params:
                if param in param_parent:
                    # Check if this param has _options
                    options = []
                    
                    # Get options directly from command_tree if they exist
                    if (ip_version in command_tree["twamp"] and 
                        "sender" in command_tree["twamp"][ip_version] and
                        param in command_tree["twamp"][ip_version]["sender"] and
                        isinstance(command_tree["twamp"][ip_version]["sender"][param], dict) and
                        "_options" in command_tree["twamp"][ip_version]["sender"][param]):
                        options = command_tree["twamp"][ip_version]["sender"][param]["_options"]
                    # Fallback for parameters without _options (like do-not-fragment)
                    elif param in param_parent:
                        options = [""]
                    
                    # For each parameter option/value
                    for option in options:
                        # Create the parameter value node if it doesn't exist
                        if option not in param_parent[param]:
                            param_parent[param][option] = {}
                        
                        # Add all sibling parameters to this parameter value node
                        for sibling in params:
                            if sibling != param and sibling in param_parent:
                                param_parent[param][option][sibling] = param_parent[sibling]
    
    # Do the same for responder parameters
    for ip_version in ['ipv4', 'ipv6']:
        if ip_version in result and 'responder' in result[ip_version]:
            responder = result[ip_version]['responder']
            
            # Define responder parameters
            resp_params = ["port", "padding", "ttl", "tos", "do-not-fragment"]
            
            # Initialize empty dictionaries for any None values
            for param in resp_params:
                if param in responder and responder[param] is None:
                    responder[param] = {}
            
            # Create mapping for each parameter
            for param in resp_params:
                if param in responder:
                    # Get options
                    options = []
                    if (ip_version in command_tree["twamp"] and 
                        "responder" in command_tree["twamp"][ip_version] and
                        param in command_tree["twamp"][ip_version]["responder"] and
                        isinstance(command_tree["twamp"][ip_version]["responder"][param], dict) and
                        "_options" in command_tree["twamp"][ip_version]["responder"][param]):
                        options = command_tree["twamp"][ip_version]["responder"][param]["_options"]
                    elif param in responder:
                        options = [""]
                    
                    # For each option
                    for option in options:
                        if option not in responder[param]:
                            responder[param][option] = {}
                        
                        # Add sibling parameters
                        for sibling in resp_params:
                            if sibling != param and sibling in responder:
                                responder[param][option][sibling] = responder[sibling]
    
    # Also do the same for stop commands
    for ip_version in ['ipv4', 'ipv6']:
        if ip_version in result and 'stop' in result[ip_version]:
            if 'responder' in result[ip_version]['stop']:
                resp_stop = result[ip_version]['stop']['responder']
                if 'port' in resp_stop:
                    for option in list(resp_stop['port'].keys()):
                        if resp_stop['port'][option] is None:
                            resp_stop['port'][option] = {}
            
            if 'sender' in result[ip_version]['stop']:
                sender_stop = result[ip_version]['stop']['sender']
                stop_params = ["destination-ip", "port"]
                
                # Initialize empty dictionaries for any None values
                for param in stop_params:
                    if param in sender_stop and sender_stop[param] is None:
                        sender_stop[param] = {}
                
                # Create sibling relationships
                for param in stop_params:
                    if param in sender_stop:
                        options = []
                        if (ip_version in command_tree["twamp"] and 
                            "stop" in command_tree["twamp"][ip_version] and
                            "sender" in command_tree["twamp"][ip_version]["stop"] and
                            param in command_tree["twamp"][ip_version]["stop"]["sender"] and
                            isinstance(command_tree["twamp"][ip_version]["stop"]["sender"][param], dict) and
                            "_options" in command_tree["twamp"][ip_version]["stop"]["sender"][param]):
                            options = command_tree["twamp"][ip_version]["stop"]["sender"][param]["_options"]
                        elif param in sender_stop:
                            options = [""]
                        
                        for option in options:
                            if option not in sender_stop[param]:
                                sender_stop[param][option] = {}
                            
                            for sibling in stop_params:
                                if sibling != param and sibling in sender_stop:
                                    sender_stop[param][option][sibling] = sender_stop[sibling]
    return result

def get_descriptions():
    """Return the description dictionary."""
    return descriptions

def format_results(results, params):
    """Formats the results dictionary into a string similar to the original output."""
    # Add debug logging to inspect the input
    log.debug(f"format_results called with: {results}")
    
    # Check for None or empty results
    if results is None:
        return "Error during test or no results: None"
        
    # Check for dictionary with error
    if not isinstance(results, dict):
        return f"Error during test or invalid results format: {type(results).__name__}"
        
    # Check if error key exists and has a value (but don't treat None as an error)
    if 'error' in results and results['error'] and results['error'] is not None:
        return f"Error during test: {results['error']}"
    
    # Check for required keys to display results
    required_keys = ['packets_tx', 'packets_rx'] 
    missing_keys = [key for key in required_keys if key not in results]
    
    if missing_keys:
        log.warning(f"Results dictionary missing required keys: {missing_keys}")
        return f"Error: Incomplete results (missing {', '.join(missing_keys)})"

    # Use .get with defaults for safety and format using dp helper
    try:
        o_min = dp(results.get('outbound_min_us'))
        o_max = dp(results.get('outbound_max_us'))
        o_avg = dp(results.get('outbound_avg_us'))
        o_jit = dp(results.get('outbound_jitter_us'))
        # Get the loss value, which might be None
        o_loss_val = results.get('outbound_loss_percent')
        i_min = dp(results.get('inbound_min_us'))
        i_max = dp(results.get('inbound_max_us'))
        i_avg = dp(results.get('inbound_avg_us'))
        i_jit = dp(results.get('inbound_jitter_us'))
        # Get the loss value, which might be None
        i_loss_val = results.get('inbound_loss_percent')
        r_min = dp(results.get('roundtrip_min_us'))
        r_max = dp(results.get('roundtrip_max_us'))
        r_avg = dp(results.get('roundtrip_avg_us'))
        r_jit = dp(results.get('roundtrip_jitter_us'))
        # Total loss should be a float
        r_loss = results.get('total_loss_percent', 0.0)
        pkts_tx = results.get('packets_tx', 0)
        pkts_rx = results.get('packets_rx', 0)
        # Use original requested count if available in params, else use packets_tx
        total_req = params.get('count', pkts_tx)
    except Exception as e:
        log.error(f"Error processing results values: {e}")
        return f"Error formatting results: {str(e)}"

    # --- Format loss values, handling None ---
    o_loss_str = f"{o_loss_val:5.1f}%" if o_loss_val is not None else "  N/A "
    i_loss_str = f"{i_loss_val:5.1f}%" if i_loss_val is not None else "  N/A "
    r_loss_str = f"{r_loss:5.1f}%" if r_loss is not None else "  0.0%" # Total loss should always be a number

    output = io.StringIO()
    # Use print to write to the StringIO object
    print("\n=====================================================================================", file=output)
    print("  Direction       Min       Max       Avg       Jitter     Loss    Pkts", file=output)
    print("-------------------------------------------------------------------------------", file=output)
    # Use the formatted loss strings
    print(f"  Outbound:    {o_min:>9} {o_max:>9} {o_avg:>9} {o_jit:>9}   {o_loss_str}   {pkts_rx:>3}/{total_req:<3}", file=output)
    print(f"  Inbound:     {i_min:>9} {i_max:>9} {i_avg:>9} {i_jit:>9}   {i_loss_str}   {pkts_rx:>3}/{total_req:<3}", file=output)
    print(f"  Roundtrip:   {r_min:>9} {r_max:>9} {r_avg:>9} {r_jit:>9}   {r_loss_str}    Total:{total_req:<3}", file=output)
    print("-------------------------------------------------------------------------------", file=output)
    print("                                                 pathgate's Onyx Test [RFC5357]", file=output)
    print("=====================================================================================", file=output)
    
    # Return the formatted output
    return output.getvalue()

# --- Helper function to terminate ---
def _terminate_process(pid, session_key_str):
    try:
        os.kill(pid, signal.SIGTERM) # Send TERM signal
        log.info(f"Sent SIGTERM to process {pid} for session {session_key_str}.")
        # Optionally wait a short time and send SIGKILL if needed
        # time.sleep(0.5)
        # os.kill(pid, signal.SIGKILL)
        return f"Termination signal sent to process {pid} for {session_key_str}."
    except ProcessLookupError:
        log.warning(f"Process {pid} for session {session_key_str} not found (already terminated?).")
        return f"Process {pid} for {session_key_str} not found."
    except Exception as e:
        log.error(f"Error terminating process {pid} for {session_key_str}: {e}")
        return f"Error terminating process {pid}: {e}"
# --- End Helper ---

# --- Helper function to stop the responder thread ---
def _stop_responder_thread(thread_obj, session_key_str):
    """Attempts to gracefully stop the responder thread using its stop() method."""
    if not isinstance(thread_obj, threading.Thread):
        log.error(f"Cannot stop: Expected a Thread object for {session_key_str}, got {type(thread_obj)}")
        return f"Error: Internal error stopping responder {session_key_str} (invalid type)."

    if not thread_obj.is_alive():
        log.warning(f"Responder thread for {session_key_str} is not alive (already stopped?).")
        return f"Responder {session_key_str} already stopped."

    try:
        # Check if the thread object has the 'stop' method (from udpSession/onyxSessionReflector)
        if hasattr(thread_obj, 'stop') and callable(thread_obj.stop):
            log.info(f"Calling stop() method on responder thread for {session_key_str} ({thread_obj.name})")
            thread_obj.stop() # Call the stop method defined in udpSession/onyxSessionReflector
            # Wait briefly for the thread to exit
            thread_obj.join(timeout=2.0) # Wait up to 2 seconds
            if thread_obj.is_alive():
                log.warning(f"Responder thread {session_key_str} did not stop within timeout after stop() call.")
                # Even if it didn't join, the stop signal was sent.
                return f"Stop signal sent to responder {session_key_str}, but it may not have terminated yet."
            else:
                log.info(f"Responder thread {session_key_str} stopped successfully.")
                return f"Responder {session_key_str} stopped successfully."
        else:
            # This shouldn't happen if twl_responder returned the correct object
            log.error(f"Cannot stop: Thread object for {session_key_str} has no callable stop() method.")
            return f"Error: Internal error stopping responder {session_key_str} (no stop method)."
    except Exception as e:
        log.error(f"Error calling stop() on responder thread {session_key_str}: {e}", exc_info=True)
        return f"Error stopping responder {session_key_str}: {e}"
# --- End Helper ---

# --- Add Helper function to stop the sender thread ---
def _stop_sender_thread(thread_obj, session_key_str):
    """Attempts to gracefully stop the sender thread using its stop() method."""
    if not isinstance(thread_obj, threading.Thread):
        log.error(f"Cannot stop: Expected a Thread object for {session_key_str}, got {type(thread_obj)}")
        return f"Error: Internal error stopping sender {session_key_str} (invalid type)."

    if not thread_obj.is_alive():
        log.warning(f"Sender thread for {session_key_str} is not alive (already stopped?).")
        return f"Sender {session_key_str} already stopped."

    try:
        # Check if the thread object has the 'stop' method (from udpSession/onyxSessionSender)
        if hasattr(thread_obj, 'stop') and callable(thread_obj.stop):
            log.info(f"Calling stop() method on sender thread for {session_key_str} ({thread_obj.name})")
            thread_obj.stop() # Call the stop method
            # Wait briefly for the thread to exit
            thread_obj.join(timeout=2.0) # Wait up to 2 seconds
            if thread_obj.is_alive():
                log.warning(f"Sender thread {session_key_str} did not stop within timeout after stop() call.")
                return f"Stop signal sent to sender {session_key_str}, but it may not have terminated yet."
            else:
                log.info(f"Sender thread {session_key_str} stopped successfully.")
                return f"Sender {session_key_str} stopped successfully."
        else:
            log.error(f"Cannot stop: Thread object for {session_key_str} has no callable stop() method.")
            return f"Error: Internal error stopping sender {session_key_str} (no stop method)."
    except Exception as e:
        log.error(f"Error calling stop() on sender thread {session_key_str}: {e}", exc_info=True)
        return f"Error stopping sender {session_key_str}: {e}"
# --- End Sender Stop Helper ---

# --- Add Helper function to store sender results ---
def _store_sender_results(session_key, results_dict):
    """Callback function to store sender results."""
    with _process_lock:
        timestamp = time.time()
        _sender_results[session_key] = {"timestamp": timestamp, "results": results_dict}
        log.info(f"Stored results for sender session {session_key} at {timestamp}. Keys: {list(_sender_results.keys())}")
        # Optional: Clean up old results if needed
        # _cleanup_old_results()
# --- End Helper ---

def handle(args, username="cli_user", hostname="vmark-node"):
    """Handle TWAMP commands. Returns output string or None."""
    # --- Check if plugin loaded ---
    if not ONYX_PLUGIN_LOADED:
        return "Error: TWAMP plugin (onyx) failed to load. Cannot execute command."
    # --- End Check ---

    if not args:
        return "Usage: twamp <ipv4|ipv6> <sender|responder|dscptable>"

    # Handle dscptable command first
    if args[0] == "dscptable":
        # Capture stdout for dscpTable
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                dscpTable()
            except Exception as e:
                log.error(f"Error executing dscpTable: {e}")
                print(f"Error executing dscpTable: {e}", file=output)
        return output.getvalue() # Return the captured output

    ip_version_str = args[0]
    if ip_version_str not in ["ipv4", "ipv6"]:
        return f"Error: Invalid IP version '{ip_version_str}'. Use 'ipv4' or 'ipv6'."
    ip_version = 6 if ip_version_str == "ipv6" else 4

    if len(args) < 2:
        return f"Usage: twamp {ip_version_str} <sender|responder|stop>"

    mode = args[1]

    if mode == "sender":
        # Initialize parameters with defaults (interval in ms)
        params = {
            'dest_ip': None, 'port': None, 'count': 100, 'interval': 100, # Default interval 100 ms
            'padding': 0, 'ttl': 64, 'tos': 0, 'do_not_fragment': False
        }
        i = 2
        while i < len(args):
            param_name = args[i]
            # Parameters expecting a value
            if param_name in ["destination-ip", "port", "count", "interval", "padding", "ttl", "tos"]:
                if i + 1 < len(args):
                    value = args[i+1]
                    try:
                        if param_name == "destination-ip": params['dest_ip'] = value
                        elif param_name == "port": params['port'] = int(value)
                        elif param_name == "count": params['count'] = int(value)
                        # --- Store interval as ms from input ---
                        elif param_name == "interval": params['interval'] = int(value)
                        # --- End change ---
                        elif param_name == "padding": params['padding'] = int(value)
                        elif param_name == "ttl": params['ttl'] = int(value)
                        elif param_name == "tos": params['tos'] = int(value)
                    except ValueError:
                        return f"Error: Invalid numeric value '{value}' for parameter '{param_name}'"
                    i += 2 # Move past parameter and value
                else:
                    # Parameter expects a value, but none provided
                    return f"Error: Missing value for parameter '{param_name}'"
            # Flag parameters (no value expected)
            elif param_name == "do-not-fragment":
                if ip_version == 4: params['do_not_fragment'] = True
                else: log.warning("Ignoring 'do-not-fragment' for IPv6 sender.")
                i += 1 # Move past flag
            else:
                # Unknown parameter
                log.warning(f"Skipping unknown sender argument: {param_name}")
                i += 1 # Move past unknown argument


        # Validate required parameters
        if not params['dest_ip']:
            return "Error: Missing required parameter: destination-ip"
        if not params['port']:
            return "Error: Missing required parameter: port"

        try:
            # Create Args object for twl_sender
            class Args:
                pass
            parsed_args = Args()

            parsed_args.far_end = f"{params['dest_ip']}:{params['port']}"
            parsed_args.near_end = ":0" # Bind to ephemeral port for sender
            parsed_args.count = params['count']
            # --- Convert interval from ms to seconds HERE ---
            parsed_args.interval = float(params['interval']) / 1000.0
            # --- End conversion ---
            parsed_args.padding = params['padding']
            parsed_args.ttl = params['ttl']
            parsed_args.tos = params['tos']
            parsed_args.do_not_fragment = params['do_not_fragment']
            # --- FIX: Correct attribute name ---
            parsed_args.ip_version = ip_version # Pass IP version (use underscore)
            # --- End Fix ---
            parsed_args.timer = 0 # Example default if needed

            # --- Add the results callback and session key ---
            parsed_args.results_callback = _store_sender_results
            sender_key = (ip_version, params['dest_ip'], params['port'])
            parsed_args.session_key = sender_key
            # --- End Additions ---

            # Log the actual interval being used (now in seconds)
            log.info(f"Starting TWAMP {ip_version_str} sender to {params['dest_ip']}:{params['port']} with count={parsed_args.count}, interval={parsed_args.interval:.4f}s")

            # --- FIX: Remove redundant first call ---
            # Call twl_sender
            # results = twl_sender(parsed_args) # REMOVE THIS LINE
            # --- End Fix ---

            # --- MODIFICATION: Handle async sender start ---
            log.info(f"Attempting to start TWAMP {ip_version_str} sender via twl_sender to {params['dest_ip']}:{params['port']}")
            result = twl_sender(parsed_args) # Call the modified function from onyx.py

            # Add more detailed logging to help diagnose the issue
            log.debug(f"Raw result from twl_sender: {result}")
            
            if isinstance(result, threading.Thread):
                sender_thread_obj = result
                # Create a unique key for the sender session
                sender_key = (ip_version, params['dest_ip'], params['port'])
                sender_key_str = f"{ip_version_str}-sender-{params['dest_ip']}-{params['port']}"

                with _process_lock:
                    # Check if sender already running for this target
                    if sender_key in _active_senders and _active_senders[sender_key].is_alive():
                         log.warning(f"Sender already running for {sender_key_str}. Cannot start another.")
                         return f"Error: Sender already active for {params['dest_ip']}:{params['port']} ({ip_version_str})."
                    _active_senders[sender_key] = sender_thread_obj # Store the thread object
                    log.debug(f"Stored sender thread object in _active_senders for key {sender_key}. Current keys: {list(_active_senders.keys())}")

                log.info(f"Successfully started and tracked sender thread '{sender_thread_obj.name}' for {sender_key_str}")
                # Return status message - results will not be available immediately
                return f"TWAMP sender to {params['dest_ip']}:{params['port']} started successfully."

            elif isinstance(result, dict):
                # IMPORTANT BUGFIX: Check for error first, then handle results.
                # If result has 'error' key with a value, it's an error
                if 'error' in result and result['error']:
                    # Check for network connectivity issue
                    if 'Network is unreachable' in result['error']:
                        log.error(f"Network connectivity error: {result['error']}")
                        return f"Error: Cannot reach {params['dest_ip']}:{params['port']} - Network is unreachable"
                    
                    # Other specific error with valid message
                    log.error(f"Failed to start sender: {result['error']}")
                    return f"Error: {result['error']}"
                
                # BUGFIX: If we have results dict with packets_tx but no error, it's SUCCESS
                elif 'packets_tx' in result:
                    log.info(f"Sender completed successfully, formatting results.")
                    
                    # Debug log the full result structure
                    log.debug(f"Full result structure: {result}")
                    
                    # This is a success case with results, format and return
                    formatted_results = format_results(result, params)
                    
                    # Check if formatting succeeded
                    if "Error" in formatted_results:
                        log.warning(f"Results formatting failed: {formatted_results}")
                        
                        # Try to extract some basic data to show something useful
                        pkts_tx = result.get('packets_tx', 0)
                        pkts_rx = result.get('packets_rx', 0)
                        loss = result.get('total_loss_percent', 'N/A')
                        
                        return f"\nTWAMP test completed:\n- Packets sent: {pkts_tx}\n- Packets received: {pkts_rx}\n- Packet loss: {loss}%\n(Detailed formatting failed, check logs)"
                    else:
                        return formatted_results
                
                # Only treat None error as connection issue if no packets were transmitted
                # This handles the case where result has 'error': None but no packet data
                elif 'error' in result and result['error'] is None and ('packets_tx' not in result or result['packets_tx'] == 0):
                    log.error("Failed to start sender: Got error=None response with no packets transmitted")
                    return f"Error: Cannot connect to {params['dest_ip']}:{params['port']} - No TWAMP responder running on that address/port"
                
                # Fallback for any other dict format
                else:
                    log.warning(f"Unexpected result format from twl_sender: {result}")
                    return format_results(result, params)
            
            else:
                # Unexpected result type
                log.error(f"Unexpected result type from twl_sender: {type(result)}")
                return f"Error: Internal error starting sender (unexpected result type: {type(result).__name__})"
            # --- End Modification ---

        except ValueError as ve:
             return f"Error: Invalid parameter value: {str(ve)}"
        except Exception as e:
            log.exception("Error during sender startup:") # Log full traceback
            return f"Error: {str(e)}"

    elif mode == "responder":
        # Initialize parameters with defaults
        params = {
            'port': None, 'padding': 0, 'ttl': 64, 'tos': 0, 'do_not_fragment': False
            # --- Add bind_addr and timer to params if needed for parsing ---
            # 'bind_addr': 'any',
            # 'timer': 0
        }
        i = 2
        # --- Your existing responder parameter parsing loop ---
        while i < len(args):
            param_name = args[i]
            if param_name == "port" and i + 1 < len(args):
                try:
                    port_val = int(args[i+1])
                    if 1024 <= port_val <= 65535:
                         params['port'] = port_val
                    else:
                         return f"Error: Port must be between 1024 and 65535"
                except ValueError: return f"Error: Invalid port value '{args[i+1]}'"
                i += 2
            # --- Add parsing for bind_addr and timer if needed ---
            # elif param_name == "bind-addr" and i + 1 < len(args):
            #     params['bind_addr'] = args[i+1]
            #     i += 2
            # elif param_name == "timer" and i + 1 < len(args):
            #     try: params['timer'] = int(args[i+1])
            #     except ValueError: return f"Error: Invalid timer value '{args[i+1]}'"
            #     i += 2
            # --- End optional parsing ---
            elif param_name == "padding" and i + 1 < len(args):
                 try: params['padding'] = int(args[i+1])
                 except ValueError: return f"Error: Invalid padding value '{args[i+1]}'"
                 i += 2
            elif param_name == "ttl" and i + 1 < len(args):
                 try: params['ttl'] = int(args[i+1])
                 except ValueError: return f"Error: Invalid ttl value '{args[i+1]}'"
                 i += 2
            elif param_name == "tos" and i + 1 < len(args):
                 try: params['tos'] = int(args[i+1])
                 except ValueError: return f"Error: Invalid tos value '{args[i+1]}'"
                 i += 2
            elif param_name == "do-not-fragment":
                 if ip_version == 4: params['do_not_fragment'] = True
                 else: log.warning("Ignoring 'do-not-fragment' for IPv6 responder.")
                 i += 1
            else:
                log.warning(f"Skipping unknown responder argument: {args[i]}")
                i += 1 # Increment even if unknown
        # --- End parameter parsing ---

        # --- Outer try block starts here ---
        try:
            # Validate required parameter
            if not params.get('port'):
                 # Use KeyError to be consistent with except block below
                 raise KeyError("port")

            # --- This inner try block is for the actual call to twl_responder ---
            session_key = (ip_version, params['port'])
            session_key_str = f"{ip_version_str}-responder-{params['port']}"

            # Check if already running
            with _process_lock:
                if session_key in _active_responders:
                    existing_thread = _active_responders[session_key]
                    if isinstance(existing_thread, threading.Thread) and existing_thread.is_alive():
                        log.warning(f"Responder already running for {session_key_str}. Cannot start another.")
                        return f"Error: Responder already active on port {params['port']} for {ip_version_str}."
                    else:
                        log.warning(f"Found stale/dead responder entry for {session_key_str}, removing.")
                        _active_responders.pop(session_key, None)

            # Create a simple namespace object for args
            parsed_args = argparse.Namespace()
            parsed_args.port = params['port']
            parsed_args.ip_version = ip_version # Use the integer version
            # Add optional attributes from parsed params
            parsed_args.bind_addr = params.get('bind_addr', 'any') # Get optional bind_addr
            parsed_args.timer = params.get('timer', 0) # Get optional timer
            # Add other params if needed by twl_responder (padding, ttl, tos?)
            # parsed_args.padding = params['padding']
            # parsed_args.ttl = params['ttl']
            # parsed_args.tos = params['tos']
            # parsed_args.do_not_fragment = params['do_not_fragment']

            log.debug(f"Starting responder with params: {vars(parsed_args)}")
            log.info(f"Attempting to start TWAMP responder via twl_responder for {session_key_str}")
            result = twl_responder(parsed_args) # Call the modified function from onyx.py

            log.debug(f"Raw result from twl_responder for {session_key_str}: type={type(result)}, value='{result}'")

            # Check result and track if successful
            if isinstance(result, threading.Thread):
                responder_thread_obj = result
                with _process_lock:
                    _active_responders[session_key] = responder_thread_obj
                    log.debug(f"Stored thread object in _active_responders for key {session_key}. Current keys: {list(_active_responders.keys())}")
                log.info(f"Successfully started and tracked responder thread '{responder_thread_obj.name}' for {session_key_str}")
                # FIXED: Return a more informative message with port and IP version
                return f"TWAMP responder started successfully on port {params['port']} for {ip_version_str}."
            elif isinstance(result, dict) and 'error' in result:
                error_msg = result['error']
                log.error(f"Failed to start responder for {session_key_str}: {error_msg}")
                return f"Error: {error_msg}"
            else:
                log.error(f"Unexpected result type from twl_responder for {session_key_str}: {type(result)}")
                return f"Error: Internal error starting responder {session_key_str} (unexpected result)."

        # --- These except blocks now belong to the outer try ---
        except ValueError as ve:
             return f"Error: Invalid parameter value: {str(ve)}"
        except KeyError as ke:
             # This will catch the raise KeyError("port") if port is missing
             return f"Error: Missing required responder parameter: {str(ke)}"
        except Exception as e:
            log.exception("Error during responder startup:")
            return f"Error: {str(e)}"
        # --- End outer try/except ---

    elif mode == "stop":
        # ... (stop logic remains the same, including logging added previously) ...
        if len(args) < 3:
            return f"Error: Usage: twamp {ip_version_str} stop <responder|sender> [params...]"

        stop_target_type = args[2]

        if stop_target_type == "responder":
            # Parse responder stop params (port)
            port_to_stop = None
            i = 3
            while i < len(args):
                if args[i] == "port" and i + 1 < len(args):
                    try:
                        port_to_stop = int(args[i+1])
                        if not (1024 <= port_to_stop <= 65535):
                             return f"Error: Port must be between 1024 and 65535"
                    except ValueError:
                        return f"Error: Invalid port value '{args[i+1]}' for stop command."
                    i += 2
                else:
                    # Allow only 'port' parameter for stop responder
                    return f"Error: Unknown or misplaced parameter for stop responder: {args[i]}"

            if port_to_stop is None:
                return "Error: Missing required parameter 'port' for stopping responder."

            session_key = (ip_version, port_to_stop)
            session_key_str = f"{ip_version_str}-responder-{port_to_stop}"
            log.info(f"Attempting to stop responder for {session_key_str}")

            target_thread = None
            with _process_lock:
                # +++ Add Logging +++
                log.debug(f"Checking _active_responders for key {session_key}. Current keys: {list(_active_responders.keys())}")
                # +++ End Logging +++
                if session_key in _active_responders:
                    target_thread = _active_responders.pop(session_key) # Remove while locked
                    log.debug(f"Found and removed thread object for key {session_key}. Type: {type(target_thread)}")
                else:
                     log.warning(f"No active responder found in tracking for {session_key_str}.")
                     return f"Error: No active responder found for port {port_to_stop} ({ip_version_str})." # Return error without prompt

            # --- Call the modified stop helper ---
            stop_result_msg = _stop_responder_thread(target_thread, session_key_str)
            return stop_result_msg # Return result directly

        elif stop_target_type == "sender":
            # Parse sender stop params (destination-ip, port)
            dest_ip_to_stop = None
            port_to_stop = None
            i = 3
            while i < len(args):
                if args[i] == "destination-ip" and i + 1 < len(args):
                    dest_ip_to_stop = args[i+1]
                    i += 2
                elif args[i] == "port" and i + 1 < len(args):
                    try:
                        port_to_stop = int(args[i+1])
                        if not (1024 <= port_to_stop <= 65535):
                             return f"Error: Port must be between 1024 and 65535"
                    except ValueError:
                        return f"Error: Invalid port value '{args[i+1]}' for stop sender command."
                    i += 2
                else:
                    return f"Error: Unknown or misplaced parameter for stop sender: {args[i]}"

            if dest_ip_to_stop is None:
                return "Error: Missing required parameter 'destination-ip' for stopping sender."
            if port_to_stop is None:
                return "Error: Missing required parameter 'port' for stopping sender."

            sender_key = (ip_version, dest_ip_to_stop, port_to_stop)
            sender_key_str = f"{ip_version_str}-sender-{dest_ip_to_stop}-{port_to_stop}"
            log.info(f"Attempting to stop sender for {sender_key_str}")

            target_thread = None
            with _process_lock:
                log.debug(f"Checking _active_senders for key {sender_key}. Current keys: {list(_active_senders.keys())}")
                if sender_key in _active_senders:
                    target_thread = _active_senders.pop(sender_key) # Remove while locked
                    log.debug(f"Found and removed sender thread object for key {sender_key}. Type: {type(target_thread)}")
                else:
                     log.warning(f"No active sender found in tracking for {sender_key_str}.")
                     return f"Error: No active sender found for {dest_ip_to_stop}:{port_to_stop} ({ip_version_str})."

            # Call the sender stop helper
            stop_result_msg = _stop_sender_thread(target_thread, sender_key_str)
            return stop_result_msg
        else:
            return f"Error: Unknown stop target type '{stop_target_type}'. Use 'responder' or 'sender'."

    # --- ADD NEW MODE: Get Sender Status/Results ---
    elif mode == "status":
        if len(args) < 3:
            return {"error": f"Usage: twamp {ip_version_str} status sender [params...]"}

        status_target_type = args[2]
        if status_target_type != "sender":
            return {"error": "Status check only implemented for 'sender'."}

        # Parse sender status params (destination-ip, port)
        dest_ip_to_check = None
        port_to_check = None
        i = 3
        while i < len(args):
            if args[i] == "destination-ip" and i + 1 < len(args):
                dest_ip_to_check = args[i+1]
                i += 2
            elif args[i] == "port" and i + 1 < len(args):
                try:
                    port_to_check = int(args[i+1])
                except ValueError:
                    return {"error": f"Invalid port value '{args[i+1]}' for status sender command."}
                i += 2
            else:
                return {"error": f"Unknown or misplaced parameter for status sender: {args[i]}"}

        if dest_ip_to_check is None or port_to_check is None:
            return {"error": "Missing required parameters 'destination-ip' and 'port' for status sender."}

        sender_key = (ip_version, dest_ip_to_check, port_to_check)
        sender_key_str = f"{ip_version_str}-sender-{dest_ip_to_check}-{port_to_check}"

        with _process_lock:
            # Check if running
            if sender_key in _active_senders:
                thread_obj = _active_senders[sender_key]
                if thread_obj.is_alive():
                    log.debug(f"Status check for {sender_key_str}: Thread is active.")
                    return {"status": "running"}
                else:
                    # Thread object exists but not alive - means it finished but maybe results not stored yet, or error?
                    # Check for results immediately. If not found, assume finished without results (or error)
                    log.warning(f"Status check for {sender_key_str}: Thread object found but not alive.")
                    # Remove the dead thread reference
                    del _active_senders[sender_key]

            # Check if results exist (and thread is not running)
            if sender_key in _sender_results:
                log.debug(f"Status check for {sender_key_str}: Found results.")
                result_data = _sender_results.pop(sender_key) # Retrieve and remove results
                return {"status": "completed", "results": result_data["results"], "timestamp": result_data["timestamp"]}

            # If neither running nor results found
            log.debug(f"Status check for {sender_key_str}: No active thread or stored results found.")
            return {"status": "unknown"}
    # --- END STATUS MODE ---

    else:
        return f"Unknown TWAMP mode: '{mode}'. Use 'sender', 'responder', or 'stop'."

    # Fallback if no mode matched
    return f"Unknown TWAMP command structure: {' '.join(args)}"