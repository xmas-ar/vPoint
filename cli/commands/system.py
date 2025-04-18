import subprocess

descriptions = {
    "run": "Run system-level operations",
}

def handle(args):
    return f"System command executed: {' '.join(args)}"