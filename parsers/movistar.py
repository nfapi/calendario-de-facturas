"""Parser local para facturas de Movistar."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_movistar_bill(email_text: str) -> list:
    """Extrae total, vencimiento, cuenta y línea del aviso de Movistar."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    due_date = first_match(r"Vencimiento\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    amount = first_match(r"Total\s+a\s+pagar\s+\$?\s*([0-9.,]+)", text)
    account = first_match(r"Número\s+de\s+cuenta\s+([0-9]+)", text)
    line = first_match(r"Número\s+de\s+l[ií]nea\s+([0-9]+)", text)
    if not amount or not due_date:
        return []

    return [{
        "id": f"movistar-{account or line or '1'}",
        "service": "Movistar",
        "detail": "Factura de telefonía móvil",
        "location": f"Línea {line}" if line else "",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"Cuenta {account}" if account else "Parser local de Movistar",
    }]