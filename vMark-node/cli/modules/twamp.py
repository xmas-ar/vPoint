import subprocess
import logging

# Set up logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create and configure the twamp logger
log = logging.getLogger('twamp')
log.setLevel(logging.INFO)

# Also silence pyroute2 debug messages
logging.getLogger('pyroute2').setLevel(logging.WARNING)

# Now import the plugin after logging is configured
from plugins.twamp.onyx import (
    dscpTable, 
    twl_sender, 
    twl_responder,
    start_sender,
    start_responder
)

# Expose the logger to the plugin
import plugins.twamp.onyx as onyx
onyx.log = log

# Command tree structure
command_tree = {
    "dscptable": {},
    "ipv4": {
        "sender": {
            "destination-ip": {  # Changed back to destination-ip from <destination-ip>
                "_options": ["<ip-address>"],
                "format": "Enter destination IP address (REQUIRED)"
            },
            "port": {
                "_options": ["<1024-65535>"],
                "format": "Enter port number (1024-65535) (REQUIRED)"
            },
            "count": {
                "_options": ["<1-9999>"],
                "format": "Enter number of packets to send"
            },
            "interval": {
                "_options": ["<10-1000>"],
                "format": "Enter packet interval in milliseconds"
            },
            "padding": {
                "_options": ["<0-9000>"],
                "format": "Enter padding size in bytes"
            },
            "ttl": {
                "_options": ["<1-255>"],
                "format": "Enter TTL value"
            },
            "tos": {
                "_options": ["<0-255>"],
                "format": "Enter ToS value"
            },
            "do-not-fragment": {}
        },
        "responder": {
            "port": {
                "_options": ["<1024-65535>"],
                "format": "Enter port number (1024-65535) (REQUIRED)"
            },
            "padding": {
                "_options": ["<0-9000>"],
                "format": "Enter padding size in bytes"
            },
            "ttl": {
                "_options": ["<1-255>"],
                "format": "Enter TTL value"
            },
            "tos": {
                "_options": ["<0-255>"],
                "format": "Enter ToS value"
            },
            "do-not-fragment": {}
        }
    },
    "ipv6": {
        "sender": {
            "destination-ip": {
                "_options": ["<ipv6-address>"],
                "format": "Enter IPv6 address (REQUIRED)"
            },
            "port": {
                "_options": ["<1024-65535>"],
                "format": "Enter port number (1024-65535) (REQUIRED)"
            },
            "count": {
                "_options": ["<1-9999>"],
                "format": "Enter number of packets to send"
            },
            "interval": {
                "_options": ["<10-1000>"],
                "format": "Enter packet interval in milliseconds"
            },
            "padding": {
                "_options": ["<0-9000>"],
                "format": "Enter padding size in bytes"
            },
            "ttl": {
                "_options": ["<1-255>"],
                "format": "Enter Time to Live value"
            },
            "tos": {
                "_options": ["<0-255>"],
                "format": "Enter Type of Service value"
            },
            "do-not-fragment": {}
        },
        "responder": {
            "port": {
                "_options": ["<1024-65535>"],
                "format": "Enter port number (1024-65535) (REQUIRED)"
            },
            "padding": {
                "_options": ["<0-9000>"],
                "format": "Enter padding size in bytes"
            },
            "ttl": {
                "_options": ["<1-255>"],
                "format": "Enter TTL value"
            },
            "tos": {
                "_options": ["<0-255>"],
                "format": "Enter ToS value"
            },
            "do-not-fragment": {}
        }
    }
}

# Command descriptions
descriptions = {
    "dscptable": "Display DSCP mapping table",
    "ipv4": {
        "": "IPv4 TWAMP commands",
        "sender": {
            "": "Start TWAMP sender session",
            "destination-ip": {
                "": "Destination IP address (REQUIRED)",
                "_options": ["<ip-address>"]
            },
            "port": {
                "": "Set destination port (REQUIRED)",
                "_options": ["<1024-65535>"]
            },
            "count": {
                "": "Set number of packets",
                "_options": ["<1-9999>"]
            },
            "interval": {
                "": "Set packet interval",
                "_options": ["<10-1000>"]
            },
            "padding": {
                "": "Set packet padding",
                "_options": ["<0-9000>"]
            },
            "ttl": {
                "": "Set Time to Live",
                "_options": ["<1-255>"]
            },
            "tos": {
                "": "Set Type of Service",
                "_options": ["<0-255>"]
            },
            "do-not-fragment": "Set Do Not Fragment flag"
        },
        "responder": {
            "": "Start TWAMP responder session",
            "port": {
                "": "Set local port (REQUIRED)",
                "_options": ["<1024-65535>"]
            },
            "padding": {
                "": "Set packet padding",
                "_options": ["<0-9000>"]
            },
            "ttl": {
                "": "Set Time to Live",
                "_options": ["<1-255>"]
            },
            "tos": {
                "": "Set Type of Service",
                "_options": ["<0-255>"]
            },
            "do-not-fragment": "Set Do Not Fragment flag"
        }
    },
    "ipv6": {
        "": "IPv6 TWAMP commands",
        "sender": {
            "": "Start TWAMP sender session",
            "destination-ip": {
                "": "Destination IPv6 address (REQUIRED)",
                "_options": ["<ipv6-address>"]
            },
            "port": {
                "": "Set destination port (REQUIRED)",
                "_options": ["<1024-65535>"]
            },
            "count": {
                "": "Set number of packets",
                "_options": ["<1-9999>"]
            },
            "interval": {
                "": "Set packet interval",
                "_options": ["<10-1000>"]
            },
            "padding": {
                "": "Set packet padding",
                "_options": ["<0-9000>"]
            },
            "ttl": {
                "": "Set Time to Live",
                "_options": ["<1-255>"]
            },
            "tos": {
                "": "Set Type of Service",
                "_options": ["<0-255>"]
            },
            "do-not-fragment": "Set Do Not Fragment flag"
        },
        "responder": {
            "": "Start TWAMP responder session",
            "port": {
                "": "Set local port (REQUIRED)",
                "_options": ["<1024-65535>"]
            },
            "padding": {
                "": "Set packet padding",
                "_options": ["<0-9000>"]
            },
            "ttl": {
                "": "Set Time to Live",
                "_options": ["<1-255>"]
            },
            "tos": {
                "": "Set Type of Service",
                "_options": ["<0-255>"]
            },
            "do-not-fragment": "Set Do Not Fragment flag"
        }
    }
}

