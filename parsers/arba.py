"""Parser local para boletas del impuesto automotor de ARBA."""

import re
from datetime import date
from email.utils import parsedate_to_datetime

from .common import first_match, normalize_text, parse_amount, parse_date


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


def parse_arba_bill(email_text: str, email_date: str = "") -> list:
    """Extrae patente, cuota, importe y vencimiento de un aviso de ARBA."""
    text = normalize_text(email_text or "")
    if not text or not re.search(r"\bImpuesto\s+Automotor\b", text, re.IGNORECASE):
        return []

    due_date = first_match(
        r"Vencimiento\s*[:|]?\s*(\d{2}/\d{2}/\d{4})",
        text,
    )
    if not due_date:
        due_date_match = re.search(
            r"(?:el\s+)?(\d{1,2})\s+de\s+([a-záéíóú]+)"
            r"(?:\s+de\s+(\d{4}))?\s+vence\b",
            text,
            re.IGNORECASE,
        )
        if not due_date_match:
            return []

        month = SPANISH_MONTHS.get(due_date_match.group(2).casefold())
        if not month:
            return []
        year = due_date_match.group(3)
        if not year:
            try:
                year = str(parsedate_to_datetime(email_date).year)
            except (TypeError, ValueError, OverflowError):
                return []
        try:
            due_date = date(
                int(year), month, int(due_date_match.group(1))
            ).strftime("%d/%m/%Y")
        except ValueError:
            return []

    plate = first_match(
        r"Objeto\s+Imponible\s+((?:[A-Z]{2}\s*\d{3}\s*[A-Z]{2})|(?:[A-Z]{3}\s*\d{3}))",
        text,
    )
    if not plate:
        plate = first_match(
            r"\b([A-Z]{2}\s*\d{3}\s*[A-Z]{2}|[A-Z]{3}\s*\d{3})\b",
            text,
        )
    plate = re.sub(r"\s+", "", plate.upper())
    amount = first_match(
        r"Importe\s*\$?\s*([0-9]+(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        text,
    )
    if not amount and plate:
        amount = first_match(
            rf"\b{re.escape(plate)}\s+\$?([0-9]+(?:\.[0-9]{{3}})*,[0-9]{{2}}|[0-9]+,[0-9]{{2}})\b",
            text,
        )
    installment = first_match(r"\bCuota\s+(\d{1,2})\b", text)
    if not plate or not amount or not due_date:
        return []

    return [{
        "id": f"arba-automotor-{plate}-{installment or '1'}",
        "service": "ARBA",
        "detail": f"Impuesto Automotor{f' - Cuota {installment}' if installment else ''}",
        "location": f"Patente {plate}",
        "date": parse_date(due_date),
        "amount": parse_amount(amount),
        "extra": f"Patente {plate}" + (f" - Cuota {installment}" if installment else ""),
    }]
