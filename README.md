# Help Desk Ticket Logger

A full-featured command-line help desk ticket management system built for IT support teams. Create, track, search, and report on support tickets entirely from the terminal — with zero external dependencies.

Designed to mirror the core workflows of enterprise ticketing systems like WebTMA and ServiceNow: logging issues, categorizing and prioritizing them, tracking SLA compliance, auto-assigning to teams, generating reports, and sending email notifications — all powered by Python's standard library.

## Features

- **Ticket Management** — create, view, update, delete tickets with full CRUD operations
- **Ticket Templates** — predefined templates for common issues (printer, network outage, software install, projector, account lockout) with fill-in-the-blank descriptions
- **Auto-Assignment** — category-based routing to teams via configurable rules
- **SLA Tracking** — priority-based thresholds (critical: 4h, high: 8h, medium: 24h, low: 72h) with on-track/warning/breached status
- **Audit History** — every create, update, and assignment is logged with timestamps
- **Search & Filter** — AND-combined filters for category, priority, status, and keyword
- **Summary Reports** — terminal output + markdown file with resolution times, SLA compliance, and breakdowns by category/priority
- **CSV Export** — full data export with flattened history for spreadsheet analysis
- **Recurring Tickets** — scheduled ticket creation linked to templates, with pause/resume and cron-friendly `--run`
- **Email Notifications** — generates `.eml` files on create, update, and SLA breach events
- **Web Dashboard** — local HTTP server with live stats, filterable table, bar charts, and click-to-expand details
- **Interactive TUI** — persistent terminal UI with single-key navigation and live refresh
- **Color-Coded Output** — ANSI colors for priority, status, and SLA with `--no-color` fallback

## Requirements

- **Python 3.9+**
- No external packages — 100% standard library

## Installation

```bash
git clone https://github.com/fadhilmohammed/helpdesk-ticket-logger.git
cd helpdesk-ticket-logger
python helpdesk.py --help
```

No `pip install`, no virtual environment, no setup script. Clone and run.

## Usage

```
python helpdesk.py [--file PATH] [--no-color] <command> [options]
```

### Global Options

| Flag         | Description                                      |
|--------------|--------------------------------------------------|
| `--file`     | Path to a custom tickets JSON file               |
| `--no-color` | Disable colored terminal output                  |

---

### Create a Ticket

```
$ python helpdesk.py create

=== Create a New Ticket ===

Title: Printer jam on 3rd floor
Description: HP LaserJet in room 310 has recurring paper jams
Category [hardware, software, network, av-equipment, account, other]: hardware
Priority [low, medium, high, critical]: high

Ticket created successfully.
  ID:       a1b2c3d4
  Title:    Printer jam on 3rd floor
  Assigned: Hardware Team
  Status:   open
  Created:  2026-04-13 18:30 UTC
```

### Create from Template

```
$ python helpdesk.py create --template printer

=== Create Ticket from 'printer' template ===

Title: Broken printer in lobby

  Template description: Printer model: ___ Location: ___ Issue: ___
  Fill in the blanks below:

  Printer model: HP LaserJet Pro
  Location: Main lobby, 1st floor
  Issue: Paper jam every 5 pages

  Category (from template): hardware
  Priority (from template): medium

Ticket created successfully.
  ID:       e5f6a7b8
  Assigned: Hardware Team
```

### List All Tickets

```
$ python helpdesk.py list

----------------------------------------------------------------------------------------------------
ID         TITLE                          CATEGORY       PRIORITY   STATUS        CREATED
----------------------------------------------------------------------------------------------------
a1b2c3d4   Printer jam on 3rd floor       hardware       high       open          2026-04-13 18:30 UTC
e5f6a7b8   VPN disconnects randomly       network        critical   open          2026-04-13 17:15 UTC
c9d0e1f2   Outlook not syncing            software       medium     in-progress   2026-04-13 16:00 UTC
----------------------------------------------------------------------------------------------------
Total: 3 ticket(s)
```

### View Ticket Details

```
$ python helpdesk.py view a1b2c3d4

========================================
  Ticket:      a1b2c3d4
========================================
  Title:       Printer jam on 3rd floor
  Description: HP LaserJet in room 310 has recurring paper jams
  Category:    hardware
  Priority:    high
  Status:      in-progress
  Assigned to: Hardware Team
  SLA:         on-track
  Created:     2026-04-13 18:30 UTC
  Updated:     2026-04-13 19:00 UTC
========================================
  History:
    2026-04-13 18:30 UTC  created: Printer jam on 3rd floor [hardware/high]
    2026-04-13 18:30 UTC  assigned: Hardware Team
    2026-04-13 19:00 UTC  status_changed: open -> in-progress
========================================
```

### Update a Ticket

```
$ python helpdesk.py update a1b2c3d4

=== Update Ticket a1b2c3d4 ===
  Current status:   open
  Current priority: high

Press Enter to keep the current value.

New status [open, in-progress, resolved, closed] (current: open): in-progress
New priority [low, medium, high, critical] (current: high):
New category [hardware, software, network, av-equipment, account, other] (current: hardware):

Ticket a1b2c3d4 updated successfully.
```

