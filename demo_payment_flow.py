"""
demo_payment_flow.py
Assignment 8: REST API and Networking Lab (the scripted demonstration)
Blockchain module (BLCH9X2), Master of Financial Engineering, University of Johannesburg

WHAT THIS PROGRAM DOES
    Starts three nodes on this computer (ports 5000, 5001 and 5002), then drives them
    through their API (Application Programming Interface) exactly as any outside client
    would, printing every request and every reply.

        Section 1  a full payment on one node: fund, pay, mine, confirm, and three refusals
        Section 2  the explorer view of that node
        Section 3  three nodes: peer discovery, catching up, and a payment and a block
                   spreading by gossip, with the merged message log
        Section 4  self-checks, ending in a count of checks passed

HOW TO RUN
    python demo_payment_flow.py                    the full demonstration, a few seconds
    python demo_payment_flow.py --hold             keep the nodes running afterwards, so
                                                   http://127.0.0.1:5000/explorer can be opened
    python demo_payment_flow.py --base-port 5100   use ports 5100 to 5102 instead

    The program also writes everything it prints to sample_outputs.txt.

REPRODUCIBILITY
    Every hash, nonce, txid and balance printed is identical on any machine. Only the
    "seconds" value in the two mining replies differs.
"""

import argparse          # argparse reads options such as --hold from the command line
import contextlib        # contextlib lets us send print() output through our own object for a while
import json              # json prints replies in an indented, readable form
import sys               # sys.stdout is the screen that print() normally writes to

from api import start_background_node, stop_background_nodes   # start and stop nodes inside this program
from explorer import fetch_snapshot, render_text               # the explorer's reader and its text view
from network import call_node                                  # sends one request to a node

CHECKS = []                            # every self-check is recorded here as (description, passed)
OUTPUT_FILE = "sample_outputs.txt"     # the file that receives a copy of everything printed

# ===========================================================================
# PRINTING HELPERS
# ===========================================================================

class Tee:
    """Passes printed text on to the screen while also keeping a copy, like a T-shaped pipe."""

    def __init__(self, screen):
        """Remember the screen and start with an empty copy."""
        self.screen = screen          # where the text should still appear
        self.copy = []                # every piece of text printed so far

    def write(self, text: str) -> int:
        """Called by print() for each piece of text."""
        self.screen.write(text)       # show the text on the screen as usual
        self.copy.append(text)        # and keep a copy for the output file
        return len(text)              # print() expects to be told how many characters were written

    def flush(self):
        """Called by Python when it wants pending text pushed out."""
        self.screen.flush()           # pass the request on to the screen


def section(title: str):
    """Print a heading for one section of the demonstration."""
    print()                       # a blank line before the heading
    print("=" * 100)              # a rule above
    print(title)                  # the heading itself
    print("=" * 100)              # a rule below


def step(title: str):
    """Print a heading for one step within a section."""
    print()                       # a blank line before the heading
    print("-" * 100)              # a rule above
    print(title)                  # the heading itself
    print("-" * 100)              # a rule below


def call(method: str, address: str, path: str, body=None, show: bool = True) -> tuple:
    """Send one request, print it with its reply, and return (status code, reply)."""
    status, reply = call_node(method, address, path, body)        # the request itself
    if show:                                                      # most calls are printed in full
        print(f"{method} http://{address}{path}")                 # what was asked
        if body is not None:                                      # only POST requests carry a body
            print(f"body: {json.dumps(body)}")                    # the JSON (JavaScript Object Notation) that was sent
        print(f"HTTP {status}")                                   # the status code of the reply
        print(json.dumps(reply, indent=2))                        # the reply, indented for reading
        print()                                                   # a blank line after each exchange
    return status, reply                                          # hand both back so later steps can use them


def check(description: str, passed: bool):
    """Record one self-check for the summary at the end."""
    CHECKS.append((description, bool(passed)))   # store the description with its outcome

# ===========================================================================
# SECTION 1: A FULL PAYMENT ON ONE NODE
# ===========================================================================

