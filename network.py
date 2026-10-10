"""
network.py
Assignment 8: REST API and Networking Lab (the peer-to-peer layer)
Blockchain module (BLCH9X2), Master of Financial Engineering, University of Johannesburg

WHAT THIS FILE DOES
    Gives each node a list of peers and a way to gossip with them. Bitcoin nodes talk
    over long-lived connections using named messages. This lab keeps the same ideas
    but sends each message as one HTTP (HyperText Transfer Protocol) request:

        Bitcoin message         This lab
        ---------------------   --------------------------------------------------
        version / verack        the "from" field of POST /nodes/register
        getaddr                 GET  /nodes
        addr                    POST /nodes/register   (body: the addresses)
        inv                     POST /inv              (body: a type and a hash)
        getdata                 GET  /getdata/<type>/<hash>
        tx / block              the JSON (JavaScript Object Notation) reply to getdata
        getheaders, getblocks   GET  /chain            (used by GET /nodes/resolve)

    PeerBook   the peer list, restricted to this computer
    Node       one participant: a Blockchain, a PeerBook and the gossip rules

    Gossip stops by itself because a node only passes on what was new to it: an
    address it did not know, or a hash it did not hold.

SAFETY
    Only loopback addresses (127.0.0.1 or localhost) can be registered as peers, so a
    node can never be told to send requests to another computer.

HOW TO RUN
    This file is a library and is not run directly. Start a node with:
        python api.py
"""

import itertools                    # itertools.count gives us a simple counter for numbering log entries
import threading                    # threading provides locks, so two requests cannot change the ledger at the same moment
from urllib.parse import urlsplit   # urlsplit breaks a web address into its host and port

import requests                     # requests sends HTTP requests to other nodes

from blockchain import DIFFICULTY, Block, Blockchain, is_address   # the chain core this layer sits on top of

# ===========================================================================
# CONFIGURATION
# ===========================================================================

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")   # the only hosts a peer may live on: both names mean "this computer"
MAX_PEERS = 16                                # an upper limit on the peer list, so it cannot grow without bound
REQUEST_TIMEOUT = 10                          # seconds to wait for another node before giving up
MAX_EVENTS = 500                              # how many log entries each node remembers
EVENT_COUNTER = itertools.count(1)            # one counter shared by every node in this program, starting at 1

# ===========================================================================
# ADDRESS AND REQUEST HELPERS
# ===========================================================================

def normalise_address(text):
    """Turn "http://localhost:5001/" or "127.0.0.1:5001" into "127.0.0.1:5001". Return None if it is not a local node."""
    if not isinstance(text, str) or not text.strip():          # a peer address has to be non-empty text
        return None                                            # anything else is unusable
    candidate = text.strip()                                   # remove any spaces around the address
    if "//" not in candidate:                                  # urlsplit only finds the host when a scheme is present
        candidate = "http://" + candidate                      # so add one when the caller left it out
    try:                                                       # a malformed address can make the parser raise an error
        parts = urlsplit(candidate)                            # split the address into scheme, host, port and path
        host, port = parts.hostname, parts.port                # pick out the two parts we need
    except ValueError:                                         # for example a port that is not a number
        return None                                            # unusable
    if parts.scheme != "http" or host not in LOOPBACK_HOSTS:   # the safety rule: plain HTTP on this computer only
        return None                                            # any other computer is refused
    if port is None or not 1 <= port <= 65535:                 # a node is identified by its port, so one must be given
        return None                                            # unusable without a valid port
    return f"127.0.0.1:{port}"                                 # one agreed spelling, so the same node is never listed twice


def short_name(address: str) -> str:
    """Shorten "127.0.0.1:5001" to ":5001" for compact log lines."""
    return ":" + address.rsplit(":", 1)[-1]   # keep only the text after the last colon, which is the port


