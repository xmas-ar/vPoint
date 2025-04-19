descriptions = {
    "interface": {
        "": "Edit an existing interface configuration",
        "advanced": "Edit advanced interface settings",
    },
    "new-interface": "Add a new interface configuration",
    "rf2544": "Edit an existing rfc2544 configuration",
    "new-rf2544": "Add a new rfc2544 configuration",
    "obfd": "Edit an existing open-BFD configuration",
    "new-obfd": "Add a new open-BFD configuration",
}

def handle(args):
    return f"Configurando: {' '.join(args)}"