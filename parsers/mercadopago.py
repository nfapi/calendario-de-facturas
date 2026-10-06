"""Parser local para avisos de débito automático de tarjetas de Mercado Pago."""

import re
from datetime import date
from email.utils import parsedate_to_datetime

from .common import normalize_text, parse_amount


SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def parse_mercadopago_bill(email_text: str, email_date: str = "") -> list:
    """Extrae importe y fecha del débito automático de una tarjeta."""
    text = normalize_text(email_text or "")
    if not text or not re.search(r"\btarjeta\b", text, re.IGNORECASE):
        return []

    due_date_pattern = re.compile(
        r"\bEl\s+(\d{1,2})\s+de\s+([a-záéíóú]+)\b",
        re.IGNORECASE,
    )
    amount_pattern = re.compile(r"\$\s*([0-9][0-9.]*\s*,\s*[0-9]{2})")
    due_date_match = None
    amount_match = None
    for candidate_date in due_date_pattern.finditer(text):
        candidate_amount = amount_pattern.search(
            text[candidate_date.end():candidate_date.end() + 200]
        )
        if candidate_amount:
            due_date_match = candidate_date
            amount_match = candidate_amount
            break

    if not due_date_match or not amount_match:
        return []

    month = SPANISH_MONTHS.get(due_date_match.group(2).casefold())
    if not month:
        return []

    try:
        reference_date = parsedate_to_datetime(email_date).date()
    except (TypeError, ValueError, OverflowError):
        return []

    try:
        due_date = date(
            reference_date.year, month, int(due_date_match.group(1))
        )
        if due_date < reference_date:
            due_date = due_date.replace(year=due_date.year + 1)
    except ValueError:
        return []

    return [{
        "id": "mercadopago-tarjeta",
        "service": "Mercado Pago",
        "detail": "Resumen de tarjeta de crédito",
        "location": "",
        "date": due_date.strftime("%Y-%m-%d"),
        "amount": parse_amount(amount_match.group(1)),
        "extra": "Débito automático",
    }]