### Search Tickets

Filters are AND-combined. All flags are optional.

```
$ python helpdesk.py search --priority high --status open
$ python helpdesk.py search --keyword vpn
$ python helpdesk.py search --category network --priority critical
```

### Summary Report

Generates both terminal output and a `report_YYYY-MM-DD.md` markdown file.

```
$ python helpdesk.py report

==========================================================
  HELP DESK SUMMARY REPORT  (2026-04-14)
==========================================================
  Total tickets: 10

  Tickets by Status:
    open             4  ####
    in-progress      1  #
    resolved         2  ##
    closed           3  ###

  Avg resolution time: 5h 12m
  SLA compliance:      80% (4/5)

  Tickets by Category:
    hardware          2  ##
    software          2  ##
    network           2  ##
    ...

  Longest Open Tickets:
    [264971b0] New hire account setup  age: 1d 6h 0m  sla: breached
    ...

  Overdue Tickets:
    [8b4b1b08] Laptop won't boot  (6h 0m / 4h SLA)
    ...

==========================================================
  Report saved to /path/to/report_2026-04-14.md
```

### SLA Check

```
$ python helpdesk.py sla

------------------------------------------------------------------------------
ID         TITLE                          PRIORITY   SLA        ELAPSED
------------------------------------------------------------------------------
8b4b1b08   Laptop won't boot              critical   breached   6.0h / 4h
076ee257   Conference room B audio        high       breached   15.0h / 8h
------------------------------------------------------------------------------
At-risk: 2 ticket(s)
```

### CSV Export

```
$ python helpdesk.py export
Exported 10 ticket(s) to /path/to/tickets_export.csv

$ python helpdesk.py export --output backup.csv
Exported 10 ticket(s) to /path/to/backup.csv
```

### Templates

```
$ python helpdesk.py templates

---------------------------------------------------------------------------------------
TEMPLATE             CATEGORY       PRIORITY   DESCRIPTION
---------------------------------------------------------------------------------------
account-lockout      account        high       Username: ___ Last known access: ___
network-outage       network        critical   Building: ___ Floor: ___ Affected use...
printer              hardware       medium     Printer model: ___ Location: ___ Issu...
projector            av-equipment   high       Room: ___ Issue: ___ Event time: ___
software-install     software       low        Software name: ___ Version: ___ Machi...
---------------------------------------------------------------------------------------
Total: 5 template(s)

$ python helpdesk.py templates --add    # Interactive custom template creation
```

### Recurring Tickets

```
$ python helpdesk.py recurring --add     # Add a recurring definition
$ python helpdesk.py recurring           # List all recurring definitions
$ python helpdesk.py recurring --run     # Create tickets for all due definitions
$ python helpdesk.py recurring --pause <id>
$ python helpdesk.py recurring --resume <id>
$ python helpdesk.py recurring --delete <id>
```

Example `--run` output (designed for cron):

```
$ python helpdesk.py recurring --run
  Created ticket a05ec967 from 'printer' — next due 2026-04-21 00:00 UTC
  Created ticket 48ee6c2a from 'network-outage' — next due 2026-04-15 00:00 UTC

2 recurring ticket(s) created.
```

### Email Notifications

Notifications are automatically saved as `.eml` files when tickets are created, updated, or breach SLA.

```
$ python helpdesk.py notifications

------------------------------------------------------------------------------------
FILE                                                 SIZE     DATE
------------------------------------------------------------------------------------
ticket-a3c20c08-updated-20260414-014204.eml          2967B    2026-04-14 01:42 UTC
ticket-a3c20c08-created-20260414-014159.eml          2955B    2026-04-14 01:41 UTC
------------------------------------------------------------------------------------
Showing 2 of 2 notification(s)
Directory: /path/to/notifications
```

### Web Dashboard

```
$ python helpdesk.py dashboard
Dashboard running at http://localhost:8080 — press Ctrl+C to stop
```

Serves a responsive HTML page with:
- KPI cards (total, open, overdue, SLA compliance)
- Filterable ticket table with click-to-expand details
- CSS bar chart by category
- Auto-refresh every 30 seconds

### Interactive TUI

```
$ python helpdesk.py interactive
```

Full-screen terminal UI with live stats, color-coded ticket table, and single-key commands: `[C]reate [U]pdate [V]iew [S]earch [R]eport [D]elete [Q]uit`.

### Delete a Ticket

```
$ python helpdesk.py delete a1b2c3d4

About to delete ticket:
  ID:    a1b2c3d4
  Title: Printer jam on 3rd floor
Are you sure? (y/N): y
Ticket a1b2c3d4 deleted.
```

## Architecture

### Design Philosophy

This project intentionally uses **zero external dependencies** to demonstrate that a fully functional ticketing system can be built with Python's standard library alone. Every component — CLI, data model, persistence, web server, email generation, terminal UI — uses only stdlib modules.

