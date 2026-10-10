# Blockchain Assignment 8: REST API and Networking Lab

A blockchain node with a web interface, built to follow one payment from a client's request to a
confirmed block, and then across a network of three nodes.

Course work for **BLCH9X2 Blockchain**, Master of Financial Engineering, University of Johannesburg.
Bukho Ndziweni, student number 220081696.

The node is a REST (Representational State Transfer) API (Application Programming Interface) written
with Flask. It sits on top of the chain built in Assignments 2 to 6: blocks sealed with SHA-256
(Secure Hash Algorithm, 256-bit), proof-of-work mining and a coinbase reward. Every request and
reply is JSON (JavaScript Object Notation) sent over HTTP (HyperText Transfer Protocol).

## Files

| File | What it is |
|---|---|
| `api.py` | The Flask API. One node per process, bound to `127.0.0.1` |
| `network.py` | The peer list and the gossip rules: address relay, `inv` and `getdata`, chain synchronisation |
| `explorer.py` | The block explorer: a text view for the terminal and a web page served at `/explorer` |
| `blockchain.py` | The chain core: blocks, mining, coinbase, pending pool and the validation rules |
| `demo_payment_flow.py` | The scripted demonstration: starts three nodes and prints every request and reply |
| `sample_outputs.txt` | The output of `demo_payment_flow.py`, written by the program |
| `Assignment8_Bukho_Ndziweni_Blockchain_220081696.ipynb` | The same work cell by cell |
| `Assignment8_Bukho_Ndziweni_Blockchain_220081696.html` | The notebook with its outputs, saved as a web page that opens without Jupyter |
| `requirements.txt` | The two external dependencies, Flask and requests |

## Running it

Python 3.8 or later.

```bash
pip install -r requirements.txt
```

There are three ways to run the work. Each one starts from a fresh chain holding only the genesis block.

**1. The scripted demonstration.** Starts three nodes on ports 5000 to 5002, runs the payment flow
and the network steps, and ends with `28 passed, 0 failed`. It takes a few seconds.

```bash
python demo_payment_flow.py           # the full demonstration, also written to sample_outputs.txt
python demo_payment_flow.py --hold    # the same, then keeps the nodes running so the explorer page can be opened
```

**2. The notebook.** Open the `.ipynb` file and choose **Restart Kernel and Run All Cells**.

**3. By hand.** Start a node in one terminal and send it requests from another, using the curl
sequence further down.

```bash
python api.py                 # one node on port 5000
python api.py --port 5001     # a second node, in a second terminal
python explorer.py            # the explorer's text view of the node on port 5000
```

If port 5000 is taken on your machine, `python api.py --port 5100` and
`python demo_payment_flow.py --base-port 5100` use other ports.

## Endpoints

| Method | Path | Purpose | Success | Refusals |
|---|---|---|---|---|
| GET | `/chain` | The full chain | 200 | |
| POST | `/transactions/new` | Submit a payment | 201 | 400, 409, 422 |
| POST | `/mine` | Mine a block holding the pending payments | 201 | 400 |
| GET | `/nodes` | This node's peer list | 200 | |
| POST | `/nodes/register` | Add peers | 201 or 200 | 400 |
| GET | `/` | Status of the node and a list of endpoints | 200 | |
| GET | `/transactions/pending` | Payments waiting to be mined | 200 | |
| GET | `/transactions/<txid>` | One transaction and its confirmations | 200 | 404 |
| GET | `/balance/<address>` | What an address holds and can spend | 200 | 400 |
| GET | `/nodes/resolve` | Adopt the longest valid chain among the peers | 200 | |
| POST | `/inv` | A peer announces that it holds a hash | 200 | 400, 403 |
| GET | `/getdata/<type>/<hash>` | The full transaction or block behind a hash | 200 | 400, 404 |
| GET | `/log` | This node's gossip log | 200 | |
| GET | `/explorer` | The explorer as a web page | 200 | |