def payment_flow(node_a: str):
    """Fund Alice, pay Bob, mine the payment, confirm it, and show three refused requests."""
    section("SECTION 1  A FULL PAYMENT ON ONE NODE (brief items a and b)")   # print the heading for this section

    step("Step 1  The chain at the start holds only the genesis block")   # print the heading for this step
    status, reply = call("GET", node_a, "/chain")                                        # read the full chain
    check("GET /chain returns 200 and a chain of one block", status == 200 and reply["length"] == 1)   # genesis only

    step("Step 2  Alice mines block 1, so the block reward gives her funds to send")   # print the heading for this step
    status, reply = call("POST", node_a, "/mine", {"miner": "alice"})                    # mine with Alice as the miner
    check("POST /mine returns 201 and block 1", status == 201 and reply["block"]["index"] == 1)   # the first mined block

    step("Step 3  Alice's balance is now the block subsidy of 50")   # print the heading for this step
    status, reply = call("GET", node_a, "/balance/alice")                                # read Alice's balance
    check("Alice holds 50 after mining", reply["confirmed"] == 50)                       # the subsidy, with no fees yet

    step("Step 4  Alice submits a payment of 20 to Bob")   # print the heading for this step
    payment = {"sender": "alice", "receiver": "bob", "amount": 20, "reference": "remittance-001"}   # the payment instruction
    status, reply = call("POST", node_a, "/transactions/new", payment)                   # submit it
    txid = reply["transaction"]["txid"]                                                  # keep the identifier for later steps
    check("POST /transactions/new returns 201 and a txid", status == 201 and len(txid) == 64)   # accepted into the pool

    step("Step 5  The payment is pending: it is in the pool, and Alice's funds are reserved")   # print the heading for this step
    status, reply = call("GET", node_a, "/transactions/pending")                         # read the pending pool
    check("the pending pool holds exactly that payment", reply["count"] == 1 and reply["transactions"][0]["txid"] == txid)   # one payment waiting
    status, reply = call("GET", node_a, "/balance/alice")                                # read Alice's balance again
    check("Alice has 21 reserved (amount 20 plus fee 1) and 29 available", reply["pending_out"] == 21 and reply["available"] == 29)   # reserved but not yet moved

    step("Step 6  A miner mines block 2, which includes the pending payment")   # print the heading for this step
    status, reply = call("POST", node_a, "/mine", {"miner": "miner-a"})                  # mine with a separate miner address
    mined_txids = [transaction["txid"] for transaction in reply["block"]["transactions"]]   # every identifier in the new block
    check("block 2 contains the payment", reply["block"]["index"] == 2 and txid in mined_txids)   # the payment was mined

    step("Step 7  The payment is confirmed, with one confirmation")   # print the heading for this step
    status, reply = call("GET", node_a, f"/transactions/{txid}")                         # look the payment up by identifier
    check("the payment is confirmed in block 2", reply["status"] == "confirmed" and reply["block_index"] == 2 and reply["confirmations"] == 1)   # final status

    step("Step 8  Final balances: Alice 29, Bob 20, the miner 51 (subsidy 50 plus the fee of 1)")   # print the heading for this step
    balances = {}                                                                        # collect the three balances
    for name in ("alice", "bob", "miner-a"):                                             # ask for each address in turn
        status, reply = call("GET", node_a, f"/balance/{name}")                          # read one balance
        balances[name] = reply["confirmed"]                                              # keep the confirmed figure
    check("balances are Alice 29, Bob 20, miner 51", balances == {"alice": 29, "bob": 20, "miner-a": 51})   # value moved correctly
    check("total balances equal total subsidy (2 blocks x 50)", sum(balances.values()) == 100)   # nothing was created or lost

    step("Step 9  Three requests the node refuses")   # print the heading for this step
    print("(a) The same payment sent again: same txid, so it cannot pay twice\n")       # explain the first refusal
    status, reply = call("POST", node_a, "/transactions/new", payment)                   # resubmit the identical payment
    check("a repeated payment is refused with 409", status == 409)                       # conflict
    print("(b) A payment larger than the sender's available balance\n")                 # explain the second refusal
    status, reply = call("POST", node_a, "/transactions/new", {"sender": "alice", "receiver": "bob", "amount": 500})   # Alice only has 29
    check("an unaffordable payment is refused with 422", status == 422)                  # cannot be processed
    print("(c) A malformed payment: the amount is not a whole number\n")                # explain the third refusal
    status, reply = call("POST", node_a, "/transactions/new", {"sender": "alice", "receiver": "bob", "amount": 2.5})   # decimals are not allowed
    check("a malformed payment is refused with 400", status == 400)                      # bad request
    status, reply = call("GET", node_a, "/transactions/pending", show=False)             # read the pool without printing
    check("no refused payment entered the pending pool", reply["count"] == 0)            # the pool is still empty
    return txid                                                                          # later sections refer to this payment

