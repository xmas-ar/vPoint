import threading
import time
import signal
import sys
import json
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import logging # Import logging

# Get a logger specific to the API server
api_logger = logging.getLogger('api_server')

# Add global variables for the API server
_api_server_thread = None
_api_server = None

# Define the RegisterConfig class
class RegisterConfig:
    def __init__(self):
        self.config_dir = Path.home() / ".vmark"
        self.config_file = self.config_dir / "register.json"
        self.config_dir.mkdir(exist_ok=True)

    def generate_token(self, use_pin=False):
        """Generate a new token and create an initial config"""
        if use_pin:
            import random
            token = ''.join([str(random.randint(0, 9)) for _ in range(4)])
        else:
            import secrets
            token = secrets.token_urlsafe(32)
            
        config = {
            "auth_token": token,
            "registered": False,
            "node_id": f"vmark-node-{socket.gethostname()}",
            "vmark_id": None,
            "listen_ip": None,
            "port": None
        }
        self.config_file.write_text(json.dumps(config))
        return token

    def get_config(self):
        """Get the current configuration"""
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text())
            except:
                return None
        return None

    def set_registered(self, status: bool, vmark_id: str = None):
        """Update registration status and optionally the vMark ID"""
        if self.config_file.exists():
            try:
                config = json.loads(self.config_file.read_text())
                config["registered"] = status
                if vmark_id:
                    config["vmark_id"] = vmark_id
                self.config_file.write_text(json.dumps(config))
                return True
            except:
                return False
        return False

    def update_listen_info(self, listen_ip, port):
        """Store the listening IP and port"""
        if self.config_file.exists():
            try:
                config = json.loads(self.config_file.read_text())
                config["listen_ip"] = listen_ip
                config["port"] = port
                self.config_file.write_text(json.dumps(config))
                return True
            except:
                return False
        return False
        
    # This method is now directly defined in the class
    def is_registered(self):
        """Helper method to check if registered"""
        config = self.get_config()
        return bool(config and config.get("registered") and config.get("vmark_id"))

# Also need to define RegistrationState class
class RegistrationState:
    def __init__(self):
        self.registered = False
        self.running = True

# Define the handler creation function needed for registration
def create_handler(reg_state):
    class RegistrationHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/register":
                try:
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    client_address = self.client_address[0]
                    client_port = self.client_address[1]
                    print(f"[Registration] Received request from {client_address}:{client_port}")
                    
                    config = RegisterConfig().get_config()
                    if not config:
                        print("[Registration] No configuration found")
                        self.send_error(500, "No registration configuration found")
                        return

                    if data.get("auth_token") == config["auth_token"]:
                        print("[Registration] Token validated successfully - registration complete")
                        reg_state.registered = True
                        reg_state.running = False
                        
                        # Store vMark ID if provided
                        vmark_id = data.get("vmark_id", "unknown_vmark")
                        RegisterConfig().set_registered(True, vmark_id)
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "status": "success",
                            "node_id": config.get("node_id", "vmark-node")
                        }).encode())
                    else:
                        print(f"[Registration] Invalid token received")
                        self.send_error(401, "Invalid authentication token")
                except Exception as e:
                    print(f"[Registration] Error processing request: {str(e)}")
                    self.send_error(500, f"Registration error: {str(e)}")
            else:
                self.send_error(404, "Not found")
                
        def log_message(self, format, *args):
            print(f"[Registration Server] {format%args}")
            
    return RegistrationHandler

