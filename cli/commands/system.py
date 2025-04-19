import subprocess

descriptions = {
    "run": {
        "": "Run system-level operations",
        "diagnostics": "Run system diagnostics",
    },
}

def handle(args):
    return f"System command executed: {' '.join(args)}"