def call_node(method: str, address: str, path: str, payload=None) -> tuple:
    """Send one HTTP request to a node. Return (status code, decoded JSON), or (None, None) if it could not be reached."""
    url = f"http://{address}{path}"                             # build the full web address of the endpoint
    try:                                                        # the other node may be switched off or slow
        with requests.Session() as session:                     # a session is one short-lived connection manager
            session.trust_env = False                           # ignore any proxy settings: local nodes are reached directly
            response = session.request(method, url, json=payload, timeout=REQUEST_TIMEOUT)   # send the request and wait for the reply
        return response.status_code, response.json()            # hand back the status code and the decoded body
    except (requests.RequestException, ValueError):             # connection problems, timeouts and non-JSON replies land here
        return None, None                                       # tell the caller the node could not be used

# ===========================================================================
# THE PEER LIST
# ===========================================================================

class PeerBook:
    """The set of other nodes this node knows about."""

    def __init__(self, own_address: str):
        """Create an empty peer list for the node living at own_address."""
        self.own_address = own_address      # remembered so the node never lists itself as a peer
        self._peers = set()                 # a set holds each address at most once
        self._lock = threading.Lock()       # protects the set when several requests arrive together

    def add(self, address: str) -> str:
        """Try to add an already normalised address. Return "added", "known" or "full"."""
        with self._lock:                                              # only one request may change the list at a time
            if address == self.own_address or address in self._peers: # the node itself and existing peers are nothing new
                return "known"                                        # report that nothing changed
            if len(self._peers) >= MAX_PEERS:                         # the list has reached its limit
                return "full"                                         # report that there is no room
            self._peers.add(address)                                  # a new peer joins the list
            return "added"                                            # report the change

    def contains(self, address: str) -> bool:
        """Return True if the address is a known peer."""
        with self._lock:                      # read under the lock so the answer is consistent
            return address in self._peers     # True when the address is on the list

    def all(self) -> list:
        """Return every known peer in sorted order, so output is the same on every run."""
        with self._lock:                      # read under the lock so the list is not changing while it is copied
            return sorted(self._peers)        # a sorted copy of the set

# ===========================================================================
# ONE NODE: LEDGER, PEERS AND GOSSIP
# ===========================================================================