# Rest of your existing code...
class APIHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, vmark_id=None, **kwargs):
        self.vmark_id = vmark_id
        super().__init__(*args, **kwargs)
        
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            # Verify the vmark_id matches the one we registered with
            if data.get("vmark_id") != self.vmark_id:
                # Log the error to the file
                api_logger.warning(f"Received request with invalid vMark ID: {data.get('vmark_id')}")
                self.send_error(403, "Invalid vMark ID")
                return
            
            # Handle different API endpoints
            if self.path == "/api/status":
                response = {
                    "status": "online",
                    "timestamp": time.time()
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                
            elif self.path == "/api/heartbeat":
                response = {
                    "status": "online",
                    "timestamp": time.time()
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                
            else:
                self.send_error(404, "Endpoint not found")
                
        except Exception as e:
            # Log the error to the file
            api_logger.error(f"Error processing request: {str(e)}", exc_info=True)
            self.send_error(500, f"API error: {str(e)}")
            
    def log_message(self, format, *args):
        """Override to log messages to the file via api_logger."""
        # Check if the first argument is a string (likely a request line)
        if isinstance(args[0], str) and args[0].startswith('POST /api/heartbeat'):
            # Suppress logging for heartbeat requests entirely
            pass
        else:
            # Log other requests and all errors to the file
            api_logger.info(format % args)

# Rest of the file continues as before
def create_api_handler(vmark_id):
    return lambda *args, **kwargs: APIHandler(*args, vmark_id=vmark_id, **kwargs)

def start_api_server(ip, port, vmark_id):
    """Start the persistent API server"""
    global _api_server_thread, _api_server
    
    # Check if already running
    if _api_server_thread and _api_server_thread.is_alive():
        api_logger.info("API server already running.") # Log to file
        return True
        
    try:
        api_logger.info(f"Attempting to start API server on {ip}:{port}") # Log to file
        # Create and configure the server
        _api_server = HTTPServer((ip, port), create_api_handler(vmark_id))
        _api_server_thread = threading.Thread(target=_api_server.serve_forever)
        _api_server_thread.daemon = True  # Thread will exit when main thread exits
        _api_server_thread.start()
        api_logger.info(f"API server thread started for {ip}:{port}") # Log to file
        return True
    except Exception as e:
        api_logger.error(f"Error starting API server: {str(e)}", exc_info=True) # Log to file
        return False

def initialize_api_on_startup():
    """Check if we're registered and start the API server on startup"""
    config_instance = RegisterConfig()
    
    if config_instance.is_registered():
        # This print remains for console feedback
        print("[Startup] Node is registered with vMark, attempting to start API server...")
        
        config = config_instance.get_config()
        if not config:
            # This print remains for console feedback
            print("[Startup] Error: Could not load configuration")
            api_logger.error("Could not load configuration during startup.") # Log detail
            return
            
        ip = config.get("listen_ip", "0.0.0.0")
        port = int(config.get("port", 1050))
        vmark_id = config.get("vmark_id")
        
        if not vmark_id:
            # This print remains for console feedback
            print("[Startup] Error: No vMark ID found in configuration")
            api_logger.error("No vMark ID found in configuration during startup.") # Log detail
            return
            
        if start_api_server(ip, port, vmark_id):
            # This print remains for console feedback
            print(f"[Startup] API server started successfully on {ip}:{port}")
        else:
            # This print remains for console feedback
            print("[Startup] Failed to start API server")
    else:
        # This print remains for console feedback
        print("[Startup] Node is not registered with vMark, skipping API server startup")

def execute_registration(listen_ip, port, prompt, use_pin=False):
    """Execute the actual registration process"""
    try:
        # Generate token and prepare state
        config = RegisterConfig()
        token = config.generate_token(use_pin)
        
        # Save listen info
        config.update_listen_info(listen_ip, port)
        
        reg_state = RegistrationState()
        
        try:
            # Start HTTP server in a separate thread
            server = HTTPServer((listen_ip, port), create_handler(reg_state))
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.daemon = True
            server_thread.start()
            
            print(f"""
{prompt}Registration server started on {listen_ip}:{port}
Your authentication token is: {token}

Please use this token when adding this node in vMark.
Waiting for registration... (Press Ctrl+C to cancel)
""")

            # Wait for registration or cancellation
            try:
                while reg_state.running:
                    time.sleep(1)
                
                if reg_state.registered:
                    print(f"{prompt}Stopping registration server...")
                    server.shutdown()
                    server.server_close()
                    
                    # Get the updated config with vMark ID
                    config_data = config.get_config()
                    if not config_data or not config_data.get("vmark_id"):
                        return f"{prompt}Registration error: No vMark ID received"
                    
                    # Start persistent API server
                    if start_api_server(listen_ip, port, config_data.get("vmark_id")):
                        return f"{prompt}Registration successful! Node is now connected to vMark."
                    else:
                        return f"{prompt}Registration completed but failed to start API server."
                else:
                    return f"{prompt}Registration cancelled."
                    
            except KeyboardInterrupt:
                reg_state.running = False
                return f"{prompt}Registration cancelled by user."
            finally:
                print(f"{prompt}Stopping registration server...")
                server.shutdown()
                server.server_close()
                
        except Exception as e:
            return f"{prompt}Error starting registration server: {str(e)}"
            
    except Exception as e:
        return f"{prompt}Error in registration process: {str(e)}"

def get_command_tree():
    """Return the command tree structure for register commands."""
    # Structure representing peer options under link-api
    # None indicates a command/option that might expect a value
    # or is a flag. The completion logic should use descriptions
    # to show expected value format (e.g., <ip-address>).
    command_tree = {
        "vmark": {
            "link-api": {
                "listen-ip": None,  # Expects <ip-address>
                "port": None,       # Expects <port>
                "pin": None         # Flag option
            }
        }
    }
    return command_tree

# Variable descriptions a nivel de módulo
descriptions = {
    "": "Register this node with a vMark server",
    "vmark": {
        "": "vMark server registration commands",
        "link-api": {
            "": "Start registration API listener",
            # These _options should guide the completion helper (?)
            "listen-ip": {
                "": "IP address to listen on",
                "_options": ["<ip-address>"] # Hint for expected value
            },
            "port": {
                "": "Port number to listen on (1024-65535)",
                "_options": ["<port>"] # Hint for expected value
            },
            "pin": {
                "": "Use a 4-digit PIN instead of a long token"
                # No _options needed as it's a flag
            }
        }
    }
}

def get_descriptions():
    """Return the description tree for register commands"""
    return descriptions

def handle(args, username, hostname):
    """Handle registration commands"""
    prompt = f"{username}/{hostname}@vMark-node> "
    
    if not args:
        return f"{prompt}Usage: register vmark link-api [listen-ip <ip-address>] [port <port>] [pin]"
    
    # Initialize variables to store parameters
    listen_ip = None
    port = None
    use_pin = False
    
    # Check basic command structure
    if len(args) >= 2 and args[0] == "vmark" and args[1] == "link-api":
        # Parse parameters in any order
        i = 2
        while i < len(args):
            if args[i] == "pin":
                use_pin = True
                i += 1
            elif i + 1 < len(args):
                if args[i] == "listen-ip":
                    listen_ip = args[i + 1]
                    i += 2
                elif args[i] == "port":
                    try:
                        port_value = int(args[i + 1])
                        if 1024 <= port_value <= 65535:
                            port = port_value
                        else:
                            return f"{prompt}Error: Port must be between 1024 and 65535"
                    except ValueError:
                        return f"{prompt}Error: Invalid port number"
                    i += 2
                else:
                    return f"{prompt}Unknown parameter: {args[i]}"
            else:
                return f"{prompt}Missing value for parameter: {args[i]}"
        
        # Check if we have both required parameters
        if listen_ip and port:
            return execute_registration(listen_ip, port, prompt, use_pin)
        else:
            missing = []
            if not listen_ip:
                missing.append("listen-ip")
            if not port:
                missing.append("port")
            return f"{prompt}Missing required parameters: {', '.join(missing)}"
    
    return f"{prompt}Invalid command. Usage: register vmark link-api [listen-ip <ip-address>] [port <port>] [pin]"