def get_command_tree():
    """Build and return command tree based on descriptions"""
    def build_tree(source, target):
        for key, value in source.items():
            if key in ["_options", "format"]:
                continue
                
            if isinstance(value, dict):
                target[key] = {}
                build_tree(value, target[key])
            else:
                target[key] = None

    result = {}
    build_tree(command_tree, result)
    return result

def get_descriptions():
    """Return the description dictionary."""
    return descriptions

def handle(args, username, hostname):
    """Handle TWAMP commands"""
    prompt = f"{username}/{hostname}@vMark-node> "
    
    if not args:
        return f"{prompt}Usage: twamp <ipv4|ipv6> <sender|responder|dscptable>"

    # Handle dscptable command first
    if args[0] == "dscptable":
        dscpTable()
        return None  # Return None to prevent double prompt
        
    ip_version = args[0]
    if len(args) < 2:
        return f"{prompt}Usage: twamp {ip_version} <sender|responder>"

    mode = args[1]

    if mode == "sender":
        # Initialize parameters with defaults
        params = {
            'dest_ip': None,
            'port': None,
            'count': 100,
            'interval': 100,
            'padding': 0,
            'ttl': 64,
            'tos': 0,
            'do_not_fragment': False
        }

        # Parse parameters
        i = 2
        while i < len(args):
            if args[i] == "destination-ip" and i + 1 < len(args):  # Changed back to destination-ip
                params['dest_ip'] = args[i + 1]
                i += 2
            elif args[i] == "port" and i + 1 < len(args):
                params['port'] = int(args[i + 1])
                i += 2
            elif args[i] == "count" and i + 1 < len(args):
                params['count'] = int(args[i + 1])
                i += 2
            elif args[i] == "interval" and i + 1 < len(args):
                params['interval'] = int(args[i + 1])
                i += 2
            elif args[i] == "padding" and i + 1 < len(args):
                params['padding'] = int(args[i + 1])
                i += 2
            elif args[i] == "ttl" and i + 1 < len(args):
                params['ttl'] = int(args[i + 1])
                i += 2
            elif args[i] == "tos" and i + 1 < len(args):
                params['tos'] = int(args[i + 1])
                i += 2
            elif args[i] == "do-not-fragment":
                params['do_not_fragment'] = True
                i += 1
            else:
                i += 1

        # Validate required parameters
        if not params['dest_ip']:
            return f"{prompt}Error: Missing required parameter: destination-ip"
        if not params['port']:
            return f"{prompt}Error: Missing required parameter: port"

        try:
            class Args:
                def __init__(self):
                    # Fix IPv6 address formatting for socket
                    if ip_version == "ipv6":
                        # Format IPv6 address with square brackets
                        self.far_end = f"[{params['dest_ip']}]:{params['port']}"
                    else:
                        self.far_end = f"{params['dest_ip']}:{params['port']}"
                    self.near_end = ":20001"  # Default local port
                    self.count = params['count']
                    self.interval = params['interval']
                    self.padding = params['padding']
                    self.ttl = params['ttl']
                    self.tos = params['tos']
                    self.do_not_fragment = params['do_not_fragment']

            parsed_args = Args()
            # Print start message before starting the test
            print(f"{prompt}Started TWAMP {ip_version} sender to {params['dest_ip']}:{params['port']}")
            
            # Start the test and capture results
            results = twl_sender(parsed_args)
            
            # Let the test output complete before showing summary
            if results and isinstance(results, dict):
                # Enhanced results display with packet counts
                print("""
=====================================================================================
Direction         Min         Max         Avg          Jitter     Loss     Pkts
-------------------------------------------------------------------------------
  Outbound:         {o_min:3}us       {o_max:3}us       {o_avg:3}us        {o_jit:2}us      {o_loss:.1f}%    {o_pkts:>3}/{o_total:<3}
  Inbound:          {i_min:3}us       {i_max:3}us       {i_avg:3}us        {i_jit:2}us      {i_loss:.1f}%    {i_pkts:>3}/{i_total:<3}
  Roundtrip:        {r_min:3}us       {r_max:3}us       {r_avg:3}us        {r_jit:2}us      {r_loss:.1f}%    Total:{total:>3}
-------------------------------------------------------------------------------
                                         results -  pathgate's Onyx Test [RFC5357]
=====================================================================================""".format(
                    o_min=results.get('outbound_min', 0), 
                    o_max=results.get('outbound_max', 0),
                    o_avg=results.get('outbound_avg', 0), 
                    o_jit=results.get('outbound_jitter', 0),
                    o_loss=results.get('outbound_loss', 0), 
                    o_pkts=results.get('packets_tx', params['count']),
                    o_total=params['count'],
                    i_min=results.get('inbound_min', 0), 
                    i_max=results.get('inbound_max', 0),
                    i_avg=results.get('inbound_avg', 0), 
                    i_jit=results.get('inbound_jitter', 0),
                    i_loss=results.get('inbound_loss', 0), 
                    i_pkts=results.get('packets_rx', 0),
                    i_total=params['count'],
                    r_min=results.get('roundtrip_min', 0), 
                    r_max=results.get('roundtrip_max', 0),
                    r_avg=results.get('roundtrip_avg', 0), 
                    r_jit=results.get('roundtrip_jitter', 0),
                    r_loss=results.get('total_loss', 0), 
                    total=params['count']
                ))
            
            return None  # Return None to prevent double prompt

        except Exception as e:
            return f"{prompt}Error: {str(e)}"

    elif mode == "responder":
        try:
            # Initialize parameters with defaults
            params = {
                'port': None,
                'padding': 0,
                'ttl': 64,
                'tos': 0,
                'do_not_fragment': False
            }

            # Parse parameters in any order
            i = 2
            while i < len(args):
                if args[i] == "port" and i + 1 < len(args):
                    params['port'] = int(args[i + 1])
                    i += 2
                elif args[i] == "padding" and i + 1 < len(args):
                    params['padding'] = int(args[i + 1])
                    i += 2
                elif args[i] == "ttl" and i + 1 < len(args):
                    params['ttl'] = int(args[i + 1])
                    i += 2
                elif args[i] == "tos" and i + 1 < len(args):
                    params['tos'] = int(args[i + 1])
                    i += 2
                elif args[i] == "do-not-fragment":
                    params['do_not_fragment'] = True
                    i += 1
                else:
                    i += 1

            # Validate required parameter
            if not params['port']:
                return f"{prompt}Error: Missing required parameter: port"

            class Args:
                def __init__(self):
                    self.near_end = f":{params['port']}"
                    self.padding = params['padding']
                    self.ttl = params['ttl']
                    self.tos = params['tos']
                    self.do_not_fragment = params['do_not_fragment']

            parsed_args = Args()
            print(f"{prompt}Onyx-Twamp Listening {ip_version} on port {params['port']}")
            twl_responder(parsed_args)
            return None

        except ValueError as ve:
            return f"{prompt}Error: Invalid parameter value: {str(ve)}"
        except Exception as e:
            return f"{prompt}Error: {str(e)}"

    return f"{prompt}Unknown TWAMP command: {' '.join(args)}"

