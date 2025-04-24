from cli.modules import show, config, system, twamp  # Changed from commands to modules

def dispatch(cmd, username, hostname):
    tokens = cmd.strip().split()
    if not tokens:
        return f"{username}/{hostname}@vMark-node> No command entered. Type 'help' for more information."

    if tokens[0] == 'show':
        return show.handle(tokens[1:], username, hostname)
    elif tokens[0] == 'config':
        return config.handle(tokens[1:], username, hostname)
    elif tokens[0] == 'system':
        return system.handle(tokens[1:], username, hostname)
    elif tokens[0] == 'twamp':  # Add TWAMP command handling
        return twamp.handle(tokens[1:], username, hostname)
    else:
        return f"{username}/{hostname}@vMark-node> Unknown command: {tokens[0]}"