The first five are the endpoints the brief requires. Every refusal has the same shape, a JSON
object with one `error` field explaining what was wrong. An unknown path returns 404 and a wrong
method (for example `GET /mine`) returns 405, both in that shape.

### The two objects

Every reply is built from two objects.

A **transaction** has seven fields:

| Field | Type | Meaning |
|---|---|---|
| `type` | text | `"payment"` or `"coinbase"` (the block reward) |
| `sender` | text or null | Who pays. Null for a coinbase, which creates new units |
| `receiver` | text | Who is paid |
| `amount` | whole number | The value moved, in whole units |
| `fee` | whole number | 1 for a payment, paid to the miner. 0 for a coinbase |
| `reference` | text | The payer's reference. For a coinbase, `reward for block N` |
| `txid` | text | The transaction's identifier: the SHA-256 hash of the six fields above |

A **block** has six fields:

| Field | Type | Meaning |
|---|---|---|
| `index` | whole number | Position in the chain. The genesis block is 0 |
| `timestamp` | whole number | Unix time from the logical clock: genesis time plus 600 seconds per block |
| `transactions` | list | The coinbase first, then the payments in the order they arrived |
| `previous_hash` | text | The hash of the block before it |
| `nonce` | whole number | The value the miner found |
| `hash` | text | SHA-256 of the five fields above. It must start with four zeros |

An address is 1 to 64 letters, digits, hyphens or underscores.

### Contracts

The replies below are the real replies from the demonstration, in the order it runs. Flask sends
them on one line; they are indented here for reading.

#### GET /chain

No body. Returns 200.

```json
{
  "length": 1,
  "difficulty": 4,
  "chain": [
    {
      "index": 0,
      "timestamp": 1790812800,
      "transactions": [],
      "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "nonce": 16969,
      "hash": "0000b4bcb3caad5c9e80b5c9cc18f3cecfa7f1a70ff0c46b8347937b3de41f13"
    }
  ]
}
```

`length` counts the genesis block. `difficulty` is the number of leading zeros every block hash must show.

#### POST /mine

Body, optional: `{"miner": "alice"}`. The miner is the address that receives the reward. Without a
body the reward goes to the node's own address, `miner-<port>`.

Returns 201:

```json
{
  "message": "block 1 mined",
  "block": {
    "index": 1,
    "timestamp": 1790813400,
    "transactions": [
      {
        "type": "coinbase",
        "sender": null,
        "receiver": "alice",
        "amount": 50,
        "fee": 0,
        "reference": "reward for block 1",
        "txid": "b3969a560d8f9b685f10b7917c01b8aa464d5949c7136cc9edc83ecc7d92f484"
      }
    ],
    "previous_hash": "0000b4bcb3caad5c9e80b5c9cc18f3cecfa7f1a70ff0c46b8347937b3de41f13",
    "nonce": 112065,
    "hash": "0000d180ac57b00df72b03e2574d9665fe7d36cca699dc373a975a82a10c43d9"
  },
  "attempts": 112066,
  "seconds": <time taken on your machine>,
  "announced_to": []
}
```

`attempts` is the number of hashes tried. `seconds` is the mining time rounded to three decimals.
`announced_to` lists the peers that were told about the block, which is empty here because the node
has no peers yet. Returns 400 if `miner` is not a valid address.

Mining with nothing pending is allowed and produces a block holding only the coinbase. That is how
an address is first funded.

#### POST /transactions/new

Body:

```json
{"sender": "alice", "receiver": "bob", "amount": 20, "reference": "remittance-001"}
```

`sender`, `receiver` and `amount` are required. `reference` is optional and defaults to an empty string.

Returns 201 when the payment enters the pending pool:

