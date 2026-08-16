from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm

from youtrack_api import YouTrackClient, YouTrackError


NAMED_VALUE_TYPES = {
    "enum",
    "state",
    "ownedField",
    "version",
    "build",
    "group",
}


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")

    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)

    raise ValueError(
        f"Unsupported file type: {suffix}"
    )


def validate_columns(df: pd.DataFrame, columns: dict, field_mappings: dict):
    """
    Ensure every configured column exists.
    """

    required = list(columns.values())

    for mapping in field_mappings.values():
        if isinstance(mapping, str):
            required.append(mapping)
        else:
            required.append(mapping["column"])

    missing = [
        column
        for column in required
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            "Missing columns:\n\n"
            + "\n".join(missing)
        )


def issue_id_sort_value(value: str) -> int:
    match = re.search(r"(?:^|-)(\d+)$", value.strip())

    if not match:
        return sys.maxsize

    return int(match.group(1))


def get_parent_epic(row, config) -> list:
    """Return a list of parent epic IDs for the given row.

    1. If `component_epics` mapping is defined, look up the component value(s)
       from the CSV column defined by `component_column` (defaults to "Component").
       The component column may contain multiple components separated by commas or semicolons.
       All matching epics are returned.
    2. If no component mapping matches, fall back to the legacy single‑parent logic
       (respecting `link_after_issue_id`). Returns a single‑item list or an empty list.
    """
    component_epics = config.get("component_epics")
    component_col = config.get("component_column", "Component")
    epics = []
    if component_epics:
        component_value = get_cell(row, component_col)
        if component_value:
            # split_multi_value is defined later in the file; import it here via the function itself
            for comp in split_multi_value(component_value):
                if comp in component_epics:
                    epics.append(component_epics[comp])
    # Legacy fallback (single parent)
    parent_epic = config.get("parent_epic")
    if parent_epic and not epics:
        link_after_issue_id = config.get("link_after_issue_id")
        if not link_after_issue_id:
            epics.append(parent_epic)
        else:
            column = config.get("issue_id_column", "Issue Id")
            current_number = issue_id_sort_value(get_cell(row, column))
            parent_number = issue_id_sort_value(str(link_after_issue_id))
            if current_number > parent_number:
                epics.append(parent_epic)
    # Remove duplicates
    return list(dict.fromkeys(epics))


