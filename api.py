"""
api.py
Assignment 8: REST API and Networking Lab (the web interface of one node)
Blockchain module (BLCH9X2), Master of Financial Engineering, University of Johannesburg

WHAT THIS PROGRAM DOES
    Wraps one Node (see network.py) in a REST (Representational State Transfer) API
    built with Flask. Each endpoint is a web address that reads or changes the node:

        Required by the brief
            GET  /chain                  the full chain
            POST /transactions/new       submit a payment
            POST /mine                   mine a block holding the pending payments
            GET  /nodes                  this node's peer list
            POST /nodes/register         add peers
        Supporting the payment flow
            GET  /                       a short status report and this list
            GET  /transactions/pending   payments waiting to be mined
            GET  /transactions/<txid>    one transaction and its confirmations
            GET  /balance/<address>      what an address holds and can spend
        Supporting the network (Part B)
            GET  /nodes/resolve          adopt the longest valid chain among the peers
            POST /inv                    "I hold this hash" from a peer
            GET  /getdata/<type>/<hash>  the full transaction or block behind a hash
            GET  /log                    this node's gossip log
        Explorer
            GET  /explorer               a web page listing recent blocks and transactions

    Every reply except /explorer is JSON (JavaScript Object Notation). The exact
    request and reply of every endpoint is documented in README.md.

SAFETY
    The server binds to 127.0.0.1, so it can only be reached from this computer. There
    is no login and payments are not signed, which is acceptable for a local
    demonstration only. Do not change the host to expose it on a network.

HOW TO RUN
    python api.py                 one node on port 5000
    python api.py --port 5001     a second node, in a second terminal
"""

import argparse                      # argparse reads options such as --port from the command line
import logging                       # logging lets us quieten the web server's request log when running in the background
import socket                        # socket lets us test whether a port is already taken
import threading                     # threading lets a node run in the background while other code carries on

from flask import Flask, Response, jsonify, request   # the pieces of Flask this file uses
from werkzeug.serving import make_server              # builds a web server object that can be stopped again

from blockchain import is_address                     # the address check from the chain core
from explorer import render_html                      # builds the explorer web page
from network import Node                              # one participant in the network

# ===========================================================================
# CONFIGURATION
# ===========================================================================

HOST = "127.0.0.1"       # the loopback address: reachable from this computer only
DEFAULT_PORT = 5000      # the port a node listens on unless told otherwise

ENDPOINTS = [                                                                   # the list returned by GET /
    "GET  /                       status of this node and this list",           # the index itself
    "GET  /chain                  the full chain",                              # required by the brief
    "POST /transactions/new       submit a payment",                            # required by the brief
    "GET  /transactions/pending   payments waiting to be mined",                # supports the payment flow
    "GET  /transactions/<txid>    one transaction and its confirmations",       # supports the payment flow
    "POST /mine                   mine a block holding the pending payments",   # required by the brief
    "GET  /balance/<address>      what an address holds and can spend",         # supports the payment flow
    "GET  /nodes                  this node's peer list",                       # required by the brief
    "POST /nodes/register         add peers",                                   # required by the brief
    "GET  /nodes/resolve          adopt the longest valid chain among the peers",   # supports the network
    "POST /inv                    announcement of a hash by a peer",            # supports the network
    "GET  /getdata/<type>/<hash>  the full transaction or block behind a hash", # supports the network
    "GET  /log                    this node's gossip log",                      # supports the network
    "GET  /explorer               web page of recent blocks and transactions",  # the explorer view
]

# ===========================================================================
# BUILDING THE FLASK APPLICATION
# ===========================================================================