```json
{
  "message": "payment accepted into the pending pool",
  "transaction": {
    "type": "payment",
    "sender": "alice",
    "receiver": "bob",
    "amount": 20,
    "fee": 1,
    "reference": "remittance-001",
    "txid": "52ad97a885a7b741ae1e2729c86f98ea666221353bdf2e92a6f4e76777488aa1"
  },
  "pending_count": 1,
  "announced_to": []
}
```

The three refusals:

| Status | When | Reply |
|---|---|---|
| 400 | A field is missing or malformed: not JSON, an invalid address, sender equal to receiver, or an amount that is not a whole number above zero | `{"error": "'amount' must be a whole number greater than zero"}` |
| 409 | This exact payment was already submitted, so it has the same `txid` | `{"error": "this exact payment has already been submitted; change 'reference' to pay again", "txid": "52ad97a885a7b741ae1e2729c86f98ea666221353bdf2e92a6f4e76777488aa1"}` |
| 422 | The amount plus the fee is more than the sender has available | `{"error": "'alice' needs 501 (amount plus fee) but has 29 available"}` |

A 201 means the node accepted the payment for mining. It does not mean the payment has settled.
Settlement is read from `GET /transactions/<txid>`.

#### GET /transactions/pending

No body. Returns 200.

```json
{
  "count": 1,
  "transactions": [
    {
      "type": "payment",
      "sender": "alice",
      "receiver": "bob",
      "amount": 20,
      "fee": 1,
      "reference": "remittance-001",
      "txid": "52ad97a885a7b741ae1e2729c86f98ea666221353bdf2e92a6f4e76777488aa1"
    }
  ]
}
```

#### GET /balance/&lt;address&gt;

No body. Returns 200. This reply was taken while Alice's payment was still pending:

```json
{
  "address": "alice",
  "confirmed": 50,
  "pending_out": 21,
  "available": 29
}
```

`confirmed` is the balance mined into the chain. `pending_out` is the amount plus fee of the
address's payments still in the pool. `available` is the difference, and is what a new payment is
checked against. An address the chain has never seen returns zeros. Returns 400 if the address
contains characters an address cannot have.

#### GET /transactions/&lt;txid&gt;

No body. Returns 200. This reply was taken after block 2 was mined:

```json
{
  "status": "confirmed",
  "block_index": 2,
  "confirmations": 1,
  "transaction": {
    "type": "payment",
    "sender": "alice",
    "receiver": "bob",
    "amount": 20,
    "fee": 1,
    "reference": "remittance-001",
    "txid": "52ad97a885a7b741ae1e2729c86f98ea666221353bdf2e92a6f4e76777488aa1"
  }
}
```

`status` is `"confirmed"` or `"pending"`. For a pending payment `block_index` is null and
`confirmations` is 0. Confirmations count the block holding the transaction plus every block built
on top of it. Returns 404 if the node has never seen the `txid`.

#### POST /nodes/register

Body: a list of one or more node addresses.

```json
{"nodes": ["http://127.0.0.1:5001"]}
```

Returns 201 when at least one peer was new:

```json
{
  "message": "1 peer(s) added",
  "added": [
    "127.0.0.1:5001"
  ],
  "already_known": [],
  "rejected": [],
  "nodes": [
    "127.0.0.1:5001"
  ]
}
```

`added`, `already_known` and `rejected` say what happened to each address, and `nodes` is the full
peer list afterwards. Returns 200 with `"message": "no new peers, all were already known"` when
nothing was new. Returns 400 when the body has no `nodes` list, or when nothing was added and at
least one address was refused:

```json
{
  "error": "no peer was added",
  "added": [],
  "already_known": [],
  "rejected": [
    {
      "address": "http://example.com:5000",
      "reason": "not an http address on this computer (127.0.0.1 or localhost) with a port"
    }
  ],
  "nodes": [
    "127.0.0.1:5001",
    "127.0.0.1:5002"
  ]
}
```

Only `http` addresses on `127.0.0.1` or `localhost` with a port are accepted. `localhost:5001`,
`127.0.0.1:5001` and `http://127.0.0.1:5001/` are all stored as `127.0.0.1:5001`.

