"""Fallback local para proveedores todavía no especializados."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_generic_provider_bill(provider: str, email_text: str) -> list:
    """Extrae monto y vencimiento con etiquetas genéricas."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    amount = first_match(
        r"(?:total a pagar|monto|importe|saldo)[:\s]*\$?\s*"
        r"([0-9]+(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        text,
    )
    due_date = first_match(
        r"(?:venc(?:e|imiento)|fecha de vencimiento)[:\s]*"
        r"([0-9]{2}/[0-9]{2}/[0-9]{4})",
        text,
    )
    if not amount or not due_date:
        return []

    label = provider.replace("-", " ").title()
    return [{
        "id": f"{provider}-1",
        "service": label,
        "detail": f"Factura de {label}",
        "location": "",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"Parser local de {label}",
    }]