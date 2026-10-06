"""Carga la configuración compartida de servicios desde data/services.json."""

import json
from pathlib import Path


SERVICE_CONFIG_PATH = Path(__file__).resolve().parent / "data" / "services.json"
REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "aliases",
    "palette",
    "parser",
    "senders",
    "particularities",
}


def load_service_configs() -> dict[str, dict]:
    """Carga y valida todas las configuraciones de servicios."""
    try:
        catalog = json.loads(SERVICE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"No se pudo leer el catálogo de servicios: {error}") from error

    configs = {}
    if not isinstance(catalog, dict) or not isinstance(catalog.get("services"), list):
        raise RuntimeError("El catálogo debe contener una lista 'services'.")

    for config in catalog["services"]:
        if not isinstance(config, dict):
            raise RuntimeError("Cada servicio del catálogo debe ser un objeto JSON.")
        missing_fields = REQUIRED_FIELDS - config.keys() if isinstance(config, dict) else REQUIRED_FIELDS
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise RuntimeError(f"Faltan campos en una configuración de servicio: {missing}")
        service_id = config["id"]
        if not isinstance(service_id, str) or not service_id:
            raise RuntimeError("Cada servicio debe declarar un id de texto no vacío.")
        if service_id in configs:
            raise RuntimeError(f"El catálogo contiene el id duplicado {service_id!r}.")
        if not isinstance(config["palette"], dict) or not {
            "background",
            "foreground",
        }.issubset(config["palette"]):
            raise RuntimeError(f"La paleta de {service_id} requiere background y foreground.")
        if not all(
            isinstance(config["palette"][field], str)
            and config["palette"][field].startswith("#")
            for field in ("background", "foreground")
        ):
            raise RuntimeError(f"Los colores de la paleta de {service_id} deben ser textos hexadecimales.")
        if not all(
            isinstance(config[field], list)
            for field in ("aliases", "senders", "particularities")
        ):
            raise RuntimeError(
                f"aliases, senders y particularities deben ser listas en {service_id}."
            )
        parser_config = config["parser"]
        if not isinstance(parser_config, dict) or not parser_config.get("reference"):
            raise RuntimeError(f"Falta la referencia al parser en {service_id}.")
        arguments = parser_config.get("arguments", ["email_text"])
        if not isinstance(arguments, list) or not set(arguments).issubset({
            "email_text",
            "email_date",
            "provider_id",
        }):
            raise RuntimeError(f"Los argumentos del parser no son válidos en {service_id}.")
        if "routing" in config:
            routing = config["routing"]
            if not isinstance(routing, dict) or not all(
                field in routing for field in (
                    "priority",
                    "workflow",
                    "keywords",
                    "email_patterns",
                )
            ):
                raise RuntimeError(f"La configuración de enrutamiento es inválida en {service_id}.")
            if not isinstance(routing["priority"], int) or not isinstance(
                routing["workflow"], bool
            ) or not all(
                isinstance(routing[field], list)
                for field in ("keywords", "email_patterns")
            ):
                raise RuntimeError(f"La configuración de enrutamiento es inválida en {service_id}.")

        configs[service_id] = config

    return configs


SERVICE_CONFIGS = load_service_configs()
ROUTED_SERVICES = sorted(
    (
        (service_id, config)
        for service_id, config in SERVICE_CONFIGS.items()
        if "routing" in config
    ),
    key=lambda item: item[1]["routing"]["priority"],
)
PROVIDER_PRIORITY = [service_id for service_id, _ in ROUTED_SERVICES]
PROVIDER_KEYWORDS = {
    service_id: config["routing"]["keywords"]
    for service_id, config in ROUTED_SERVICES
}
PROVIDER_EMAILS = {
    service_id: config["routing"]["email_patterns"]
    for service_id, config in ROUTED_SERVICES
}


def get_provider_ids(*, workflow_only: bool = False) -> list[str]:
    """Devuelve rutas ordenadas para la CLI o para los jobs paralelos."""
    return [
        service_id
        for service_id, config in ROUTED_SERVICES
        if not workflow_only or config["routing"].get("workflow", False)
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Consulta el catálogo de servicios")
    parser.add_argument(
        "--providers-json",
        action="store_true",
        help="Imprime las rutas paralelizables como JSON para GitHub Actions.",
    )
    args = parser.parse_args()
    if args.providers_json:
        print(json.dumps(get_provider_ids(workflow_only=True)))
