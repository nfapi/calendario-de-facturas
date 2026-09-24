"""Parser local para facturas de Camuzzi."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_camuzzi_bill(email_text: str) -> list:
    """Extrae total, vencimiento y cuenta de la factura de Camuzzi."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    account = first_match(
        r"(?:Nro\.?\s*Cuenta|Cuenta)\s*[:\-]?\s*([0-9]{4}/[0-9]-?[0-9]{4}-?[0-9]{8,})",
        text,
    )
    if not account:
        account = first_match(
            r"(?:suministro|Nro\.?\s*cuenta)\s*[:=]?\s*([0-9]{4,}/?[0-9]{0,4}-?[0-9]{4}-?[0-9]{8,})",
            text,
        )

    invoice = first_match(
        r"(?:Factura|Nro\.?\s*Factura)\s*[:\-]?\s*([0-9]{5}-[0-9]{8}/[0-9])",
        text,
    )
    due_date = first_match(
        r"(?:Vencimiento|Fecha de vencimiento)\s*[:\-]?\s*([0-9]{2}/[0-9]{2}/[0-9]{4})",
        text,
    )
    amount = first_match(
        r"(?:Total|Monto|Importe)\s*[:\-]?\s*\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        text,
    )

    if not amount or not due_date:
        return []

    return [{
        "id": f"camuzzi-{account or invoice or '1'}",
        "service": "Camuzzi",
        "detail": "Factura de gas y servicios de Camuzzi",
        "location": f"Cuenta {account}" if account else "",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"Factura {invoice}" if invoice else (f"Cuenta {account}" if account else "Parser local de Camuzzi"),
    }]
