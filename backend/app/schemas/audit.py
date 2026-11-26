"""Validated internal audit event payloads."""

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class AuditEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_user_id: UUID
    actor_roles: list[str]
    action: Literal[
        "meeting.status_changed",
        "meeting.metadata_updated",
        "meeting.agenda_changed",
        "meeting.participant_changed",
        "meeting.notetaker_handover_requested",
        "meeting.notetaker_handover_approved",
        "minutes.revised",
        "decision_brief.saved",
        "decision_brief.submitted",
        "decision_brief.withdrawn",
        "decision_brief.approved",
        "decision_brief.rejected",
        "disposition.created",
        "action_item.created",
        "action_item.assignment_changed",
        "action_item.updated",
        "action_item.deleted",
    ]
    object_type: Literal["meeting", "decision_brief_version", "disposition", "action_item"]
    object_id: UUID
    result: Literal["SUCCEEDED", "DENIED"]
    correlation_id: UUID | None = None
    before_values: Mapping[str, str | None] | None = None
    after_values: Mapping[str, str | None] | None = None

    @model_validator(mode="after")
    def enforce_event_payload_allowlist(self) -> "AuditEventCreate":
        if self.action == "meeting.status_changed":
            if self.object_type != "meeting":
                raise ValueError("Meeting status events must reference meetings")
            for values in (self.before_values, self.after_values):
                if values is not None and not set(values) <= {"status"}:
                    raise ValueError("Meeting status event payload contains unsupported fields")
            return self

        if self.action == "minutes.revised":
            if self.object_type != "meeting" or self.result != "SUCCEEDED":
                raise ValueError("Minutes revision events must reference a successful meeting save")
            if self.after_values is None or set(self.after_values) != {
                "revision_id",
                "revision_number",
                "format_version",
                "decision_count",
            }:
                raise ValueError("Minutes revision event payload does not match the allowlist")
            if self.before_values is not None and set(self.before_values) != {
                "revision_id",
                "revision_number",
            }:
                raise ValueError("Minutes revision before-values do not match the allowlist")
            if (
                self.after_values["revision_number"] is None
                or not str(self.after_values["revision_number"]).isdigit()
            ):
                raise ValueError("Minutes revision number must be numeric")
            if self.after_values["format_version"] not in {"1", "2"}:
                raise ValueError("Minutes format version must be supported")
            if (
                self.after_values["decision_count"] is None
                or not str(self.after_values["decision_count"]).isdigit()
            ):
                raise ValueError("Minutes decision count must be numeric")
            return self

        if self.action == "meeting.metadata_updated":
            allowed_fields = {
                "meeting_number",
                "title",
                "meeting_type",
                "meeting_date",
                "start_time",
                "end_time",
                "location",
                "chairperson_id",
                "notetaker_id",
            }
            if self.object_type != "meeting" or self.result != "SUCCEEDED":
                raise ValueError("Meeting metadata events must record successful meeting changes")
            if (
                self.before_values is None
                or self.after_values is None
                or not self.before_values
                or set(self.before_values) != set(self.after_values)
                or not set(self.before_values) <= allowed_fields
            ):
                raise ValueError("Meeting metadata event payload does not match the allowlist")
            return self

        if self.action == "meeting.agenda_changed":
            return self._validate_meeting_child_event(
                allowed_fields={
                    "agenda_id",
                    "operation",
                    "agenda_number",
                    "title",
                    "lead_user_id",
                    "pic_suggestion",
                    "supporting_pic_suggestion",
                    "duration_minutes",
                    "sort_order",
                    "changed_fields",
                }
            )

        if self.action == "meeting.participant_changed":
            return self._validate_meeting_child_event(
                allowed_fields={
                    "participant_user_id",
                    "operation",
                    "attendance_status",
                    "participant_title",
                    "changed_fields",
                }
            )

        if self.action in {
            "meeting.notetaker_handover_requested",
            "meeting.notetaker_handover_approved",
        }:
            allowed_fields = {
                "handover_id",
                "from_notetaker_id",
                "to_notetaker_id",
                "status",
            }
            if self.object_type != "meeting" or self.result != "SUCCEEDED":
                raise ValueError("Notetaker handover events must reference a meeting")
            if (
                self.after_values is None
                or not self.after_values
                or not set(self.after_values) <= allowed_fields
                or (
                    self.before_values is not None and not set(self.before_values) <= allowed_fields
                )
            ):
                raise ValueError("Notetaker handover event payload does not match the allowlist")
            return self

        if self.action in {
            "decision_brief.saved",
            "decision_brief.submitted",
            "decision_brief.withdrawn",
            "decision_brief.approved",
            "decision_brief.rejected",
        }:
            if self.object_type != "decision_brief_version" or self.result != "SUCCEEDED":
                raise ValueError("Decision Brief workflow events must reference a version")
            if self.action == "decision_brief.saved":
                if (
                    self.before_values is not None
                    or self.after_values is None
                    or set(self.after_values)
                    != {
                        "meeting_id",
                        "source_minutes_revision_id",
                        "version_number",
                        "decision_count",
                    }
                ):
                    raise ValueError("Decision Brief save payload does not match the allowlist")
                for field in ("version_number", "decision_count"):
                    value = self.after_values[field]
                    if value is None or not value.isdigit():
                        raise ValueError(f"Decision Brief {field} must be numeric")
                return self
            if (
                self.before_values is None
                or set(self.before_values) != {"state"}
                or self.after_values is None
                or set(self.after_values) != {"state", "meeting_id", "version_number"}
            ):
                raise ValueError("Decision Brief workflow payload does not match the allowlist")
            return self

        if self.action == "action_item.assignment_changed":
            if self.object_type != "action_item" or self.result != "SUCCEEDED":
                raise ValueError("Action Item assignment events must record successful changes")
            if self.after_values is None:
                raise ValueError("Action Item assignment events require after-values")

            operation = self.after_values.get("operation")
            assignment_fields = {
                "assignment_id",
                "assignee_user_id",
                "assignment_role",
                "pic_origin_unit_id",
            }
            optional_assignment_fields = {"assignee_display_name"}
            allowed_fields = (
                assignment_fields | optional_assignment_fields | {"operation", "ended_by_user_id"}
            )
            if not set(self.after_values) <= allowed_fields or operation not in {
                "ASSIGNED",
                "REPLACED",
                "ENDED",
            }:
                raise ValueError("Action Item assignment payload contains unsupported fields")

            if operation == "ASSIGNED":
                if (
                    self.before_values is not None
                    or not assignment_fields | {"operation"} <= set(self.after_values)
                    or set(self.after_values)
                    - (assignment_fields | optional_assignment_fields | {"operation"})
                ):
                    raise ValueError("Assignment creation payload does not match the allowlist")
                return self

            if (
                self.before_values is None
                or not assignment_fields <= set(self.before_values)
                or set(self.before_values) - (assignment_fields | optional_assignment_fields)
            ):
                raise ValueError("Assignment change payload does not match the allowlist")
            if operation == "REPLACED":
                if not assignment_fields | {"operation"} <= set(self.after_values) or set(
                    self.after_values
                ) - (assignment_fields | optional_assignment_fields | {"operation"}):
                    raise ValueError("Assignment replacement payload does not match the allowlist")
            elif set(self.after_values) != {
                "operation",
                "assignment_id",
                "ended_by_user_id",
            }:
                raise ValueError("Assignment end payload does not match the allowlist")
            return self

        if self.action == "action_item.created":
            if self.object_type != "action_item" or self.result != "SUCCEEDED":
                raise ValueError("Action Item events must record successful task creation")
            if self.before_values is not None or self.after_values is None:
                raise ValueError("Action Item creation requires an after-value snapshot only")
            required_fields = {"source_minutes_revision_id", "source_decision_id"}
            allowed_fields = required_fields | {"disposition_id"}
            if (
                not required_fields <= set(self.after_values)
                or not set(self.after_values) <= allowed_fields
            ):
                raise ValueError("Action Item event payload does not match the allowlist")
            return self

        if self.action in {"action_item.updated", "action_item.deleted"}:
            if self.object_type != "action_item" or self.result != "SUCCEEDED":
                raise ValueError("Action Item edit events must record successful task changes")
            if (
                self.before_values is not None
                or self.after_values is None
                or set(self.after_values) != {"changed_fields"}
            ):
                raise ValueError("Action Item edit event payload does not match the allowlist")
            changed_fields = self.after_values["changed_fields"]
            allowed_fields = (
                {"title", "description", "output_expected", "due_date", "priority"}
                if self.action == "action_item.updated"
                else {"deleted_at"}
            )
            if (
                changed_fields is None
                or not changed_fields
                or not set(changed_fields.split(",")).issubset(allowed_fields)
            ):
                raise ValueError("Action Item changed fields are not allowlisted")
            return self

        if self.object_type != "disposition" or self.result != "SUCCEEDED":
            raise ValueError("Disposition events must record successful disposition creation")
        if self.before_values is not None or self.after_values is None:
            raise ValueError("Disposition creation requires an after-value snapshot only")
        if set(self.after_values) != {
            "source_minutes_revision_id",
            "source_decision_id",
            "target_count",
            "target_types",
        }:
            raise ValueError("Disposition event payload does not match the allowlist")
        target_count = self.after_values["target_count"]
        if target_count is None or not target_count.isdigit():
            raise ValueError("Disposition target count must be numeric")
        return self

    def _validate_meeting_child_event(self, *, allowed_fields: set[str]) -> "AuditEventCreate":
        if self.object_type != "meeting" or self.result != "SUCCEEDED":
            raise ValueError("Meeting child events must record successful meeting changes")
        for values in (self.before_values, self.after_values):
            if values is not None and (not values or not set(values) <= allowed_fields):
                raise ValueError("Meeting child event payload does not match the allowlist")
        if self.before_values is None and self.after_values is None:
            raise ValueError("Meeting child event requires an allowlisted snapshot")
        return self
