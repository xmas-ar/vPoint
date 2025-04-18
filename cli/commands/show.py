descriptions = {
    "interfaces": "Show interface-related information",
    "routes": "Show routing table information",
}

def handle(args, username, hostname):
    prompt = f"{username}/{hostname}@vMark-node> "
    if not args:
        return f"{prompt}Incomplete command. Type 'help' for more information."
    if args[0] == 'interfaces':
        return f"""
  -- Interface list:"""
    elif args[0] == 'routes':
        return f"{prompt}Routing table:"
    else:
        return f"{prompt}Unknown command {args[0]}"