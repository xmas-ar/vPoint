import subprocess

descriptions = {
    "run": {
        "": "Run system-level operations",
        # "diagnostics": "Run system diagnostics",
    },
}

def get_command_tree():
    """Build and return command tree based on descriptions"""
    # Helper function to recursively build the command tree
    def build_tree_from_descriptions(desc_tree):
        tree = {}
        for key, value in desc_tree.items():
            if key == "_options":
                # Add options as leaf nodes for autocompletion
                for option in value:
                    tree[option] = None
            elif isinstance(value, dict):
                # Recursively build subtrees
                tree[key] = build_tree_from_descriptions(value)
            else:
                # Leaf nodes (commands without subcommands)
                tree[key] = None
        return tree

    # Build tree from descriptions
    command_tree = build_tree_from_descriptions(descriptions)
    return command_tree

def get_descriptions():
    """Return the description dictionary."""
    return descriptions

def handle(args, username, hostname):
    return f"System command executed: {' '.join(args)}"