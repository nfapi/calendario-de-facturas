"""Parsers deterministas de facturas por proveedor."""

from .dispatcher import parse_provider_bills
from .absa import parse_absa_bill
from .edes import parse_edes_bill
from .generic import parse_generic_provider_bill
from .movistar import parse_movistar_bill
from .municipalidad import parse_municipalidad_bill
from .personal import parse_personal_bill

__all__ = [
    "parse_absa_bill",
    "parse_edes_bill",
    "parse_generic_provider_bill",
    "parse_movistar_bill",
    "parse_municipalidad_bill",
    "parse_personal_bill",
    "parse_provider_bills",
]