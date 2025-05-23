import threading
import time
import signal
import sys
import json
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn # Import ThreadingMixIn for API server
from pathlib import Path
import logging
import getpass # Import getpass
import os # Import os
import traceback # Import traceback

# Get a logger specific to the API server
api_logger = logging.getLogger('api_server')

# Add global variables for the API server
_api_server_thread = None
_api_server = None

# --- Configuration Management ---
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
        try:
            self.config_file.write_text(json.dumps(config, indent=4))
            api_logger.info(f"Generated initial config with token in {self.config_file}")
        except Exception as e:
            api_logger.error(f"Error writing initial config file {self.config_file}: {e}")
            return None # Indicate failure
        return token

    def get_config(self):
        """Get the current configuration"""
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text())
            except json.JSONDecodeError:
                api_logger.error(f"Error decoding JSON from {self.config_file}")
                return None
            except Exception as e:
                api_logger.error(f"Error reading config file {self.config_file}: {e}")
                return None
        api_logger.warning(f"Config file {self.config_file} does not exist.")
        return None

    def set_registered(self, status: bool, vmark_id: str = None):
        """Update registration status and optionally the vMark ID"""
        config = self.get_config()
        if config:
            config["registered"] = status
            if vmark_id is not None: # Allow setting vmark_id even if status is False (e.g., during unregister)
                config["vmark_id"] = vmark_id
            try:
                self.config_file.write_text(json.dumps(config, indent=4))
                api_logger.info(f"Updated registration status to {status} in {self.config_file}")
            except Exception as e:
                 api_logger.error(f"Error writing config file {self.config_file}: {e}")
        else:
             api_logger.error("Failed to update registration status: could not load config.")


    def update_listen_info(self, listen_ip, port):
        """Store the listening IP and port"""
        config = self.get_config()
        if config:
            config["listen_ip"] = listen_ip
            config["port"] = port
            try:
                self.config_file.write_text(json.dumps(config, indent=4))
                api_logger.info(f"Updated listen info (IP: {listen_ip}, Port: {port}) in {self.config_file}")
            except Exception as e:
                 api_logger.error(f"Error writing config file {self.config_file}: {e}")
        else:
             api_logger.error("Failed to update listen info: could not load config.")

    def is_registered(self):
        """Helper method to check if registered"""
        config = self.get_config()
        # Check for registered=True AND a non-empty vmark_id
        return bool(config and config.get("registered") and config.get("vmark_id"))

# --- Registration State (Temporary) ---
class RegistrationState:
    def __init__(self):
        self.registered = False
        self.running = True

# --- Custom HTTPServer with SO_REUSEADDR ---
class ReusableHTTPServer(HTTPServer):
    """HTTPServer that allows address reuse"""
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        # Set allow_reuse_address before binding
        self.allow_reuse_address = True
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        api_logger.debug(f"ReusableHTTPServer initialized for {server_address}, allow_reuse_address={self.allow_reuse_address}")

class ThreadingReusableHTTPServer(ThreadingMixIn, ReusableHTTPServer):
    """Threading HTTPServer that allows address reuse"""
    daemon_threads = True # Allow server thread to exit if main thread exits
    pass

# --- Temporary Registration Handler ---
def create_handler(reg_state):
    """Factory to create the temporary registration handler"""
    class RegistrationHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/register":
                try:
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))

                    client_address = self.client_address[0]
                    client_port = self.client_address[1]
                    #print(f"[Registration] Received request from {client_address}:{client_port}")

                    config_manager = RegisterConfig() # Use instance
                    config = config_manager.get_config()
                    if not config:
                        print("[Registration] Error: No configuration found")
                        self.send_error(500, "No registration configuration found")
                        return

                    if data.get("auth_token") == config["auth_token"]:
                        print("[Registration] Token validated successfully - registration complete")
                        reg_state.registered = True
                        reg_state.running = False # Signal main loop to stop

                        # Store vMark ID provided by the backend
                        vmark_id = data.get("vmark_id")
                        if not vmark_id:
                             print("[Registration] Error: Backend did not provide vMark ID in registration response.")
                             # Don't mark as registered if ID is missing
                             config_manager.set_registered(False, None)
                             self.send_error(500, "Backend did not provide vMark ID")
                             return

                        config_manager.set_registered(True, vmark_id) # Use instance

                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "status": "success",
                            "node_id": config.get("node_id", f"vmark-node-{socket.gethostname()}")
                        }).encode())
                    else:
                        print(f"[Registration] Invalid token received")
                        self.send_error(401, "Invalid authentication token")
                except Exception as e:
                    print(f"[Registration] Error processing request: {str(e)}\n{traceback.format_exc()}")
                    self.send_error(500, f"Registration error: {str(e)}")
            else:
                self.send_error(404, "Not found")

        def log_message(self, format, *args):
            # Log registration server messages to console only for clarity
            print(f"[Registration Server] {format%args}")

    return RegistrationHandler

