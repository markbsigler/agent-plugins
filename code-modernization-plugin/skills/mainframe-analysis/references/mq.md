# IBM MQ on z/OS

MQ carries asynchronous contracts and takes part in units of work. The options on each MQI call, not the queue names, decide durability, ordering, and recovery, so inventory both the object definitions and the calls before designing a replacement.

## Queue managers and queue-sharing groups

- A queue manager is a z/OS subsystem with a name of up to 4 characters. Programs reach it through an adapter: CICS, IMS, batch and TSO, or RRS.
- A queue-sharing group joins queue managers in a sysplex. Shared queues (`QSGDISP(SHARED)`) live in coupling facility structures, so any member can serve them; group definitions (`QSGDISP(GROUP)`) are stored in Db2 and copied to every member (`QSGDISP(COPY)`).
- Persistent messages are logged; on shared queues they are recovered with `BACKUP CFSTRUCT` and `RECOVER CFSTRUCT`. Nonpersistent messages are lost when a structure fails and, on private queues, when the queue manager restarts.

## Objects

| Object | Purpose | Watch for |
| --- | --- | --- |
| `QLOCAL` | Holds messages | `DEFPSIST`, `MAXDEPTH`, `MAXMSGL`, `MSGDLVSQ` (`PRIORITY` or `FIFO`), `INDXTYPE`, `BOTHRESH`, `BOQNAME`, trigger attributes |
| `QREMOTE` | Local definition of a remote queue (`RNAME`, `RQMNAME`, `XMITQ`), or a queue manager or reply-to alias | Routing that the program never shows |
| `QALIAS` | Another name for a queue or topic (`TARGET`) | Programs and security profiles can use either name |
| `QMODEL` | Template for dynamic queues created at `MQOPEN` | Temporary reply queues (`DEFTYPE(TEMPDYN)`) |
| Transmission queue | `QLOCAL` with `USAGE(XMITQ)` drained by a sender channel | Messages wait here while a partner is down |
| Channels | Sender and receiver, server and requester, server-connection for clients, cluster channels | `CONNAME`, TLS (`SSLCIPH`), `MCAUSER`, `CONVERT` |
| `PROCESS` | What a trigger starts (`APPLTYPE`, `APPLICID`, `USERDATA`) | For CICS, `APPLICID` is a transaction to map to programs |
| Initiation queue | Receives trigger messages for a trigger monitor | `CKTI` in CICS; trigger monitors must be running |

Triggering (`TRIGGER`, `TRIGTYPE` of `FIRST`, `EVERY`, or `DEPTH`, `INITQ`, `PROCESS`) starts programs that no caller in the code shows. Record every trigger chain in the dependency graph.

## MQI options that change behavior

| Option or field | Behavior to preserve |
| --- | --- |
| `MQPMO_SYNCPOINT`, `MQGMO_SYNCPOINT` | When neither the syncpoint nor the no-syncpoint option is coded, puts and gets on z/OS run inside the unit of work; on other platforms they run outside it. State the option explicitly in ported code |
| Unit of work | CICS: `EXEC CICS SYNCPOINT` or task end commits MQ with VSAM, Db2, and TS and TD queues (`MQCMIT` cannot be used). IMS: MQ follows IMS syncpoints (`GU` to the I/O PCB, `CHKP`). Batch with `CSQBSTUB`: `MQCMIT` and `MQBACK` cover MQ only; with the RRS stubs `CSQBRRSI` and `CSQBRSTB`, RRS commits MQ and Db2 together (`SRRCMIT`). A batch program that ends normally without `MQDISC` commits; an abend backs out |
| Persistence (MQMD `Persistence`, queue `DEFPSIST`) | Whether a message survives failures |
| `MQGMO_WAIT` and `WaitInterval` | How long a get waits; reason code 2033 (`MQRC_NO_MSG_AVAILABLE`) often ends a batch loop |
| Browse (`MQGMO_BROWSE_FIRST`, `MQGMO_BROWSE_NEXT`, `MQGMO_MSG_UNDER_CURSOR`) | Reading without removing, and browse-then-get patterns |
| `MQGMO_CONVERT` with MQMD `Format`, `CodedCharSetId`, `Encoding` | The queue manager converts `MQSTR` messages as text, never converts `MQFMT_NONE`, and needs a data-conversion exit for other formats. `Encoding` gives the byte order of binary, packed, and float fields (z/OS native 785, x86 546). Packed or binary fields inside an `MQSTR` message are corrupted by conversion |
| Groups (`MQMF_MSG_IN_GROUP`, `GroupId`, `MsgSeqNumber`, `MQGMO_LOGICAL_ORDER`, `MQGMO_ALL_MSGS_AVAILABLE`) | Multi-message business transactions. Message segmentation is not supported on z/OS |
| `MsgId`, `CorrelId`, `MQMO_MATCH_CORREL_ID` | Request and reply matching; repliers usually copy the request `MsgId` into the reply `CorrelId` |
| `ReplyToQ`, `ReplyToQMgr` | Where replies go, often a dynamic queue created from a model |
| `BackoutCount`, `BOTHRESH`, `BOQNAME`, `HARDENBO` | The queue manager only counts backouts. MQI programs must compare the count with the threshold and move poison messages to the backout queue themselves (the IBM MQ classes for JMS do this for Java). `MQGMO_MARK_SKIP_BACKOUT` avoids get-fail-backout loops |
| Dead-letter queue (`DEADQ`) | Undeliverable messages arrive with an `MQDLH` header and a reason code; the `CSQUDLQH` utility processes them with a rules table |

