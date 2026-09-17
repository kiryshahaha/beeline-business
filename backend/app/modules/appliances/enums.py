"""Domain enumerations for appliances."""

from enum import StrEnum


class ApplianceType(StrEnum):
    CLIENT_ROUTER = "CLIENT_ROUTER"
    RACK_ROUTER = "RACK_ROUTER"
    CABLE = "CABLE"
    FIBER = "FIBER"
    TOOL = "TOOL"
    TV_BOX = "TV_BOX"
    SPEAKER = "SPEAKER"
    IP_CAMERA = "IP_CAMERA"
    OTHER = "OTHER"
