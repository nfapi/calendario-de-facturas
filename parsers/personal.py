"""Parser local para facturas de Personal."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_personal_bill(email_text: str) -> list:
    """Extrae monto y vencimiento de un correo de Personal."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    amount = first_match(
        r"(?:saldo total|total a pagar|cargos del mes)[:\s]*\$?\s*"
        r"([0-9]+(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        text,
    )
    due_date = first_match(
        r"(?:vence el|vencimiento)[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})",
        text,
    )
    if not amount or not due_date:
        return []

    return [{
        "id": "personal-1",
        "service": "Personal",
        "detail": "Factura de servicios de Personal",
        "location": "",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": "Parser local de Personal",
    }]