Nodes also use this endpoint to talk to each other. A node passing addresses on adds a `from` field
holding its own address, and the receiver registers that sender as a peer too.

#### GET /nodes

No body. Returns 200. This reply is from node A after node C joined:

```json
{
  "node": "127.0.0.1:5000",
  "count": 2,
  "nodes": [
    "127.0.0.1:5001",
    "127.0.0.1:5002"
  ]
}
```

#### GET /nodes/resolve

No body. Returns 200. The node downloads each peer's chain and adopts one if it is valid and
strictly longer than its own. This reply is from node B, which held only the genesis block:

```json
{
  "message": "chain replaced by a longer valid chain",
  "replaced": true,
  "length": 3,
  "checked": [
    {
      "peer": "127.0.0.1:5000",
      "adopted": true,
      "detail": "adopted the longer valid chain"
    },
    {
      "peer": "127.0.0.1:5002",
      "adopted": false,
      "detail": "the other chain is not longer"
    }
  ]
}
```

When no peer has a longer valid chain, `replaced` is false and `message` is
`"this node's chain was kept"`.

#### POST /inv

Sent by one node to another, not by a client. It announces a hash without sending the item.

```json
{"type": "block", "hash": "0000477c464f83742b3706bc70b79c9c134ccad477a642a32c2a7f7618dfde4e", "from": "127.0.0.1:5001"}
```

`type` is `"tx"` or `"block"`. Returns 200 with the action the receiver took:

```json
{
  "action": "ignored",
  "detail": "already held"
}
```

| `action` | Meaning |
|---|---|
| `ignored` | The receiver already holds the item |
| `fetched` | The receiver requested the item with `getdata`, checked it and stored it |
| `synchronised` | The block did not attach to the receiver's chain, so it downloaded the sender's chain and adopted it |
| `rejected` | The item failed a check and was not stored. `detail` says which |
| `failed` | The sender did not supply the item when asked |

Returns 403 if `from` is not a registered peer, and 400 if `type` or `hash` is malformed.

#### GET /getdata/&lt;type&gt;/&lt;hash&gt;

No body. `type` is `tx` or `block`. Returns 200 with the transaction or block object itself:

```json
{
  "type": "payment",
  "sender": "alice",
  "receiver": "bob",
  "amount": 20,
  "fee": 1,
  "reference": "remittance-001",
  "txid": "52ad97a885a7b741ae1e2729c86f98ea666221353bdf2e92a6f4e76777488aa1"
}
```

Returns 404 if the node does not hold the item, and 400 for any other `type`.

#### GET /log

No body. Returns 200 with every gossip message the node has sent or received. This is node B's log
after it joined the network and caught up:

```json
{
  "node": "127.0.0.1:5001",
  "count": 4,
  "events": [
    {
      "seq": 6,
      "node": "127.0.0.1:5001",
      "event": "got addr from :5000: learned :5000"
    },
    {
      "seq": 11,
      "node": "127.0.0.1:5001",
      "event": "got addr from :5000: learned :5002"
    },
    {
      "seq": 12,
      "node": "127.0.0.1:5001",
      "event": "sent addr (:5001) to :5002"
    },
    {
      "seq": 16,
      "node": "127.0.0.1:5001",
      "event": "adopted the chain of :5000, now 3 blocks"
    }
  ]
}
```

`seq` comes from one counter per Python process. In the demonstration and the notebook all three
nodes run in one process, so sorting the three logs by `seq` gives the order in which messages
crossed the network. Nodes started in separate terminals each count on their own.

#### GET /

No body. Returns 200.