def create_app(port: int = DEFAULT_PORT) -> Flask:
    """Create one node and the Flask application that exposes it."""
    node = Node(port)                              # the participant this application speaks for
    app = Flask(__name__)                          # the Flask application object
    app.config["NODE"] = node                      # keep a reference so other code can reach the node
    app.config["JSON_SORT_KEYS"] = False           # older Flask versions: keep reply fields in the order written below
    if hasattr(app, "json"):                       # newer Flask versions use a different setting for the same thing
        app.json.sort_keys = False                 # keep reply fields in the order written below

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------
    @app.route("/", methods=["GET"])               # GET / answers with a short status report
    def index():
        """Describe this node and list its endpoints."""
        view = node.snapshot()                               # one consistent reading of the node
        return jsonify({                                     # reply in JSON
            "node": node.address,                            # which node is answering
            "chain_length": len(view["chain"]),              # how many blocks it holds, including genesis
            "pending_count": len(view["pending"]),           # how many payments are waiting
            "peer_count": len(view["nodes"]),                # how many peers it knows
            "endpoints": ENDPOINTS,                          # what can be asked of it
        }), 200                                              # 200 means "OK"

    # -----------------------------------------------------------------------
    # The chain
    # -----------------------------------------------------------------------
    @app.route("/chain", methods=["GET"])          # GET /chain returns every block
    def get_chain():
        """Return the full chain."""
        view = node.snapshot()                               # one consistent reading of the node
        return jsonify({                                     # reply in JSON
            "length": len(view["chain"]),                    # how many blocks, including genesis
            "difficulty": view["difficulty"],                # the number of leading zeros every hash must show
            "chain": view["chain"],                          # the blocks, oldest first
        }), 200                                              # 200 means "OK"

    # -----------------------------------------------------------------------
    # Payments
    # -----------------------------------------------------------------------
    @app.route("/transactions/new", methods=["POST"])   # POST /transactions/new submits a payment
    def new_transaction():
        """Validate a payment, add it to the pending pool and announce it to the peers."""
        data = request.get_json(silent=True)                         # read the JSON body, or None if it is missing or malformed
        outcome, message, payment, announced_to = node.submit_payment(data)   # hand the payment to the node
        if outcome == "invalid":                                     # the fields were wrong
            return jsonify({"error": message}), 400                  # 400 means "bad request"
        if outcome == "duplicate":                                   # this exact payment was submitted before
            return jsonify({"error": message, "txid": payment["txid"]}), 409   # 409 means "conflict"
        if outcome == "insufficient_funds":                          # the sender cannot afford it
            return jsonify({"error": message}), 422                  # 422 means "understood, but cannot be processed"
        return jsonify({                                             # the payment was accepted
            "message": message,                                      # a sentence saying so
            "transaction": payment,                                  # the payment as stored, including its txid
            "pending_count": len(node.snapshot()["pending"]),        # how many payments are now waiting
            "announced_to": announced_to,                            # the peers that were told
        }), 201                                                      # 201 means "created"

    @app.route("/transactions/pending", methods=["GET"])   # GET /transactions/pending lists the pool
    def pending_transactions():
        """Return the payments waiting to be mined."""
        pending = node.snapshot()["pending"]                         # a copy of the pool
        return jsonify({"count": len(pending), "transactions": pending}), 200   # how many, then the payments themselves

    @app.route("/transactions/<txid>", methods=["GET"])    # GET /transactions/<txid> looks one transaction up
    def get_transaction(txid):
        """Return one transaction with its status and number of confirmations."""
        with node.lock:                                              # read the ledger while nothing is changing it
            found = node.blockchain.find_transaction(txid)           # search the chain, then the pool
        if found is None:                                            # this node has never seen that identifier
            return jsonify({"error": "no transaction with that txid is known to this node"}), 404   # 404 means "not found"
        return jsonify(found), 200                                   # the status report

    @app.route("/balance/<address>", methods=["GET"])      # GET /balance/<address> reports one balance
    def get_balance(address):
        """Return what an address holds, what is waiting to leave it, and what it can still spend."""
        if not is_address(address):                                  # refuse names that could never be an address
            return jsonify({"error": "an address is 1 to 64 letters, digits, hyphens or underscores"}), 400   # 400 means "bad request"
        with node.lock:                                              # read the ledger while nothing is changing it
            report = node.blockchain.balance_of(address)             # confirmed, pending out and available
        return jsonify(report), 200                                  # the balance report

    # -----------------------------------------------------------------------
    # Mining
    # -----------------------------------------------------------------------
    @app.route("/mine", methods=["POST"])          # POST /mine mines one block
    def mine():
        """Mine a block holding every pending payment, then announce it to the peers."""
        data = request.get_json(silent=True) or {}                   # the body is optional, so default to no fields
        miner = data.get("miner") if isinstance(data, dict) else None   # the address to reward, if one was named
        block, attempts, seconds, announced_to = node.mine(miner)    # the proof-of-work search happens here
        if block is None:                                            # the miner address was refused
            return jsonify({"error": "'miner' must be 1 to 64 letters, digits, hyphens or underscores"}), 400   # 400 means "bad request"
        return jsonify({                                             # the block was mined
            "message": f"block {block.index} mined",                 # a sentence saying so
            "block": block.to_dict(),                                # the new block
            "attempts": attempts,                                    # how many hashes the search needed
            "seconds": round(seconds, 3),                            # how long it took on this machine
            "announced_to": announced_to,                            # the peers that were told
        }), 201                                                      # 201 means "created"

    # -----------------------------------------------------------------------
    # Peers
    # -----------------------------------------------------------------------
    @app.route("/nodes", methods=["GET"])          # GET /nodes returns the peer list
    def get_nodes():
        """Return this node's address and its peers."""
        peers = node.peers.all()                                     # the sorted peer list
        return jsonify({"node": node.address, "count": len(peers), "nodes": peers}), 200   # who is answering, how many peers, and which

    @app.route("/nodes/register", methods=["POST"])   # POST /nodes/register adds peers
    def register_nodes():
        """Add one or more peers and relay the new ones to the rest of the network."""
        data = request.get_json(silent=True)                         # read the JSON body, or None if it is missing or malformed
        addresses = data.get("nodes") if isinstance(data, dict) else None   # the list of addresses to add
        if not isinstance(addresses, list) or not addresses:         # a non-empty list is required
            return jsonify({"error": "send a JSON object such as {\"nodes\": [\"http://127.0.0.1:5001\"]}"}), 400   # 400 means "bad request"
        result = node.register_peers(addresses, data.get("from"))    # add them and relay what was new
        if result["added"]:                                          # at least one peer was new
            result = {"message": f"{len(result['added'])} peer(s) added", **result}   # put a summary sentence first
            return jsonify(result), 201                              # 201 means "created"
        if result["rejected"]:                                       # nothing was added and something was refused
            result = {"error": "no peer was added", **result}        # put the error first
            return jsonify(result), 400                              # 400 means "bad request"
        result = {"message": "no new peers, all were already known", **result}   # nothing was new and nothing was wrong
        return jsonify(result), 200                                  # 200 means "OK"

    @app.route("/nodes/resolve", methods=["GET"])  # GET /nodes/resolve compares chains with the peers
    def resolve():
        """Adopt the longest valid chain held by any peer."""
        result = node.resolve()                                      # download and compare each peer's chain
        message = "chain replaced by a longer valid chain" if result["replaced"] else "this node's chain was kept"   # a summary sentence
        return jsonify({"message": message, **result}), 200          # 200 means "OK"

    # -----------------------------------------------------------------------
    # Gossip between nodes
    # -----------------------------------------------------------------------
    @app.route("/inv", methods=["POST"])           # POST /inv receives an announcement from a peer
    def inventory():
        """Receive "I hold this hash" from a peer, and fetch the item if it is new."""
        data = request.get_json(silent=True)                         # read the JSON body, or None if it is missing or malformed
        if not isinstance(data, dict):                               # the body must be a JSON object
            return jsonify({"error": "send a JSON object with 'type', 'hash' and 'from'"}), 400   # 400 means "bad request"
        status, reply = node.receive_inventory(data.get("type"), data.get("hash"), data.get("from"))   # let the node decide what to do
        return jsonify(reply), status                                # pass the node's answer back

    @app.route("/getdata/<kind>/<item_hash>", methods=["GET"])   # GET /getdata/<type>/<hash> supplies a full item
    def getdata(kind, item_hash):
        """Return the full transaction or block behind a hash."""
        if kind not in ("tx", "block"):                              # only two kinds of item exist
            return jsonify({"error": "the type must be \"tx\" or \"block\""}), 400   # 400 means "bad request"
        item = node.get_item(kind, item_hash)                        # look the item up
        if item is None:                                             # this node does not hold it
            return jsonify({"error": f"this node holds no {kind} with that hash"}), 404   # 404 means "not found"
        return jsonify(item), 200                                    # the transaction or block itself

    @app.route("/log", methods=["GET"])            # GET /log returns the gossip log
    def get_log():
        """Return every gossip message this node has sent or received."""
        events = list(node.events)                                   # a copy of the log
        return jsonify({"node": node.address, "count": len(events), "events": events}), 200   # who is answering, how many entries, and which

    # -----------------------------------------------------------------------
    # Explorer page
    # -----------------------------------------------------------------------
    @app.route("/explorer", methods=["GET"])       # GET /explorer returns a web page instead of JSON
    def explorer_page():
        """Return the block explorer as a HyperText Markup Language (HTML) page."""
        page = render_html(node.snapshot())                          # build the page from a reading of the node
        return Response(page, mimetype="text/html")                  # label the reply as a web page

    # -----------------------------------------------------------------------
    # Errors
    # -----------------------------------------------------------------------
    @app.errorhandler(404)                         # runs when no endpoint matches the web address
    def not_found(_error):
        """Answer unknown addresses in JSON, like every other reply."""
        return jsonify({"error": "no such endpoint; GET / lists the endpoints"}), 404   # 404 means "not found"

    @app.errorhandler(405)                         # runs when the address exists but the method is wrong
    def wrong_method(_error):
        """Answer a wrong method (for example GET /mine) in JSON, like every other reply."""
        return jsonify({"error": "this endpoint does not accept that method; GET / lists the endpoints"}), 405   # 405 means "method not allowed"

    return app                                     # hand back the finished application

