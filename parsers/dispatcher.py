"""Selección del parser local según el proveedor."""

from .absa import parse_absa_bill
from .edes import parse_edes_bill
from .generic import parse_generic_provider_bill
from .movistar import parse_movistar_bill
from .municipalidad import parse_municipalidad_bill
from .personal import parse_personal_bill


def parse_provider_bills(provider: str, emails_data: list) -> list:
    """Parsea correos del proveedor y devuelve sus facturas detectadas."""
    if not emails_data:
        return []

    parser = {
        "personal": parse_personal_bill,
        "edes": parse_edes_bill,
        "absa": parse_absa_bill,
        "movistar": parse_movistar_bill,
        "municipalidad": parse_municipalidad_bill,
    }.get(provider)
    bills = []
    for email_data in emails_data:
        combined_text = "\n".join([
            email_data.get("subject", ""),
            email_data.get("body", ""),
        ])
        parsed = parser(combined_text) if parser else parse_generic_provider_bill(provider, combined_text)
        bills.extend(parsed)
    return bills