def execute(command_parts):
    """Execute TWAMP commands"""
    if command_parts[0] == "dscptable":
        dscpTable()
        return

    ip_version = command_parts[0]  # ipv4 or ipv6
    mode = command_parts[1]        # sender or responder
    args = command_parts[2:]       # remaining arguments

    # Convert command line args to argparse format
    parser_args = []
    i = 0
    while i < len(args):
        if args[i] in ["near-end", "far-end", "count", "interval", "padding", "ttl", "tos", "dscp"]:
            parser_args.extend([f"--{args[i]}", args[i+1]])
            i += 2
        elif args[i] == "do-not-fragment":
            parser_args.append("--do-not-fragment")
            i += 1
        else:
            i += 1

    # Create namespace object with parsed args
    class Args:
        pass
    parsed_args = Args()
    
    # Set defaults and parsed values
    parsed_args.near_end = ""
    parsed_args.far_end = ""
    parsed_args.count = 100
    parsed_args.interval = 100
    parsed_args.padding = 0
    parsed_args.ttl = 64
    parsed_args.tos = 0
    parsed_args.do_not_fragment = False

    i = 0
    while i < len(parser_args):
        if parser_args[i].startswith("--"):
            arg_name = parser_args[i][2:].replace("-", "_")
            if i + 1 < len(parser_args):
                setattr(parsed_args, arg_name, parser_args[i+1])
                i += 2
            else:
                setattr(parsed_args, arg_name, True)
                i += 1
        else:
            i += 1

    if mode == "sender":
        twl_sender(parsed_args)
    elif mode == "responder":
        twl_responder(parsed_args)