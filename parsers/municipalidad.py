"""Parser local para tasas de inmuebles de la Municipalidad de Bahía Blanca."""

from .common import first_match, normalize_text, parse_amount, parse_date


def parse_municipalidad_bill(email_text: str) -> list:
    """Extrae partida, cuota, importe y vencimiento de una tasa municipal."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    property_id = first_match(r"Partida\s+([0-9]+-?)", text)
    installment = first_match(r"Cuota\s+([0-9]{2}-[0-9]{4})", text)
    due_date = first_match(r"Vencimiento(?:\s+el)?\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    amount = first_match(r"Importe.{0,500}?\$\s*([0-9.,]+)", text)
    if not amount or not due_date:
        return []

    return [{
        "id": f"municipalidad-{property_id or '1'}-{installment or '1'}",
        "service": "Municipalidad de Bahía Blanca",
        "detail": "Tasa por Servicios Urbanos",
        "location": f"Partida {property_id}" if property_id else "",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"Cuota {installment}" if installment else "Parser local de Municipalidad",
    }]