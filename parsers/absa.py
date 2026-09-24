"""Parser local para facturas digitales de ABSA."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_absa_bill(email_text: str) -> list:
    """Extrae unidad, importe y vencimiento del aviso de ABSA."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    unit = first_match(r"Unidad\s+de\s+Facturaci[oó]n\s*:?\s*([0-9]+)", text)
    due_date = first_match(r"Vencimiento\s*[|:]?\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    amount = first_match(
        r"Importe\s*[|:]?\s*\$?\s*([0-9.,]+)",
        text,
    )
    if not amount or not due_date:
        return []

    return [{
        "id": f"absa-{unit or '1'}",
        "service": "ABSA",
        "detail": "Factura de agua y saneamiento",
        "location": f"Unidad de facturación {unit}" if unit else "",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"Unidad de facturación {unit}" if unit else "Parser local de ABSA",
    }]