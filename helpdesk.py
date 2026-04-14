"""Help Desk Ticket Logger — a local CLI ticketing system.

A command-line tool for creating, tracking, and managing help desk
tickets. All data is stored in a local JSON file with zero external
dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional


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
        created_at: ISO 8601 timestamp of when the ticket was created.
        updated_at: ISO 8601 timestamp of the last modification.
    """

    title: str
    description: str
    category: Category
    priority: Priority
    id: str = field(default_factory=_generate_id)
    status: Status = Status.OPEN
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

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
            created_at=data["created_at"],
            updated_at=data["updated_at"],
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

    Prompts the user for title, description, category, and priority,
    then auto-generates an ID and timestamps before writing to disk.

    Args:
        args: Parsed CLI arguments (contains ``file`` for store path).
    """
    store = TicketStore(args.file)

    print("=== Create a New Ticket ===\n")
    title = _prompt_text("Title")
    description = _prompt_text("Description")
    category = _prompt_choice("Category", [c.value for c in Category])
    priority = _prompt_choice("Priority", [p.value for p in Priority])

    ticket = Ticket(
        title=title,
        description=description,
        category=Category(category),
        priority=Priority(priority),
    )

    tickets = store.load()
    tickets.append(ticket)
    store.save(tickets)

    print(f"\n{color.green('Ticket created successfully.')}")
    print(f"  ID:       {ticket.id}")
    print(f"  Title:    {ticket.title}")
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

    print(f"{'='*40}")
    print(f"  Ticket:      {color.bold(ticket.id)}")
    print(f"{'='*40}")
    print(f"  Title:       {ticket.title}")
    print(f"  Description: {ticket.description}")
    print(f"  Category:    {ticket.category.value}")
    print(f"  Priority:    {_color_priority(ticket.priority.value)}")
    print(f"  Status:      {_color_status(ticket.status.value)}")
    print(f"  Created:     {_format_datetime(ticket.created_at)}")
    print(f"  Updated:     {_format_datetime(ticket.updated_at)}")
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
            target.status = Status(new_status)
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
            target.priority = Priority(new_priority)
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
            target.category = Category(new_category)
            changed = True

    if changed:
        target.updated_at = _now_iso()
        store.save(tickets)
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


def cmd_report(args: argparse.Namespace) -> None:
    """Print a summary report of all tickets.

    Includes total count, breakdown by status / category / priority,
    and the 3 most recently created tickets.

    Args:
        args: Parsed CLI arguments (contains ``file`` for store path).
    """
    store = TicketStore(args.file)
    tickets = store.load()

    if not tickets:
        print("No tickets found. Create one with: python helpdesk.py create")
        return

    status_counts: Counter[str] = Counter(t.status.value for t in tickets)
    category_counts: Counter[str] = Counter(t.category.value for t in tickets)
    priority_counts: Counter[str] = Counter(t.priority.value for t in tickets)

    width = 50
    divider = "=" * width

    # --- Header ---
    print(divider)
    print(f"  {color.bold('HELP DESK SUMMARY REPORT')}")
    print(divider)
    print(f"  Total tickets: {color.bold(str(len(tickets)))}")
    print()

    # --- By Status ---
    print(f"  {color.bold('Tickets by Status:')}")
    for status in Status:
        count = status_counts.get(status.value, 0)
        bar = "#" * count
        label = _pad_colored(
            _color_status(status.value), status.value, 13
        )
        print(f"    {label} {count:>4}  {bar}")
    print()

    # --- By Category ---
    print(f"  {color.bold('Tickets by Category:')}")
    for cat in Category:
        count = category_counts.get(cat.value, 0)
        bar = "#" * count
        print(f"    {cat.value:<14} {count:>4}  {bar}")
    print()

    # --- By Priority ---
    print(f"  {color.bold('Tickets by Priority:')}")
    for pri in Priority:
        count = priority_counts.get(pri.value, 0)
        bar = "#" * count
        label = _pad_colored(
            _color_priority(pri.value), pri.value, 10
        )
        print(f"    {label} {count:>4}  {bar}")
    print()

    # --- Recent Tickets ---
    recent = sorted(tickets, key=lambda t: t.created_at, reverse=True)[:3]
    print(f"  {color.bold('3 Most Recent Tickets:')}")
    for t in recent:
        print(f"    [{color.bold(t.id)}] {t.title}")
        print(
            f"      {_color_status(t.status.value)} | "
            f"{_color_priority(t.priority.value)} | "
            f"{_format_datetime(t.created_at)}"
        )
    print(divider)


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
    sp_create.set_defaults(func=cmd_create)

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
