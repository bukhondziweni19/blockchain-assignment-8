"""
blockchain.py
Assignment 8: REST API and Networking Lab (the chain core)
Blockchain module (BLCH9X2), Master of Financial Engineering, University of Johannesburg

WHAT THIS FILE DOES
    Holds the ledger that the Application Programming Interface (API) in api.py exposes.
    It carries forward the semester build: blocks sealed with SHA-256 (Secure Hash
    Algorithm, 256-bit), proof-of-work mining, a coinbase reward and a pending pool.

        Block        one batch of transactions, sealed with a hash
        Blockchain   the ordered list of blocks plus the pool of pending payments

    Two rules are new in this assignment, because a payment API needs them:

        1. A payment is only accepted if the sender can afford it, counting payments
           the sender already has waiting in the pending pool.
        2. Every transaction has an identifier (txid), the hash of its own fields.
           Submitting the same payment twice gives the same txid and is refused, so a
           retried request can never pay twice.

HOW TO RUN
    This file is a library and is not run directly. Start a node with:
        python api.py

REPRODUCIBILITY
    Block timestamps come from a logical clock (genesis time plus ten minutes per
    block) and every nonce search starts at zero, so every nonce, hash and txid is
    identical on any machine. Only the mining seconds differ.
"""

import hashlib          # hashlib gives us SHA-256, the fingerprint function
import json             # json turns Python dictionaries into text in a controlled, repeatable way
import re               # re lets us check that an address only uses permitted characters
import time             # time lets us measure how long mining takes, in seconds

# ===========================================================================
# CONFIGURATION
# ===========================================================================

DIFFICULTY = 4                        # our mining rule: a valid block hash must start with this many zero characters
GENESIS_TIMESTAMP = 1790812800        # a fixed Unix timestamp (01 October 2026, 00:00:00 UTC, Coordinated Universal Time)
SECONDS_PER_BLOCK = 600               # the logical clock moves 600 seconds (10 minutes) for every block, as Bitcoin aims for
GENESIS_PREVIOUS_HASH = "0" * 64      # 64 zeros, the agreed convention meaning "there is no earlier block"
BLOCK_SUBSIDY = 50                    # new units created by the rules and paid to whoever mines a block
FEE_PER_PAYMENT = 1                   # a flat charge the sender pays to the miner for including a payment
MAX_TEXT_LENGTH = 64                  # the longest address or payment reference the node will accept
ADDRESS_PATTERN = re.compile(r"[A-Za-z0-9_-]+")   # an address may use letters, digits, underscores and hyphens only

# ===========================================================================
# HASHING HELPERS
# ===========================================================================

def canonical_json(payload) -> str:
    """Turn a dictionary into one single agreed text string, so hashing is repeatable."""
    # sort_keys=True    : always writes the fields in alphabetical order, so field order can never change the hash
    # separators=(...)  : removes all optional spaces, so spacing can never change the hash
    # ensure_ascii=True : escapes any non-English characters, so the text is identical on every machine
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    """Return the SHA-256 fingerprint of a piece of text, written as 64 hexadecimal characters."""
    encoded_text = text.encode("utf-8")           # convert the text into raw bytes, because hashing works on bytes, not letters
    digest = hashlib.sha256(encoded_text)         # run the SHA-256 algorithm over those bytes
    return digest.hexdigest()                     # return the result as a readable 64 character string


def meets_difficulty(hash_hex: str, difficulty: int = DIFFICULTY) -> bool:
    """Return True only if the hash starts with the required number of zeros (our proof-of-work target)."""
    required_prefix = "0" * difficulty            # build the pattern we demand, for example "0000" when difficulty is 4
    return hash_hex.startswith(required_prefix)   # True means this hash was mined properly, False means it was not


def block_timestamp(index: int) -> int:
    """Return the timestamp the logical clock assigns to the block at this position."""
    return GENESIS_TIMESTAMP + index * SECONDS_PER_BLOCK   # genesis time plus ten minutes for every block after it

# ===========================================================================
# TRANSACTIONS
# ===========================================================================

def is_address(value) -> bool:
    """Return True if the value is usable as an account address."""
    if not isinstance(value, str):                          # an address has to be text, not a number or a list
        return False                                        # anything else is refused
    if len(value) > MAX_TEXT_LENGTH:                        # very long names are refused to keep records small
        return False                                        # too long, so not a valid address
    return ADDRESS_PATTERN.fullmatch(value) is not None     # True only if every character is a permitted one


