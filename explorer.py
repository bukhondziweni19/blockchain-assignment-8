"""
explorer.py
Assignment 8: REST API and Networking Lab (the block explorer)
Blockchain module (BLCH9X2), Master of Financial Engineering, University of Johannesburg

WHAT THIS PROGRAM DOES
    Shows what a node holds, in the way a public block explorer does: a summary of the
    node, its recent blocks, its recent transactions, its pending payments and the
    balance of every address. The same information is produced in two forms:

        render_text   a plain text report for the terminal
        render_html   a HyperText Markup Language (HTML) page, served by the node itself
                      at /explorer and also written to a file with --html

    Run from the command line, this program is a client of the API (Application
    Programming Interface) in api.py: it only reads GET /chain,
    GET /transactions/pending and GET /nodes, so it sees exactly what any other
    client of the node would see.

HOW TO RUN (a node must already be running, see api.py)
    python explorer.py                                 the node on port 5000
    python explorer.py --node http://127.0.0.1:5001    a different node
    python explorer.py --last 10                       show up to 10 rows per table
    python explorer.py --html explorer.html            also save the page to a file
"""

import argparse                              # argparse reads options such as --node from the command line
import html                                  # html.escape makes text safe to place inside a web page
from datetime import datetime, timezone      # used to turn a Unix timestamp into a readable date and time

from blockchain import apply_transaction     # the same balance arithmetic the nodes use
from network import call_node, normalise_address   # the request helper and the local-address check

# ===========================================================================
# CONFIGURATION
# ===========================================================================

DEFAULT_NODE = "http://127.0.0.1:5000"   # the node the explorer reads unless told otherwise
DEFAULT_ROWS = 5                         # how many recent blocks and transactions to list
HASH_CHARACTERS = 16                     # how much of each 64 character hash to display

# ===========================================================================
# READING A NODE THROUGH ITS API
# ===========================================================================

def fetch_snapshot(node_url: str = DEFAULT_NODE):
    """Read a node over HTTP (HyperText Transfer Protocol). Return a snapshot, or None if it cannot be reached."""
    address = normalise_address(node_url)                                  # convert the address to the agreed spelling
    if address is None:                                                    # the explorer only reads nodes on this computer
        return None                                                        # an unusable address gives no snapshot
    chain_status, chain_reply = call_node("GET", address, "/chain")        # the blocks
    pending_status, pending_reply = call_node("GET", address, "/transactions/pending")   # the pending payments
    nodes_status, nodes_reply = call_node("GET", address, "/nodes")        # the peers
    if (chain_status, pending_status, nodes_status) != (200, 200, 200):    # all three requests must succeed
        return None                                                        # otherwise there is nothing reliable to show
    return {                                                               # the same shape that Node.snapshot() produces
        "node": address,                                                   # which node was read
        "difficulty": chain_reply["difficulty"],                           # its mining rule
        "chain": chain_reply["chain"],                                     # its blocks
        "pending": pending_reply["transactions"],                          # its pending payments
        "nodes": nodes_reply["nodes"],                                     # its peers
    }

# ===========================================================================
# TURNING A SNAPSHOT INTO ROWS
# ===========================================================================

def shorten(hash_hex: str) -> str:
    """Show the start of a hash followed by three dots, so tables stay narrow."""
    return hash_hex[:HASH_CHARACTERS] + "..."     # the leading characters are enough to recognise a hash


def format_time(timestamp: int) -> str:
    """Turn a Unix timestamp into a date and time in UTC (Coordinated Universal Time)."""
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)   # interpret the number of seconds as a UTC moment
    return moment.strftime("%Y-%m-%d %H:%M")                      # for example "2026-10-01 00:10"


def transaction_row(place: str, transaction: dict) -> list:
    """Describe one transaction as a list of table cells."""
    return [                                                      # one cell per column
        place,                                                    # the block number, or the word "pending"
        transaction["type"],                                      # "coinbase" or "payment"
        transaction["sender"] or "(new coins)",                   # a coinbase has no sender, so say where the value came from
        transaction["receiver"],                                  # who was paid
        f"{transaction['amount']:,}",                             # the amount, with thousands separators
        str(transaction["fee"]),                                  # the fee paid to the miner
        transaction["reference"],                                 # the payer's reference
        shorten(transaction["txid"]),                             # the start of the identifier
    ]