### Data Storage

All ticket data lives in a single `tickets.json` file. This was chosen over SQLite for simplicity and transparency:

- **Human-readable** — open the file and see your data as formatted JSON
- **Portable** — copy one file to move your entire ticket database
- **No schema migrations** — new fields use `.get()` with defaults for backward compatibility
- **Atomic writes** — data is serialized to a temporary file via `tempfile.NamedTemporaryFile`, then moved into place with `os.replace()`, which is an atomic operation on most filesystems. This ensures a crash mid-write never leaves a corrupted `tickets.json` — the previous version remains intact until the new one is fully written.

Trade-off: this approach reads/writes the full file on every operation, which is fine for the hundreds-to-low-thousands ticket range this tool targets.

### Auto-Assignment Routing

When a ticket is created, the system looks up the ticket's category in `assignment_rules.json` and automatically assigns it to the mapped team (e.g. `"hardware"` routes to `"Hardware Team"`, `"network"` routes to `"Network Admin"`). This can be overridden per-ticket with the `--assign` flag. The routing table is a simple JSON object, making it easy for admins to reconfigure without touching code.

### SLA Compliance Engine

SLA thresholds are defined per priority level (critical: 4h, high: 8h, medium: 24h, low: 72h). The system calculates SLA status by parsing the ticket's `created_at` ISO 8601 timestamp, computing the elapsed `timedelta` against `datetime.now(UTC)`, and comparing it to the threshold. Tickets are classified as `on-track` (under 75% elapsed), `warning` (75%+ elapsed), or `breached` (threshold exceeded). Resolution time for closed tickets is derived from the audit history — specifically, the timestamp of the most recent `status_changed` event where `new_value` is `"closed"` or `"resolved"`.

### Email Notification Simulation

The notification system generates standards-compliant `.eml` files using `email.mime.multipart` and `email.mime.text` from the stdlib. Each notification contains both a plain-text and an HTML body with inline CSS styling, proper `From`/`To`/`Subject`/`Date` headers, and a summary of the ticket state at notification time. Files are saved to `notifications/` and can be opened in any email client for testing. This approach simulates a real notification pipeline without requiring SMTP configuration, making it suitable for development, demos, and portfolio review.

### File Structure

```
helpdesk-ticket-logger/
  helpdesk.py            # All application code (single file)
  templates.json         # Predefined ticket templates
  assignment_rules.json  # Category-to-team routing rules
  tickets.json           # Ticket data (created at runtime)
  recurring.json         # Recurring ticket definitions (created at runtime)
  notifications/         # Generated .eml files (created at runtime)
  report_YYYY-MM-DD.md   # Generated reports (created at runtime)
  tickets_export.csv     # CSV exports (created at runtime)
```

### Tech Stack

| Component          | Technology                                 |
|--------------------|--------------------------------------------|
| Language           | Python 3.9+                                |
| CLI framework      | `argparse` (stdlib)                        |
| Data model         | `dataclasses` (stdlib)                     |
| Storage            | JSON via `json` (stdlib)                   |
| ID generation      | `uuid` (stdlib)                            |
| Timestamps         | `datetime` (stdlib)                        |
| Terminal color     | ANSI escape codes (no dependencies)        |
| Web dashboard      | `http.server` (stdlib)                     |
| Email generation   | `email.mime` (stdlib)                      |
| CSV export         | `csv` (stdlib)                             |
| External deps      | **None** — 100% standard library           |

## Ticket Schema

| Field       | Type   | Values                                                    |
|-------------|--------|-----------------------------------------------------------|
| id          | string | Auto-generated 8-character hex ID                         |
| title       | string | Short summary of the issue                                |
| description | string | Detailed problem description                              |
| category    | enum   | hardware, software, network, av-equipment, account, other |
| priority    | enum   | low, medium, high, critical                               |
| status      | enum   | open, in-progress, resolved, closed                       |
| assigned_to | string | Auto-assigned team or manual override                     |
| created_at  | string | ISO 8601 UTC timestamp                                    |
| updated_at  | string | ISO 8601 UTC timestamp                                    |
| history     | list   | Audit log of all changes with timestamps                  |

## Future Improvements

- **SQLite migration** — replace JSON flat-file storage with SQLite (`sqlite3` is in stdlib) to support concurrent multi-user access, transactional writes, and indexed queries without adding external dependencies
- **REST API layer** — build a lightweight REST API on top of `http.server` to accept remote ticket submissions, enabling integration with web forms, mobile apps, and third-party automation tools
- **Role-based access control** — implement user authentication with technician, admin, and viewer roles so that ticket creation, updates, and deletions can be scoped to authorized personnel
- **Prometheus-compatible metrics endpoint** — expose a `/metrics` endpoint from the dashboard server with ticket counts, SLA compliance rates, and queue depth in Prometheus format for monitoring and alerting integration
- **Docker containerization** — package the application with a `Dockerfile` for consistent deployment across environments, with volume mounts for persistent data and environment variables for configuration

## License

MIT