def transaction_id(fields: dict) -> str:
    """Return the identifier of a transaction: the SHA-256 hash of every field except the identifier itself."""
    body = {name: value for name, value in fields.items() if name != "txid"}   # copy the fields, leaving out the txid
    return sha256_hex(canonical_json(body))                                    # fingerprint the agreed text form of those fields


def make_payment(sender: str, receiver: str, amount: int, reference: str = "") -> dict:
    """Build one ordinary payment, which pays a flat fee to whichever miner includes it."""
    payment = {                               # a dictionary holding the fields of one payment
        "type": "payment",                    # marks this as an ordinary transfer rather than a reward
        "sender": sender,                     # who is paying
        "receiver": receiver,                 # who is being paid
        "amount": amount,                     # the value, in whole units so no rounding can ever occur
        "fee": FEE_PER_PAYMENT,               # what the sender pays the miner for including this payment
        "reference": reference,               # the payer's own reference, which also keeps repeat payments distinct
    }
    payment["txid"] = transaction_id(payment)   # the identifier is the hash of all the fields above
    return payment                              # hand back the finished payment


def make_coinbase(miner_address: str, block_index: int, total_fees: int) -> dict:
    """Build the special first transaction that pays the miner for finding this block."""
    coinbase = {                                            # the coinbase has no sender: these units are newly created
        "type": "coinbase",                                 # marks this as the reward rather than a transfer
        "sender": None,                                     # nobody is debited, so the sender is left empty
        "receiver": miner_address,                          # the address being paid
        "amount": BLOCK_SUBSIDY + total_fees,               # the fixed subsidy plus every fee collected in this block
        "fee": 0,                                           # a reward pays no fee
        "reference": f"reward for block {block_index}",     # naming the block stops the same coinbase being reused elsewhere
    }
    coinbase["txid"] = transaction_id(coinbase)   # the identifier is the hash of all the fields above
    return coinbase                               # hand back the finished reward transaction


def payment_field_error(data):
    """Check the fields of a submitted payment. Return a message describing the first problem, or None if all is well."""
    if not isinstance(data, dict):                                              # the submission must be a set of named fields
        return "the request body must be a JSON object"                         # JSON is JavaScript Object Notation
    for field in ("sender", "receiver"):                                        # both parties are checked the same way
        if not is_address(data.get(field)):                                     # .get returns None when the field is missing
            return f"'{field}' must be 1 to {MAX_TEXT_LENGTH} letters, digits, hyphens or underscores"   # explain the rule that failed
    if data["sender"] == data["receiver"]:                                      # paying yourself moves nothing
        return "'sender' and 'receiver' must be different"                      # so it is refused
    amount = data.get("amount")                                                 # read the amount, or None if it is missing
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:  # Python treats True as 1, so booleans are excluded first
        return "'amount' must be a whole number greater than zero"              # decimals, text and negatives are all refused
    reference = data.get("reference", "")                                       # the reference is optional and defaults to empty
    if not isinstance(reference, str) or len(reference) > MAX_TEXT_LENGTH:      # it must be text and not too long
        return f"'reference' must be text of at most {MAX_TEXT_LENGTH} characters"   # explain the rule that failed
    return None                                                                 # None means no problem was found


def apply_transaction(balances: dict, transaction: dict):
    """Move the value of one transaction through a dictionary of balances."""
    if transaction["type"] == "payment":                                                  # only ordinary payments debit somebody
        cost = transaction["amount"] + transaction["fee"]                                 # the sender pays the amount plus the fee
        balances[transaction["sender"]] = balances.get(transaction["sender"], 0) - cost   # debit the sender
    receiver = transaction["receiver"]                                                    # whoever is being paid
    balances[receiver] = balances.get(receiver, 0) + transaction["amount"]                # credit the receiver (or the miner, for a coinbase)

# ===========================================================================
# THE BLOCK CLASS, CARRIED FORWARD FROM ASSIGNMENT 2
# ===========================================================================