# --- Persistent API Handler ---
class APIHandler(BaseHTTPRequestHandler):
    """Handles persistent API requests after registration"""
    def __init__(self, *args, vmark_id=None, **kwargs):
        if vmark_id is None:
            # This should not happen if start_api_server is called correctly
            api_logger.error("CRITICAL: APIHandler initialized without a vmark_id!")
        self.vmark_id = vmark_id # Store the expected vMark ID
        super().__init__(*args, **kwargs)

    def do_POST(self):
        # Import dispatch here to avoid potential circular dependencies at module level
        from cli.dispatcher import dispatch
        output = "" # Initialize output
        status_code = 200 # Default status code
        response_data = {} # Initialize response data structure

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                 api_logger.warning(f"Received POST request on {self.path} with no Content-Length from {self.client_address[0]}")
                 self.send_error(411, "Content-Length required") # Length Required
                 return

            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            #api_logger.info(f"Received POST request on {self.path} from {self.client_address[0]}")
            #api_logger.debug(f"Request data: {data}") # Log data only in debug

            # --- Authentication ---
            received_vmark_id = data.get("vmark_id")
            if received_vmark_id != self.vmark_id:
                api_logger.warning(f"Received request with invalid vMark ID: '{received_vmark_id}' (expected: '{self.vmark_id}') from {self.client_address[0]}")
                self.send_error(403, "Invalid vMark ID") # Forbidden
                return
            #api_logger.debug(f"vMark ID validated successfully for request to {self.path}.")
            # --- End Authentication ---

            # --- API Routing ---
            if self.path == "/api/status":
                response_data = { "status": "online", "timestamp": time.time() }
                status_code = 200
                #api_logger.debug("Responding to /api/status")

            elif self.path == "/api/heartbeat":
                 response_data = { "status": "online", "timestamp": time.time() }
                 status_code = 200
                 #api_logger.debug("Responding to /api/heartbeat")

            elif self.path == "/api/execute":
                command_str = data.get("command")
                if not command_str:
                    output = "Missing 'command' in request body"
                    status_code = 400
                    api_logger.warning("Received execute request without 'command'.")
                    response_data = {"error": output}
                else:
                    api_logger.info(f"Executing command: {command_str}")
                    try:
                        # Use dispatch to handle the command
                        command_parts = command_str.split()
                        # Pass dummy user/host for API context
                        command_output = dispatch(command_str, "api_user", "remote")
                        output = command_output if command_output is not None else "" # Use returned output
                        api_logger.info(f"Command output length: {len(output)} chars")
                        api_logger.debug(f"Command output: {output}") # Log full output only in debug

                        # Check if output indicates an error to set status code (optional)
                        if isinstance(output, str) and output.lower().startswith("error:"):
                            status_code = 400 # Bad request if command failed due to params etc.
                        elif isinstance(output, str) and "unavailable" in output.lower():
                             status_code = 501 # Not Implemented if plugin failed to load

                        # Structure the response for execute
                        response_data = {"output": output}

                    except Exception as cmd_exc:
                        # Handle errors during command dispatch/execution
                        error_output = f"Error executing command '{command_str}': {str(cmd_exc)}"
                        api_logger.error(error_output, exc_info=True)
                        # Return error in the standard output format if possible
                        response_data = {"output": error_output}
                        status_code = 500 # Internal Server Error

            else:
                output = "Endpoint not found"
                status_code = 404
                api_logger.warning(f"Request received for unknown endpoint: {self.path}")
                response_data = {"error": output}

            # --- Generic Response Sending ---
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            #api_logger.debug(f"Sent {status_code} response for {self.path}")

        except json.JSONDecodeError:
            api_logger.error(f"Invalid JSON received from {self.client_address[0]} for path {self.path}")
            self.send_error(400, "Invalid JSON format") # Bad Request
        except ConnectionAbortedError:
             api_logger.warning(f"Connection aborted by client during request to {self.path}.")
        except Exception as e:
            api_logger.error(f"Internal server error processing {self.path}: {e}\n{traceback.format_exc()}")
            # Avoid sending detailed exception back unless needed for debugging
            try:
                # Try to send a 500 error if headers haven't been sent
                if not self.headers_sent:
                     self.send_error(500, f"Internal Server Error")
            except Exception as send_err:
                 api_logger.error(f"Failed to send 500 error response: {send_err}")

    def log_message(self, format, *args):
        """Override default logging to use our api_logger."""
        #api_logger.info("%s - %s" % (self.address_string(), format % args))

    def log_error(self, format, *args):
        """Override default error logging to use api_logger."""
        api_logger.error("%s - %s" % (self.address_string(), format % args))