def build_view(snapshot: dict, last: int = DEFAULT_ROWS) -> tuple:
    """Reduce a snapshot to the summary facts and the tables that both views display."""
    chain, pending, peers = snapshot["chain"], snapshot["pending"], snapshot["nodes"]   # the three things a node holds
    facts = [                                                                  # the summary shown at the top
        ("Node", snapshot["node"]),                                            # which node this is
        ("Chain height", f"{len(chain) - 1} ({len(chain)} blocks including genesis)"),   # height counts from zero
        ("Difficulty", f"{snapshot['difficulty']} leading zeros"),             # the mining rule
        ("Pending payments", str(len(pending))),                               # how many payments are waiting
        ("Peers", ", ".join(peers) if peers else "none"),                      # the peers, or the word "none"
    ]
    block_rows = [                                                             # one row per recent block
        [                                                                      # one cell per column
            str(block["index"]),                                               # position in the chain
            format_time(block["timestamp"]),                                   # time on the logical clock
            str(len(block["transactions"])),                                   # how many transactions it holds
            f"{block['nonce']:,}",                                             # the nonce the miner found
            shorten(block["hash"]),                                            # the start of its hash
            shorten(block["previous_hash"]),                                   # the start of its parent's hash
        ]
        for block in reversed(chain[-last:])                                   # the last few blocks, newest first
    ]
    mined = [(block["index"], transaction)                                     # pair every mined transaction with its block number
             for block in chain                                                # walking the chain from genesis
             for transaction in block["transactions"]]                         # and every transaction inside each block
    transaction_rows = [transaction_row(str(index), transaction)               # one row per recent transaction
                        for index, transaction in reversed(mined[-last:])]     # the last few, newest first
    pending_rows = [transaction_row("pending", payment) for payment in pending]   # one row per waiting payment
    balances = {}                                                              # work out every balance from the chain
    for _, transaction in mined:                                               # replay every mined transaction
        apply_transaction(balances, transaction)                               # move its value
    balance_rows = [[address, f"{value:,}"] for address, value in sorted(balances.items())]   # one row per address, in name order
    transaction_headers = ["Block", "Type", "From", "To", "Amount", "Fee", "Reference", "Txid"]   # shared by two tables
    sections = [                                                               # each table: a title, column headings and rows
        (f"RECENT BLOCKS (newest first, {len(block_rows)} of {len(chain)})",   # the title says how many are shown
         ["Index", "Time (UTC)", "Txs", "Nonce", "Hash", "Previous hash"], block_rows),   # headings, then the rows
        (f"RECENT TRANSACTIONS (newest first, {len(transaction_rows)} of {len(mined)})",   # the title says how many are shown
         transaction_headers, transaction_rows),                               # headings, then the rows
        (f"PENDING PAYMENTS ({len(pending_rows)})", transaction_headers, pending_rows),   # the waiting payments
        ("CONFIRMED BALANCES", ["Address", "Balance"], balance_rows),          # what each address holds
    ]
    return facts, sections                                                     # everything the two views need

# ===========================================================================
# THE TEXT VIEW
# ===========================================================================

def render_text(snapshot: dict, last: int = DEFAULT_ROWS) -> str:
    """Return the explorer as plain text for the terminal."""
    facts, sections = build_view(snapshot, last)                               # the facts and tables to display
    lines = ["=" * 100, f"BLOCK EXPLORER  node {snapshot['node']}", "=" * 100]   # a heading between two rules
    for name, value in facts:                                                  # the summary, one fact per line
        lines.append(f"{name:<17}: {value}")                                   # "<17" pads the name so the colons line up
    for title, headers, rows in sections:                                      # then each table in turn
        lines.append("")                                                       # a blank line before the table
        lines.append(title)                                                    # the table's title
        if not rows:                                                           # an empty table is shown as one word
            lines.append("  (none)")                                           # so the reader knows nothing is missing
            continue                                                           # move on to the next table
        widths = [max(len(row[column]) for row in [headers] + rows)            # each column is as wide as its longest cell
                  for column in range(len(headers))]                           # worked out column by column
        for row in [headers] + rows:                                           # print the headings, then every row
            cells = [cell.ljust(width) for cell, width in zip(row, widths)]    # pad each cell to its column width
            lines.append("  " + "  ".join(cells).rstrip())                     # join the cells with two spaces between columns
    return "\n".join(lines)                                                    # one string with a line break between lines

# ===========================================================================
# THE WEB PAGE VIEW
# ===========================================================================

