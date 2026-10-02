"""Parser local para avisos de servicios por vencer de Brubank."""

import re
from datetime import datetime

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


def parse_brubank_bill(email_text: str) -> list:
    """Extrae un resumen de tarjeta o las facturas de terceros de Brubank."""
    text = normalize_text(email_text or "")
    if not text:
        return []

    if re.search(r"tarjeta\s+de\s+cr[eé]dito", text, re.IGNORECASE):
        due_date_match = re.search(
            r"(\d{1,2})\s+([a-záéíóú]+)\s+(\d{4})\s*\*?\s*"
            r"Fecha\s+de\s+vencimiento",
            text,
            re.IGNORECASE,
        )
        amount_match = re.search(
            r"Fecha\s+de\s+vencimiento\s+\*?\$\s*([0-9.,]+)\s*\*?"
            r"\s*Saldo\s+en\s+pesos",
            text,
            re.IGNORECASE,
        )
        if not due_date_match or not amount_match:
            return []

        month = SPANISH_MONTHS.get(due_date_match.group(2).casefold())
        if not month:
            return []
        due_date = datetime(
            int(due_date_match.group(3)), month, int(due_date_match.group(1))
        ).strftime("%Y-%m-%d")
        return [{
            "id": "brubank-tarjeta",
            "service": "Brubank",
            "detail": "Resumen de tarjeta de crédito",
            "location": "",
            "date": due_date,
            "amount": parse_amount(amount_match.group(1)),
            "extra": "Saldo en pesos",
        }]

    pattern = re.compile(
        r"\*?([A-Za-z][A-Za-z0-9 .&'-]{1,30}?):\*?\s*"
        r"\*?\$\s*([0-9.,]+)\*?.{0,120}?"
        r"\bVence(?:\s+el)?\s+(\d{2}[-/]\d{2}[-/]\d{4})",
        re.IGNORECASE,
    )
    bills = []
    for index, match in enumerate(pattern.finditer(text), start=1):
        service = match.group(1).strip()
        service_key = service.casefold()
        if service_key == "absa":
            service = "ABSA"
        elif service_key == "edes":
            service = "EDES"
        due_date = datetime.strptime(
            match.group(3), "%d-%m-%Y" if "-" in match.group(3) else "%d/%m/%Y"
        ).strftime("%Y-%m-%d")
        bills.append({
            "id": f"brubank-{index}",
            "service": service,
            "detail": "Factura informada por Brubank",
            "location": "",
            "date": due_date,
            "amount": parse_amount(match.group(2)),
            "extra": "Aviso de servicios por vencer de Brubank",
        })

    return bills