# ===========================================================================
# RUNNING NODES IN THE BACKGROUND (USED BY THE NOTEBOOK AND THE DEMONSTRATION SCRIPT)
# ===========================================================================

RUNNING = globals().get("RUNNING", {})   # background nodes by port; kept if this file is reloaded, so none are lost track of


def port_in_use(port: int) -> bool:
    """Return True if something on this computer is already listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:   # open a temporary network socket
        probe.settimeout(0.5)                                          # give up after half a second
        return probe.connect_ex((HOST, port)) == 0                     # 0 means the connection succeeded, so the port is taken


class BackgroundNode:
    """One node running inside this program on a background thread."""

    def __init__(self, port: int):
        """Create the node and start serving it straight away."""
        self.port = port                                             # the port this node listens on
        self.url = f"http://{HOST}:{port}"                           # the base web address of the node
        self.app = create_app(port)                                  # the Flask application
        self.node = self.app.config["NODE"]                          # the node behind it
        self.server = make_server(HOST, port, self.app, threaded=True)   # a web server that handles each request on its own thread
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)   # daemon=True lets the program exit without waiting
        self.thread.start()                                          # begin answering requests

    def stop(self):
        """Stop serving and release the port."""
        self.server.shutdown()             # ask the serving loop to finish
        self.server.server_close()         # close the listening socket so the port is free again
        self.thread.join()                 # wait for the background thread to end


def start_background_node(port: int) -> BackgroundNode:
    """Start a fresh node on the port, replacing any background node already running there."""
    if port in RUNNING:                                              # a node from an earlier run is still on this port
        RUNNING.pop(port).stop()                                     # stop it so the new node starts from a clean ledger
    if port_in_use(port):                                            # some other program holds the port
        raise RuntimeError(f"port {port} is already in use; close the program using it or choose another port")   # explain how to fix it
    logging.getLogger("werkzeug").setLevel(logging.ERROR)            # keep the web server's request log out of the output
    RUNNING[port] = BackgroundNode(port)                             # start the node and remember it
    return RUNNING[port]                                             # hand it back to the caller


def stop_background_nodes():
    """Stop every background node this program started."""
    for port in list(RUNNING):             # list() copies the ports, because the dictionary shrinks as we go
        RUNNING.pop(port).stop()           # stop each node and forget it

# ===========================================================================
# RUNNING ONE NODE FROM THE COMMAND LINE
# ===========================================================================

def main():
    """Read the port from the command line and serve one node until Ctrl+C is pressed."""
    parser = argparse.ArgumentParser(description="Run one blockchain node on this computer.")   # describes the program for --help
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to listen on (default 5000)")   # the only option
    arguments = parser.parse_args()                                  # read what was typed
    if port_in_use(arguments.port):                                  # refuse to start two nodes on one port
        raise SystemExit(f"Port {arguments.port} is already in use. Choose another with --port.")   # stop with a clear message
    app = create_app(arguments.port)                                 # build the node and its application
    print(f"Node listening on http://{HOST}:{arguments.port}  (explorer at http://{HOST}:{arguments.port}/explorer)")   # where to find it
    app.run(host=HOST, port=arguments.port, threaded=True)           # serve on the loopback address only


if __name__ == "__main__":      # True only when this file is run directly, not when it is imported
    main()                      # start the node