# --- API Server Management ---
def create_api_handler(vmark_id):
    """Factory function to create APIHandler instances with the vmark_id"""
    if not vmark_id:
         api_logger.error("Attempted to create API handler factory without vmark_id!")
         # Return a dummy handler or raise error? Raising is safer.
         raise ValueError("vmark_id is required to create the API handler")
    return lambda *args, **kwargs: APIHandler(*args, vmark_id=vmark_id, **kwargs)

def start_api_server(ip, port, vmark_id):
    """Start the persistent API server using ThreadingReusableHTTPServer"""
    global _api_server_thread, _api_server

    if not vmark_id:
        api_logger.error("Cannot start API server: vmark_id is missing.")
        return False

    # Check if already running
    if _api_server_thread and _api_server_thread.is_alive():
        api_logger.info(f"API server already running on {ip}:{port}.")
        return True

    try:
        api_logger.info(f"Attempting to start API server on {ip}:{port} with vMark ID {vmark_id}")
        # Use the ThreadingReusableHTTPServer and the factory
        _api_server = ThreadingReusableHTTPServer((ip, port), create_api_handler(vmark_id))
        _api_server_thread = threading.Thread(target=_api_server.serve_forever)
        _api_server_thread.daemon = True  # Thread will exit when main thread exits
        _api_server_thread.name = "vMarkNodeAPI"
        _api_server_thread.start()
        api_logger.info(f"API server thread '{_api_server_thread.name}' started successfully for {ip}:{port}")
        return True
    except OSError as e:
        # Specifically handle address already in use
        if e.errno == 98: # EADDRINUSE
             api_logger.error(f"API server failed to start: Address {ip}:{port} already in use.")
        else:
             api_logger.error(f"API server failed to start due to OS error: {str(e)}", exc_info=True)
        _api_server = None # Ensure server object is cleared on failure
        return False
    except Exception as e:
        api_logger.error(f"Error starting API server: {str(e)}", exc_info=True)
        _api_server = None
        return False

def stop_api_server():
    """Stops the persistent API server thread."""
    global _api_server_thread, _api_server
    if _api_server:
        api_logger.info("Shutting down API server...")
        try:
            _api_server.shutdown() # Signal the server to stop serving
            _api_server.server_close() # Close the server socket
            api_logger.info("API server socket closed.")
        except Exception as e:
            api_logger.error(f"Error during API server shutdown: {e}")
        finally:
             _api_server = None

    if _api_server_thread and _api_server_thread.is_alive():
        api_logger.info("Waiting for API server thread to join...")
        _api_server_thread.join(timeout=5.0) # Wait for the thread to finish
        if _api_server_thread.is_alive():
            api_logger.warning("API server thread did not join cleanly.")
        else:
            api_logger.info("API server thread joined successfully.")
    else:
        api_logger.info("API server thread was not running or already stopped.")

    _api_server_thread = None


def initialize_api_on_startup():
    """Check if we're registered and start the API server on startup"""
    config_instance = RegisterConfig()

    if config_instance.is_registered():
        api_logger.info("Node is registered, attempting API server startup.")

        config = config_instance.get_config()
        if not config:
            print("[Startup] Error: Could not load configuration")
            api_logger.error("Could not load configuration during startup.")
            return

        ip = config.get("listen_ip")
        port_str = config.get("port")
        vmark_id = config.get("vmark_id")

        if not ip or not port_str:
             print("[Startup] Error: Listen IP or Port missing in configuration.")
             api_logger.error("Listen IP or Port missing in configuration during startup.")
             return
        if not vmark_id:
            print("[Startup] Error: No vMark ID found in configuration")
            api_logger.error("No vMark ID found in configuration during startup.")
            return

        try:
            port = int(port_str)
        except (ValueError, TypeError):
             print(f"[Startup] Error: Invalid port number '{port_str}' in configuration.")
             api_logger.error(f"Invalid port number '{port_str}' in configuration during startup.")
             return

        # Call start_api_server with the correct parameters
        if start_api_server(ip, port, vmark_id):
            print(f"[Startup] API server started successfully on {ip}:{port}")
        else:
            print("[Startup] Failed to start API server (check ~/.vmark/api.log)")
    else:
        api_logger.info("Node not registered, skipping API server startup.")


