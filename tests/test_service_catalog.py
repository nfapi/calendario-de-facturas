import json
import unicodedata
import unittest
from pathlib import Path

from agent_facturas_gmail_github import normalize_service
from parsers.dispatcher import PARSER_BY_PROVIDER, resolve_parser
from service_catalog import (
    PROVIDER_PRIORITY,
    SERVICE_CONFIGS,
    SERVICE_CONFIG_PATH,
    get_provider_ids,
    load_service_configs,
)


def normalize_service_name(value):
    normalized = unicodedata.normalize("NFD", value)
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(normalized.casefold().split())


class ServiceCatalogTests(unittest.TestCase):
    def test_all_service_configs_are_in_the_single_catalog(self):
        catalog = json.loads(SERVICE_CONFIG_PATH.read_text(encoding="utf-8"))
        service_ids = [config["id"] for config in catalog["services"]]

        self.assertEqual(len(service_ids), len(set(service_ids)))
        self.assertEqual(set(service_ids), set(SERVICE_CONFIGS))
        self.assertEqual(load_service_configs(), SERVICE_CONFIGS)

    def test_every_service_declares_a_resolvable_parser_and_palette(self):
        for service_id, config in SERVICE_CONFIGS.items():
            with self.subTest(service=service_id):
                self.assertEqual(config["id"], service_id)
                self.assertTrue(config["name"])
                self.assertTrue(config["description"])
                self.assertTrue(config["senders"] is not None)
                self.assertTrue(config["particularities"])
                self.assertRegex(config["palette"]["background"], r"^#[0-9a-f]{6}$")
                self.assertRegex(config["palette"]["foreground"], r"^#[0-9a-f]{6}$")
                self.assertTrue(callable(resolve_parser(config["parser"]["reference"])))

    def test_all_historical_bill_services_have_a_palette_config(self):
        project_root = Path(__file__).resolve().parents[1]
        bills = json.loads(
            (project_root / "data" / "bills.json").read_text(encoding="utf-8")
        )
        aliases = {
            normalize_service_name(name)
            for config in SERVICE_CONFIGS.values()
            for name in [config["name"], *config["aliases"]]
        }

        for service in {bill["service"] for bill in bills}:
            with self.subTest(service=service):
                self.assertIn(normalize_service_name(service), aliases)

    def test_provider_routes_and_parser_dispatch_are_catalog_driven(self):
        route_ids = [
            service_id
            for service_id, config in SERVICE_CONFIGS.items()
            if "routing" in config
        ]

        self.assertEqual(PROVIDER_PRIORITY, get_provider_ids())
        self.assertEqual(set(PARSER_BY_PROVIDER), set(route_ids))
        self.assertEqual(
            get_provider_ids(workflow_only=True),
            [
                service_id
                for service_id in PROVIDER_PRIORITY
                if SERVICE_CONFIGS[service_id]["routing"].get("workflow", False)
            ],
        )
        self.assertNotIn("general", get_provider_ids(workflow_only=True))

    def test_historical_service_normalization_uses_catalog_rules(self):
        self.assertEqual(normalize_service("ARBA Automotor"), "arba")
        self.assertEqual(normalize_service("EDES - Casa"), "edes")
        self.assertEqual(normalize_service("ABSA agua"), "absa")
        self.assertEqual(
            normalize_service("B Roela Siro / Consorcio Zelarrayan 133"),
            "consorcio",
        )
        self.assertEqual(normalize_service("Zoho invoice"), "assertia")


if __name__ == "__main__":
    unittest.main()