def sort_dataframe(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    if not config.get("sort_by_issue_id"):
        return df

    column = config.get("issue_id_column", "Issue Id")

    if column not in df.columns:
        raise ValueError(
            f"Cannot sort by missing issue id column: {column}"
        )

    return (
        df.assign(
            __issue_id_sort=df[column]
            .fillna("")
            .astype(str)
            .map(issue_id_sort_value)
        )
        .sort_values("__issue_id_sort", kind="stable")
        .drop(columns="__issue_id_sort")
        .reset_index(drop=True)
    )


def get_cell(row, column_name):
    """
    Returns a cleaned string value.
    Empty cells become "".
    """

    value = row[column_name]

    if pd.isna(value):
        return ""

    return str(value).strip()


def is_unassigned(value: str) -> bool:
    return not value or value.casefold() == "unassigned"


def is_empty_value(field_name: str, value: str, config: dict) -> bool:
    if not value:
        return True

    configured = config.get("empty_values_by_field", {})
    empty_values = configured.get(field_name, [])

    return value.casefold() in {
        item.casefold()
        for item in empty_values
    }


def filter_dataframe(df: pd.DataFrame, config: dict, args) -> pd.DataFrame:
    column = config.get("issue_id_column", "Issue Id")

    if args.only_issue_id:
        if column not in df.columns:
            raise ValueError(
                f"Cannot filter by missing issue id column: {column}"
            )

        return df[
            df[column].fillna("").astype(str) == args.only_issue_id
        ].reset_index(drop=True)

    if args.start_after_issue_id:
        if column not in df.columns:
            raise ValueError(
                f"Cannot filter by missing issue id column: {column}"
            )

        start_after = issue_id_sort_value(args.start_after_issue_id)

        return df[
            df[column]
            .fillna("")
            .astype(str)
            .map(issue_id_sort_value)
            > start_after
        ].reset_index(drop=True)

    return df


def split_multi_value(value: str) -> list[str]:
    if ";" in value:
        return [
            item.strip()
            for item in value.split(";")
            if item.strip()
        ]

    if "," in value:
        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return [value]


def parse_date_millis(value: str) -> int:
    formats = (
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )

    for date_format in formats:
        try:
            return int(
                datetime.strptime(
                    value,
                    date_format,
                ).timestamp()
                * 1000
            )
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {value}")


def parse_period_minutes(value: str) -> int:
    value = value.strip()

    if value.replace(".", "", 1).isdigit():
        return int(float(value) * 60)

    total = 0
    number = ""
    multipliers = {
        "w": 5 * 8 * 60,
        "d": 8 * 60,
        "h": 60,
        "m": 1,
    }

    for char in value:
        if char.isdigit() or char == ".":
            number += char
            continue

        unit = char.casefold()
        if unit not in multipliers or not number:
            raise ValueError(f"Unsupported period format: {value}")

        total += int(float(number) * multipliers[unit])
        number = ""

    if number:
        raise ValueError(f"Unsupported period format: {value}")

    return total


def build_field_value(client: YouTrackClient, field_name: str, raw_value: str):
    field = client.fields[field_name]
    value_type = field["value_type"]

    if is_unassigned(raw_value):
        return None

    if value_type in NAMED_VALUE_TYPES:
        values = [
            {
                "name": value,
            }
            for value in split_multi_value(raw_value)
        ]
        return values if field["is_multi_value"] else values[0]

    if value_type == "user":
        users = [
            {
                "login": value,
            }
            for value in split_multi_value(raw_value)
        ]
        return users if field["is_multi_value"] else users[0]

    if value_type == "integer":
        return int(float(raw_value))

    if value_type == "float":
        return float(raw_value)

    if value_type in ("date", "date and time"):
        return parse_date_millis(raw_value)

    if value_type == "period":
        return {
            "minutes": parse_period_minutes(raw_value),
        }

    return raw_value


def main():

    parser = argparse.ArgumentParser(
        description="Import issues into YouTrack"
    )

    parser.add_argument(
        "spreadsheet",
        help="CSV or Excel file"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the spreadsheet without creating issues",
    )

    parser.add_argument(
        "--only-issue-id",
        help="Import only one old issue id, for example TMD-38",
    )

    parser.add_argument(
        "--start-after-issue-id",
        help="Import only rows after this old issue id, for example TMD-37",
    )

    args = parser.parse_args()

    config = load_config()

    columns = config["columns"]
    field_mappings = config.get("field_mappings", {})

    print("Loading spreadsheet...")

    df = load_dataframe(
        Path(args.spreadsheet)
    )

    validate_columns(df, columns, field_mappings)
    df = sort_dataframe(df, config)
    df = filter_dataframe(df, config, args)

    print(f"Loaded {len(df)} rows")
    print(f"Mapped custom fields: {len(field_mappings)}")

    print()

    dry_run = bool(config.get("dry_run") or args.dry_run)
    parent_epic = config.get("parent_epic")

    if dry_run:
        print("Dry run enabled. No issues will be created.")
        print()
        project = {
            "id": None,
        }
        client = None
    else:
        client = YouTrackClient(
            config["url"],
            config["token"],
        )

        print("Connecting to YouTrack...")

        project = client.get_project(
            config["project"]
        )

        print(
            f"Connected to project "
            f"{project['name']}"
        )

        client.load_fields(project["id"])

        print("Custom fields loaded.")
        print()

        missing_fields = [
            field_name
            for field_name in field_mappings
            if field_name not in client.fields
        ]

        if missing_fields:
            raise YouTrackError(
                "These configured YouTrack fields are not attached "
                "to the target project:\n\n"
                + "\n".join(missing_fields)
                + "\n\nAttach them to the project or remove them "
                "from field_mappings in config.yaml."
            )

        print()

    created = 0
    failed = 0
    skipped = 0
    would_create = 0
    would_link = 0
    linked = 0
    link_failed = 0

    for index, row in tqdm(
        df.iterrows(),
        total=len(df),
        desc="Importing"
    ):

        summary = get_cell(
            row,
            columns["summary"],
        )

        if not summary:

            skipped += 1
            continue

        description = get_cell(
            row,
            columns["description"],
        )

        # Determine parent epic(s) for this row
        parent_epic_ids = get_parent_epic(row, config)

        if dry_run:
            would_create += 1
            if parent_epic_ids:
                would_link += len(parent_epic_ids)
            continue

        try:
            custom_fields = []
            for field_name, mapping in field_mappings.items():
                column_name = mapping if isinstance(mapping, str) else mapping["column"]
                raw_value = get_cell(row, column_name)
                if is_empty_value(field_name, raw_value, config):
                    continue
                custom_fields.append(
                    client.custom_field(
                        field_name,
                        build_field_value(
                            client,
                            field_name,
                            raw_value,
                        ),
                    )
                )
            issue = client.create_issue(
                project_id=project["id"],
                summary=summary,
                description=description,
                custom_fields=custom_fields,
            )
            created += 1

            # Link to each parent epic (if any)
            for parent_epic_id in parent_epic_ids:
                try:
                    client.link_as_subtask(issue["id"], parent_epic_id)
                    linked += 1
                except Exception as e:
                    link_failed += 1
                    print()
                    print(
                        f"Link failed for created issue "
                        f"{issue.get('idReadable', issue['id'])}: "
                        f"subtask of {parent_epic_id}"
                    )
                    print(repr(e))
                    print(
                        "The issue was created successfully. Do not rerun "
                        "this row; add the parent link manually."
                    )

        except YouTrackError as e:
            failed += 1
            print()
            print("=" * 80)
            print(f"Row {index + 1}")
            print(f"Summary : {summary}")
            print(e)
            print("=" * 80)

        except Exception as e:
            failed += 1
            print()
            print("=" * 80)
            print(f"Unexpected error on row {index + 1}")
            print(f"Summary : {summary}")
            print(repr(e))
            print("=" * 80)

    print()
    print("=" * 60)
    print("Import Complete")
    print("=" * 60)
    if dry_run:
        print(f"Would create : {would_create}")
        print(f"Would link   : {would_link}")
    else:
        print(f"Created : {created}")
        print(f"Linked  : {linked}")
        print(f"Link failures: {link_failed}")
    print(f"Skipped : {skipped}")
    print(f"Failed  : {failed}")
    print("=" * 60)


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)

    except Exception as e:
        print()
        print("Fatal Error")
        print("-----------")
        print(e)
        sys.exit(1)
