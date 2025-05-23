from pyroute2 import IPDB

def get_dynamic_interfaces():
    """Fetch a list of available network interfaces dynamically."""
    with IPDB() as ipdb:
        return [
            str(name) for name in ipdb.interfaces.keys()
            if isinstance(name, str) and not name.isdigit()
        ]