# --- CLI Command Definitions ---
command_tree = {
    "register": {
        "vmark": {
            "link-api": {
                "listen-ip": None,  # Expects <ip-address>
                "port": None,       # Expects <port>
                "pin": None         # Flag option
            }
            # Add unlink-api, status etc. here later if needed
        }
    }
}

descriptions = {
    "register": {
        "": "Manage registration with the vMark backend API",
        "vmark": {
            "": "vMark server registration commands",
            "link-api": {
                "": "Start registration listener to link with vMark",
                "listen-ip": {
                    "": "IP address for this node to listen on",
                    "_options": ["<ip-address>"]
                },
                "port": {
                    "": "Port number for this node to listen on (1024-65535)",
                    "_options": ["<port>"]
                },
                "pin": {
                    "": "Use a 4-digit PIN for authentication instead of a long token"
                }
            }
            # Add descriptions for unlink-api, status etc. here
        }
    }
}

def get_command_tree():
    """Return the command tree structure for register commands."""
    tree = {
        "vmark": {
            "link-api": {
                "listen-ip": {
                    "<ip-address>": {}  # Change from None to {} for proper nesting
                },
                "port": {
                    "<port>": {}  # Change from None to {} for proper nesting
                },
                "pin": {}  # Change from None to {} for proper nesting
            }
        }
    }
    
    # Create proper sibling relationships
    siblings = ["listen-ip", "port", "pin"]
    for param in siblings:
        if param in tree["vmark"]["link-api"]:
            for option in tree["vmark"]["link-api"][param]:
                for sibling in siblings:
                    if sibling != param:
                        tree["vmark"]["link-api"][param][option][sibling] = tree["vmark"]["link-api"][sibling]
    
    return tree

def get_descriptions():
    """Return the description tree for register commands"""
    return descriptions

