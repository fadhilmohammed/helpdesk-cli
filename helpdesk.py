"""Help Desk Ticket Logger — a local CLI ticketing system.

A command-line tool for creating, tracking, and managing help desk
tickets. All data is stored in a local JSON file with zero external
dependencies.
"""

from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import os
import shutil
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# ANSI color support
# ---------------------------------------------------------------------------

class _Color:
    """ANSI escape codes for terminal coloring.

    All methods return plain text when color is disabled via --no-color
    or when stdout is not a TTY.
    """

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    def __init__(self) -> None:
        """Initialize with color enabled by default."""
        self.enabled: bool = True

    def _wrap(self, code: str, text: str) -> str:
        """Wrap text in an ANSI escape sequence.

        Args:
            code: The ANSI escape code to apply.
            text: The text to colorize.

        Returns:
            The wrapped string, or the original text if color is off.
        """
        if not self.enabled:
            return text
        return f"{code}{text}{self.RESET}"

    def red(self, text: str) -> str:
        """Apply red color to text."""
        return self._wrap(self.RED, text)

    def green(self, text: str) -> str:
        """Apply green color to text."""
        return self._wrap(self.GREEN, text)

    def yellow(self, text: str) -> str:
        """Apply yellow color to text."""
        return self._wrap(self.YELLOW, text)

    def bold(self, text: str) -> str:
        """Apply bold styling to text."""
        return self._wrap(self.BOLD, text)


color = _Color()


def _color_priority(value: str) -> str:
    """Colorize a priority value.

    Args:
        value: The priority string (low, medium, high, critical).

    Returns:
        The colorized string.
    """
    if value in ("critical", "high"):
        return color.red(value)
    if value == "medium":
        return color.yellow(value)
    return value


def _color_status(value: str) -> str:
    """Colorize a status value.

    Args:
        value: The status string (open, in-progress, resolved, closed).

    Returns:
        The colorized string.
    """
    if value in ("resolved", "closed"):
        return color.green(value)
    return value


def _pad_colored(text: str, raw: str, width: int) -> str:
    """Left-pad a possibly-colored string to a fixed visible width.

    ANSI codes are invisible but consume characters in the string.
    This pads based on the *raw* (uncolored) length so columns align.

    Args:
        text: The string that may contain ANSI codes.
        raw: The plain-text version (no ANSI codes).
        width: The desired visible column width.

    Returns:
        The padded string.
    """
    padding = width - len(raw)
    if padding > 0:
        return text + " " * padding
    return text


# ---------------------------------------------------------------------------
# SLA thresholds (hours)
# ---------------------------------------------------------------------------

SLA_THRESHOLDS: Dict[str, int] = {
    "critical": 4,
    "high": 8,
    "medium": 24,
    "low": 72,
}


def _color_sla(value: str) -> str:
    """Colorize an SLA status string.

    Args:
        value: The SLA status (on-track, warning, breached).

    Returns:
        The colorized string.
    """
    if value == "breached":
        return color.red(value)
    if value == "warning":
        return color.yellow(value)
    return color.green(value)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Category(str, Enum):
    """Valid ticket categories."""

    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    AV_EQUIPMENT = "av-equipment"
    ACCOUNT = "account"
    OTHER = "other"


class Priority(str, Enum):
    """Valid ticket priority levels (ascending severity)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Status(str, Enum):
    """Valid ticket lifecycle statuses."""

    OPEN = "open"
    IN_PROGRESS = "in-progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Ticket dataclass
# ---------------------------------------------------------------------------

def _generate_id() -> str:
    """Generate a unique ticket ID."""
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Ticket:
    """Represents a single help desk ticket.

    Attributes:
        id: Unique identifier for the ticket.
        title: Short summary of the issue.
        description: Detailed description of the problem.
        category: The area the issue falls under.
        priority: How urgent the issue is.
        status: Current lifecycle state of the ticket.
        assigned_to: The person or team the ticket is assigned to.
        created_at: ISO 8601 timestamp of when the ticket was created.
        updated_at: ISO 8601 timestamp of the last modification.
        history: Audit log — a list of dicts recording every change.
    """

    title: str
    description: str
    category: Category
    priority: Priority
    id: str = field(default_factory=_generate_id)
    status: Status = Status.OPEN
    assigned_to: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    history: List[dict] = field(default_factory=list)

    def log_event(
        self,
        action: str,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
    ) -> None:
        """Append an entry to the ticket's audit history.

        Args:
            action: Short label like "created", "status_changed", etc.
            old_value: The previous value (None for creation events).
            new_value: The new value.
        """
        self.history.append({
            "timestamp": _now_iso(),
            "action": action,
            "old_value": old_value,
            "new_value": new_value,
        })

    def sla_status(self) -> str:
        """Calculate the current SLA status for this ticket.

        Compares elapsed time since creation against the SLA threshold
        for the ticket's priority level.

        Returns:
            ``"on-track"`` if under 75 % of the threshold,
            ``"warning"`` if 75 %+ elapsed but not yet breached,
            ``"breached"`` if the threshold has been exceeded.
        """
        threshold_hours = SLA_THRESHOLDS.get(self.priority.value, 72)
        threshold = timedelta(hours=threshold_hours)
        created = datetime.fromisoformat(self.created_at)
        elapsed = datetime.now(timezone.utc) - created

        if elapsed >= threshold:
            return "breached"
        if elapsed >= threshold * 0.75:
            return "warning"
        return "on-track"

    def to_dict(self) -> dict:
        """Serialize the ticket to a plain dictionary.

        Enum values are stored as their string representations so the
        JSON file stays human-readable.

        Returns:
            A dictionary suitable for JSON serialization.
        """
        data = asdict(self)
        data["category"] = self.category.value
        data["priority"] = self.priority.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Ticket:
        """Deserialize a ticket from a plain dictionary.

        Args:
            data: Dictionary with ticket field values.

        Returns:
            A fully constructed Ticket instance.

        Raises:
            KeyError: If a required field is missing.
            ValueError: If an enum value is invalid.
        """
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            category=Category(data["category"]),
            priority=Priority(data["priority"]),
            status=Status(data["status"]),
            assigned_to=data.get("assigned_to", ""),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            history=data.get("history", []),
        )


# ---------------------------------------------------------------------------
# Ticket store (JSON persistence)
# ---------------------------------------------------------------------------

class TicketStore:
    """Handles reading and writing tickets to a local JSON file.

    The store keeps all tickets in a single ``tickets.json`` file.  On
    every write the entire list is serialized; on every read it is
    deserialized back into :class:`Ticket` objects.

    Attributes:
        path: The filesystem path to the JSON data file.
    """

    DEFAULT_FILE = "tickets.json"

    def __init__(self, path: Optional[str] = None) -> None:
        """Initialize the ticket store.

        Args:
            path: Optional path to the JSON file.  Defaults to
                ``tickets.json`` in the current working directory.
        """
        self.path: Path = Path(path) if path else Path(self.DEFAULT_FILE)

    def load(self) -> List[Ticket]:
        """Read all tickets from the JSON file.

        Returns:
            A list of Ticket objects.  Returns an empty list when the
            file does not yet exist.

        Raises:
            SystemExit: If the file exists but contains malformed JSON
                or ticket data that cannot be deserialized.
        """
        if not self.path.exists():
            return []

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Error: could not read {self.path}: {exc}")
            raise SystemExit(1)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"Error: {self.path} contains invalid JSON: {exc}")
            raise SystemExit(1)

        if not isinstance(data, list):
            print(f"Error: {self.path} should contain a JSON array.")
            raise SystemExit(1)

        tickets: List[Ticket] = []
        for i, entry in enumerate(data):
            try:
                tickets.append(Ticket.from_dict(entry))
            except (KeyError, ValueError) as exc:
                print(f"Error: ticket at index {i} is malformed: {exc}")
                raise SystemExit(1)

        return tickets

    def save(self, tickets: List[Ticket]) -> None:
        """Write the full list of tickets to the JSON file.

        The file is written atomically-ish by encoding first and then
        writing in a single call so a crash mid-write is less likely to
        leave a half-written file.

        Args:
            tickets: The complete list of tickets to persist.

        Raises:
            SystemExit: If the file cannot be written.
        """
        data = [t.to_dict() for t in tickets]
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        try:
            self.path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"Error: could not write {self.path}: {exc}")
            raise SystemExit(1)

    def find_by_id(self, ticket_id: str) -> Optional[Ticket]:
        """Look up a single ticket by its ID.

        Args:
            ticket_id: The unique ticket identifier to search for.

        Returns:
            The matching Ticket, or None if not found.
        """
        tickets = self.load()
        for ticket in tickets:
            if ticket.id == ticket_id:
                return ticket
        return None


# ---------------------------------------------------------------------------
# Template & assignment-rule loading
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent

TEMPLATES_FILE = _SCRIPT_DIR / "templates.json"
ASSIGNMENT_RULES_FILE = _SCRIPT_DIR / "assignment_rules.json"
NOTIFICATIONS_DIR = _SCRIPT_DIR / "notifications"

NOTIFICATION_SENDER = "helpdesk@collin-it.local"


def load_templates() -> Dict[str, dict]:
    """Load ticket templates from templates.json.

    Returns:
        A dict mapping template name to its field values.
        Returns an empty dict if the file is missing.
    """
    if not TEMPLATES_FILE.exists():
        return {}
    try:
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: could not load {TEMPLATES_FILE}: {exc}")
        return {}


def save_templates(templates: Dict[str, dict]) -> None:
    """Write the full templates dict back to templates.json.

    Args:
        templates: The complete template mapping to persist.

    Raises:
        SystemExit: If the file cannot be written.
    """
    payload = json.dumps(templates, indent=2, ensure_ascii=False) + "\n"
    try:
        TEMPLATES_FILE.write_text(payload, encoding="utf-8")
    except OSError as exc:
        print(f"Error: could not write {TEMPLATES_FILE}: {exc}")
        raise SystemExit(1)


def load_assignment_rules() -> Dict[str, str]:
    """Load category-to-assignee mappings from assignment_rules.json.

    Returns:
        A dict mapping category value to a default assignee string.
        Returns an empty dict if the file is missing.
    """
    if not ASSIGNMENT_RULES_FILE.exists():
        return {}
    try:
        return json.loads(ASSIGNMENT_RULES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: could not load {ASSIGNMENT_RULES_FILE}: {exc}")
        return {}


def _save_notification(ticket: Ticket, action: str, details: str = "") -> None:
    """Generate and save an email notification as a .eml file.

    Builds a MIME multipart email with an HTML body summarizing the
    ticket and the action that triggered the notification.  The file
    is saved to the ``notifications/`` directory.

    Args:
        ticket: The ticket the notification is about.
        action: A short action label (e.g. "created", "updated",
            "sla_breached").
        details: Optional extra detail text to include in the body.
    """
    NOTIFICATIONS_DIR.mkdir(exist_ok=True)

    recipient = ticket.assigned_to if ticket.assigned_to else "unassigned@collin-it.local"
    now = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y%m%d-%H%M%S")
    subject = f"[Helpdesk] Ticket {ticket.id} — {action}"

    # Build HTML body
    sla = ticket.sla_status()
    sla_color = "#d63031" if sla == "breached" else "#e17055" if sla == "warning" else "#00b894"
    pri_color = "#d63031" if ticket.priority.value in ("critical", "high") else "#e17055" if ticket.priority.value == "medium" else "#636e72"

    html_body = f"""\
