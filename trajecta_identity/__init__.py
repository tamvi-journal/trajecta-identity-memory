"""Trajecta Identity Memory: self-authored identity memory for agents."""

from .activation import ActivationPolicy
from .identity import CAUSAL_RELATIONS, PINNED, IdentityMemory
from .paths import data_dir, profile_db
from .profile import CORE_ID, VHO_KEYS, IdentityProfile, load_profile

__version__ = "0.1.0"

__all__ = [
    "ActivationPolicy",
    "CAUSAL_RELATIONS",
    "CORE_ID",
    "IdentityMemory",
    "IdentityProfile",
    "PINNED",
    "VHO_KEYS",
    "data_dir",
    "load_profile",
    "profile_db",
]