# ===========================================================================
# SECTION 2: THE EXPLORER
# ===========================================================================

def explorer_view(address: str, title: str):
    """Print the explorer's text view of one node."""
    section(title)                                       # the heading for this view
    print()                                              # a blank line before the report
    print(render_text(fetch_snapshot(address)))          # read the node through its API and print the text view

# ===========================================================================
# SECTION 3: THREE NODES
# ===========================================================================

def print_log(nodes: list, after: int, title: str) -> int:
    """Print the gossip messages of all nodes in the order they happened. Return the last sequence number shown."""
    events = []                                                          # the entries of every node, to be merged
    for address in nodes:                                                # read each node's log
        status, reply = call("GET", address, "/log", show=False)         # GET /log, without printing the raw reply
        events.extend(reply["events"])                                   # add its entries to the merged list
    events = sorted((entry for entry in events if entry["seq"] > after), key=lambda entry: entry["seq"])   # keep the new ones, in order
    print(title)                                                         # a title for this slice of the log
    print("  seq  node   event")                                         # column headings
    for entry in events:                                                 # one line per message
        print(f"  {entry['seq']:>3}  :{entry['node'].rsplit(':', 1)[-1]}  {entry['event']}")   # number, port and description
    print()                                                              # a blank line after the log
    return events[-1]["seq"] if events else after                        # where the next slice should start


def network_flow(node_a: str, node_b: str, node_c: str, first_txid: str):
    """Join three nodes into one network, then watch a payment and a block spread by gossip."""
    section("SECTION 3  THREE NODES: PEER DISCOVERY AND GOSSIP (Part B)")   # print the heading for this section
    nodes = [node_a, node_b, node_c]                                     # the three nodes, in port order
    status, reply = call("GET", node_a, "/log", show=False)              # read node A's log so far
    last_seen = reply["events"][-1]["seq"]                               # only messages after this point belong to this section

    step("Step 10  Node A is told about node B, and introduces itself to B")   # print the heading for this step
    status, reply = call("POST", node_a, "/nodes/register", {"nodes": [f"http://{node_b}"]})   # register B at A
    check("POST /nodes/register returns 201", status == 201 and reply["added"] == [node_b])   # one peer added

    step("Step 11  Node C joins knowing only node A, and learns about B through relayed addresses")   # print the heading for this step
    status, reply = call("POST", node_c, "/nodes/register", {"nodes": [f"http://{node_a}"]})   # C is given one seed only
    check("C learned B without being told directly", reply["nodes"] == [node_a, node_b])   # address relay worked
    for address in nodes:                                                # show each node's peer list
        status, reply = call("GET", address, "/nodes")                   # GET /nodes
        check(f"node {address} lists the other two nodes", reply["count"] == 2)   # a full mesh of three
    last_seen = print_log(nodes, last_seen, "Address messages, merged from GET /log of all three nodes:")   # the addr relay trace

    step("Step 12  Nodes B and C still hold only genesis, so they catch up from their peers")   # print the heading for this step
    for address in (node_b, node_c):                                     # the two late joiners
        status, reply = call("GET", address, "/nodes/resolve")           # adopt the longest valid chain
        check(f"node {address} adopted the 3 block chain", reply["replaced"] and reply["length"] == 3)   # now level with A
    status, reply = call("GET", node_c, f"/transactions/{first_txid}", show=False)   # look for Alice's payment on node C
    check("node C now sees Alice's payment as confirmed", status == 200 and reply["status"] == "confirmed")   # history was copied
    last_seen = print_log(nodes, last_seen, "Synchronisation messages:")  # the catch-up trace

    step("Step 13  Bob pays Carol through node C, and the payment reaches A and B by inv and getdata")   # print the heading for this step
    payment = {"sender": "bob", "receiver": "carol", "amount": 5, "reference": "school-fees"}   # the second payment
    status, reply = call("POST", node_c, "/transactions/new", payment)   # submitted at node C only
    second_txid = reply["transaction"]["txid"]                           # keep its identifier
    for address in (node_a, node_b):                                     # the two nodes that were NOT told by the client
        status, reply = call("GET", address, "/transactions/pending", show=False)   # read each pending pool
        check(f"node {address} received the payment by gossip", reply["count"] == 1 and reply["transactions"][0]["txid"] == second_txid)   # it arrived
    last_seen = print_log(nodes, last_seen, "Transaction gossip:")       # the inv and getdata trace for the payment

    step("Step 14  Node B mines block 3, and the block reaches A and C by inv and getdata")   # print the heading for this step
    status, reply = call("POST", node_b, "/mine", {"miner": "miner-b"})  # mined at node B, which never saw the client
    block_hash = reply["block"]["hash"]                                  # the hash every node should now end on
    last_seen = print_log(nodes, last_seen, "Block gossip:")             # the inv and getdata trace for the block

    step("Step 15  All three nodes agree")   # print the heading for this step
    print("  node             length  newest block hash                                                 pending")   # column headings
    for address in nodes:                                                # compare the three nodes
        status, reply = call("GET", address, "/chain", show=False)       # read each chain
        status, pool = call("GET", address, "/transactions/pending", show=False)   # and each pending pool
        newest = reply["chain"][-1]["hash"]                              # the hash of the node's newest block
        print(f"  {address}  {reply['length']:>6}  {newest}  {pool['count']:>7}")   # one line per node
        check(f"node {address} ends on block 3 with an empty pool", reply["length"] == 4 and newest == block_hash and pool["count"] == 0)   # agreement
    status, reply = call("GET", node_a, "/balance/carol", show=False)    # Carol's balance, read from a node she never used
    print(f"\n  Carol's confirmed balance on node A: {reply['confirmed']}")   # show it
    check("Carol holds 5 on node A", reply["confirmed"] == 5)            # the payment settled network-wide