class Block:
    """One block in the chain: a batch of transactions, sealed with a fingerprint."""

    def __init__(self, index: int, timestamp: int, transactions: list, previous_hash: str, nonce: int = 0):
        """Create a block and immediately seal it by computing its hash."""
        self.index = index                     # the position of this block in the chain, starting at 0 for genesis
        self.timestamp = timestamp             # when the block was created, as a Unix timestamp (whole seconds)
        self.transactions = transactions       # the list of transactions this block carries
        self.previous_hash = previous_hash     # the fingerprint of the block before this one, which is what forms the chain
        self.nonce = nonce                     # the "number used once", the only field a miner is allowed to change freely
        self.hash = self.compute_hash()        # seal the block by fingerprinting everything above

    def header_payload(self) -> dict:
        """Collect every field the hash must commit to, leaving out the hash itself."""
        return {                                 # note that self.hash is deliberately NOT included, or we would hash the answer
            "index": self.index,                 # committing to position stops a block being moved elsewhere in the chain
            "timestamp": self.timestamp,         # committing to time stops the block being back-dated
            "transactions": self.transactions,   # committing to the payments is what makes the amounts tamper evident
            "previous_hash": self.previous_hash, # committing to the parent is what links the chain together
            "nonce": self.nonce,                 # committing to the nonce is what makes the mining work count
        }

    def compute_hash(self) -> str:
        """Recompute this block's fingerprint from its current contents."""
        serialised = canonical_json(self.header_payload())  # write the fields as one agreed text string
        return sha256_hex(serialised)                       # fingerprint that text with SHA-256

    def to_dict(self) -> dict:
        """Return the block as a plain dictionary, the form in which it travels over the network."""
        as_dict = self.header_payload()   # start from the five fields the hash commits to
        as_dict["hash"] = self.hash       # then add the stored hash so the reader can check it
        return as_dict                    # hand back all six fields

    @staticmethod
    def from_dict(data):
        """Rebuild a block from a dictionary received from another node. Return None if the data is unusable."""
        try:                                                    # data from another node cannot be trusted to have the right shape
            block = Block(                                      # build the block from the five hashed fields
                index=int(data["index"]),                       # the claimed position, forced to a whole number
                timestamp=int(data["timestamp"]),               # the claimed time, forced to a whole number
                transactions=list(data["transactions"]),        # the claimed transactions, forced to a list
                previous_hash=str(data["previous_hash"]),       # the claimed parent hash, forced to text
                nonce=int(data["nonce"]),                       # the claimed nonce, forced to a whole number
            )
            block.hash = str(data["hash"])                      # keep the hash the sender CLAIMED, so it can be checked later
            return block                                        # hand back the rebuilt block
        except (KeyError, TypeError, ValueError):               # a missing field or a wrong type lands here
            return None                                         # None tells the caller the data was unusable

# ===========================================================================
# MINING AND THE GENESIS BLOCK
# ===========================================================================

def mine_block(block: Block, difficulty: int = DIFFICULTY) -> tuple:
    """Try nonce values one after another until the block hash meets the difficulty rule."""
    started = time.perf_counter()                 # start a stopwatch so the cost of mining can be reported
    block.nonce = 0                               # every search starts at zero, which makes the result repeatable
    block.hash = block.compute_hash()             # hash the block with that first nonce
    attempts = 1                                  # one hash has been tried so far
    while not meets_difficulty(block.hash, difficulty):   # keep going until the hash starts with enough zeros
        block.nonce += 1                          # move to the next nonce
        block.hash = block.compute_hash()         # hash the block again with the new nonce
        attempts += 1                             # count this attempt
    seconds = time.perf_counter() - started       # stop the stopwatch
    return attempts, seconds                      # report how many hashes it took and how long


_GENESIS_FIELDS = None   # the mined genesis block is remembered here so it only has to be mined once per program


def make_genesis_block() -> Block:
    """Return block 0, the only block that has no parent. Every node builds exactly the same one."""
    global _GENESIS_FIELDS                                # allow this function to store the remembered genesis block
    if _GENESIS_FIELDS is None:                           # the first call has to do the mining
        genesis = Block(                                  # build the block using fixed values only
            index=0,                                      # genesis always sits at position 0
            timestamp=GENESIS_TIMESTAMP,                  # the fixed starting time from the configuration
            transactions=[],                              # genesis carries no transactions, so every balance starts at zero
            previous_hash=GENESIS_PREVIOUS_HASH,          # 64 zeros, because there is no earlier block
        )
        mine_block(genesis)                               # genesis obeys the same difficulty rule as every other block
        _GENESIS_FIELDS = genesis.to_dict()               # remember the result for later calls
    return Block.from_dict(_GENESIS_FIELDS)               # hand each caller its own separate copy