## Adapters and bridges

- **CICS-MQ adapter:** supplied with CICS. The `MQCONN` resource defines the connection, programs link-edit the `CSQCSTUB` stub, and the adapter's task-related user exit runs on open TCBs, so threadsafe programs avoid TCB switches. `CKTI` and `MQMONITOR` resources start transactions from trigger messages.
- **CICS-MQ bridge:** runs a CICS DPL program for each request message that begins with an `MQCIH` header. The monitor transaction `CKBR` reads the bridge queue, and programs run under `CKBP` unless the header names another transaction. The program has no MQ calls, so its COMMAREA layout is the message contract.
- **IMS-MQ bridge:** an OTMA client in the same XCF group and sysplex as IMS. Bridge queues use a storage class that names the IMS XCF group and member; messages carry an `MQIIH` header (without one, commit mode 0 is assumed) followed by LLZZ segments; the MQMD `UserIdentifier` drives IMS security checks.

## Kafka connectors

- The IBM MQ source and sink connectors for Kafka Connect copy messages between queues and topics. IBM MQ Advanced for z/OS includes a Connector Pack that runs them in z/OS UNIX; they also run off-platform as MQ clients.
- Delivery is at least once by default. Exactly-once mode needs a state queue, a single task, and distributed Connect workers; make consumers idempotent either way.
- The source connector can take the Kafka record key from `MsgId`, `CorrelId`, or `GroupId` (`mq.record.builder.key.header`). The key chooses the partition and therefore the order that consumers see.

## Message layouts are contracts

- The payload is usually a copybook, often the same one a COMMAREA uses. Compute it with the `copybook-data` skill's `copybook_layout.py`; headers in front of the payload (`MQCIH`, `MQIIH`, `MQRFH2`) are part of the contract.
- `Format`, `CodedCharSetId`, and `Encoding` must describe the bytes actually sent. Payloads that mix text with packed or binary fields need `MQFMT_NONE` (or a conversion exit) and field-by-field conversion from the layout.
- Add a version field or a new format name before any consumer moves off-platform, and keep sample messages of every format as test data.

## Ordering

One getter receives messages in put order only if all of these hold: one putting application; all puts in one unit of work, or all outside one; the same priority and persistence; a single route between queue managers; no message diverted to a dead-letter queue; and a getter that does not select by `MsgId`, `CorrelId`, or priority. Several getters, several channels, or clusters break the order, and on z/OS a queue indexed by `GROUPID` does not keep physical order. Record which consumers depend on order before changing any of these.

## Mapping to event streaming (Rearchitect)

| MQ pattern | Event-streaming design | Decide |
| --- | --- | --- |
| Queue with competing consumers | Topic and consumer group | Partition key that keeps the required order |
| Request and reply with `CorrelId` | Synchronous API, or request and reply topics with a correlation header | Time-outs and orphaned replies |
| Trigger-started program | Consumer service | Scaling and back-pressure |
| Db2 update and `MQPUT` in one unit of work | Transactional outbox or change data capture | Never dual-write from the program |
| Backout and dead-letter queues | Retry and dead-letter topics | Who repairs and replays |
| Persistent messages | Replicated topic with acknowledged writes | Retention replaces queue depth |
| Priority, expiry, browse | No direct equivalent | Separate topics, retention, or a state store |

During transition, keep MQ at the boundary: bridge queues and topics with the connectors, use `MsgId` as the idempotency key, and reconcile counts on both sides.

## What to inventory

- MQSC definitions for every queue manager: `CSQUTIL COMMAND` with `MAKEDEF` ([../assets/mqsc-export.jcl](../assets/mqsc-export.jcl)) or `DISPLAY ... ALL` output, plus the `CSQINP2` initialization members. `mainframe_inventory.py` reads the MQSC definitions.
- Queue names in programs (`MQOD` `ObjectName` literals, names loaded from tables or files, model queues), and queue and `PROCESS` names in CICS definitions.
- For each call: open, put, and get options, persistence, `Format`, CCSID, and headers.
- The stub each program links (`CSQBSTUB`, `CSQBRRSI`, `CSQBRSTB`, `CSQCSTUB`), which shows its commit model.
- Channel partners, volumes, and peak depths (MQ SMF type 115 statistics and type 116 accounting), message copybooks, and the owner of every consumer.
