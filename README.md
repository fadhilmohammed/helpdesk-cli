# Help Desk Ticket Logger

A lightweight command-line help desk ticket manager built for IT support teams. Create, track, search, and report on support tickets entirely from the terminal — no database, no server, no external dependencies.

Designed to mirror the core workflows of enterprise ticketing systems like WebTMA and ServiceNow: logging issues, categorizing and prioritizing them, updating their status as work progresses, and generating summary reports for oversight.

## Features

- **Create tickets** interactively with guided prompts
- **List all tickets** in a formatted, color-coded table
- **View** full details of any ticket by ID
- **Update** status, priority, or category on existing tickets
- **Delete** tickets with a confirmation safeguard
- **Search** with filters for category, priority, status, and keyword (AND-combined)
- **Generate reports** with breakdowns by status, category, priority, and recent activity
- **Colored output** with ANSI codes (disable with `--no-color` or the `NO_COLOR` env var)

## Installation

No package manager needed. Clone the repository and run directly:

```bash
git clone https://github.com/<your-username>/helpdesk-ticket-logger.git
cd helpdesk-ticket-logger
python helpdesk.py --help
```

Requires **Python 3.9+**. No `pip install`, no virtual environment, no setup.

## Usage

```
python helpdesk.py <command> [options]
```

### Global Options

| Flag         | Description                                      |
|--------------|--------------------------------------------------|
| `--file`     | Path to a custom tickets JSON file               |
| `--no-color` | Disable colored terminal output                  |

### Create a ticket

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
  Status:   open
  Created:  2026-04-13 18:30 UTC
```

### List all tickets

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

### View a single ticket

```
$ python helpdesk.py view a1b2c3d4

========================================
  Ticket:      a1b2c3d4
========================================
  Title:       Printer jam on 3rd floor
  Description: HP LaserJet in room 310 has recurring paper jams
  Category:    hardware
  Priority:    high
  Status:      open
  Created:     2026-04-13 18:30 UTC
  Updated:     2026-04-13 18:30 UTC
========================================
```

### Update a ticket

```
$ python helpdesk.py update a1b2c3d4

=== Update Ticket a1b2c3d4 ===
  Current title:    Printer jam on 3rd floor
  Current status:   open
  Current priority: high
  Current category: hardware

Press Enter to keep the current value.

New status [open, in-progress, resolved, closed] (current: open): in-progress
New priority [low, medium, high, critical] (current: high):
New category [hardware, software, network, av-equipment, account, other] (current: hardware):

Ticket a1b2c3d4 updated successfully.
```

### Search tickets

Filters are AND-combined. All flags are optional.

```
$ python helpdesk.py search --priority high --status open

----------------------------------------------------------------------------------------------------
ID         TITLE                          CATEGORY       PRIORITY   STATUS        CREATED
----------------------------------------------------------------------------------------------------
a1b2c3d4   Printer jam on 3rd floor       hardware       high       open          2026-04-13 18:30 UTC
----------------------------------------------------------------------------------------------------
Matched: 1 ticket(s)
```

```
$ python helpdesk.py search --keyword vpn

----------------------------------------------------------------------------------------------------
ID         TITLE                          CATEGORY       PRIORITY   STATUS        CREATED
----------------------------------------------------------------------------------------------------
e5f6a7b8   VPN disconnects randomly       network        critical   open          2026-04-13 17:15 UTC
----------------------------------------------------------------------------------------------------
Matched: 1 ticket(s)
```

### Generate a summary report

```
$ python helpdesk.py report

==================================================
  HELP DESK SUMMARY REPORT
==================================================
  Total tickets: 5

  Tickets by Status:
    open             3  ###
    in-progress      1  #
    resolved         1  #
    closed           0

  Tickets by Category:
    hardware          2  ##
    software          1  #
    network           1  #
    av-equipment      1  #
    account           0
    other             0

  Tickets by Priority:
    low           1  #
    medium        1  #
    high          2  ##
    critical      1  #

  3 Most Recent Tickets:
    [a1b2c3d4] Printer jam on 3rd floor
      open | high | 2026-04-13 18:30 UTC
    [e5f6a7b8] VPN disconnects randomly
      open | critical | 2026-04-13 17:15 UTC
    [c9d0e1f2] Outlook not syncing
      in-progress | medium | 2026-04-13 16:00 UTC
==================================================
```

### Delete a ticket

```
$ python helpdesk.py delete a1b2c3d4

About to delete ticket:
  ID:    a1b2c3d4
  Title: Printer jam on 3rd floor
Are you sure? (y/N): y
Ticket a1b2c3d4 deleted.
```

## Data Storage

All tickets are persisted to a local `tickets.json` file. The file is created automatically on the first `create` command. Each ticket is stored as a JSON object:

```json
{
  "id": "a1b2c3d4",
  "title": "Printer jam on 3rd floor",
  "description": "HP LaserJet in room 310 has recurring paper jams",
  "category": "hardware",
  "priority": "high",
  "status": "open",
  "created_at": "2026-04-13T18:30:00+00:00",
  "updated_at": "2026-04-13T18:30:00+00:00"
}
```

## Ticket Schema

| Field       | Type   | Values                                                    |
|-------------|--------|-----------------------------------------------------------|
| id          | string | Auto-generated 8-character hex ID                         |
| title       | string | Short summary of the issue                                |
| description | string | Detailed problem description                              |
| category    | enum   | hardware, software, network, av-equipment, account, other |
| priority    | enum   | low, medium, high, critical                               |
| status      | enum   | open, in-progress, resolved, closed                       |
| created_at  | string | ISO 8601 UTC timestamp                                    |
| updated_at  | string | ISO 8601 UTC timestamp                                    |

## Tech Stack

| Component      | Technology                                |
|----------------|-------------------------------------------|
| Language        | Python 3.9+                              |
| CLI framework   | `argparse` (stdlib)                      |
| Data model      | `dataclasses` (stdlib)                   |
| Storage         | JSON via `json` (stdlib)                 |
| ID generation   | `uuid` (stdlib)                          |
| Timestamps      | `datetime` (stdlib)                      |
| Terminal color   | ANSI escape codes (no dependencies)     |
| External deps   | **None** — 100% standard library        |

## License

MIT
