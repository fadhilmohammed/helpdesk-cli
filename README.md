# helpdesk-cli

A command-line tool for managing IT support tickets. Think of it like a simplified version of ServiceNow or WebTMA that runs entirely in your terminal. You can create tickets, assign them to teams, track whether they're being resolved fast enough, and generate reports showing how your help desk is performing.

The whole thing runs on Python's standard library. No packages to install, no database to set up, no server to configure. Just clone it and run it.

## Why I Built This

I work as a campus support intern where I use ticketing systems every day to log and track work orders. I wanted to understand how these systems actually work under the hood, so I built one from scratch. The categories I used (hardware, software, network, AV equipment, accounts) are the same ones I'd triage in a real IT support role.

## What It Can Do

**The basics** work like any ticketing system. You create a ticket, give it a title and description, pick a category and priority, and the tool saves it to a local JSON file. You can list all your tickets, view one in detail, update its status, search with filters, or delete it.

**Templates** save you time on repeat issues. Instead of typing out the same printer problem description every week, you pick the "printer" template and just fill in the blanks (model, location, what's wrong). There are five built-in templates and you can add your own.

**Auto-assignment** routes tickets to the right team automatically. When you create a hardware ticket, it gets assigned to "Hardware Team." Network tickets go to "Network Admin." These rules live in a simple JSON config file you can edit.

**SLA tracking** tells you if tickets are being handled fast enough. Each priority level has a time limit: critical tickets need attention within 4 hours, high within 8, medium within 24, low within 72. The tool checks every ticket against these thresholds and flags anything that's overdue or getting close.

**Audit history** logs every change. When a ticket is created, updated, reassigned, or closed, the tool records what changed, what the old value was, and when it happened. You can see the full timeline by viewing any ticket.

**Reports** give you the big picture. Run the report command and you get a summary showing total tickets, how many are open or closed, average resolution time, SLA compliance percentage, and which categories are generating the most work. It prints to the terminal and also saves a clean markdown file you could paste into an email or a wiki.

**CSV export** lets you pull your data into Excel or Google Sheets for further analysis.

**Recurring tickets** handle scheduled maintenance. If you need to check projector bulbs every 30 days, set it up once and the tool creates a new ticket automatically when it's due. You can pause, resume, or delete recurring definitions anytime.

**Email notifications** are generated as .eml files whenever a ticket is created, updated, or breaches its SLA. The tool doesn't actually send emails (there's no mail server), but it builds properly formatted MIME messages that demonstrate the notification pipeline.

**Web dashboard** gives you a browser-based view of everything. Run `python helpdesk.py dashboard` and open localhost:8080. You'll see summary stats at the top, a filterable ticket table, and a bar chart showing tickets by category. It refreshes every 30 seconds.

**Interactive mode** turns your terminal into a live dashboard. It shows your ticket stats and a table of recent tickets, and you navigate with single-key commands: C to create, U to update, S to search, R to run a report, Q to quit.

All of the terminal output is color-coded. Critical and overdue items show up in red, warnings in yellow, resolved tickets in green. If your terminal doesn't support colors or you're piping output to a file, use the `--no-color` flag.

## Getting Started

You need Python 3.9 or newer. That's it.

```bash
git clone https://github.com/fadhilmohammed/helpdesk-cli.git
cd helpdesk-cli
python helpdesk.py --help
```

No pip install, no virtual environment, no setup script.

## Quick Examples

Create a ticket:

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

Create one from a template (fills in the category and priority for you):

```
$ python helpdesk.py create --template printer

Title: Broken printer in lobby

  Printer model: HP LaserJet Pro
  Location: Main lobby, 1st floor
  Issue: Paper jam every 5 pages

Ticket created successfully.
  ID:       e5f6a7b8
  Assigned: Hardware Team
```

List all tickets:

```
$ python helpdesk.py list

ID         TITLE                          CATEGORY       PRIORITY   STATUS        CREATED
a1b2c3d4   Printer jam on 3rd floor       hardware       high       open          2026-04-13 18:30 UTC
e5f6a7b8   VPN disconnects randomly       network        critical   open          2026-04-13 17:15 UTC
c9d0e1f2   Outlook not syncing            software       medium     in-progress   2026-04-13 16:00 UTC
```

Search with filters (they stack, so you can combine them):

```
$ python helpdesk.py search --priority high --status open
$ python helpdesk.py search --keyword vpn
$ python helpdesk.py search --category network --priority critical
```

Check SLA status:

```
$ python helpdesk.py sla

ID         TITLE                          PRIORITY   SLA        ELAPSED
8b4b1b08   Laptop won't boot              critical   breached   6.0h / 4h
076ee257   Conference room B audio        high       breached   15.0h / 8h
```

Run a report:

```
$ python helpdesk.py report

  HELP DESK SUMMARY REPORT  (2026-04-14)

  Total tickets: 10

  Tickets by Status:
    open             4  ####
    in-progress      1  #
    resolved         2  ##
    closed           3  ###

  Avg resolution time: 5h 12m
  SLA compliance:      80% (4/5)

  Report saved to report_2026-04-14.md
```

Export to CSV:

```
$ python helpdesk.py export
Exported 10 ticket(s) to tickets_export.csv
```

Set up a recurring ticket:

```
$ python helpdesk.py recurring --add     # walks you through it
$ python helpdesk.py recurring --run     # creates any tickets that are due
$ python helpdesk.py recurring           # shows all recurring definitions
```

Launch the web dashboard:

```
$ python helpdesk.py dashboard
Dashboard running at http://127.0.0.1:8080 — press Ctrl+C to stop
```

Launch interactive terminal mode:

```
$ python helpdesk.py interactive
```

## All Commands

| Command | What it does |
|---------|-------------|
| `create` | Make a new ticket (add `--template name` to use a template) |
| `list` | Show all tickets in a table |
| `view <id>` | See full details and history for one ticket |
| `update <id>` | Change a ticket's status, priority, or category |
| `delete <id>` | Remove a ticket (asks for confirmation) |
| `search` | Find tickets by category, priority, status, or keyword |
| `report` | Generate a summary with stats and save a markdown file |
| `sla` | Show tickets that are overdue or at risk |
| `export` | Save all tickets to a CSV file |
| `templates` | List available templates (add `--add` to make a new one) |
| `recurring` | Manage scheduled tickets (`--add`, `--run`, `--pause`, `--resume`, `--delete`) |
| `notifications` | List generated email notification files |
| `dashboard` | Open a web dashboard in your browser |
| `interactive` | Launch full-screen terminal mode |

Add `--no-color` before any command to disable colored output. Add `--file path.json` to use a different data file.

## How It Works

All your ticket data lives in a single `tickets.json` file. When you create or update a ticket, the tool reads the file, makes the change, and writes it back. There's no database, no server running in the background, no complicated setup.

I chose JSON over SQLite because you can open the file and actually read your data. It's just formatted text. You can copy one file to back up your entire ticket history, or email it to someone, or put it in version control.

The trade-off is that this approach reads and writes the whole file on every operation. For a personal tool or a small team handling hundreds of tickets, that's totally fine. If you needed thousands of concurrent users, you'd swap in SQLite (which is also in the standard library, so it would still require zero external packages).

Templates and assignment rules are stored in their own JSON files (`templates.json` and `assignment_rules.json`). You can edit these by hand or use the built-in commands.

The web dashboard works by starting a tiny HTTP server using Python's built-in `http.server` module. It generates the entire HTML page on the fly from your ticket data. No frontend framework, no npm, no build step.

Email notifications are built using Python's `email.mime` module, which creates properly structured MIME messages. They're saved as `.eml` files that you can open in any email client to see what they'd look like if they were actually sent.

## Project Files

```
helpdesk-cli/
  helpdesk.py            # all the code (single file)
  templates.json         # predefined ticket templates
  assignment_rules.json  # which team gets which category
  tickets.json           # your ticket data (created when you make your first ticket)
  recurring.json         # recurring ticket schedules (created when you add one)
  notifications/         # generated .eml files (created automatically)
  report_*.md            # generated reports
```

## Ticket Fields

Every ticket has these fields:

| Field | What it is |
|-------|-----------|
| id | An auto-generated 8-character code (like `a1b2c3d4`) |
| title | A short summary of the issue |
| description | The full details of what's wrong |
| category | One of: hardware, software, network, av-equipment, account, other |
| priority | One of: low, medium, high, critical |
| status | One of: open, in-progress, resolved, closed |
| assigned_to | The team or person assigned (auto-filled based on category) |
| created_at | When the ticket was created |
| updated_at | When it was last changed |
| history | A log of every change that's been made |

## What I'd Build Next

If I were to keep developing this, here's where I'd go:

Replacing the JSON file with SQLite would let multiple people use the tool at the same time without stepping on each other's data. SQLite is already in Python's standard library, so it wouldn't add any dependencies.

Adding a REST API using Python's built-in HTTP server would let other tools create and update tickets over the network instead of only through the command line.

Connecting to a real SMTP server would let the tool actually send the email notifications it currently generates as files.

Adding webhook support for Slack or Teams would let the tool post alerts to a chat channel when a ticket is created or breaches its SLA.

Building a kanban board view in the web dashboard would give you a drag-and-drop interface for moving tickets between columns.

## Built With

Python 3.9+ standard library only. No external packages.

The specific modules used: `argparse` for the CLI, `dataclasses` for the data model, `json` for storage, `csv` for exports, `http.server` for the web dashboard, `email.mime` for notifications, `uuid` for ticket IDs, `datetime` for timestamps and SLA math, and ANSI escape codes for terminal colors.

## License

MIT
