import logging
import logging.handlers # For potential rotation later
from pathlib import Path
import os # For creating directory if needed

# --- Add this Logging Configuration ---
import logging
import logging.handlers
from pathlib import Path
import os
logging.getLogger("pr2modules.ipdb.main").setLevel(logging.ERROR)
def setup_logging():
    log_dir = Path.home() / ".vmark"  # <-- Add this line
    """Configure file logging for both API server and eBPF."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(log_dir, 0o755)
    except OSError as e:
        print(f"Error creating log directory {log_dir}: {e}")
        return

    # Setup API logging
    api_log_file = log_dir / "api.log"
    api_logger = logging.getLogger('api_server')
    api_logger.setLevel(logging.DEBUG)
    api_logger.propagate = False

    api_handler = logging.FileHandler(api_log_file)
    api_handler.setLevel(logging.DEBUG)
    api_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    api_handler.setFormatter(api_formatter)
    
    if not api_logger.hasHandlers():
        api_logger.addHandler(api_handler)

    # Setup eBPF logging
    ebpf_log_file = log_dir / "shell.log"
    try:
        if not ebpf_log_file.exists():
            ebpf_log_file.touch(mode=0o644)
        else:
            os.chmod(ebpf_log_file, 0o644)
    except Exception as e:
        print(f"Error creating eBPF log file: {e}")
        return

    ebpf_logger = logging.getLogger('ebpf')
    ebpf_logger.setLevel(logging.DEBUG)
    ebpf_logger.propagate = False

    # File handler with DEBUG level
    file_handler = logging.handlers.RotatingFileHandler(
        ebpf_log_file,
        maxBytes=10*1024*1024,
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - [eBPF] - %(message)s')
    file_handler.setFormatter(file_formatter)

    # Console handler with ERROR level only
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)  # Only show errors in console
    console_formatter = logging.Formatter('%(message)s')  # Simplified format for console
    console_handler.setFormatter(console_formatter)

    # Remove any existing handlers
    ebpf_logger.handlers.clear()
    
    # Add handlers
    ebpf_logger.addHandler(file_handler)
    ebpf_logger.addHandler(console_handler)

    # Setup TWAMP logging (MODIFIED CODE)
    twamp_logger = logging.getLogger('twamp')
    twamp_logger.setLevel(logging.DEBUG)
    twamp_logger.propagate = False

    # File handler - use the same shell.log file as eBPF
    twamp_file_handler = logging.handlers.RotatingFileHandler(
        ebpf_log_file,
        maxBytes=10*1024*1024,
        backupCount=5
    )
    twamp_file_handler.setLevel(logging.DEBUG)
    twamp_file_formatter = logging.Formatter('%(asctime)s - [TWAMP] - %(message)s')
    twamp_file_handler.setFormatter(twamp_file_formatter)
    
    # Console handler - show INFO level and above for TWAMP operations
    twamp_console_handler = logging.StreamHandler()
    twamp_console_handler.setLevel(logging.ERROR)
    twamp_console_formatter = logging.Formatter('[TWAMP] %(message)s')
    twamp_console_handler.setFormatter(twamp_console_formatter)
    
    # Clear existing handlers if any
    twamp_logger.handlers.clear()
    
    # Add handlers
    twamp_logger.addHandler(twamp_file_handler)
    twamp_logger.addHandler(twamp_console_handler)
    # End of TWAMP logging setup

    # Test loggers
    api_logger.info("API logging initialized")
    ebpf_logger.info("eBPF logging initialized")
    twamp_logger.info("TWAMP logging initialized")

def ensure_forwarding_table_file():
    """
    Ensure the forwarding table JSON file exists and is initialized as an empty list if missing.
    """
    forwarding_table_path = Path.home() / ".vmark" / "forwarding_table.json"
    try:
        forwarding_table_path.parent.mkdir(parents=True, exist_ok=True)
        if not forwarding_table_path.exists():
            forwarding_table_path.write_text("[]\n")
            os.chmod(forwarding_table_path, 0o644)
    except Exception as e:
        print(f"Error creating forwarding table file {forwarding_table_path}: {e}")

def debug_forwarding_table_file():
    """Debug: Print and log the contents and type of the forwarding table file."""
    # Check both possible locations
    locations = [
        Path.home() / ".vmark" / "forwarding_table.json",  # User's home dir
    ]
    
    for forwarding_table_path in locations:
        #print(f"DEBUG: Checking forwarding table file at {forwarding_table_path}")
        try:
            if forwarding_table_path.exists():
                content = forwarding_table_path.read_text()
                import json
                try:
                    data = json.loads(content)
                    #print(f"DEBUG: JSON loaded type: {type(data)}, value: {data}")
                    #logging.getLogger('ebpf').info(f"DEBUG: forwarding_table.json loaded type: {type(data)}, value: {data}")
                    
                    # If this is the old location, copy to new location
                    if str(forwarding_table_path).startswith("/pi/") and not (Path.home() / ".vmark" / "forwarding_table.json").exists():
                        logging.getLogger('ebpf').info(f"DEBUG: Copying rules from {forwarding_table_path} to {Path.home() / '.vmark' / 'forwarding_table.json'}")
                        import shutil
                        try:
                            shutil.copy(forwarding_table_path, Path.home() / ".vmark" / "forwarding_table.json")
                            print("DEBUG: File copied successfully")
                        except Exception as e:
                            print(f"DEBUG: Failed to copy file: {e}")
                            
                except Exception as e:
                    print(f"DEBUG: Failed to parse JSON: {e}")
                    logging.getLogger('ebpf').error(f"DEBUG: Failed to parse JSON: {e}")
            else:
                print(f"DEBUG: forwarding_table.json does not exist at {forwarding_table_path}")
        except Exception as e:
            print(f"DEBUG: Exception reading forwarding_table.json at {forwarding_table_path}: {e}")

# Import your other modules AFTER setting up logging if they use logging at import time
from cli.shell import start_cli
from cli.modules.register import initialize_api_on_startup

if __name__ == '__main__':
    # Setup logging first
    setup_logging()

    # Ensure forwarding table file exists
    ensure_forwarding_table_file()

    # Debug: print and log the contents of the forwarding table file
    debug_forwarding_table_file()

    # Initialize API server if registered
    initialize_api_on_startup()
    
    # Start the CLI
    start_cli()