# ===========================================================================
# VALIDATION RULES SHARED BY EVERY NODE
# ===========================================================================

def block_error(block: Block, previous_block: Block, balances: dict, seen_txids: set):
    """Check one block against the block before it. Return a message describing the first problem, or None.

    When the block is valid, balances and seen_txids are updated to include it."""
    if block.index != previous_block.index + 1:                         # rule 1: positions must count up by one
        return "index does not follow the previous block"               # the block is out of sequence
    if block.previous_hash != previous_block.hash:                      # rule 2: the block must point at its parent
        return "previous_hash does not match the previous block"        # the link is broken
    if block.timestamp != block_timestamp(block.index):                 # rule 3: the time must follow the logical clock
        return "timestamp does not follow the logical clock"            # the block claims a time the rules do not allow
    if block.hash != block.compute_hash():                              # rule 4: the stored hash must match the contents
        return "stored hash does not match the block contents"          # something was edited after sealing
    if not meets_difficulty(block.hash):                                # rule 5: the hash must show proof of work
        return "hash does not meet the proof-of-work difficulty"        # the block was not mined
    transactions = block.transactions                                   # rules 6 to 8 concern the transactions inside
    if not transactions or not all(isinstance(item, dict) for item in transactions):   # there must be at least a coinbase, all as records
        return "block has no usable transactions"                       # an empty or malformed list is refused
    reward, payments = transactions[0], transactions[1:]                # the first transaction is the reward, the rest are payments
    if not is_address(reward.get("receiver")):                          # the reward must be paid to a usable address
        return "coinbase receiver is not a valid address"               # refuse a reward with a broken receiver
    expected_reward = make_coinbase(reward["receiver"], block.index, FEE_PER_PAYMENT * len(payments))   # rebuild the only reward the rules allow
    if reward != expected_reward:                                       # rule 6: the reward must be exactly subsidy plus fees
        return "coinbase is not the reward the rules allow"             # a miner tried to overpay itself or reuse a reward
    working_balances = dict(balances)                                   # work on a copy, so a rejected block changes nothing
    working_txids = set(seen_txids)                                     # likewise for the set of identifiers already used
    apply_transaction(working_balances, reward)                         # credit the miner
    working_txids.add(reward["txid"])                                   # remember the reward's identifier
    for payment in payments:                                            # now check every ordinary payment in order
        problem = payment_field_error(payment)                          # are the fields well formed?
        if problem is not None:                                         # a malformed payment invalidates the block
            return f"payment is malformed: {problem}"                   # report which rule failed
        rebuilt = make_payment(payment["sender"], payment["receiver"], payment["amount"], payment.get("reference", ""))   # rebuild it from its own fields
        if payment != rebuilt:                                          # rule 7: the txid and fee must match the fields
            return "payment does not match its txid"                    # the payment was altered after it was created
        if payment["txid"] in working_txids:                            # rule 7 continued: no payment may appear twice
            return "payment appears more than once in the chain"        # a replayed payment is refused
        cost = payment["amount"] + payment["fee"]                       # what the sender must be able to afford
        if working_balances.get(payment["sender"], 0) < cost:           # rule 8: no sender may spend more than it holds
            return "payment spends more than the sender holds"          # an overdrawn payment invalidates the block
        apply_transaction(working_balances, payment)                    # move the value
        working_txids.add(payment["txid"])                              # remember the identifier
    balances.clear()                                                    # the block is valid, so publish the new balances
    balances.update(working_balances)                                   # by copying the working values back
    seen_txids.update(working_txids)                                    # and publish the identifiers it used
    return None                                                         # None means the block passed every rule