# The styling rules for the page, written in CSS (Cascading Style Sheets). The page is black on white only,
# and every rule starts with .bx so the styling cannot leak into a surrounding page such as a notebook.
# "!important" keeps the table looking the same when a notebook applies its own table styling.
PAGE_STYLE = """
.bx { font-family: Calibri, Arial, sans-serif; color: #000; background: #fff; max-width: 1100px; margin: 0 auto; padding: 16px; }
.bx h1 { font-size: 22px; margin: 0 0 12px 0; }
.bx h2 { font-size: 15px; margin: 22px 0 6px 0; }
.bx table { border-collapse: collapse; width: 100%; font-size: 13px; table-layout: auto !important; margin: 0 !important; }
.bx th, .bx td { border: 1px solid #000 !important; padding: 4px 8px; text-align: left !important; color: #000; background: #fff; }
.bx th { font-weight: bold; }
.bx td.mono { font-family: Consolas, "Courier New", monospace; white-space: nowrap; }
.bx p { font-size: 13px; margin: 4px 0; }
"""


def html_table(headers: list, rows: list) -> str:
    """Return one HTML table. Every cell is escaped, so text from a transaction can never act as page code."""
    if not rows:                                                               # an empty table is shown as one word
        return "<p>(none)</p>"                                                 # so the reader knows nothing is missing
    head = "".join(f"<th>{html.escape(cell)}</th>" for cell in headers)        # the heading cells
    body = ""                                                                  # the rows are added to this text one by one
    for row in rows:                                                           # each row of the table
        cells = ""                                                             # the cells of this row
        for header, cell in zip(headers, row):                                 # each cell together with its column heading
            style = ' class="mono"' if header in ("Hash", "Previous hash", "Txid") else ""   # hashes use a fixed-width font
            cells += f"<td{style}>{html.escape(cell)}</td>"                    # add the escaped cell
        body += f"<tr>{cells}</tr>"                                            # close the row
    return f"<table><tr>{head}</tr>{body}</table>"                             # the finished table


def render_html(snapshot: dict, last: int = DEFAULT_ROWS) -> str:
    """Return the explorer as a self-contained web page."""
    facts, sections = build_view(snapshot, last)                               # the same facts and tables as the text view
    fact_rows = [[name, value] for name, value in facts]                       # the summary becomes a two column table
    parts = [f"<h1>Block explorer, node {html.escape(snapshot['node'])}</h1>"] # the page heading
    parts.append(html_table(["Item", "Value"], fact_rows))                     # the summary table
    for title, headers, rows in sections:                                      # then each table in turn
        parts.append(f"<h2>{html.escape(title)}</h2>")                         # the table's title
        parts.append(html_table(headers, rows))                                # the table itself
    content = "\n".join(parts)                                                 # all the pieces, one per line
    return (                                                                   # wrap the pieces in a complete page
        "<!DOCTYPE html>\n"                                                    # tells the browser this is modern HTML
        '<html lang="en"><head><meta charset="utf-8">\n'                       # the language and the character set
        f"<title>Block explorer {html.escape(snapshot['node'])}</title>\n"     # the text shown on the browser tab
        f"<style>{PAGE_STYLE}</style></head>\n"                                # the styling rules above
        f'<body><div class="bx">\n{content}\n</div></body></html>\n'           # the visible content
    )

# ===========================================================================
# RUNNING THE EXPLORER FROM THE COMMAND LINE
# ===========================================================================

def main():
    """Read a running node and print the explorer."""
    parser = argparse.ArgumentParser(description="Print a block explorer view of a running node.")   # describes the program for --help
    parser.add_argument("--node", default=DEFAULT_NODE, help="address of the node to read (default http://127.0.0.1:5000)")   # which node
    parser.add_argument("--last", type=int, default=DEFAULT_ROWS, help="rows per table (default 5)")   # how much to show
    parser.add_argument("--html", metavar="FILE", help="also save the view as a web page in FILE")     # optional page output
    arguments = parser.parse_args()                                            # read what was typed
    snapshot = fetch_snapshot(arguments.node)                                  # read the node through its API
    if snapshot is None:                                                       # the node did not answer
        raise SystemExit(f"No node answered at {arguments.node}. Start one with: python api.py")   # explain how to fix it
    rows = max(1, arguments.last)                                              # always show at least one row
    print(render_text(snapshot, rows))                                         # the text view
    if arguments.html:                                                         # a page was asked for as well
        with open(arguments.html, "w", encoding="utf-8") as page_file:         # open the file for writing
            page_file.write(render_html(snapshot, rows))                       # write the page
        print(f"\nWeb page written to {arguments.html}")                       # say where it went


if __name__ == "__main__":      # True only when this file is run directly, not when it is imported
    main()                      # print the explorer
