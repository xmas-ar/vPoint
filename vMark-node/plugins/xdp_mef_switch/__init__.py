"""XDP MEF Switch Plugin"""
from .xdp_loader import attach_xdp_program, detach_xdp_program
from .map_utils import add_forwarding_rule, remove_forwarding_rule