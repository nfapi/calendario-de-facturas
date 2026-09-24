"""Consolida artifacts de parsers y publica el histórico una sola vez."""

import glob
import json
import os

from agent_facturas_gmail_github import (
    append_new_bills,
    build_sync_metadata,
    commit_to_github,
    get_env,
    load_bill_database,
    save_bill_database,
)


def main():
    parsed_bills = []
    for file_path in glob.glob(os.path.join("parsed-bills", "*.json")):
        with open(file_path, "r", encoding="utf-8") as data_file:
            data = json.load(data_file)
            if isinstance(data, list):
                parsed_bills.extend(data)

    database_path = os.path.join("data", "bills.json")
    existing_bills = load_bill_database(database_path)
    merged_bills = append_new_bills(existing_bills, parsed_bills)
    database_content = save_bill_database(database_path, merged_bills)
    new_bills_count = len(merged_bills) - len(existing_bills)
    print(f"✅ Se consolidaron {len(parsed_bills)} facturas; nuevas: {new_bills_count}.")

    commit_to_github(
        repo=get_env("GITHUB_REPO"),
        file_path=database_path,
        content=database_content,
        token=get_env("GITHUB_TOKEN"),
    )
    commit_to_github(
        repo=get_env("GITHUB_REPO"),
        file_path=os.path.join("data", "sync.json"),
        content=build_sync_metadata(),
        token=get_env("GITHUB_TOKEN"),
    )


if __name__ == "__main__":
    main()