# ===========================================================================
# RUNNING THE DEMONSTRATION
# ===========================================================================

def main():
    """Start three nodes, run every section, save the output and report the self-checks."""
    parser = argparse.ArgumentParser(description="Demonstrate a full payment flow across three local nodes.")   # describes the program for --help
    parser.add_argument("--base-port", type=int, default=5000, help="first of three consecutive ports (default 5000)")   # where the nodes listen
    parser.add_argument("--hold", action="store_true", help="keep the nodes running until Enter is pressed")   # for viewing /explorer in a browser
    arguments = parser.parse_args()                                      # read what was typed
    ports = [arguments.base_port + offset for offset in range(3)]        # three consecutive ports
    addresses = [f"127.0.0.1:{port}" for port in ports]                  # the address of each node
    tee = Tee(sys.stdout)                                                # everything printed goes to the screen and into a copy
    try:                                                                 # make sure the nodes are stopped even if a step fails
        for port in ports:                                               # start the three nodes
            start_background_node(port)                                  # each begins with only the genesis block
        with contextlib.redirect_stdout(tee):                            # from here on, print() writes through the tee
            print("BLCH9X2 Assignment 8: REST API and Networking Lab")   # a title for the output
            print(f"Three nodes started: {', '.join('http://' + address for address in addresses)}")   # where they are
            first_txid = payment_flow(addresses[0])                      # section 1
            explorer_view(addresses[0], "SECTION 2  EXPLORER VIEW OF NODE A AFTER THE PAYMENT (brief item c)")   # section 2
            network_flow(addresses[0], addresses[1], addresses[2], first_txid)   # section 3
            explorer_view(addresses[2], "EXPLORER VIEW OF NODE C AFTER THE NETWORK STEPS")   # the explorer again, from another node
            section("SECTION 4  SELF-CHECKS")                            # print the heading for this section
            print()                                                      # a blank line before the list
            for description, passed in CHECKS:                           # list every check
                print(f"  [{'PASS' if passed else 'FAIL'}] {description}")   # with its outcome
            passed_count = sum(1 for _, passed in CHECKS if passed)      # how many passed
            print(f"\n{passed_count} passed, {len(CHECKS) - passed_count} failed")   # the final count
        with open(OUTPUT_FILE, "w", encoding="utf-8") as output_file:    # open the output file for writing
            output_file.write("".join(tee.copy))                         # write the copy of everything printed
        print(f"\nThis output was also written to {OUTPUT_FILE}")        # say where the copy went
        if arguments.hold:                                               # keep serving if asked to
            print(f"\nThe nodes are still running. Open http://{addresses[0]}/explorer in a browser.")   # where to look
            input("Press Enter to stop them. ")                          # wait for the Enter key
    finally:                                                             # this runs whether or not an error occurred
        stop_background_nodes()                                          # stop the nodes and free the ports


if __name__ == "__main__":      # True only when this file is run directly, not when it is imported
    main()                      # run the demonstration