class Node:
    """One participant in the network. The Application Programming Interface (API) in api.py is a thin layer over the methods of this class."""

    def __init__(self, port: int):
        """Create a node that will listen on the given local port."""
        self.address = f"127.0.0.1:{port}"       # how other nodes reach this one
        self.default_miner = f"miner-{port}"     # the address rewarded when a mining request names nobody
        self.blockchain = Blockchain()           # this node's own copy of the ledger
        self.peers = PeerBook(self.address)      # this node's own list of peers
        self.lock = threading.Lock()             # protects the ledger when several requests arrive together
        self.events = []                         # a log of every gossip message sent or received

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------
    def record(self, text: str):
        """Add one line to this node's gossip log."""
        entry = {"seq": next(EVENT_COUNTER), "node": self.address, "event": text}   # number the entry so logs can be merged in order
        self.events.append(entry)                                                   # store it
        del self.events[:-MAX_EVENTS]                                               # forget the oldest entries beyond the limit

    # -----------------------------------------------------------------------
    # Peer discovery: the counterpart of Bitcoin's version, getaddr and addr messages
    # -----------------------------------------------------------------------
    def register_peers(self, addresses: list, sender=None) -> dict:
        """Add peers, then pass on whatever was new. Return what happened to each address."""
        sender_address = normalise_address(sender)               # the node that sent this message, if it named itself
        candidates = list(addresses)                             # start with the addresses in the message
        if sender_address is not None:                           # a named sender introduces itself, like a version message
            candidates.append(sender_address)                    # so it is treated as one more address to learn
        added, already_known, rejected = [], [], []              # three lists describing the outcome
        for raw in candidates:                                   # consider each address in turn
            address = normalise_address(raw)                     # convert it to the agreed spelling
            if address is None:                                  # it was malformed or pointed at another computer
                rejected.append({"address": str(raw), "reason": "not an http address on this computer (127.0.0.1 or localhost) with a port"})   # record why
                continue                                         # move on to the next address
            if address in added or address in already_known:     # the same address listed twice is only handled once
                continue                                         # move on to the next address
            outcome = self.peers.add(address)                    # try to add it to the peer list
            if outcome == "added":                               # it was new
                added.append(address)                            # remember it for the relay step below
            elif outcome == "known":                             # it was already listed, or it is this node itself
                already_known.append(address)                    # nothing changes
            else:                                                # the only other outcome is a full list
                rejected.append({"address": address, "reason": f"peer list is full ({MAX_PEERS} peers)"})   # record why
        origin = short_name(sender_address) if sender_address else "a client"   # who sent the message, for the log
        if added:                                                # something new was learned
            learned = ", ".join(short_name(address) for address in added)       # a compact list for the log
            self.record(f"got addr from {origin}: learned {learned}")           # log the discovery
        elif sender_address is not None:                         # a peer told us only what we already knew
            self.record(f"got addr from {origin}: nothing new, so nothing relayed")   # this is what ends the gossip
        for peer in self.peers.all():                            # decide what, if anything, each peer should be told
            if peer == sender_address:                           # the node that just told us needs nothing back
                continue                                         # move on to the next peer
            news = [address for address in added if address != peer]   # the new addresses, leaving out the peer's own
            if peer in added:                                    # a brand new peer does not know this node yet
                news.insert(0, self.address)                     # so this node advertises its own address first
            if not news:                                         # nothing was new for this peer
                continue                                         # move on to the next peer
            names = ", ".join(short_name(address) for address in news)          # a compact list for the log
            self.record(f"sent addr ({names}) to {short_name(peer)}")           # log before sending, so the order is causal
            call_node("POST", peer, "/nodes/register", {"nodes": news, "from": self.address})   # the relay itself
        return {                                                 # the outcome, reported back to the caller
            "added": added,                                      # addresses that were new to this node
            "already_known": already_known,                      # addresses it already had
            "rejected": rejected,                                # addresses it refused, each with a reason
            "nodes": self.peers.all(),                           # the full peer list after any relaying
        }

    # -----------------------------------------------------------------------
    # Inventory gossip: the counterpart of Bitcoin's inv and getdata messages
    # -----------------------------------------------------------------------
    def announce(self, kind: str, item_hash: str, exclude=None) -> list:
        """Tell every peer "I hold this item" by sending its hash only. Return the peers that answered."""
        reached = []                                             # the peers that replied
        for peer in self.peers.all():                            # announce to every peer
            if peer == exclude:                                  # except the one the item came from
                continue                                         # it already holds the item
            self.record(f"sent inv ({kind} {item_hash[:8]}) to {short_name(peer)}")   # log before sending, so the order is causal
            status, _ = call_node("POST", peer, "/inv", {"type": kind, "hash": item_hash, "from": self.address})   # the announcement itself
            if status is None:                                   # the peer did not answer
                self.record(f"{short_name(peer)} could not be reached")   # log the failure and carry on
            else:                                                # the peer answered
                reached.append(peer)                             # count it as reached
        return reached                                           # the list of peers that were told

    def holds(self, kind: str, item_hash: str) -> bool:
        """Return True if this node already holds the transaction or block with this hash."""
        if kind == "block":                                                  # a block is looked up in the chain
            return self.blockchain.get_block(item_hash) is not None          # True when the chain holds that hash
        return self.blockchain.find_transaction(item_hash) is not None       # a transaction may be mined or pending

    def get_item(self, kind: str, item_hash: str):
        """Return the full transaction or block for a getdata request, or None if this node does not hold it."""
        with self.lock:                                                      # read the ledger while nothing is changing it
            if kind == "block":                                              # a block was asked for
                block = self.blockchain.get_block(item_hash)                 # look it up by hash
                item = block.to_dict() if block is not None else None        # convert it to its network form
            else:                                                            # a transaction was asked for
                found = self.blockchain.find_transaction(item_hash)          # look it up by identifier
                item = found["transaction"] if found is not None else None   # keep just the transaction
        if item is not None:                                                 # only log requests that were answered
            self.record(f"got getdata ({kind} {item_hash[:8]}), sent the {kind}")   # log the reply
        return item                                                          # the item, or None

    def receive_inventory(self, kind, item_hash, sender) -> tuple:
        """Handle an inv message: fetch the item if it is new, check it, store it and pass the news on.

        Return (HTTP status code, reply)."""
        sender_address = normalise_address(sender)                           # who is announcing
        if sender_address is None or not self.peers.contains(sender_address):   # announcements are only taken from known peers
            return 403, {"error": "inventory is only accepted from registered peers"}   # 403 means "forbidden"
        if kind not in ("tx", "block") or not isinstance(item_hash, str) or len(item_hash) != 64:   # the message must name a type and a 64 character hash
            return 400, {"error": "'type' must be \"tx\" or \"block\" and 'hash' must be 64 hexadecimal characters"}   # 400 means "bad request"
        label = f"{kind} {item_hash[:8]}"                                    # a compact name for the log
        with self.lock:                                                      # read the ledger while nothing is changing it
            already_held = self.holds(kind, item_hash)                       # is this item new to us?
        if already_held:                                                     # known items are ignored, which is what ends the gossip
            self.record(f"got inv ({label}) from {short_name(sender_address)}: already held, ignored")   # log it
            return 200, {"action": "ignored", "detail": "already held"}      # nothing more to do
        self.record(f"got inv ({label}) from {short_name(sender_address)}: new, sent getdata")   # log the decision to fetch
        status, data = call_node("GET", sender_address, f"/getdata/{kind}/{item_hash}")   # ask the announcer for the full item
        if status != 200:                                                    # the announcer could not supply it
            self.record(f"getdata ({label}) failed")                         # log the failure
            return 200, {"action": "failed", "detail": "the announcing node did not supply the item"}   # report it
        if kind == "tx":                                                     # the item is a payment
            return self._receive_payment(data, item_hash, sender_address)    # handle it as a payment
        return self._receive_block(data, item_hash, sender_address)          # otherwise handle it as a block

    def _receive_payment(self, data, item_hash: str, sender_address: str) -> tuple:
        """Check a payment fetched from a peer and add it to the pending pool."""
        if not isinstance(data, dict) or data.get("txid") != item_hash:      # the item must be the one that was announced
            return 200, {"action": "rejected", "detail": "the item does not match the announced hash"}   # refuse a swapped item
        with self.lock:                                                      # change the ledger safely
            outcome, message, _ = self.blockchain.add_payment(data)          # apply the same checks as for a client's payment
        if outcome != "accepted":                                            # the payment failed a check here
            self.record(f"tx {item_hash[:8]} refused: {message}")            # log why
            return 200, {"action": "rejected", "detail": message}            # report it
        self.record(f"tx {item_hash[:8]} added to the pending pool")         # log the success
        self.announce("tx", item_hash, exclude=sender_address)               # pass the news on to the other peers
        return 200, {"action": "fetched", "detail": "payment added to the pending pool"}   # report it

    def _receive_block(self, data, item_hash: str, sender_address: str) -> tuple:
        """Check a block fetched from a peer and add it to the chain, or fall back to comparing whole chains."""
        block = Block.from_dict(data)                                        # rebuild the block from the reply
        if block is None or block.hash != item_hash:                         # the item must be the one that was announced
            return 200, {"action": "rejected", "detail": "the item does not match the announced hash"}   # refuse a swapped item
        with self.lock:                                                      # change the ledger safely
            outcome, message = self.blockchain.accept_block(block)           # apply every block rule
        if outcome == "accepted":                                            # the block extended our chain
            self.record(f"block {block.index} ({item_hash[:8]}) appended to the chain")   # log the success
            self.announce("block", item_hash, exclude=sender_address)        # pass the news on to the other peers
            return 200, {"action": "fetched", "detail": "block appended to the chain"}   # report it
        if outcome == "detached":                                            # the block builds on something we do not hold
            self.record(f"block {block.index} ({item_hash[:8]}) does not attach, requested the whole chain")   # log the fallback
            replaced, message = self.sync_from(sender_address)               # compare whole chains with the announcer
            if replaced:                                                     # we switched to the announcer's chain
                self.announce("block", item_hash, exclude=sender_address)    # so tell the other peers about its newest block
                return 200, {"action": "synchronised", "detail": message}    # report it
        self.record(f"block {block.index} ({item_hash[:8]}) not adopted: {message}")   # every remaining case leaves our chain unchanged
        return 200, {"action": "rejected", "detail": message}                # report it

    # -----------------------------------------------------------------------
    # Chain synchronisation: the counterpart of Bitcoin's initial block download
    # -----------------------------------------------------------------------
    def sync_from(self, peer: str) -> tuple:
        """Download a peer's whole chain and adopt it if it is valid and longer. Return (replaced, message)."""
        status, data = call_node("GET", peer, "/chain")                          # ask for the peer's full chain
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("chain"), list):   # the reply must contain a list of blocks
            return False, "the peer did not supply a chain"                      # nothing to compare
        blocks = [Block.from_dict(item) for item in data["chain"]]               # rebuild every block (unreadable ones become None)
        with self.lock:                                                          # change the ledger safely
            replaced, message = self.blockchain.replace_chain(blocks)            # the longest valid chain rule
        if replaced:                                                             # only a switch is worth logging
            self.record(f"adopted the chain of {short_name(peer)}, now {len(blocks)} blocks")   # log it
        return replaced, message                                                 # report the outcome

    def resolve(self) -> dict:
        """Compare chains with every peer and keep the longest valid one."""
        checked = []                                                 # one line of results per peer
        for peer in self.peers.all():                                # visit every peer in turn
            replaced, message = self.sync_from(peer)                 # adopt its chain if it is longer and valid
            checked.append({"peer": peer, "adopted": replaced, "detail": message})   # record what happened
        with self.lock:                                              # read the ledger while nothing is changing it
            length = len(self.blockchain.chain)                      # the chain length after all comparisons
        replaced_any = any(item["adopted"] for item in checked)      # did any peer have a better chain?
        return {                                                     # the summary returned to the caller
            "replaced": replaced_any,                                # True if this node switched chains
            "length": length,                                        # how many blocks it holds now
            "checked": checked,                                      # the detail for each peer
        }

    # -----------------------------------------------------------------------
    # Actions requested by a client
    # -----------------------------------------------------------------------
    def submit_payment(self, data) -> tuple:
        """Accept a payment from a client and announce it to the peers. Return (outcome, message, payment, peers told)."""
        with self.lock:                                                  # change the ledger safely
            outcome, message, payment = self.blockchain.add_payment(data)   # validate the payment and add it to the pool
        announced_to = []                                                # the peers told about it, empty unless it was accepted
        if outcome == "accepted":                                        # only accepted payments are announced
            self.record(f"tx {payment['txid'][:8]} submitted by a client, added to the pending pool")   # log it
            announced_to = self.announce("tx", payment["txid"])          # tell the peers
        return outcome, message, payment, announced_to                   # report everything to the caller

    def mine(self, miner_address=None) -> tuple:
        """Mine the pending payments into a block and announce it. Return (block, attempts, seconds, peers told)."""
        miner = miner_address if miner_address is not None else self.default_miner   # use the node's own miner address unless one was given
        if not is_address(miner):                                        # the reward must go to a usable address
            return None, 0, 0.0, []                                      # None tells the caller the address was refused
        with self.lock:                                                  # hold the ledger still while the block is mined
            block, attempts, seconds = self.blockchain.mine_pending(miner)   # the proof-of-work search
        self.record(f"mined block {block.index} ({block.hash[:8]}) after {attempts:,} attempts")   # log it
        announced_to = self.announce("block", block.hash)                # tell the peers
        return block, attempts, seconds, announced_to                    # report everything to the caller

    def snapshot(self) -> dict:
        """Return everything the explorer needs in one consistent reading of the node."""
        with self.lock:                                                          # read the ledger while nothing is changing it
            chain = [block.to_dict() for block in self.blockchain.chain]         # every block in its network form
            pending = list(self.blockchain.pending)                              # a copy of the pending pool
        return {                                                                 # the snapshot
            "node": self.address,                                                # which node this describes
            "difficulty": DIFFICULTY,                                            # the mining rule every node shares
            "chain": chain,                                                      # its blocks
            "pending": pending,                                                  # its pending payments
            "nodes": self.peers.all(),                                           # its peers
        }
