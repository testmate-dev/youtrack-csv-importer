from __future__ import annotations

from typing import Dict, List, Optional

import requests


class YouTrackError(Exception):
    """Raised when the YouTrack API returns an error."""
    pass


class YouTrackClient:
    def __init__(self, url: str, token: str):
        self.base_url = url.rstrip("/") + "/api"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        self.project: Optional[dict] = None

        # Cached field information
        self.fields: Dict[str, dict] = {}

    ISSUE_FIELD_TYPES = {
        "enum[1]": "SingleEnumIssueCustomField",
        "enum[*]": "MultiEnumIssueCustomField",
        "state[1]": "StateIssueCustomField",
        "state[*]": "MultiStateIssueCustomField",
        "user[1]": "SingleUserIssueCustomField",
        "user[*]": "MultiUserIssueCustomField",
        "ownedField[1]": "SingleOwnedIssueCustomField",
        "ownedField[*]": "MultiOwnedIssueCustomField",
        "version[1]": "SingleVersionIssueCustomField",
        "version[*]": "MultiVersionIssueCustomField",
        "build[1]": "SingleBuildIssueCustomField",
        "build[*]": "MultiBuildIssueCustomField",
        "group[1]": "SingleGroupIssueCustomField",
        "group[*]": "MultiGroupIssueCustomField",
        "string": "SimpleIssueCustomField",
        "integer": "SimpleIssueCustomField",
        "float": "SimpleIssueCustomField",
        "date": "DateIssueCustomField",
        "date and time": "DateIssueCustomField",
        "period": "PeriodIssueCustomField",
        "text": "TextIssueCustomField",
    }

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        endpoint: str,
        fields: Optional[str] = None,
        params: Optional[dict] = None,
    ):
        params = params or {}

        if fields:
            params["fields"] = fields

        response = self.session.get(
            self.base_url + endpoint,
            params=params,
            timeout=30,
        )

        if not response.ok:
            raise YouTrackError(
                f"GET {endpoint}\n"
                f"{response.status_code}\n"
                f"{response.text}"
            )

        return response.json()

    def _post(
        self,
        endpoint: str,
        body: dict,
        fields: Optional[str] = None,
    ):
        params = {}

        if fields:
            params["fields"] = fields

        response = self.session.post(
            self.base_url + endpoint,
            params=params,
            json=body,
            timeout=30,
        )

        if not response.ok:
            raise YouTrackError(
                f"POST {endpoint}\n"
                f"{response.status_code}\n"
                f"{response.text}"
            )

        return response.json()

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    def get_project(self, short_name: str) -> dict:
        page_size = 100
        skip = 0

        while True:
            projects = self._get(
                "/admin/projects",
                fields="id,name,shortName",
                params={
                    "$top": page_size,
                    "$skip": skip,
                },
            )

            for project in projects:
                if project["shortName"] == short_name:
                    self.project = project
                    return project

            if len(projects) < page_size:
                break

            skip += page_size

        raise YouTrackError(
            f"Project '{short_name}' not found."
        )

    # ------------------------------------------------------------------
    # Custom Field Discovery
    # ------------------------------------------------------------------

    def load_fields(self, project_id: str):
        """
        Loads IssueCustomField metadata from the project.

        This works for empty projects, which is important when importing
        into a newly-created YouTrack project.
        """

        project_fields = self._get(
            f"/admin/projects/{project_id}/customFields",
            fields=(
                "id,"
                "$type,"
                "field("
                "id,"
                "name,"
                "fieldType("
                "id,"
                "valueType,"
                "isMultiValue"
                ")"
                ")"
            ),
            params={
                "$top": 1000,
            },
        )

        self.fields.clear()

        for project_field in project_fields:
            field = project_field.get("field") or {}
            field_type = field.get("fieldType") or {}
            field_type_id = field_type.get("id")
            issue_type = self.ISSUE_FIELD_TYPES.get(field_type_id)

            if not issue_type:
                continue

            self.fields[field["name"]] = {
                "id": project_field["id"],
                "type": issue_type,
                "value_type": field_type.get("valueType"),
                "is_multi_value": bool(field_type.get("isMultiValue")),
            }

    # ------------------------------------------------------------------
    # Field Helpers
    # ------------------------------------------------------------------

    def enum_field(
        self,
        field_name: str,
        value: str,
    ) -> dict:
        """
        Builds an IssueCustomField payload.

        Example:

            client.enum_field(
                "Priority",
                "Major",
            )
        """

        if field_name not in self.fields:
            raise YouTrackError(
                f"Unknown field '{field_name}'.\n\n"
                "Available fields:\n"
                + "\n".join(sorted(self.fields.keys()))
            )

        field = self.fields[field_name]

        return {
            "name": field_name,
            "id": field["id"],
            "$type": field["type"],
            "value": {
                "name": value
            },
        }

    def custom_field(
        self,
        field_name: str,
        value,
    ) -> dict:
        """
        Builds an IssueCustomField payload using field metadata discovered
        from the target project.
        """

        if field_name not in self.fields:
            raise YouTrackError(
                f"Unknown field '{field_name}'.\n\n"
                "Available fields:\n"
                + "\n".join(sorted(self.fields.keys()))
            )

        field = self.fields[field_name]

        return {
            "name": field_name,
            "id": field["id"],
            "$type": field["type"],
            "value": value,
        }

    def empty_field(
        self,
        field_name: str,
    ) -> dict:
        """
        Builds an IssueCustomField payload with no selected value.
        """

        if field_name not in self.fields:
            raise YouTrackError(
                f"Unknown field '{field_name}'.\n\n"
                "Available fields:\n"
                + "\n".join(sorted(self.fields.keys()))
            )

        field = self.fields[field_name]

        return {
            "name": field_name,
            "id": field["id"],
            "$type": field["type"],
            "value": None,
        }

    def user_field(
        self,
        field_name: str,
        login: str,
    ) -> dict:
        """
        Builds a single-user IssueCustomField payload.
        """

        if field_name not in self.fields:
            raise YouTrackError(
                f"Unknown field '{field_name}'.\n\n"
                "Available fields:\n"
                + "\n".join(sorted(self.fields.keys()))
            )

        field = self.fields[field_name]

        return {
            "name": field_name,
            "id": field["id"],
            "$type": field["type"],
            "value": {
                "login": login
            },
        }

    # ------------------------------------------------------------------
    # Issue Creation
    # ------------------------------------------------------------------

    def create_issue(
        self,
        project_id: str,
        summary: str,
        description: Optional[str] = None,
        custom_fields: Optional[List[dict]] = None,
    ):

        body = {
            "project": {
                "id": project_id
            },
            "summary": summary,
            "customFields": custom_fields or [],
        }

        if description:
            body["description"] = description

        return self._post(
            "/issues",
            body,
            fields="id,idReadable,summary",
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def execute_command(
        self,
        command: str,
        issue_ids: List[str],
    ):
        """
        Executes a YouTrack command.

        Examples:

            subtask of TMD-5
            duplicate TMD-20
            Fixed

        """

        body = {
            "query": command,
            "issues": [
                {
                    "id": issue_id
                }
                for issue_id in issue_ids
            ]
        }

        return self._post(
            "/commands",
            body,
        )

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def link_as_subtask(
        self,
        child_issue_id: str,
        parent_issue: str,
    ):
        """
        Makes the issue a subtask of another issue.
        """

        self.execute_command(
            f"subtask of {parent_issue}",
            [child_issue_id],
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def test_connection(self):
        """
        Throws an exception if authentication fails.
        """

        self._get("/users/me", fields="id,login,name")
