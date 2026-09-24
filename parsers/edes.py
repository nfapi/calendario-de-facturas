"""Parser local para avisos de factura de EDES."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_edes_bill(email_text: str) -> list:
    """Extrae importe, vencimiento, NIS y domicilio del aviso de EDES."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    nis = first_match(r"\bNIS\s+([0-9]+)", text)
    amount = first_match(
        r"\*?Importe\s+de\s+factura\*?\s+\$?\s*"
        r"([0-9]+(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        text,
    )
    due_date = first_match(r"\*?Vencimiento\*?\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    location = first_match(
        r"servicio\s+de\s+calle\s+(.+?)\s+\*?Importe\s+de\s+factura",
        text,
    )
    if not amount or not due_date:
        return []

    return [{
        "id": f"edes-{nis or '1'}",
        "service": "EDES",
        "detail": "Factura de energía eléctrica",
        "location": location.strip(" *"),
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"NIS {nis}" if nis else "Parser local de EDES",
    }]