```json
{
  "node": "127.0.0.1:5000",
  "chain_length": 3,
  "pending_count": 0,
  "peer_count": 2,
  "endpoints": [
    "GET  /                       status of this node and this list",
    "GET  /chain                  the full chain",
    "POST /transactions/new       submit a payment",
    "GET  /transactions/pending   payments waiting to be mined",
    "GET  /transactions/<txid>    one transaction and its confirmations",
    "POST /mine                   mine a block holding the pending payments",
    "GET  /balance/<address>      what an address holds and can spend",
    "GET  /nodes                  this node's peer list",
    "POST /nodes/register         add peers",
    "GET  /nodes/resolve          adopt the longest valid chain among the peers",
    "POST /inv                    announcement of a hash by a peer",
    "GET  /getdata/<type>/<hash>  the full transaction or block behind a hash",
    "GET  /log                    this node's gossip log",
    "GET  /explorer               web page of recent blocks and transactions"
  ]
}
```

#### GET /explorer

No body. Returns 200 with a web page (`text/html`) rather than JSON.

## The payment flow with curl

With `python api.py` running, these commands reproduce section 1 of the demonstration. They are
written for Command Prompt on Windows and also work unchanged in bash. Windows PowerShell handles
quotation marks differently, so use Command Prompt or `python demo_payment_flow.py` there.

```bash
curl http://127.0.0.1:5000/chain
curl -X POST http://127.0.0.1:5000/mine -H "Content-Type: application/json" -d "{\"miner\": \"alice\"}"
curl http://127.0.0.1:5000/balance/alice
curl -X POST http://127.0.0.1:5000/transactions/new -H "Content-Type: application/json" -d "{\"sender\": \"alice\", \"receiver\": \"bob\", \"amount\": 20, \"reference\": \"remittance-001\"}"
curl http://127.0.0.1:5000/transactions/pending
curl -X POST http://127.0.0.1:5000/mine -H "Content-Type: application/json" -d "{\"miner\": \"miner-a\"}"
curl http://127.0.0.1:5000/transactions/52ad97a885a7b741ae1e2729c86f98ea666221353bdf2e92a6f4e76777488aa1
curl http://127.0.0.1:5000/balance/bob
```

| Step | What happens | Expected |
|---|---|---|
| 1 | The chain holds only the genesis block | `"length": 1` |
| 2 | Alice mines block 1 and earns the reward | 201, block hash `0000d180...` |
| 3 | Alice now has funds | `"confirmed": 50` |
| 4 | Alice submits a payment of 20 to Bob | 201, `txid` `52ad97a8...` |
| 5 | The payment waits in the pending pool | `"count": 1` |
| 6 | A miner mines block 2, which includes the payment | 201, block hash `0000477c...` |
| 7 | The payment is confirmed | `"status": "confirmed"`, `"confirmations": 1` |
| 8 | Bob has been paid | `"confirmed": 20` |

Because the chain is reproducible, the `txid` in step 7 is the same on every machine. Sending step 4
a second time returns 409, and changing its amount to 500 returns 422.

To add a second node, start it with `python api.py --port 5001` and then:

```bash
curl -X POST http://127.0.0.1:5000/nodes/register -H "Content-Type: application/json" -d "{\"nodes\": [\"http://127.0.0.1:5001\"]}"
curl http://127.0.0.1:5001/nodes
curl http://127.0.0.1:5001/nodes/resolve
```

## The explorer

`python explorer.py` reads a running node through `GET /chain`, `GET /transactions/pending` and
`GET /nodes`, and prints a summary of the node, its recent blocks, its recent transactions, its
pending payments and the balance of every address. The same view is served as a web page at
`http://127.0.0.1:5000/explorer`.

```bash
python explorer.py                                 # the node on port 5000
python explorer.py --node http://127.0.0.1:5001    # a different node
python explorer.py --last 10                       # up to 10 rows per table
python explorer.py --html explorer.html            # also save the page to a file
```

Block times in the explorer are in UTC (Coordinated Universal Time) and come from the logical
clock, so they step by ten minutes per block whatever the real time is.

## How the network layer maps to Bitcoin

