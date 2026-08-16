# YouTrack Bulk Issue Importer

Bulk import issues into a YouTrack project from a CSV or Excel spreadsheet.

The importer:

- Creates new issues
- Sets configured custom fields (Priority, Type, Assignee, Stage, Component, Estimation, etc.)
- Automatically links every created issue as a subtask of a parent issue (for example `TMD-5`).
- If a `component_epics` mapping is defined in `config.yaml`, issues will be linked to the epic corresponding to their component value (column defined by `component_column`).
- Falls back to the original `parent_epic` behavior when no mapping matches.
- Supports CSV and Excel (`.xlsx`)
- Displays progress during the import
- Continues importing if an individual row fails

---

# Requirements

- Python 3.11+
- A YouTrack permanent token
- Permission to:
  - Read Projects
  - Create Issues
  - Apply Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Configuration

Create a `config.yaml` file.

```yaml
url: "https://youtrack.example.com"

token: "perm:xxxxxxxxxxxxxxxxxxxxxxxx"

project: "TMD"

parent_epic: "TMD-5"
link_after_issue_id: "TMD-5"

sort_by_issue_id: true
issue_id_column: "Issue Id"

columns:
  summary: "Summary"
  description: "Description"

ignored_columns:
  - "Issue Id"

field_mappings:
  Priority: "Priority"
  Type: "Type"
  Assignee: "Assignee"
  Stage: "Stage"
  Component: "Component"
  Estimation: "Estimation"

empty_values_by_field:
  Assignee:
    - "Unassigned"
  Component:
    - "No component"

dry_run: true
```

| Setting | Description |
|----------|-------------|
| url | Your YouTrack URL |
| token | Permanent API token |
| project | Project short name |
| parent_epic | Every imported issue becomes a subtask of this issue |
| link_after_issue_id | Skips parent linking through this old issue ID, useful when the parent is created during the same import |
| sort_by_issue_id | Sorts rows by the numeric suffix of the old issue ID before import |
| issue_id_column | CSV column containing the old issue ID |
| columns | Maps built-in issue columns |
| ignored_columns | Columns that should not be imported, such as old issue IDs |
| field_mappings | Maps CSV columns to YouTrack custom fields with the same intended meaning |
| empty_values_by_field | Values that should be skipped rather than import text literally |
| dry_run | Prints what would be imported without creating issues |

---

# Spreadsheet Format

Minimum example:

| Summary | Description | Priority | Type | Assignee | Stage |
|---------|-------------|----------|------|----------|-------|
| Debugger | Add debugger | Major | Feature | Unassigned | Backlog |
| Step Over | Step through execution | Major | Feature | jsmith | Backlog |

The column names can be changed in `config.yaml`.

---

# Running

CSV:

```bash
python import_issues.py backlog.csv
```

Import one row that was not created:

```bash
python import_issues.py --only-issue-id TMD-38 allissues.csv
```

Resume after an old issue ID:

```bash
python import_issues.py --start-after-issue-id TMD-37 allissues.csv
```

Excel:

```bash
python import_issues.py backlog.xlsx
```

---

# Example Output

```
Loading spreadsheet...
Loaded 42 rows

Connecting to YouTrack...
Connected to project Testmate

Loading custom fields...

Importing
██████████████████████████ 42/42

============================================================
Import Complete
============================================================
Created : 42
Skipped : 0
Failed  : 0
============================================================
```

---

# How It Works

For each row in the spreadsheet the importer:

1. Reads the issue information.
2. Creates a new issue in YouTrack, unless `dry_run` is enabled.
3. Sets all configured fields in `field_mappings`.
4. Links the issue as a subtask of the matching `component_epics` epic, or the fallback `parent_epic`, if configured.
5. Continues to the next row.

The importer **never modifies existing issues**.

---

# Notes

- Source issue IDs may be numeric (for example `13`) or have a project prefix (for example `TMD-13`). New YouTrack issue IDs are assigned automatically.
- For a fresh project, `sort_by_issue_id: true` makes the old `TMD-5` row the fifth issue created, so it should receive `TMD-5` if the project has no existing issues.
- `link_after_issue_id: "TMD-5"` creates old `TMD-1` through `TMD-5` without parent linking, then links the remaining imported issues to `TMD-5`.
- If an issue is created but its parent link fails, the importer reports the created issue ID and continues. Do not rerun that source row; add its parent link manually to avoid creating a duplicate.
- Existing issues are not updated.
- Empty Summary values are skipped.
- Empty Assignee values and `Unassigned` leave the issue unassigned.
- Invalid custom field values are reported by the YouTrack API and the importer continues with the next row.

---

# Troubleshooting

## Unknown field

Check the field names in `config.yaml`.

For example:

```yaml
fields:
  stage: "Stage"
```

must match the field name inside YouTrack exactly.

---

## Invalid value

Example:

```
'Backlog' is not a valid value for Stage
```

Verify the value exists in the project's custom field.

---

## Authentication failed

Ensure the permanent token:

- has not expired
- has permission to create issues
- belongs to a user with access to the target project

---

# References

- JetBrains YouTrack REST API documentation
- Create Issue API
- Custom Fields API