def chain_error(blocks: list):
    """Check a whole chain from genesis. Return a message describing the first problem, or None."""
    if not blocks or any(block is None for block in blocks):            # an empty chain or an unreadable block is refused
        return "chain is empty or contains an unreadable block"         # nothing further can be checked
    if blocks[0].to_dict() != make_genesis_block().to_dict():           # every node must start from the same genesis block
        return "chain does not start from the shared genesis block"     # this chain belongs to a different network
    balances, seen_txids = {}, set()                                    # replay the chain from nothing
    for previous_block, block in zip(blocks, blocks[1:]):               # walk each block together with the one before it
        problem = block_error(block, previous_block, balances, seen_txids)   # apply the block rules
        if problem is not None:                                         # stop at the first broken block
            return f"block {block.index}: {problem}"                    # say which block failed and why
    return None                                                         # None means the whole chain is valid

# ===========================================================================
# THE BLOCKCHAIN CLASS: THE CHAIN PLUS THE PENDING POOL
# ===========================================================================

class Blockchain:
    """The ledger held by one node: its chain of blocks and its pool of payments waiting to be mined."""

    def __init__(self):
        """Start a new ledger holding only the genesis block."""
        self.chain = [make_genesis_block()]   # the ordered list of blocks, oldest first
        self.pending = []                     # payments accepted but not yet mined, oldest first

    @property
    def last_block(self) -> Block:
        """Return the newest block, which the next block must point at."""
        return self.chain[-1]                 # "[-1]" means the last item in a list

    # -----------------------------------------------------------------------
    # Reading the ledger
    # -----------------------------------------------------------------------
    def confirmed_balances(self) -> dict:
        """Replay every mined transaction and return what each address holds."""
        balances = {}                                 # start with nobody holding anything
        for block in self.chain:                      # walk the chain from genesis
            for transaction in block.transactions:    # and every transaction inside each block
                apply_transaction(balances, transaction)   # move its value
        return balances                               # the finished table of address to balance

    def confirmed_txids(self) -> set:
        """Return the identifier of every transaction already mined into the chain."""
        return {transaction["txid"] for block in self.chain for transaction in block.transactions}   # one pass over every block

    def balance_of(self, address: str) -> dict:
        """Report what an address holds, what it has waiting to leave, and what it can still spend."""
        confirmed = self.confirmed_balances().get(address, 0)      # the mined balance, or zero for an unknown address
        pending_out = sum(payment["amount"] + payment["fee"]       # add up amount plus fee
                          for payment in self.pending              # over every payment in the pool
                          if payment["sender"] == address)         # that this address is sending
        return {                                                   # a small report in three parts
            "address": address,                                    # whose balance this is
            "confirmed": confirmed,                                # value already mined into the chain
            "pending_out": pending_out,                            # value committed to payments still in the pool
            "available": confirmed - pending_out,                  # what the address may still spend
        }

    def find_transaction(self, txid: str):
        """Look a transaction up by identifier. Return its status, or None if this node has never seen it."""
        for block in self.chain:                                   # search the mined blocks first
            for transaction in block.transactions:                 # and every transaction inside each
                if transaction["txid"] == txid:                    # found it in the chain
                    return {                                       # report where it was mined
                        "status": "confirmed",                     # it is part of the chain
                        "block_index": block.index,                # the block that holds it
                        "confirmations": self.last_block.index - block.index + 1,   # that block plus every block built on top
                        "transaction": transaction,                # the transaction itself
                    }
        for payment in self.pending:                               # otherwise search the pending pool
            if payment["txid"] == txid:                            # found it waiting
                return {                                           # report that it is not yet mined
                    "status": "pending",                           # it is waiting for a block
                    "block_index": None,                           # so it has no block yet
                    "confirmations": 0,                            # and no confirmations
                    "transaction": payment,                        # the payment itself
                }
        return None                                                # this node has never seen that identifier

    def get_block(self, block_hash: str):
        """Return the block with this hash, or None if this node does not hold it."""
        for block in self.chain:              # search the chain
            if block.hash == block_hash:      # compare each stored hash with the one asked for
                return block                  # found it
        return None                           # no block with that hash

    # -----------------------------------------------------------------------
    # Changing the ledger
    # -----------------------------------------------------------------------
    def add_payment(self, data) -> tuple:
        """Try to place a payment in the pending pool. Return (outcome, message, payment)."""
        problem = payment_field_error(data)                                  # first check the shape of the fields
        if problem is not None:                                              # a malformed payment goes no further
            return "invalid", problem, None                                  # say what was wrong
        payment = make_payment(data["sender"], data["receiver"], data["amount"], data.get("reference", ""))   # build the payment and its txid
        if "txid" in data and data != payment:                               # a payment relayed by another node arrives with a txid
            return "invalid", "payment does not match its txid", None        # refuse it if the fields were altered on the way
        already_pending = any(item["txid"] == payment["txid"] for item in self.pending)   # is the same payment already waiting?
        if already_pending or payment["txid"] in self.confirmed_txids():     # or has it already been mined?
            return "duplicate", "this exact payment has already been submitted; change 'reference' to pay again", payment   # refuse the repeat
        cost = payment["amount"] + payment["fee"]                            # what this payment takes from the sender
        available = self.balance_of(payment["sender"])["available"]          # what the sender can still spend
        if cost > available:                                                 # the affordability rule
            return "insufficient_funds", f"'{payment['sender']}' needs {cost} (amount plus fee) but has {available} available", payment   # refuse it
        self.pending.append(payment)                                         # all checks passed, so the payment joins the pool
        return "accepted", "payment accepted into the pending pool", payment # report success

    def mine_pending(self, miner_address: str) -> tuple:
        """Mine one block holding the reward and every pending payment. Return (block, attempts, seconds)."""
        index = self.last_block.index + 1                                    # the new block takes the next position
        total_fees = FEE_PER_PAYMENT * len(self.pending)                     # every pending payment contributes one fee
        coinbase = make_coinbase(miner_address, index, total_fees)           # the reward for whoever is mining
        block = Block(                                                       # assemble the candidate block
            index=index,                                                     # its position
            timestamp=block_timestamp(index),                                # its time on the logical clock
            transactions=[coinbase] + self.pending,                          # the reward first, then the payments in arrival order
            previous_hash=self.last_block.hash,                              # the link to the current newest block
        )
        attempts, seconds = mine_block(block)                                # the proof-of-work search, the only slow step
        self.chain.append(block)                                             # the mined block joins the chain
        self.pending = []                                                    # its payments are no longer pending
        return block, attempts, seconds                                      # report the block and what it cost

    def accept_block(self, block: Block) -> tuple:
        """Try to add a block received from another node. Return (outcome, message)."""
        if self.get_block(block.hash) is not None:                           # this node already holds a block with that hash
            return "duplicate", "block already held"                         # nothing to do
        if block.previous_hash != self.last_block.hash:                      # the block builds on something other than our newest block
            return "detached", "block does not extend this node's newest block"   # the caller will compare whole chains instead
        problem = block_error(block, self.last_block, self.confirmed_balances(), self.confirmed_txids())   # apply every block rule
        if problem is not None:                                              # an invalid block is never stored
            return "rejected", problem                                       # say which rule it broke
        self.chain.append(block)                                             # the block is valid, so it joins the chain
        self._rebuild_pending(self.pending)                                  # payments it mined leave the pending pool
        return "accepted", "block appended"                                  # report success

    def replace_chain(self, blocks: list) -> tuple:
        """Adopt another node's chain if it is valid and longer than ours. Return (replaced, message)."""
        if len(blocks) <= len(self.chain):                                   # only a strictly longer chain can win
            return False, "the other chain is not longer"                    # ties keep the chain seen first
        problem = chain_error(blocks)                                        # validate the candidate from genesis
        if problem is not None:                                              # an invalid chain never wins, whatever its length
            return False, f"the other chain is invalid ({problem})"          # say why it was refused
        dropped = [transaction                                               # collect the payments
                   for block in self.chain                                   # from every block of the chain being abandoned
                   for transaction in block.transactions                     # looking at each transaction
                   if transaction["type"] == "payment"]                      # rewards from abandoned blocks simply vanish
        self.chain = blocks                                                  # adopt the longer chain
        self._rebuild_pending(dropped + self.pending)                        # payments the new chain lacks go back to the pool
        return True, "adopted the longer valid chain"                        # report the switch

    def _rebuild_pending(self, candidates: list):
        """Refill the pending pool, keeping only payments that are still unmined and still affordable."""
        self.pending = []                     # start from an empty pool
        for payment in candidates:            # offer each candidate back to the pool in its original order
            self.add_payment(payment)         # the normal checks drop anything already mined or no longer affordable