Bitcoin nodes hold long-lived connections and exchange named messages. This lab keeps the same
ideas and sends each message as one HTTP request.

| Bitcoin message | This lab | What it does |
|---|---|---|
| `version` / `verack` | The `from` field of `POST /nodes/register` | A node introduces itself, and the receiver records it as a peer |
| `getaddr` | `GET /nodes` | Ask a node which peers it knows |
| `addr` | `POST /nodes/register` | Tell a node about peers. New addresses are passed on, known ones are not |
| `inv` | `POST /inv` | Announce a transaction or block by hash only |
| `getdata` | `GET /getdata/<type>/<hash>` | Ask for the full item behind a hash |
| `tx` / `block` | The JSON reply to `getdata` | The item itself |
| `getheaders` / `getblocks` | `GET /chain`, used by `GET /nodes/resolve` | Catch up with a peer's chain |

Gossip ends by itself. A node only passes on what was new to it, an address it did not know or a
hash it did not hold, so once every node has an item the announcements are ignored and stop.

In section 3 of the demonstration node C is told about node A only, and learns of node B from the
addresses that A and B pass on. A payment submitted to node C then reaches A and B by `inv` and
`getdata`, and a block mined by node B reaches A and C the same way.

## The rules

A payment is accepted into the pending pool only if:

1. its fields are well formed,
2. its `txid` is not already in the pool or the chain, and
3. the sender's available balance covers the amount plus the fee of 1.

Rule 2 makes submission idempotent. The `txid` is the hash of the payment's own fields, so a
request that is retried after a timeout produces the same `txid` and is refused with 409 instead of
paying twice. To make the same payment again on purpose, change the `reference`.

A block received from a peer is appended only if its index, parent hash, logical-clock timestamp,
stored hash and proof of work are all correct, its coinbase pays exactly 50 plus the fees, and every
payment inside it passes the same three rules. A whole chain from a peer is adopted only if it
starts from the same genesis block, passes those checks block by block and is strictly longer.
With equal lengths a node keeps the chain it saw first. Because every block is mined at the same
difficulty, the longest valid chain is also the one with the most work.

When a node switches chains, payments that were only in its abandoned blocks go back to its pending
pool if they are still affordable.

## Reproducibility

Block timestamps come from a logical clock, genesis time plus 600 seconds per block, and every
nonce search starts at zero. Every hash, nonce, `txid` and balance in this README and in
`sample_outputs.txt` therefore reproduces on any machine. The one exception is the `seconds` field
of `POST /mine`, which is measured on the machine doing the mining.

The logical clock is also a consensus rule: a block whose timestamp is not genesis time plus 600
seconds times its index is rejected.

## Safety

The server binds to `127.0.0.1`, so it accepts connections from the same computer only. Peers can
only be registered on `127.0.0.1` or `localhost`, so a node cannot be told to send requests to
another machine. There is no login and payments are not signed: anyone who can reach the API can
submit a payment in any sender's name. That is acceptable for a demonstration on one computer and
for nothing else, so the host should not be changed to expose the node on a network.

## Scope

Payments are not signed, so the `sender` field is a claim and not proof. The wallet and signature
work from Assignment 4 would have to be added before the API could face a network. Balances are
kept per account, not as unspent outputs. Difficulty is fixed and there is no retargeting, which
Assignment 6 covered. Each `inv` announces one hash and is sent to every peer in turn, where Bitcoin
batches many hashes into one message and tracks what each peer already knows. Peers are never
checked for liveness or removed. The chain and the pending pool are held in memory, so a node that
is restarted begins again from the genesis block and catches up with `GET /nodes/resolve`.

Two nodes can each accept a payment from the same sender at the same moment, each seeing enough
funds. Both clients receive 201. Whichever payment is mined first stands, and the other is dropped
from every pool when that block arrives. The ledger stays correct, but this is why a 201 from
`POST /transactions/new` is not settlement, and why a client must wait for confirmations.