<html>
<body style="font-family: -apple-system, 'Segoe UI', sans-serif; color: #2d3436; max-width: 600px;">
  <div style="background: #2d3436; color: #fff; padding: 16px 20px; border-radius: 6px 6px 0 0;">
    <h2 style="margin: 0; font-size: 1.1rem;">Help Desk Notification</h2>
  </div>
  <div style="border: 1px solid #dfe6e9; border-top: none; padding: 20px; border-radius: 0 0 6px 6px;">
    <p style="margin-top: 0;"><strong>Action:</strong> {html_mod.escape(action)}</p>
    {f'<p>{html_mod.escape(details)}</p>' if details else ''}
    <table style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Ticket ID</strong></td><td style="padding: 6px 0; font-family: monospace;">{html_mod.escape(ticket.id)}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Title</strong></td><td style="padding: 6px 0;">{html_mod.escape(ticket.title)}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Category</strong></td><td style="padding: 6px 0;">{html_mod.escape(ticket.category.value)}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Priority</strong></td><td style="padding: 6px 0; color: {pri_color}; font-weight: 600;">{html_mod.escape(ticket.priority.value)}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Status</strong></td><td style="padding: 6px 0;">{html_mod.escape(ticket.status.value)}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Assigned To</strong></td><td style="padding: 6px 0;">{html_mod.escape(ticket.assigned_to or '(unassigned)')}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>SLA Status</strong></td><td style="padding: 6px 0; color: {sla_color}; font-weight: 600;">{html_mod.escape(sla)}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Created</strong></td><td style="padding: 6px 0;">{html_mod.escape(_format_datetime(ticket.created_at))}</td></tr>
      <tr><td style="padding: 6px 0; color: #636e72;"><strong>Updated</strong></td><td style="padding: 6px 0;">{html_mod.escape(_format_datetime(ticket.updated_at))}</td></tr>
    </table>
    <p style="margin-bottom: 0; font-size: 0.8rem; color: #b2bec3;">
      This notification was generated by Help Desk Ticket Logger at {html_mod.escape(now.strftime('%Y-%m-%d %H:%M UTC'))}.
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = NOTIFICATION_SENDER
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = now.strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Plain-text fallback
    plain = (
        f"Help Desk Notification\n"
        f"Action: {action}\n"
        f"{'Details: ' + details + chr(10) if details else ''}"
        f"Ticket: {ticket.id}\n"
        f"Title: {ticket.title}\n"
        f"Category: {ticket.category.value}\n"
        f"Priority: {ticket.priority.value}\n"
        f"Status: {ticket.status.value}\n"
        f"Assigned: {ticket.assigned_to or '(unassigned)'}\n"
        f"SLA: {ticket.sla_status()}\n"
        f"Created: {_format_datetime(ticket.created_at)}\n"
        f"Updated: {_format_datetime(ticket.updated_at)}\n"
    )

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    filename = f"ticket-{ticket.id}-{action}-{ts_file}.eml"
    filepath = NOTIFICATIONS_DIR / filename

    try:
        filepath.write_text(msg.as_string(), encoding="utf-8")
    except OSError:
        pass  # Best-effort — don't crash the command on notification failure


RECURRING_FILE = _SCRIPT_DIR / "recurring.json"


