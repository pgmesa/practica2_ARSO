
# Imports para definicion del comando
from dependencies.cli.aux_classes import Command, Flag, Option

# --------------------------------------------------------------------
def get_info_cmd():
    msg = """
    shows important information about how the platform is built and 
    deployed, and the requirements that the container images need to 
    fulfill, in order to fit into the platform (in case an specific
    image is passed to the program)
    """
    info = Command("info", description=msg)
    return info

# --------------------------------------------------------------------
# --------------------------------------------------------------------
def info():
    pass