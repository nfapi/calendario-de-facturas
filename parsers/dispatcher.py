"""Selección del parser local según el proveedor."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module

from service_catalog import SERVICE_CONFIGS

from .generic import parse_generic_provider_bill


def resolve_parser(reference: str):
    """Resuelve una referencia declarada como modulo:funcion en el catálogo."""
    module_name, separator, function_name = reference.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError(f"Referencia de parser inválida: {reference!r}")
    parser = getattr(import_module(module_name), function_name, None)
    if not callable(parser):
        raise ValueError(f"No se encontró el parser {reference!r}.")
    return parser


PARSER_BY_PROVIDER = {
    service_id: resolve_parser(config["parser"]["reference"])
    for service_id, config in SERVICE_CONFIGS.items()
    if "routing" in config
}


def parse_provider_bills(provider: str, emails_data: list) -> list:
    """Parsea correos del proveedor y devuelve sus facturas detectadas."""
    if not emails_data:
        return []

    parser = PARSER_BY_PROVIDER.get(provider)
    config = SERVICE_CONFIGS.get(provider)
    if config and "routing" in config:
        parser_arguments = config["parser"].get("arguments", ["email_text"])
    elif parser:
        parser_arguments = ["email_text"]
    else:
        parser = parse_generic_provider_bill
        parser_arguments = ["provider_id", "email_text"]

    bills = []
    for email_data in emails_data:
        combined_text = "\n".join([
            email_data.get("subject", ""),
            email_data.get("body", ""),
        ])
        values = {
            "provider_id": provider,
            "email_text": combined_text,
            "email_date": email_data.get("date", ""),
        }
        bills.extend(parser(*(values[name] for name in parser_arguments)))
    return bills


def parse_providers_in_parallel(grouped_emails: dict, providers: list | None = None) -> tuple[dict, dict]:
    """Ejecuta todos los parsers y conserva resultados aunque alguno falle."""
    providers_to_process = [
        provider for provider in (providers or grouped_emails)
        if grouped_emails.get(provider)
    ]
    if not providers_to_process:
        return {}, {}

    parsed_bills = {}
    failures = {}
    worker_count = min(len(providers_to_process), 8)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(parse_provider_bills, provider, grouped_emails[provider]): provider
            for provider in providers_to_process
        }
        for future in as_completed(futures):
            provider = futures[future]
            try:
                bills = future.result()
            except Exception as error:
                failures[provider] = f"{type(error).__name__}: {error}"
                continue

            if bills:
                parsed_bills[provider] = bills
            else:
                failures[provider] = "El parser no extrajo ninguna factura."

    return parsed_bills, failures