def load_recurring() -> List[dict]:
    """Load recurring ticket definitions from recurring.json.

    Returns:
        A list of recurring-definition dicts.  Returns an empty list
        if the file is missing.
    """
    if not RECURRING_FILE.exists():
        return []
    try:
        data = json.loads(RECURRING_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: could not load {RECURRING_FILE}: {exc}")
        return []


def save_recurring(definitions: List[dict]) -> None:
    """Write the full recurring definitions list to recurring.json.

    Args:
        definitions: The complete list of recurring definitions.

    Raises:
        SystemExit: If the file cannot be written.
    """
    payload = json.dumps(definitions, indent=2, ensure_ascii=False) + "\n"
    try:
        RECURRING_FILE.write_text(payload, encoding="utf-8")
    except OSError as exc:
        print(f"Error: could not write {RECURRING_FILE}: {exc}")
        raise SystemExit(1)


def _fill_template_description(template_desc: str) -> str:
    """Interactively fill in blanks (___) in a template description.

    Each ``___`` placeholder is replaced by user input.  The rest of
    the template text is kept as-is.

    Args:
        template_desc: The description string with ``___`` placeholders.

    Returns:
        The description with all blanks filled in.
    """
    parts = template_desc.split("___")
    if len(parts) <= 1:
        return template_desc

    # Extract the label before each blank (e.g. "Printer model: ")
    result_parts: List[str] = []
    for i, part in enumerate(parts):
        result_parts.append(part)
        if i < len(parts) - 1:
            # Derive a prompt label from the text just before the blank
            label = part.strip().rstrip(":").split("\n")[-1].strip()
            if not label:
                label = f"Field {i + 1}"
            value = _prompt_text(f"  {label}")
            result_parts.append(value)

    return "".join(result_parts)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _prompt_choice(prompt_text: str, choices: List[str]) -> str:
    """Prompt the user to pick from a list of valid choices.

    Re-prompts until the user enters a valid value.

    Args:
        prompt_text: The label shown before the options.
        choices: The allowed values.

    Returns:
        The validated user choice.
    """
    choices_str = ", ".join(choices)
    while True:
        value = input(f"{prompt_text} [{choices_str}]: ").strip().lower()
        if value in choices:
            return value
        print(f"  Invalid choice. Please enter one of: {choices_str}")


def _prompt_text(prompt_text: str) -> str:
    """Prompt the user for a non-empty string.

    Re-prompts until the user provides at least one non-whitespace
    character.

    Args:
        prompt_text: The label displayed to the user.

    Returns:
        The trimmed user input.
    """
    while True:
        value = input(f"{prompt_text}: ").strip()
        if value:
            return value
        print("  This field cannot be empty.")


def _format_datetime(iso_string: str) -> str:
    """Convert an ISO 8601 string to a short human-readable form.

    Args:
        iso_string: An ISO 8601 datetime string.

    Returns:
        A formatted date string like '2026-04-13 14:30 UTC'.
    """
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso_string


def _truncate(text: str, width: int) -> str:
    """Truncate text to a given width, adding ellipsis if needed.

    Args:
        text: The string to truncate.
        width: Maximum allowed character width.

    Returns:
        The original or truncated string.
    """
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


# ---------------------------------------------------------------------------
# Shared table display
# ---------------------------------------------------------------------------

def _print_ticket_table(tickets: List[Ticket], *, label: str = "Total") -> None:
    """Print a list of tickets as a formatted table.

    Shared by the ``list`` and ``search`` commands so the output format
    stays consistent.  Priority and status columns are colorized.

    Args:
        tickets: The tickets to display.
        label: The noun used in the summary line (e.g. "Total", "Match").
    """
    id_w, title_w, cat_w, pri_w, stat_w, date_w = 10, 30, 14, 10, 13, 18

    header = (
        f"{color.bold('ID'):<{id_w}} "
        f"{color.bold('TITLE'):<{title_w}} "
        f"{color.bold('CATEGORY'):<{cat_w}} "
        f"{color.bold('PRIORITY'):<{pri_w}} "
        f"{color.bold('STATUS'):<{stat_w}} "
        f"{color.bold('CREATED'):<{date_w}}"
    ) if color.enabled else (
        f"{'ID':<{id_w}} "
        f"{'TITLE':<{title_w}} "
        f"{'CATEGORY':<{cat_w}} "
        f"{'PRIORITY':<{pri_w}} "
        f"{'STATUS':<{stat_w}} "
        f"{'CREATED':<{date_w}}"
    )
    # Separator width based on raw (uncolored) column widths
    raw_width = id_w + 1 + title_w + 1 + cat_w + 1 + pri_w + 1 + stat_w + 1 + date_w
    separator = "-" * raw_width

    print(separator)
    print(header)
    print(separator)

    for t in tickets:
        pri_colored = _pad_colored(
            _color_priority(t.priority.value), t.priority.value, pri_w
        )
        stat_colored = _pad_colored(
            _color_status(t.status.value), t.status.value, stat_w
        )
        row = (
            f"{t.id:<{id_w}} "
            f"{_truncate(t.title, title_w):<{title_w}} "
            f"{t.category.value:<{cat_w}} "
            f"{pri_colored} "
            f"{stat_colored} "
            f"{_format_datetime(t.created_at):<{date_w}}"
        )
        print(row)

    print(separator)
    print(f"{label}: {len(tickets)} ticket(s)")


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> None:
    """Interactively create a new ticket and save it.

    Supports ``--template <name>`` to pre-fill category, priority, and
    description from a template.  Supports ``--assign <name>`` to
    override auto-assignment.  Without ``--assign``, the ticket is
    auto-assigned based on category using assignment_rules.json.

    Args:
        args: Parsed CLI arguments (contains ``file``, ``template``,
            and ``assign``).
    """
    store = TicketStore(args.file)
    template: Optional[dict] = None

    # --- Resolve template if provided ---
    if args.template:
        templates = load_templates()
        if args.template not in templates:
            print(f"Error: unknown template '{args.template}'.")
            names = ", ".join(sorted(templates)) if templates else "(none)"
            print(f"  Available templates: {names}")
            raise SystemExit(1)
        template = templates[args.template]
        print(f"=== Create Ticket from '{args.template}' template ===\n")
    else:
        print("=== Create a New Ticket ===\n")

    # --- Title (always asked) ---
    title = _prompt_text("Title")

    # --- Description ---
    if template:
        print(f"\n  Template description: {template['description']}")
        print("  Fill in the blanks below:\n")
        description = _fill_template_description(template["description"])
    else:
        description = _prompt_text("Description")

    # --- Category ---
    if template:
        category = template["category"]
        print(f"\n  Category (from template): {category}")
    else:
        category = _prompt_choice("Category", [c.value for c in Category])

    # --- Priority ---
    if template:
        priority = template["priority"]
        print(f"  Priority (from template): {priority}")
    else:
        priority = _prompt_choice("Priority", [p.value for p in Priority])

    # --- Assignment ---
    if args.assign:
        assigned_to = args.assign
    else:
        rules = load_assignment_rules()
        assigned_to = rules.get(category, "")

    ticket = Ticket(
        title=title,
        description=description,
        category=Category(category),
        priority=Priority(priority),
        assigned_to=assigned_to,
    )
    ticket.log_event("created", new_value=f"{title} [{category}/{priority}]")
    if assigned_to:
        ticket.log_event("assigned", new_value=assigned_to)

    tickets = store.load()
    tickets.append(ticket)
    store.save(tickets)
    _save_notification(ticket, "created", f"New ticket: {ticket.title}")

    print(f"\n{color.green('Ticket created successfully.')}")
    print(f"  ID:       {ticket.id}")
    print(f"  Title:    {ticket.title}")
    print(f"  Assigned: {ticket.assigned_to or '(unassigned)'}")
    print(f"  Status:   {_color_status(ticket.status.value)}")
    print(f"  Created:  {_format_datetime(ticket.created_at)}")


def cmd_list(args: argparse.Namespace) -> None:
    """Display all tickets in a formatted table.

    Shows ID, title, category, priority, status, and created date.
    Prints a friendly message when no tickets exist yet.

    Args:
        args: Parsed CLI arguments (contains ``file`` for store path).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    if not tickets:
        print("No tickets found. Create one with: python helpdesk.py create")
        return

    _print_ticket_table(tickets)


def cmd_view(args: argparse.Namespace) -> None:
    """Display the full details of a single ticket.

    Args:
        args: Parsed CLI arguments (contains ``id`` and ``file``).
    """
    store = TicketStore(args.file)
    ticket = store.find_by_id(args.id)

    if ticket is None:
        print(f"Error: no ticket found with ID '{args.id}'.")
        raise SystemExit(1)

    sla = ticket.sla_status()

    print(f"{'='*40}")
    print(f"  Ticket:      {color.bold(ticket.id)}")
    print(f"{'='*40}")
    print(f"  Title:       {ticket.title}")
    print(f"  Description: {ticket.description}")
    print(f"  Category:    {ticket.category.value}")
    print(f"  Priority:    {_color_priority(ticket.priority.value)}")
    print(f"  Status:      {_color_status(ticket.status.value)}")
    print(f"  Assigned to: {ticket.assigned_to or '(unassigned)'}")
    print(f"  SLA:         {_color_sla(sla)}")
    print(f"  Created:     {_format_datetime(ticket.created_at)}")
    print(f"  Updated:     {_format_datetime(ticket.updated_at)}")

    if ticket.history:
        print(f"{'='*40}")
        print(f"  {color.bold('History:')}")
        for entry in ticket.history:
            ts = _format_datetime(entry["timestamp"])
            action = entry["action"]
            old = entry.get("old_value")
            new = entry.get("new_value")
            if old:
                detail = f"{old} -> {new}"
            elif new:
                detail = new
            else:
                detail = ""
            print(f"    {ts}  {action}: {detail}")

    print(f"{'='*40}")


def cmd_update(args: argparse.Namespace) -> None:
    """Update a ticket's status, priority, or category.

    Presents the current values and prompts the user to enter new ones.
    Pressing Enter without typing keeps the existing value.  The
    ``updated_at`` timestamp is refreshed on any change.

    Args:
        args: Parsed CLI arguments (contains ``id`` and ``file``).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    target: Optional[Ticket] = None
    for ticket in tickets:
        if ticket.id == args.id:
            target = ticket
            break

    if target is None:
        print(f"Error: no ticket found with ID '{args.id}'.")
        raise SystemExit(1)

    print(f"=== Update Ticket {target.id} ===")
    print(f"  Current title:    {target.title}")
    print(f"  Current status:   {target.status.value}")
    print(f"  Current priority: {target.priority.value}")
    print(f"  Current category: {target.category.value}")
    print()
    print("Press Enter to keep the current value.\n")

    changed = False

    # --- Status ---
    status_choices = [s.value for s in Status]
    new_status = input(
        f"New status [{', '.join(status_choices)}] "
        f"(current: {target.status.value}): "
    ).strip().lower()
    if new_status:
        if new_status not in status_choices:
            print(f"  Invalid status. Keeping '{target.status.value}'.")
        elif new_status != target.status.value:
            old = target.status.value
            target.status = Status(new_status)
            target.log_event("status_changed", old_value=old, new_value=new_status)
            changed = True

    # --- Priority ---
    priority_choices = [p.value for p in Priority]
    new_priority = input(
        f"New priority [{', '.join(priority_choices)}] "
        f"(current: {target.priority.value}): "
    ).strip().lower()
    if new_priority:
        if new_priority not in priority_choices:
            print(f"  Invalid priority. Keeping '{target.priority.value}'.")
        elif new_priority != target.priority.value:
            old = target.priority.value
            target.priority = Priority(new_priority)
            target.log_event("priority_changed", old_value=old, new_value=new_priority)
            changed = True

    # --- Category ---
    category_choices = [c.value for c in Category]
    new_category = input(
        f"New category [{', '.join(category_choices)}] "
        f"(current: {target.category.value}): "
    ).strip().lower()
    if new_category:
        if new_category not in category_choices:
            print(f"  Invalid category. Keeping '{target.category.value}'.")
        elif new_category != target.category.value:
            old = target.category.value
            target.category = Category(new_category)
            target.log_event("category_changed", old_value=old, new_value=new_category)
            changed = True

    if changed:
        target.updated_at = _now_iso()
        store.save(tickets)
        _save_notification(target, "updated", "Ticket fields changed.")
        print(f"\n{color.green('Ticket ' + target.id + ' updated successfully.')}")
    else:
        print(f"\n{color.yellow('No changes made.')}")


def cmd_search(args: argparse.Namespace) -> None:
    """Search tickets with optional filters (AND-combined).

    Supported filters: --category, --priority, --status, --keyword.
    The keyword flag does a case-insensitive substring match against
    both the title and description fields.

    Args:
        args: Parsed CLI arguments with optional filter values.
    """
    store = TicketStore(args.file)
    tickets = store.load()

    if not tickets:
        print("No tickets found. Create one with: python helpdesk.py create")
        return

    results = tickets

    if args.category:
        results = [t for t in results if t.category.value == args.category]

    if args.priority:
        results = [t for t in results if t.priority.value == args.priority]

    if args.status:
        results = [t for t in results if t.status.value == args.status]

    if args.keyword:
        kw = args.keyword.lower()
        results = [
            t for t in results
            if kw in t.title.lower() or kw in t.description.lower()
        ]

    if not results:
        print("No tickets matched the given filters.")
        return

    _print_ticket_table(results, label="Matched")


def _get_resolution_time(ticket: Ticket) -> Optional[timedelta]:
    """Calculate the resolution time for a closed/resolved ticket.

    Looks for the most recent ``status_changed`` history entry whose
    ``new_value`` is ``"closed"`` or ``"resolved"`` and computes the
    delta from ``created_at`` to that timestamp.

    Args:
        ticket: The ticket to inspect.

    Returns:
        A timedelta if a closing event exists, otherwise None.
    """
    closed_ts: Optional[str] = None
    for entry in ticket.history:
        if (
            entry.get("action") == "status_changed"
            and entry.get("new_value") in ("closed", "resolved")
        ):
            closed_ts = entry["timestamp"]

    if closed_ts is None:
        return None

    created = datetime.fromisoformat(ticket.created_at)
    closed = datetime.fromisoformat(closed_ts)
    return closed - created


def _format_delta(td: timedelta) -> str:
    """Format a timedelta as a human-readable string.

    Args:
        td: The time delta to format.

    Returns:
        A string like ``"2d 5h 30m"`` or ``"45m"``.
    """
    total_seconds = int(td.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _was_resolved_within_sla(ticket: Ticket) -> bool:
    """Check whether a resolved/closed ticket met its SLA threshold.

    Args:
        ticket: A ticket with status resolved or closed.

    Returns:
        True if the resolution time is within the SLA threshold.
    """
    res_time = _get_resolution_time(ticket)
    if res_time is None:
        return False
    threshold_hours = SLA_THRESHOLDS.get(ticket.priority.value, 72)
    return res_time <= timedelta(hours=threshold_hours)


def cmd_report(args: argparse.Namespace) -> None:
    """Print a summary report and generate a markdown report file.

    Includes total count, breakdown by status / category / priority,
    average resolution time, SLA compliance, longest-open tickets,
    and overdue tickets.  Saves a ``report_YYYY-MM-DD.md`` file.

    Args:
        args: Parsed CLI arguments (contains ``file`` for store path).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    if not tickets:
        print("No tickets found. Create one with: python helpdesk.py create")
        return

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # ---- Bucket tickets ----
    status_counts: Counter[str] = Counter(t.status.value for t in tickets)
    category_counts: Counter[str] = Counter(t.category.value for t in tickets)
    priority_counts: Counter[str] = Counter(t.priority.value for t in tickets)

    resolved_tickets = [
        t for t in tickets
        if t.status in (Status.RESOLVED, Status.CLOSED)
    ]
    active_tickets = [
        t for t in tickets
        if t.status in (Status.OPEN, Status.IN_PROGRESS)
    ]

    # ---- Average resolution time ----
    res_times: List[timedelta] = []
    for t in resolved_tickets:
        rt = _get_resolution_time(t)
        if rt is not None:
            res_times.append(rt)

    avg_res: Optional[timedelta] = None
    if res_times:
        avg_res = sum(res_times, timedelta()) / len(res_times)

    # ---- SLA compliance ----
    sla_met = sum(1 for t in resolved_tickets if _was_resolved_within_sla(t))
    sla_pct = (sla_met / len(resolved_tickets) * 100) if resolved_tickets else 0.0

    # ---- Longest open tickets ----
    longest_open = sorted(active_tickets, key=lambda t: t.created_at)[:5]

    # ---- Overdue tickets ----
    overdue = [t for t in active_tickets if t.sla_status() == "breached"]

    # ---- Resolution time by category ----
    cat_res: Dict[str, List[timedelta]] = {c.value: [] for c in Category}
    for t in resolved_tickets:
        rt = _get_resolution_time(t)
        if rt is not None:
            cat_res[t.category.value].append(rt)

    # ---- Resolution time by priority ----
    pri_res: Dict[str, List[timedelta]] = {p.value: [] for p in Priority}
    for t in resolved_tickets:
        rt = _get_resolution_time(t)
        if rt is not None:
            pri_res[t.priority.value].append(rt)

    # ==================================================================
    # Terminal output
    # ==================================================================
    width = 58
    divider = "=" * width

    print(divider)
    print(f"  {color.bold('HELP DESK SUMMARY REPORT')}  ({today})")
    print(divider)
    print(f"  Total tickets: {color.bold(str(len(tickets)))}")
    print()

    print(f"  {color.bold('Tickets by Status:')}")
    for status in Status:
        count = status_counts.get(status.value, 0)
        bar = "#" * count
        label = _pad_colored(
            _color_status(status.value), status.value, 13
        )
        print(f"    {label} {count:>4}  {bar}")
    print()

    avg_str = _format_delta(avg_res) if avg_res else "N/A"
    print(f"  {color.bold('Avg resolution time:')} {avg_str}")
    print(f"  {color.bold('SLA compliance:')}      {sla_pct:.0f}% ({sla_met}/{len(resolved_tickets)})")
    print()

    print(f"  {color.bold('Tickets by Category:')}")
    for cat in Category:
        count = category_counts.get(cat.value, 0)
        bar = "#" * count
        print(f"    {cat.value:<14} {count:>4}  {bar}")
    print()

    print(f"  {color.bold('Tickets by Priority:')}")
    for pri in Priority:
        count = priority_counts.get(pri.value, 0)
        bar = "#" * count
        label = _pad_colored(
            _color_priority(pri.value), pri.value, 10
        )
        print(f"    {label} {count:>4}  {bar}")
    print()

    if longest_open:
        print(f"  {color.bold('Longest Open Tickets:')}")
        for t in longest_open:
            age = now - datetime.fromisoformat(t.created_at)
            sla = t.sla_status()
            print(
                f"    [{color.bold(t.id)}] {_truncate(t.title, 28)}  "
                f"age: {_format_delta(age)}  sla: {_color_sla(sla)}"
            )
        print()

    if overdue:
        print(f"  {color.bold(color.red('Overdue Tickets:'))}")
        for t in overdue:
            age = now - datetime.fromisoformat(t.created_at)
            threshold = SLA_THRESHOLDS.get(t.priority.value, 72)
            print(
                f"    {color.red('[' + t.id + ']')} {t.title}  "
                f"({_format_delta(age)} / {threshold}h SLA)"
            )
        print()

    print(divider)

    # ==================================================================
    # Markdown report file
    # ==================================================================
    md_lines: List[str] = []
    md = md_lines.append

    md(f"# Help Desk Report — {today}")
    md("")
    md(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}")
    md("")

    md("## Overview")
    md("")
    md(f"| Metric | Value |")
    md(f"|--------|-------|")
    md(f"| Total tickets | {len(tickets)} |")
    md(f"| Open | {status_counts.get('open', 0)} |")
    md(f"| In-progress | {status_counts.get('in-progress', 0)} |")
    md(f"| Resolved | {status_counts.get('resolved', 0)} |")
    md(f"| Closed | {status_counts.get('closed', 0)} |")
    md(f"| Avg resolution time | {avg_str} |")
    md(f"| SLA compliance | {sla_pct:.0f}% ({sla_met}/{len(resolved_tickets)}) |")
    md("")

    md("## Breakdown by Category")
    md("")
    md("| Category | Count | Avg Resolution Time |")
    md("|----------|------:|---------------------|")
    for cat in Category:
        count = category_counts.get(cat.value, 0)
        times = cat_res[cat.value]
        if times:
            avg = sum(times, timedelta()) / len(times)
            avg_s = _format_delta(avg)
        else:
            avg_s = "—"
        md(f"| {cat.value} | {count} | {avg_s} |")
    md("")

    md("## Breakdown by Priority")
    md("")
    md("| Priority | Count | Avg Resolution Time |")
    md("|----------|------:|---------------------|")
    for pri in Priority:
        count = priority_counts.get(pri.value, 0)
        times = pri_res[pri.value]
        if times:
            avg = sum(times, timedelta()) / len(times)
            avg_s = _format_delta(avg)
        else:
            avg_s = "—"
        md(f"| {pri.value} | {count} | {avg_s} |")
    md("")

    md("## 5 Longest-Open Tickets")
    md("")
    if longest_open:
        md("| ID | Title | Category | Priority | Age | SLA Status |")
        md("|----|-------|----------|----------|-----|------------|")
        for t in longest_open:
            age = now - datetime.fromisoformat(t.created_at)
            md(
                f"| {t.id} | {t.title} | {t.category.value} "
                f"| {t.priority.value} | {_format_delta(age)} "
                f"| {t.sla_status()} |"
            )
    else:
        md("No active tickets.")
    md("")

    md("## Overdue Tickets")
    md("")
    if overdue:
        md("| ID | Title | Priority | Age | SLA Threshold |")
        md("|----|-------|----------|-----|---------------|")
        for t in overdue:
            age = now - datetime.fromisoformat(t.created_at)
            threshold = SLA_THRESHOLDS.get(t.priority.value, 72)
            md(
                f"| {t.id} | {t.title} | {t.priority.value} "
                f"| {_format_delta(age)} | {threshold}h |"
            )
    else:
        md("All active tickets are within SLA thresholds.")
    md("")

    report_path = Path(f"report_{today}.md")
    try:
        report_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"Error: could not write {report_path}: {exc}")
        raise SystemExit(1)

    print(f"  Report saved to {color.green(str(report_path.resolve()))}")


def cmd_sla(args: argparse.Namespace) -> None:
    """List tickets that are at-risk or breached against SLA thresholds.

    Only tickets with status ``open`` or ``in-progress`` are evaluated.
    Breached tickets are shown in red, warnings in yellow.

    Args:
        args: Parsed CLI arguments (contains ``file`` for store path).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    if not tickets:
        print("No tickets found. Create one with: python helpdesk.py create")
        return

    active = [
        t for t in tickets
        if t.status in (Status.OPEN, Status.IN_PROGRESS)
    ]

    if not active:
        print("No active (open/in-progress) tickets to evaluate.")
        return

    at_risk: List[Ticket] = []
    for t in active:
        sla = t.sla_status()
        if sla in ("warning", "breached"):
            at_risk.append(t)
            if sla == "breached":
                threshold = SLA_THRESHOLDS.get(t.priority.value, 72)
                _save_notification(
                    t, "sla_breached",
                    f"SLA breached — {t.priority.value} threshold is {threshold}h.",
                )

    if not at_risk:
        print(color.green("All active tickets are within SLA thresholds."))
        return

    id_w, title_w, pri_w, sla_w, elapsed_w = 10, 30, 10, 10, 14

    header_raw = (
        f"{'ID':<{id_w}} "
        f"{'TITLE':<{title_w}} "
        f"{'PRIORITY':<{pri_w}} "
        f"{'SLA':<{sla_w}} "
        f"{'ELAPSED':<{elapsed_w}}"
    )
    raw_width = id_w + 1 + title_w + 1 + pri_w + 1 + sla_w + 1 + elapsed_w
    separator = "-" * raw_width

    print(separator)
    if color.enabled:
        print(
            f"{color.bold('ID'):<{id_w}} "
            f"{color.bold('TITLE'):<{title_w}} "
            f"{color.bold('PRIORITY'):<{pri_w}} "
            f"{color.bold('SLA'):<{sla_w}} "
            f"{color.bold('ELAPSED'):<{elapsed_w}}"
        )
    else:
        print(header_raw)
    print(separator)

    for t in at_risk:
        sla = t.sla_status()
        created = datetime.fromisoformat(t.created_at)
        elapsed = datetime.now(timezone.utc) - created
        hours = elapsed.total_seconds() / 3600
        threshold = SLA_THRESHOLDS.get(t.priority.value, 72)
        elapsed_str = f"{hours:.1f}h / {threshold}h"

        pri_colored = _pad_colored(
            _color_priority(t.priority.value), t.priority.value, pri_w
        )
        sla_colored = _pad_colored(
            _color_sla(sla), sla, sla_w
        )
        row = (
            f"{t.id:<{id_w}} "
            f"{_truncate(t.title, title_w):<{title_w}} "
            f"{pri_colored} "
            f"{sla_colored} "
            f"{elapsed_str:<{elapsed_w}}"
        )
        print(row)

    print(separator)
    print(f"At-risk: {len(at_risk)} ticket(s)")


def cmd_export(args: argparse.Namespace) -> None:
    """Export all tickets to a CSV file.

    Flattens every field into a column.  The ``history`` field is
    serialized as a JSON string so it fits in a single CSV cell.

    Args:
        args: Parsed CLI arguments (contains ``file`` and ``output``).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    if not tickets:
        print("No tickets found. Nothing to export.")
        return

    output_path = Path(args.output)
    fieldnames = [
        "id", "title", "description", "category", "priority",
        "status", "assigned_to", "created_at", "updated_at",
        "sla_status", "history",
    ]

    try:
        with open(output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for t in tickets:
                writer.writerow({
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "category": t.category.value,
                    "priority": t.priority.value,
                    "status": t.status.value,
                    "assigned_to": t.assigned_to,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                    "sla_status": t.sla_status(),
                    "history": json.dumps(t.history),
                })
    except OSError as exc:
        print(f"Error: could not write {output_path}: {exc}")
        raise SystemExit(1)

    resolved = output_path.resolve()
    print(f"{color.green('Exported')} {len(tickets)} ticket(s) to {resolved}")


def cmd_templates(args: argparse.Namespace) -> None:
    """List available ticket templates, or add a new custom template.

    With ``--add``, interactively prompts the user for a template name,
    category, priority, and description (with ``___`` placeholders for
    blanks), then saves it to templates.json.

    Args:
        args: Parsed CLI arguments (contains ``add`` flag).
    """
    templates = load_templates()

    if args.add:
        print("=== Add a Custom Template ===\n")
        name = _prompt_text("Template name (e.g. 'server-reboot')").lower().strip()
        if name in templates:
            print(f"  Template '{name}' already exists. Choose a different name.")
            raise SystemExit(1)
        category = _prompt_choice("Category", [c.value for c in Category])
        priority = _prompt_choice("Priority", [p.value for p in Priority])
        print("\n  Use ___ for blanks the user will fill in.")
        description = _prompt_text("Description template")

        templates[name] = {
            "category": category,
            "priority": priority,
            "description": description,
        }
        save_templates(templates)
        print(f"\n{color.green('Template added successfully:' )} {name}")
        return

    if not templates:
        print("No templates found.")
        return

    name_w, cat_w, pri_w = 20, 14, 10
    raw_width = name_w + 1 + cat_w + 1 + pri_w + 1 + 40
    separator = "-" * raw_width

    print(separator)
    if color.enabled:
        print(
            f"{color.bold('TEMPLATE'):<{name_w}} "
            f"{color.bold('CATEGORY'):<{cat_w}} "
            f"{color.bold('PRIORITY'):<{pri_w}} "
            f"{color.bold('DESCRIPTION')}"
        )
    else:
        print(
            f"{'TEMPLATE':<{name_w}} "
            f"{'CATEGORY':<{cat_w}} "
            f"{'PRIORITY':<{pri_w}} "
            f"{'DESCRIPTION'}"
        )
    print(separator)

    for name, tmpl in sorted(templates.items()):
        desc_preview = _truncate(tmpl.get("description", ""), 40)
        pri_colored = _pad_colored(
            _color_priority(tmpl.get("priority", "")),
            tmpl.get("priority", ""),
            pri_w,
        )
        print(
            f"{name:<{name_w}} "
            f"{tmpl.get('category', ''):<{cat_w}} "
            f"{pri_colored} "
            f"{desc_preview}"
        )

    print(separator)
    print(f"Total: {len(templates)} template(s)")
    print(f"\nUse: python helpdesk.py create --template <name>")


def _build_dashboard_html(store: TicketStore) -> str:
    """Generate the full HTML dashboard page from current ticket data.

    Reads tickets fresh from disk on every call so auto-refresh picks
    up changes made via the CLI while the server is running.

    Args:
        store: The TicketStore to load tickets from.

    Returns:
        A complete HTML document as a string.
    """
    tickets = store.load()
    now = datetime.now(timezone.utc)
    esc = html_mod.escape

    # ---- Compute stats ----
    total = len(tickets)
    open_count = sum(1 for t in tickets if t.status in (Status.OPEN, Status.IN_PROGRESS))
    overdue_count = sum(
        1 for t in tickets
        if t.status in (Status.OPEN, Status.IN_PROGRESS) and t.sla_status() == "breached"
    )
    resolved = [t for t in tickets if t.status in (Status.RESOLVED, Status.CLOSED)]
    sla_met = sum(1 for t in resolved if _was_resolved_within_sla(t))
    sla_pct = (sla_met / len(resolved) * 100) if resolved else 0.0

    cat_counts = Counter(t.category.value for t in tickets)
    max_cat = max(cat_counts.values()) if cat_counts else 1

    # ---- Build ticket rows JSON for JS filtering ----
    ticket_data: List[dict] = []
    for t in tickets:
        age = now - datetime.fromisoformat(t.created_at)
        sla = t.sla_status()
        history_html = ""
        if t.history:
            history_html += '<div class="history"><strong>History:</strong><ul>'
            for entry in t.history:
                ts = _format_datetime(entry["timestamp"])
                action = esc(entry["action"])
                old = entry.get("old_value")
                new_val = entry.get("new_value")
                if old:
                    detail = f"{esc(str(old))} &rarr; {esc(str(new_val))}"
                elif new_val:
                    detail = esc(str(new_val))
                else:
                    detail = ""
                history_html += f"<li><span class='hist-ts'>{esc(ts)}</span> <strong>{action}</strong>: {detail}</li>"
            history_html += "</ul></div>"

        ticket_data.append({
            "id": t.id,
            "title": esc(t.title),
            "description": esc(t.description),
            "category": t.category.value,
            "priority": t.priority.value,
            "status": t.status.value,
            "assigned_to": esc(t.assigned_to or "(unassigned)"),
            "created": _format_datetime(t.created_at),
            "updated": _format_datetime(t.updated_at),
            "age": _format_delta(age),
            "sla": sla,
            "history_html": history_html,
        })

    tickets_json = json.dumps(ticket_data)

    # ---- Bar chart data ----
    bar_html_parts: List[str] = []
    bar_colors = {
        "hardware": "#4a90d9", "software": "#50c878", "network": "#e8915c",
        "av-equipment": "#9b59b6", "account": "#e74c3c", "other": "#95a5a6",
    }
    for cat in Category:
        count = cat_counts.get(cat.value, 0)
        pct = (count / max_cat * 100) if max_cat else 0
        clr = bar_colors.get(cat.value, "#95a5a6")
        bar_html_parts.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{esc(cat.value)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%;background:{clr};"></div></div>'
            f'<span class="bar-count">{count}</span>'
            f'</div>'
        )
    bars_html = "\n".join(bar_html_parts)

    # ---- Filter option lists ----
    cat_options = "".join(f'<option value="{c.value}">{c.value}</option>' for c in Category)
    pri_options = "".join(f'<option value="{p.value}">{p.value}</option>' for p in Priority)
    stat_options = "".join(f'<option value="{s.value}">{s.value}</option>' for s in Status)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Help Desk Dashboard</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
         background:#f5f6fa; color:#2d3436; }}
  .header {{ background:#2d3436; color:#fff; padding:16px 24px; display:flex;
             align-items:center; justify-content:space-between; }}
  .header h1 {{ font-size:1.3rem; font-weight:600; }}
  .header .ts {{ font-size:0.8rem; opacity:0.7; }}
  .kpi-row {{ display:flex; gap:16px; padding:20px 24px; flex-wrap:wrap; }}
  .kpi {{ background:#fff; border-radius:8px; padding:16px 24px; flex:1; min-width:160px;
          box-shadow:0 1px 3px rgba(0,0,0,0.08); text-align:center; }}
  .kpi .value {{ font-size:2rem; font-weight:700; }}
  .kpi .label {{ font-size:0.8rem; text-transform:uppercase; color:#636e72; margin-top:4px; }}
  .kpi.danger .value {{ color:#d63031; }}
  .kpi.success .value {{ color:#00b894; }}
  .container {{ padding:0 24px 24px; }}
  .card {{ background:#fff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.08);
           padding:20px; margin-bottom:20px; }}
  .card h2 {{ font-size:1rem; margin-bottom:12px; color:#2d3436; }}
  .filters {{ display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; align-items:center; }}
  .filters select {{ padding:6px 10px; border:1px solid #dfe6e9; border-radius:4px;
                     font-size:0.85rem; background:#fff; }}
  .filters label {{ font-size:0.8rem; color:#636e72; text-transform:uppercase; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
  th {{ background:#f5f6fa; text-align:left; padding:10px 12px; font-weight:600;
       border-bottom:2px solid #dfe6e9; white-space:nowrap; }}
  td {{ padding:10px 12px; border-bottom:1px solid #f1f2f6; vertical-align:top; }}
  tr:hover {{ background:#f8f9fa; }}
  tr.expanded {{ background:#fafbfc; }}
  .id-link {{ cursor:pointer; color:#0984e3; text-decoration:underline; font-family:monospace; }}
  .detail-row td {{ padding:12px 24px; background:#fafbfc; }}
  .detail-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr));
                  gap:8px; margin-bottom:10px; }}
  .detail-grid .field {{ font-size:0.82rem; }}
  .detail-grid .field strong {{ color:#636e72; }}
  .history {{ font-size:0.82rem; }}
  .history ul {{ list-style:none; padding-left:0; margin-top:6px; }}
  .history li {{ padding:3px 0; border-bottom:1px solid #f1f2f6; }}
  .hist-ts {{ color:#636e72; font-family:monospace; font-size:0.78rem; }}
  .pri-critical,.pri-high {{ color:#d63031; font-weight:600; }}
  .pri-medium {{ color:#e17055; font-weight:600; }}
  .pri-low {{ color:#636e72; }}
  .sla-breached {{ background:#ffeaa7; color:#d63031; padding:2px 8px; border-radius:3px;
                   font-size:0.78rem; font-weight:600; }}
  .sla-warning {{ background:#ffeaa7; color:#e17055; padding:2px 8px; border-radius:3px;
                  font-size:0.78rem; font-weight:600; }}
  .sla-on-track {{ background:#dfe6e9; color:#00b894; padding:2px 8px; border-radius:3px;
                   font-size:0.78rem; }}
  .status-badge {{ padding:2px 8px; border-radius:3px; font-size:0.78rem; font-weight:500; }}
  .status-open {{ background:#dfe6e9; color:#2d3436; }}
  .status-in-progress {{ background:#81ecec; color:#00796b; }}
  .status-resolved {{ background:#55efc4; color:#006644; }}
  .status-closed {{ background:#b2bec3; color:#2d3436; }}
  .bar-row {{ display:flex; align-items:center; margin-bottom:8px; }}
  .bar-label {{ width:110px; font-size:0.82rem; text-align:right; padding-right:12px; }}
  .bar-track {{ flex:1; background:#f1f2f6; border-radius:4px; height:22px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:4px; transition:width 0.3s ease; }}
  .bar-count {{ width:36px; text-align:right; font-size:0.82rem; font-weight:600; padding-left:8px; }}
  @media (max-width:768px) {{
    .kpi-row {{ flex-direction:column; }}
    table {{ font-size:0.78rem; }}
    .detail-grid {{ grid-template-columns:1fr; }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>Help Desk Dashboard</h1>
  <span class="ts">Auto-refreshes every 30s &middot; {esc(now.strftime('%Y-%m-%d %H:%M UTC'))}</span>
</div>

<div class="kpi-row">
  <div class="kpi"><div class="value">{total}</div><div class="label">Total Tickets</div></div>
  <div class="kpi{'  danger' if open_count else ''}"><div class="value">{open_count}</div><div class="label">Open</div></div>
  <div class="kpi{' danger' if overdue_count else ''}"><div class="value">{overdue_count}</div><div class="label">Overdue</div></div>
  <div class="kpi success"><div class="value">{sla_pct:.0f}%</div><div class="label">SLA Compliance</div></div>
</div>

<div class="container">
  <div class="card">
    <h2>Tickets by Category</h2>
    {bars_html}
  </div>

  <div class="card">
    <h2>All Tickets</h2>
    <div class="filters">
      <div><label>Category</label><br>
        <select id="fCat"><option value="">All</option>{cat_options}</select></div>
      <div><label>Priority</label><br>
        <select id="fPri"><option value="">All</option>{pri_options}</select></div>
      <div><label>Status</label><br>
        <select id="fStat"><option value="">All</option>{stat_options}</select></div>
    </div>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Title</th><th>Category</th><th>Priority</th>
          <th>Status</th><th>Assigned</th><th>Age</th><th>SLA</th>
        </tr>
      </thead>
      <tbody id="tBody"></tbody>
    </table>
  </div>
</div>

<script>
const T = {tickets_json};
let expanded = {{}};

function priCls(p) {{ return 'pri-' + p; }}
function slaCls(s) {{ return 'sla-' + s; }}
function statCls(s) {{ return 'status-' + s.replace('-',''); }}

function render() {{
  const fc = document.getElementById('fCat').value;
  const fp = document.getElementById('fPri').value;
  const fs = document.getElementById('fStat').value;
  const tbody = document.getElementById('tBody');
  tbody.innerHTML = '';

  T.forEach(t => {{
    if (fc && t.category !== fc) return;
    if (fp && t.priority !== fp) return;
    if (fs && t.status !== fs) return;

    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="id-link" data-id="' + t.id + '">' + t.id + '</td>' +
      '<td>' + t.title + '</td>' +
      '<td>' + t.category + '</td>' +
      '<td class="' + priCls(t.priority) + '">' + t.priority + '</td>' +
      '<td><span class="status-badge ' + statCls(t.status) + '">' + t.status + '</span></td>' +
      '<td>' + t.assigned_to + '</td>' +
      '<td>' + t.age + '</td>' +
      '<td><span class="' + slaCls(t.sla) + '">' + t.sla + '</span></td>';
    tbody.appendChild(tr);

    if (expanded[t.id]) {{
      const dr = document.createElement('tr');
      dr.className = 'detail-row';
      dr.innerHTML = '<td colspan="8">' +
        '<div class="detail-grid">' +
        '<div class="field"><strong>ID:</strong> ' + t.id + '</div>' +
        '<div class="field"><strong>Description:</strong> ' + t.description + '</div>' +
        '<div class="field"><strong>Created:</strong> ' + t.created + '</div>' +
        '<div class="field"><strong>Updated:</strong> ' + t.updated + '</div>' +
        '<div class="field"><strong>Assigned:</strong> ' + t.assigned_to + '</div>' +
        '<div class="field"><strong>SLA:</strong> ' + t.sla + '</div>' +
        '</div>' + t.history_html + '</td>';
      tbody.appendChild(dr);
    }}
  }});

  tbody.querySelectorAll('.id-link').forEach(el => {{
    el.addEventListener('click', () => {{
      const id = el.getAttribute('data-id');
      expanded[id] = !expanded[id];
      render();
    }});
  }});
}}

document.getElementById('fCat').addEventListener('change', render);
document.getElementById('fPri').addEventListener('change', render);
document.getElementById('fStat').addEventListener('change', render);
render();
</script>
</body>
</html>"""


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Start a local web server serving a live HTML dashboard.

    The dashboard reads ticket data fresh from disk on every request,
    so changes made via the CLI are reflected on the next auto-refresh
    (every 30 seconds).

    Args:
        args: Parsed CLI arguments (contains ``file`` and ``port``).
    """
    store = TicketStore(args.file)
    port: int = args.port

    class _Handler(BaseHTTPRequestHandler):
        """HTTP request handler that serves the dashboard HTML."""

        def do_GET(self) -> None:
            """Serve the dashboard page for any GET request."""
            page = _build_dashboard_html(store)
            payload = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *log_args: object) -> None:
            """Suppress default access-log noise."""
            pass

    server = HTTPServer(("", port), _Handler)
    print(f"Dashboard running at http://localhost:{port} — press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


# ---------------------------------------------------------------------------
# Interactive TUI
# ---------------------------------------------------------------------------

# ANSI escape sequences for screen control
_CLEAR_SCREEN = "\033[2J\033[H"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_BG_DARK = "\033[48;5;236m"
_FG_WHITE = "\033[97m"
_BG_RESET = "\033[49m"
_REVERSE = "\033[7m"


def _get_term_width() -> int:
    """Return the current terminal width, with a safe fallback.

    Returns:
        The number of columns, or 100 if detection fails.
    """
    try:
        return shutil.get_terminal_size((100, 24)).columns
    except Exception:
        return 100


def _get_term_height() -> int:
    """Return the current terminal height, with a safe fallback.

    Returns:
        The number of rows, or 24 if detection fails.
    """
    try:
        return shutil.get_terminal_size((100, 24)).lines
    except Exception:
        return 24


def _tui_header_bar(width: int) -> str:
    """Build the dark header bar with app name, time, and stats.

    Args:
        width: Terminal width in columns.

    Returns:
        A formatted string for the header (multiple lines).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = "HELP DESK TICKET LOGGER"
    right = f"Last refresh: {now}"
    padding = width - len(title) - len(right)
    if padding < 2:
        padding = 2
    return (
        f"{_BG_DARK}{_FG_WHITE}{_BOLD}"
        f" {title}{' ' * padding}{right} "
        f"{_RESET}"
    )


def _tui_stats_row(tickets: List[Ticket], width: int) -> str:
    """Build the KPI stats row below the header.

    Args:
        tickets: All loaded tickets.
        width: Terminal width in columns.

    Returns:
        A formatted stats string.
    """
    total = len(tickets)
    open_count = sum(
        1 for t in tickets if t.status in (Status.OPEN, Status.IN_PROGRESS)
    )
    overdue = sum(
        1 for t in tickets
        if t.status in (Status.OPEN, Status.IN_PROGRESS)
        and t.sla_status() == "breached"
    )
    resolved = [t for t in tickets if t.status in (Status.RESOLVED, Status.CLOSED)]
    sla_met = sum(1 for t in resolved if _was_resolved_within_sla(t))
    sla_pct = (sla_met / len(resolved) * 100) if resolved else 0.0

    parts = [
        f"  Total: {color.bold(str(total))}",
        f"Open: {color.bold(str(open_count))}",
        f"Overdue: {color.red(str(overdue)) if overdue else '0'}",
        f"SLA: {color.green(f'{sla_pct:.0f}%')}",
    ]
    return "    ".join(parts)


def _tui_ticket_table(tickets: List[Ticket], width: int, max_rows: int) -> List[str]:
    """Build the ticket table lines for the TUI.

    Shows the most recent tickets that fit within ``max_rows``, with
    color-coded priority and status.

    Args:
        tickets: All loaded tickets (will be sorted newest-first).
        width: Terminal width in columns.
        max_rows: Maximum number of data rows to display.

    Returns:
        A list of formatted strings (one per line).
    """
    lines: List[str] = []
    id_w, title_w, cat_w, pri_w, stat_w, sla_w, date_w = 10, 24, 14, 10, 13, 10, 18

    # Adjust title width to fill available space
    fixed = id_w + cat_w + pri_w + stat_w + sla_w + date_w + 8  # 8 = column gaps
    avail_title = width - fixed - 2  # 2 for left margin
    if avail_title > 10:
        title_w = avail_title
    if title_w < 10:
        title_w = 10

    header = (
        f"  {color.bold('ID'):<{id_w}} "
        f"{color.bold('TITLE'):<{title_w}} "
        f"{color.bold('CATEGORY'):<{cat_w}} "
        f"{color.bold('PRIORITY'):<{pri_w}} "
        f"{color.bold('STATUS'):<{stat_w}} "
        f"{color.bold('SLA'):<{sla_w}} "
        f"{color.bold('CREATED')}"
    ) if color.enabled else (
        f"  {'ID':<{id_w}} "
        f"{'TITLE':<{title_w}} "
        f"{'CATEGORY':<{cat_w}} "
        f"{'PRIORITY':<{pri_w}} "
        f"{'STATUS':<{stat_w}} "
        f"{'SLA':<{sla_w}} "
        f"{'CREATED'}"
    )

    raw_sep_width = id_w + title_w + cat_w + pri_w + stat_w + sla_w + date_w + 8
    separator = f"  {'-' * raw_sep_width}"

    lines.append(separator)
    lines.append(header)
    lines.append(separator)

    recent = sorted(tickets, key=lambda t: t.created_at, reverse=True)[:max_rows]

    for t in recent:
        sla = t.sla_status()
        pri_c = _pad_colored(_color_priority(t.priority.value), t.priority.value, pri_w)
        stat_c = _pad_colored(_color_status(t.status.value), t.status.value, stat_w)
        sla_c = _pad_colored(_color_sla(sla), sla, sla_w)
        row = (
            f"  {t.id:<{id_w}} "
            f"{_truncate(t.title, title_w):<{title_w}} "
            f"{t.category.value:<{cat_w}} "
            f"{pri_c} "
            f"{stat_c} "
            f"{sla_c} "
            f"{_format_datetime(t.created_at)}"
        )
        lines.append(row)

    lines.append(separator)
    shown = len(recent)
    hidden = len(tickets) - shown
    summary = f"  Showing {shown} of {len(tickets)} ticket(s)"
    if hidden > 0:
        summary += f"  ({hidden} older tickets not shown)"
    lines.append(summary)

    return lines


def _tui_command_bar(width: int) -> str:
    """Build the bottom command bar.

    Args:
        width: Terminal width in columns.

    Returns:
        A formatted command bar string.
    """
    commands = [
        f"{_REVERSE} C {_RESET} Create",
        f"{_REVERSE} U {_RESET} Update",
        f"{_REVERSE} V {_RESET} View",
        f"{_REVERSE} S {_RESET} Search",
        f"{_REVERSE} R {_RESET} Report",
        f"{_REVERSE} D {_RESET} Delete",
        f"{_REVERSE} Q {_RESET} Quit",
    ]
    return "  " + "   ".join(commands)


def _tui_draw(store: TicketStore, status_msg: str = "") -> None:
    """Clear the screen and redraw the entire TUI.

    Reads tickets fresh from disk so the display always reflects the
    current state of the JSON file.

    Args:
        store: The TicketStore to load from.
        status_msg: An optional one-line message shown above the
            command bar (e.g. "Ticket abc123 created.").
    """
    try:
        width = _get_term_width()
        height = _get_term_height()

        # Reserve lines: header(1) + blank(1) + stats(1) + blank(1)
        #   + table header(3) + separator(1) + summary(1) + blank(1)
        #   + status(1) + command_bar(1) + prompt(1) = ~12 overhead
        max_rows = max(height - 12, 3)
        if max_rows > 15:
            max_rows = 15

        tickets = store.load()

        output: List[str] = []
        output.append(_CLEAR_SCREEN)
        output.append(_tui_header_bar(width))
        output.append("")
        output.append(_tui_stats_row(tickets, width))
        output.append("")
        output.extend(_tui_ticket_table(tickets, width, max_rows))
        output.append("")

        if status_msg:
            output.append(f"  {status_msg}")
            output.append("")

        output.append(_tui_command_bar(width))

        sys.stdout.write("\n".join(output) + "\n")
        sys.stdout.flush()
    except Exception:
        # Handle resize or broken pipe gracefully
        pass


def _tui_pause(msg: str = "Press Enter to continue...") -> None:
    """Pause and wait for the user to press Enter.

    Args:
        msg: The prompt message to display.
    """
    try:
        input(f"\n  {_DIM}{msg}{_RESET}")
    except EOFError:
        pass


def _tui_create(store: TicketStore) -> str:
    """Run the interactive create flow inside the TUI.

    Args:
        store: The TicketStore to save to.

    Returns:
        A status message string for the main screen.
    """
    print(f"\n  {color.bold('=== Create a New Ticket ===')}\n")
    try:
        title = _prompt_text("  Title")
        description = _prompt_text("  Description")
        category = _prompt_choice("  Category", [c.value for c in Category])
        priority = _prompt_choice("  Priority", [p.value for p in Priority])
    except EOFError:
        return color.yellow("Create cancelled.")

    rules = load_assignment_rules()
    assigned_to = rules.get(category, "")

    ticket = Ticket(
        title=title,
        description=description,
        category=Category(category),
        priority=Priority(priority),
        assigned_to=assigned_to,
    )
    ticket.log_event("created", new_value=f"{title} [{category}/{priority}]")
    if assigned_to:
        ticket.log_event("assigned", new_value=assigned_to)

    tickets = store.load()
    tickets.append(ticket)
    store.save(tickets)

    return color.green(f"Ticket {ticket.id} created — assigned to {assigned_to or '(none)'}.")


def _tui_update(store: TicketStore) -> str:
    """Run the interactive update flow inside the TUI.

    Args:
        store: The TicketStore to read/write.

    Returns:
        A status message string for the main screen.
    """
    print()
    try:
        ticket_id = input("  Enter ticket ID to update: ").strip()
    except EOFError:
        return ""

    if not ticket_id:
        return color.yellow("No ID entered.")

    tickets = store.load()
    target: Optional[Ticket] = None
    for t in tickets:
        if t.id == ticket_id:
            target = t
            break

    if target is None:
        return color.red(f"No ticket found with ID '{ticket_id}'.")

    print(f"\n  Updating: {color.bold(target.title)}")
    print(f"  Status: {target.status.value} | Priority: {target.priority.value} | Category: {target.category.value}")
    print(f"  {_DIM}Press Enter to keep current value.{_RESET}\n")

    changed = False

    try:
        new_status = input(f"  New status [{', '.join(s.value for s in Status)}]: ").strip().lower()
        if new_status and new_status in [s.value for s in Status] and new_status != target.status.value:
            old = target.status.value
            target.status = Status(new_status)
            target.log_event("status_changed", old_value=old, new_value=new_status)
            changed = True

        new_priority = input(f"  New priority [{', '.join(p.value for p in Priority)}]: ").strip().lower()
        if new_priority and new_priority in [p.value for p in Priority] and new_priority != target.priority.value:
            old = target.priority.value
            target.priority = Priority(new_priority)
            target.log_event("priority_changed", old_value=old, new_value=new_priority)
            changed = True

        new_category = input(f"  New category [{', '.join(c.value for c in Category)}]: ").strip().lower()
        if new_category and new_category in [c.value for c in Category] and new_category != target.category.value:
            old = target.category.value
            target.category = Category(new_category)
            target.log_event("category_changed", old_value=old, new_value=new_category)
            changed = True
    except EOFError:
        return color.yellow("Update cancelled.")

    if changed:
        target.updated_at = _now_iso()
        store.save(tickets)
        return color.green(f"Ticket {target.id} updated.")
    return color.yellow("No changes made.")


def _tui_view(store: TicketStore) -> str:
    """Show full ticket details inside the TUI.

    Args:
        store: The TicketStore to read from.

    Returns:
        A status message string for the main screen.
    """
    print()
    try:
        ticket_id = input("  Enter ticket ID to view: ").strip()
    except EOFError:
        return ""

    if not ticket_id:
        return color.yellow("No ID entered.")

    ticket = store.find_by_id(ticket_id)
    if ticket is None:
        return color.red(f"No ticket found with ID '{ticket_id}'.")

    sla = ticket.sla_status()
    print(f"\n  {'=' * 44}")
    print(f"  Ticket:      {color.bold(ticket.id)}")
    print(f"  {'=' * 44}")
    print(f"  Title:       {ticket.title}")
    print(f"  Description: {ticket.description}")
    print(f"  Category:    {ticket.category.value}")
    print(f"  Priority:    {_color_priority(ticket.priority.value)}")
    print(f"  Status:      {_color_status(ticket.status.value)}")
    print(f"  Assigned to: {ticket.assigned_to or '(unassigned)'}")
    print(f"  SLA:         {_color_sla(sla)}")
    print(f"  Created:     {_format_datetime(ticket.created_at)}")
    print(f"  Updated:     {_format_datetime(ticket.updated_at)}")

    if ticket.history:
        print(f"  {'=' * 44}")
        print(f"  {color.bold('History:')}")
        for entry in ticket.history:
            ts = _format_datetime(entry["timestamp"])
            action = entry["action"]
            old = entry.get("old_value")
            new = entry.get("new_value")
            if old:
                detail = f"{old} -> {new}"
            elif new:
                detail = new
            else:
                detail = ""
            print(f"    {ts}  {action}: {detail}")

    print(f"  {'=' * 44}")
    _tui_pause()
    return ""


def _tui_search(store: TicketStore) -> str:
    """Run a search and display results inside the TUI.

    Args:
        store: The TicketStore to search.

    Returns:
        A status message string for the main screen.
    """
    print(f"\n  {color.bold('=== Search Tickets ===')}")
    print(f"  {_DIM}Leave blank to skip a filter.{_RESET}\n")

    try:
        kw = input("  Keyword (title/description): ").strip()
        cat = input(f"  Category [{', '.join(c.value for c in Category)}]: ").strip().lower()
        pri = input(f"  Priority [{', '.join(p.value for p in Priority)}]: ").strip().lower()
        stat = input(f"  Status [{', '.join(s.value for s in Status)}]: ").strip().lower()
    except EOFError:
        return ""

    tickets = store.load()
    results = tickets

    if cat and cat in [c.value for c in Category]:
        results = [t for t in results if t.category.value == cat]
    if pri and pri in [p.value for p in Priority]:
        results = [t for t in results if t.priority.value == pri]
    if stat and stat in [s.value for s in Status]:
        results = [t for t in results if t.status.value == stat]
    if kw:
        kw_lower = kw.lower()
        results = [
            t for t in results
            if kw_lower in t.title.lower() or kw_lower in t.description.lower()
        ]

    if not results:
        print(f"\n  {color.yellow('No tickets matched.')}")
    else:
        print()
        _print_ticket_table(results, label="Matched")

    _tui_pause()
    return f"Search returned {len(results)} result(s)." if results else ""


def _tui_report(store: TicketStore, file_arg: Optional[str]) -> str:
    """Run the report command inside the TUI.

    Args:
        store: The TicketStore to report on.
        file_arg: The --file path (passed to cmd_report).

    Returns:
        A status message string for the main screen.
    """
    print()

    class _NS:
        """Minimal namespace to satisfy cmd_report's args interface."""
        file = file_arg

    cmd_report(_NS())  # type: ignore[arg-type]
    _tui_pause()
    return "Report generated."


def _tui_delete(store: TicketStore) -> str:
    """Run the delete flow inside the TUI.

    Args:
        store: The TicketStore to read/write.

    Returns:
        A status message string for the main screen.
    """
    print()
    try:
        ticket_id = input("  Enter ticket ID to delete: ").strip()
    except EOFError:
        return ""

    if not ticket_id:
        return color.yellow("No ID entered.")

    tickets = store.load()
    target: Optional[Ticket] = None
    target_index: int = -1
    for i, t in enumerate(tickets):
        if t.id == ticket_id:
            target = t
            target_index = i
            break

    if target is None:
        return color.red(f"No ticket found with ID '{ticket_id}'.")

    print(f"\n  {color.yellow('About to delete:')}")
    print(f"  ID:    {target.id}")
    print(f"  Title: {target.title}")

    try:
        confirm = input("  Are you sure? (y/N): ").strip().lower()
    except EOFError:
        return "Delete cancelled."

    if confirm != "y":
        return "Delete cancelled."

    tickets.pop(target_index)
    store.save(tickets)
    return color.red(f"Ticket {target.id} deleted.")


def cmd_interactive(args: argparse.Namespace) -> None:
    """Launch the persistent interactive terminal UI.

    Clears the screen and presents a live ticket dashboard with
    single-letter command navigation.  Redraws after each action.

    Args:
        args: Parsed CLI arguments (contains ``file``).
    """
    store = TicketStore(args.file)
    status_msg = color.green("Welcome! Ready to manage tickets.")

    while True:
        try:
            _tui_draw(store, status_msg)
            status_msg = ""

            try:
                cmd = input("\n  > ").strip().lower()
            except EOFError:
                break

            if cmd in ("q", "quit", "exit"):
                print(_CLEAR_SCREEN)
                print("  Goodbye!")
                break
            elif cmd in ("c", "create"):
                status_msg = _tui_create(store)
            elif cmd in ("u", "update"):
                status_msg = _tui_update(store)
            elif cmd in ("v", "view"):
                status_msg = _tui_view(store)
            elif cmd in ("s", "search"):
                status_msg = _tui_search(store)
            elif cmd in ("r", "report"):
                status_msg = _tui_report(store, args.file)
            elif cmd in ("d", "delete"):
                status_msg = _tui_delete(store)
            elif cmd == "":
                continue
            else:
                status_msg = color.yellow(
                    f"Unknown command '{cmd}'. Use C/U/V/S/R/D/Q."
                )

        except KeyboardInterrupt:
            print(_CLEAR_SCREEN)
            print("  Goodbye!")
            break
        except Exception as exc:
            # Catch resize / broken pipe / unexpected errors
            status_msg = color.red(f"Error: {exc}")


def cmd_recurring(args: argparse.Namespace) -> None:
    """Manage recurring ticket definitions.

    Supports adding, listing, pausing, resuming, deleting, and running
    recurring ticket definitions.  The ``--run`` flag checks all active
    definitions against the current time and creates tickets for any
    that are due.

    Args:
        args: Parsed CLI arguments with action flags and optional ``rec_id``.
    """
    definitions = load_recurring()
    templates = load_templates()

    # ---- --add: create a new recurring definition ----
    if args.add:
        if not templates:
            print("Error: no templates found. Create one first with: python helpdesk.py templates --add")
            raise SystemExit(1)

        print("=== Add Recurring Ticket ===\n")
        print(f"  Available templates: {', '.join(sorted(templates))}\n")
        tmpl_name = _prompt_text("Template name").strip().lower()
        if tmpl_name not in templates:
            print(f"Error: unknown template '{tmpl_name}'.")
            raise SystemExit(1)

        while True:
            freq_str = input("Frequency in days (e.g. 7 for weekly): ").strip()
            if freq_str.isdigit() and int(freq_str) > 0:
                frequency_days = int(freq_str)
                break
            print("  Please enter a positive integer.")

        default_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_input = input(f"Start date [YYYY-MM-DD] (default: {default_start}): ").strip()
        if not start_input:
            start_input = default_start
        try:
            start_date = datetime.strptime(start_input, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            print("Error: invalid date format. Use YYYY-MM-DD.")
            raise SystemExit(1)

        rec_id = uuid.uuid4().hex[:8]
        next_due = start_date.isoformat()

        definition = {
            "id": rec_id,
            "template_name": tmpl_name,
            "frequency_days": frequency_days,
            "last_created": None,
            "next_due": next_due,
            "active": True,
        }
        definitions.append(definition)
        save_recurring(definitions)

        print(f"\n{color.green('Recurring ticket added.')}")
        print(f"  ID:        {rec_id}")
        print(f"  Template:  {tmpl_name}")
        print(f"  Frequency: every {frequency_days} day(s)")
        print(f"  Next due:  {_format_datetime(next_due)}")
        return

    # ---- --pause <id> ----
    if args.pause:
        for defn in definitions:
            if defn["id"] == args.pause:
                if not defn["active"]:
                    print(f"Recurring ticket {args.pause} is already paused.")
                    return
                defn["active"] = False
                save_recurring(definitions)
                print(f"{color.yellow('Paused')} recurring ticket {args.pause}.")
                return
        print(f"Error: no recurring definition with ID '{args.pause}'.")
        raise SystemExit(1)

    # ---- --resume <id> ----
    if args.resume:
        for defn in definitions:
            if defn["id"] == args.resume:
                if defn["active"]:
                    print(f"Recurring ticket {args.resume} is already active.")
                    return
                defn["active"] = True
                save_recurring(definitions)
                print(f"{color.green('Resumed')} recurring ticket {args.resume}.")
                return
        print(f"Error: no recurring definition with ID '{args.resume}'.")
        raise SystemExit(1)

    # ---- --delete <id> ----
    if args.rec_delete:
        for i, defn in enumerate(definitions):
            if defn["id"] == args.rec_delete:
                definitions.pop(i)
                save_recurring(definitions)
                print(f"{color.red('Deleted')} recurring definition {args.rec_delete}.")
                return
        print(f"Error: no recurring definition with ID '{args.rec_delete}'.")
        raise SystemExit(1)

    # ---- --run: create tickets for all due definitions ----
    if args.run:
        store = TicketStore(args.file)
        rules = load_assignment_rules()
        now = datetime.now(timezone.utc)
        created_count = 0
        changed = False

        for defn in definitions:
            if not defn["active"]:
                continue

            next_due = datetime.fromisoformat(defn["next_due"])
            if next_due > now:
                continue

            tmpl_name = defn["template_name"]
            if tmpl_name not in templates:
                print(
                    f"  {color.yellow('Warning:')} template '{tmpl_name}' "
                    f"not found for recurring {defn['id']}, skipping."
                )
                continue

            tmpl = templates[tmpl_name]
            category = tmpl["category"]
            priority = tmpl["priority"]
            description = tmpl["description"]
            assigned_to = rules.get(category, "")

            title = f"[Recurring] {tmpl_name}"
            ticket = Ticket(
                title=title,
                description=description,
                category=Category(category),
                priority=Priority(priority),
                assigned_to=assigned_to,
            )
            ticket.log_event(
                "created",
                new_value=f"{title} [{category}/{priority}] (recurring:{defn['id']})",
            )
            if assigned_to:
                ticket.log_event("assigned", new_value=assigned_to)

            tickets = store.load()
            tickets.append(ticket)
            store.save(tickets)

            # Advance next_due forward, skipping any missed intervals
            freq = timedelta(days=defn["frequency_days"])
            new_next = next_due + freq
            while new_next <= now:
                new_next += freq

            defn["last_created"] = now.isoformat()
            defn["next_due"] = new_next.isoformat()
            changed = True
            created_count += 1

            print(
                f"  {color.green('Created')} ticket {color.bold(ticket.id)} "
                f"from '{tmpl_name}' — next due {_format_datetime(new_next.isoformat())}"
            )

        if changed:
            save_recurring(definitions)

        if created_count == 0:
            print("No recurring tickets are due at this time.")
        else:
            print(f"\n{created_count} recurring ticket(s) created.")
        return

    # ---- --list (default action) ----
    if not definitions:
        print("No recurring ticket definitions. Add one with: python helpdesk.py recurring --add")
        return

    id_w, tmpl_w, freq_w, status_w, next_w, last_w = 10, 20, 10, 10, 20, 20
    raw_width = id_w + tmpl_w + freq_w + status_w + next_w + last_w + 7
    separator = "-" * raw_width

    print(separator)
    if color.enabled:
        print(
            f"{color.bold('ID'):<{id_w}} "
            f"{color.bold('TEMPLATE'):<{tmpl_w}} "
            f"{color.bold('FREQUENCY'):<{freq_w}} "
            f"{color.bold('STATUS'):<{status_w}} "
            f"{color.bold('NEXT DUE'):<{next_w}} "
            f"{color.bold('LAST CREATED')}"
        )
    else:
        print(
            f"{'ID':<{id_w}} "
            f"{'TEMPLATE':<{tmpl_w}} "
            f"{'FREQUENCY':<{freq_w}} "
            f"{'STATUS':<{status_w}} "
            f"{'NEXT DUE':<{next_w}} "
            f"{'LAST CREATED'}"
        )
    print(separator)

    for defn in definitions:
        status_str = "active" if defn["active"] else "paused"
        status_colored = (
            color.green(status_str) if defn["active"]
            else color.yellow(status_str)
        )
        status_padded = _pad_colored(status_colored, status_str, status_w)

        freq_str = f"{defn['frequency_days']}d"
        next_str = _format_datetime(defn["next_due"]) if defn["next_due"] else "—"
        last_str = _format_datetime(defn["last_created"]) if defn["last_created"] else "never"

        # Check if overdue
        if defn["active"] and defn["next_due"]:
            next_dt = datetime.fromisoformat(defn["next_due"])
            if next_dt <= datetime.now(timezone.utc):
                next_str = color.red(next_str + " (DUE)")
                next_str = _pad_colored(
                    next_str,
                    _format_datetime(defn["next_due"]) + " (DUE)",
                    next_w + 6,
                )

        print(
            f"{defn['id']:<{id_w}} "
            f"{_truncate(defn['template_name'], tmpl_w):<{tmpl_w}} "
            f"{freq_str:<{freq_w}} "
            f"{status_padded} "
            f"{next_str:<{next_w}} "
            f"{last_str}"
        )

    print(separator)
    print(f"Total: {len(definitions)} recurring definition(s)")


def cmd_notifications(args: argparse.Namespace) -> None:
    """List recent email notification files from the notifications/ directory.

    Shows the most recent .eml files with filename, size, and
    modification time.

    Args:
        args: Parsed CLI arguments (unused beyond standard flags).
    """
    if not NOTIFICATIONS_DIR.exists():
        print("No notifications directory found. Notifications are created when tickets are created, updated, or breach SLA.")
        return

    eml_files = sorted(NOTIFICATIONS_DIR.glob("*.eml"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not eml_files:
        print("No notification files found.")
        return

    limit = 20
    shown = eml_files[:limit]

    name_w, size_w, date_w = 52, 8, 20
    raw_width = name_w + size_w + date_w + 4
    separator = "-" * raw_width

    print(separator)
    if color.enabled:
        print(
            f"{color.bold('FILE'):<{name_w}} "
            f"{color.bold('SIZE'):<{size_w}} "
            f"{color.bold('DATE')}"
        )
    else:
        print(
            f"{'FILE':<{name_w}} "
            f"{'SIZE':<{size_w}} "
            f"{'DATE'}"
        )
    print(separator)

    for fp in shown:
        stat = fp.stat()
        size = f"{stat.st_size}B"
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        date_str = mtime.strftime("%Y-%m-%d %H:%M UTC")
        print(
            f"{_truncate(fp.name, name_w):<{name_w}} "
            f"{size:<{size_w}} "
            f"{date_str}"
        )

    print(separator)
    total = len(eml_files)
    print(f"Showing {len(shown)} of {total} notification(s)")
    print(f"Directory: {NOTIFICATIONS_DIR.resolve()}")


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete a ticket after user confirmation.

    Args:
        args: Parsed CLI arguments (contains ``id`` and ``file``).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    target: Optional[Ticket] = None
    target_index: int = -1
    for i, ticket in enumerate(tickets):
        if ticket.id == args.id:
            target = ticket
            target_index = i
            break

    if target is None:
        print(f"Error: no ticket found with ID '{args.id}'.")
        raise SystemExit(1)

    print(f"{color.yellow('About to delete ticket:')}")
    print(f"  ID:    {target.id}")
    print(f"  Title: {target.title}")
    confirm = input("Are you sure? (y/N): ").strip().lower()

    if confirm != "y":
        print("Delete cancelled.")
        return

    tickets.pop(target_index)
    store.save(tickets)
    print(f"{color.red('Ticket ' + target.id + ' deleted.')}")


# ---------------------------------------------------------------------------
# Argument parser & entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands.

    Returns:
        A fully configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="helpdesk",
        description="Help Desk Ticket Logger — manage support tickets from the command line.",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Path to the tickets JSON file (default: tickets.json).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable colored terminal output.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available commands:",
    )

    # create
    sp_create = subparsers.add_parser(
        "create",
        help="Create a new ticket interactively.",
    )
    sp_create.add_argument(
        "--template",
        default=None,
        help="Use a predefined template to pre-fill fields.",
    )
    sp_create.add_argument(
        "--assign",
        default=None,
        help="Override auto-assignment with a specific person or team.",
    )
    sp_create.set_defaults(func=cmd_create)

    # templates
    sp_templates = subparsers.add_parser(
        "templates",
        help="List available ticket templates or add a new one.",
    )
    sp_templates.add_argument(
        "--add",
        action="store_true",
        default=False,
        help="Interactively add a new custom template.",
    )
    sp_templates.set_defaults(func=cmd_templates)

    # list
    sp_list = subparsers.add_parser(
        "list",
        help="List all tickets in a table.",
    )
    sp_list.set_defaults(func=cmd_list)

    # view
    sp_view = subparsers.add_parser(
        "view",
        help="View full details of a ticket.",
    )
    sp_view.add_argument("id", help="The ticket ID to view.")
    sp_view.set_defaults(func=cmd_view)

    # update
    sp_update = subparsers.add_parser(
        "update",
        help="Update a ticket's status, priority, or category.",
    )
    sp_update.add_argument("id", help="The ticket ID to update.")
    sp_update.set_defaults(func=cmd_update)

    # search
    sp_search = subparsers.add_parser(
        "search",
        help="Search tickets by category, priority, status, or keyword.",
    )
    sp_search.add_argument(
        "--category",
        choices=[c.value for c in Category],
        help="Filter by category.",
    )
    sp_search.add_argument(
        "--priority",
        choices=[p.value for p in Priority],
        help="Filter by priority.",
    )
    sp_search.add_argument(
        "--status",
        choices=[s.value for s in Status],
        help="Filter by status.",
    )
    sp_search.add_argument(
        "--keyword",
        help="Search title and description (case-insensitive).",
    )
    sp_search.set_defaults(func=cmd_search)

    # report
    sp_report = subparsers.add_parser(
        "report",
        help="Print a summary report of all tickets.",
    )
    sp_report.set_defaults(func=cmd_report)

    # sla
    sp_sla = subparsers.add_parser(
        "sla",
        help="List tickets at-risk or breached against SLA thresholds.",
    )
    sp_sla.set_defaults(func=cmd_sla)

    # export
    sp_export = subparsers.add_parser(
        "export",
        help="Export all tickets to a CSV file.",
    )
    sp_export.add_argument(
        "--output",
        default="tickets_export.csv",
        help="Output CSV file path (default: tickets_export.csv).",
    )
    sp_export.set_defaults(func=cmd_export)

    # recurring
    sp_recurring = subparsers.add_parser(
        "recurring",
        help="Manage recurring ticket definitions.",
    )
    sp_recurring.add_argument(
        "--add",
        action="store_true",
        default=False,
        help="Add a new recurring ticket definition.",
    )
    sp_recurring.add_argument(
        "--list",
        action="store_true",
        default=False,
        dest="rec_list",
        help="List all recurring definitions (default action).",
    )
    sp_recurring.add_argument(
        "--pause",
        default=None,
        metavar="ID",
        help="Pause a recurring definition by ID.",
    )
    sp_recurring.add_argument(
        "--resume",
        default=None,
        metavar="ID",
        help="Resume a paused recurring definition by ID.",
    )
    sp_recurring.add_argument(
        "--delete",
        default=None,
        metavar="ID",
        dest="rec_delete",
        help="Delete a recurring definition by ID.",
    )
    sp_recurring.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Create tickets for all due recurring definitions.",
    )
    sp_recurring.set_defaults(func=cmd_recurring)

    # notifications
    sp_notifications = subparsers.add_parser(
        "notifications",
        help="List recent email notification files.",
    )
    sp_notifications.set_defaults(func=cmd_notifications)

    # interactive
    sp_interactive = subparsers.add_parser(
        "interactive",
        help="Launch the persistent interactive terminal UI.",
    )
    sp_interactive.set_defaults(func=cmd_interactive)

    # dashboard
    sp_dashboard = subparsers.add_parser(
        "dashboard",
        help="Start a local web dashboard on port 8080.",
    )
    sp_dashboard.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to serve the dashboard on (default: 8080).",
    )
    sp_dashboard.set_defaults(func=cmd_dashboard)

    # delete
    sp_delete = subparsers.add_parser(
        "delete",
        help="Delete a ticket (with confirmation).",
    )
    sp_delete.add_argument("id", help="The ticket ID to delete.")
    sp_delete.set_defaults(func=cmd_delete)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate command handler."""
    parser = build_parser()
    args = parser.parse_args()

    # Disable color when explicitly requested, when stdout is not a TTY
    # (e.g. piped to a file), or when the NO_COLOR env var is set.
    if args.no_color or not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        color.enabled = False

    if args.command is None:
        parser.print_help()
        raise SystemExit(0)

    args.func(args)


if __name__ == "__main__":
    main()
