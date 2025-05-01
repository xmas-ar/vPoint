import logging
import logging.handlers # For potential rotation later
from pathlib import Path
import os # For creating directory if needed

# --- Add this Logging Configuration ---
def setup_logging():
    """Configure file logging for the API server."""
    log_dir = Path.home() / ".vmark"
    log_file = log_dir / "api.log"

    # Ensure log directory exists
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error creating log directory {log_dir}: {e}")
        # Decide how to handle this - maybe exit or log to console only

    # Get the specific logger
    api_logger = logging.getLogger('api_server')
    api_logger.setLevel(logging.INFO) # Set the minimum level for this logger

    # Prevent messages from propagating to the root logger (which might print to console)
    api_logger.propagate = False

    # Create file handler
    # Use RotatingFileHandler for production to prevent huge log files
    # file_handler = logging.handlers.RotatingFileHandler(
    #     log_file, maxBytes=10*1024*1024, backupCount=5 # e.g., 10MB per file, 5 backups
    # )
    file_handler = logging.FileHandler(log_file) # Simple file handler for now
    file_handler.setLevel(logging.INFO) # Set level for this handler

    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Add handler to the logger (only if it doesn't have one already)
    if not api_logger.hasHandlers():
        api_logger.addHandler(file_handler)

    # --- Optional: Configure root logger for other messages if needed ---
    # logging.basicConfig(level=logging.WARNING, format='%(levelname)s:%(name)s:%(message)s')
    # --------------------------------------------------------------------

# --- End Logging Configuration ---


# Import your other modules AFTER setting up logging if they use logging at import time
from cli.shell import start_cli
from cli.modules.register import initialize_api_on_startup

if __name__ == '__main__':
    # Setup logging first
    setup_logging()

    # Initialize API server if registered
    initialize_api_on_startup()
    
    # Start the CLI
    start_cli()