# --- Registration Execution Logic ---
def execute_registration(listen_ip, port, prompt, use_pin=False):
    """Execute the actual registration process"""
    config_manager = RegisterConfig() # Use instance
    server = None # Initialize server to None
    server_thread = None # Initialize thread to None
    reg_state = RegistrationState() # State for the temporary server loop

    try:
        # Generate token and prepare state
        token = config_manager.generate_token(use_pin)
        if token is None:
             return f"{prompt}Error: Failed to generate/save initial configuration."

        # Save listen info before starting server
        config_manager.update_listen_info(listen_ip, port)

        # Start HTTP server in a separate thread using ReusableHTTPServer
        # This allows the persistent server to potentially reuse the address faster
        server = ReusableHTTPServer((listen_ip, port), create_handler(reg_state))
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.name = "vMarkNodeRegTemp"
        server_thread.start()
        print(f"[Registration] Temporary registration server thread '{server_thread.name}' started.")

        print(f"""
{prompt}Registration server started on {listen_ip}:{port}
Your authentication token is: {token}

Please use this token when adding this node in vMark.
Waiting for registration... (Press Ctrl+C to cancel)
""")

        # Wait for registration or cancellation in the main thread
        while reg_state.running:
            # Check if thread died unexpectedly
            if not server_thread.is_alive():
                 print(f"\n{prompt}Error: Registration server thread stopped unexpectedly.")
                 api_logger.error("Temporary registration server thread stopped unexpectedly.")
                 reg_state.running = False # Exit loop
                 reg_state.registered = False # Mark as not registered
                 break
            time.sleep(0.5) # Short sleep to be responsive

    except KeyboardInterrupt:
        print(f"\n{prompt}Ctrl+C detected. Cancelling registration...")
        reg_state.running = False # Signal loop to stop if it hasn't already
        # No need to set registered=False, it defaults to that
        return f"{prompt}Registration cancelled by user."
    except OSError as e:
         if e.errno == 98: # EADDRINUSE
             print(f"{prompt}Error starting registration server: Address {listen_ip}:{port} already in use.")
             api_logger.error(f"Failed to start temporary registration server: Address {listen_ip}:{port} already in use.")
             return f"{prompt}Error: Address {listen_ip}:{port} already in use. Cannot start registration."
         else:
             print(f"{prompt}Error starting registration server: {str(e)}")
             api_logger.error(f"Failed to start temporary registration server: {str(e)}", exc_info=True)
             return f"{prompt}Error starting registration server: {str(e)}"
    except Exception as e:
        print(f"{prompt}Error during registration process: {str(e)}")
        api_logger.error(f"Unexpected error during registration process: {str(e)}", exc_info=True)
        return f"{prompt}Error during registration process: {str(e)}"
    finally:
        # --- Shutdown Temporary Server ---
        if server:
            print(f"{prompt}Shutting down temporary registration server...")
            server.shutdown()
            server.server_close()
            print(f"{prompt}Temporary registration server shut down.")
        if server_thread and server_thread.is_alive():
             print(f"{prompt}Waiting for temporary registration server thread to join...")
             server_thread.join(timeout=2.0) # Wait briefly for thread to finish
             if server_thread.is_alive():
                  api_logger.warning("Temporary registration server thread did not join cleanly.")
             else:
                  print(f"{prompt}Temporary registration server thread joined.")

        # --- REMOVED time.sleep() ---
        # Rely on SO_REUSEADDR instead of sleep

    # --- Start Persistent API Server (if registration was successful) ---
    if reg_state.registered:
        print(f"{prompt}Registration successful! Node is now connected to vMark.")
        api_logger.info("Temporary registration successful, proceeding to start persistent API server.")
        # Get the updated config with vMark ID
        config_data = config_manager.get_config() # Use instance
        if not config_data or not config_data.get("vmark_id"):
            api_logger.error("Registration marked successful, but vMark ID missing in config.")
            return f"{prompt}Registration error: No vMark ID found after registration."

        # Use the same IP/Port for the persistent server
        persistent_ip = config_data.get("listen_ip")
        persistent_port_str = config_data.get("port")
        vmark_id = config_data.get("vmark_id")

        if not persistent_ip or not persistent_port_str:
             api_logger.error("Listen IP or Port missing in config before starting persistent server.")
             return f"{prompt}Registration error: IP/Port missing in config."

        try:
            persistent_port = int(persistent_port_str)
        except (ValueError, TypeError):
             api_logger.error(f"Invalid port '{persistent_port_str}' in config before starting persistent server.")
             return f"{prompt}Registration error: Invalid port in config."

        # Start persistent API server
        if start_api_server(persistent_ip, persistent_port, vmark_id):
            return f"{prompt}Persistent API server started successfully on {persistent_ip}:{persistent_port}."
        else:
            # start_api_server logs the specific error (like EADDRINUSE)
            return f"{prompt}Registration completed but failed to start persistent API server (check ~/.vmark/api.log)."
    elif not reg_state.running and not reg_state.registered:
         # This case handles unexpected server thread death or other errors
         # where the loop exited but registration didn't complete.
         api_logger.warning("Registration loop exited without completing registration.")
         return f"{prompt}Registration did not complete successfully."
    else:
        # This case handles cancellation (KeyboardInterrupt already returned)
        # or if the loop somehow exited while still running (shouldn't happen).
        api_logger.info("Registration was cancelled or did not complete.")
        # Return message for cancellation is handled in the except block
        # If it wasn't cancelled, provide a generic message.
        if 'prompt' in locals(): # Ensure prompt is defined
            return f"{prompt}Registration cancelled or not completed."
        else:
            return "Registration cancelled or not completed."


# --- CLI Command Handler ---
def handle(args, username, hostname):
    """Handle registration commands"""
    prompt = f"{username}/{hostname}@vMark-node> "

    if not args:
        return f"{prompt}Usage: register vmark link-api listen-ip <ip-address> port <port> [pin]"

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
                param_name = args[i]
                param_value = args[i + 1]
                if param_name == "listen-ip":
                    listen_ip = param_value
                    # Basic IP validation could be added here if desired
                    i += 2
                elif param_name == "port":
                    try:
                        port_value = int(param_value)
                        if 1024 <= port_value <= 65535:
                            port = port_value
                        else:
                            return f"{prompt}Error: Port must be between 1024 and 65535"
                    except ValueError:
                        return f"{prompt}Error: Invalid port number '{param_value}'"
                    i += 2
                else:
                    return f"{prompt}Unknown parameter or missing value: {param_name}"
            else:
                # Handle case where parameter is last argument without a value (except 'pin')
                if args[i] != "pin":
                     return f"{prompt}Missing value for parameter: {args[i]}"
                else: # If 'pin' is last, it's okay
                     use_pin = True
                     i += 1

        # Check if we have both required parameters
        if listen_ip and port:
            return execute_registration(listen_ip, port, prompt, use_pin)
        else:
            missing = []
            if not listen_ip:
                missing.append("listen-ip")
            if not port:
                missing.append("port")
            return f"{prompt}Missing required parameters: {', '.join(missing)}. Usage: register vmark link-api listen-ip <ip> port <port> [pin]"

    # Add handlers for other register commands like 'status', 'unlink-api' here later

    return f"{prompt}Invalid command or structure. Usage: register vmark link-api ..."