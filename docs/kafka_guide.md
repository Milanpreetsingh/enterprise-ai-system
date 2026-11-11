# Apache Kafka: Core-to-Advanced Masterclass Guide

Welcome to Apache Kafka! This guide is designed to take you from a complete beginner to an advanced understanding of Kafka's architecture. Since you have experience with RabbitMQ, we will directly address your questions about **Brokers**, **Topics**, **Partitions**, **Consumer Groups**, **Exactly-Once Semantics (EOS)**, and **KRaft Mode**.

---

## 1. Concept Mapping: Quick Reference

| RabbitMQ Concept | Kafka Equivalent | Key Architectural Difference |
| :--- | :--- | :--- |
| **Message Broker** | **Distributed Commit Log** | RabbitMQ deletes messages after delivery. Kafka persists messages to disk in an append-only log for a configurable retention period. |
| **Exchange** | **Topic** | RabbitMQ routes messages dynamically using bindings. Kafka topics write messages sequentially, and routing is determined by the producer using **Message Keys**. |
| **Queue** | **Partition** | A RabbitMQ queue is a smart buffer. A Kafka partition is a physical file on a broker disk containing immutable records. |
| **Consumer** | **Consumer Group Member** | RabbitMQ load-balances queue messages to active consumers. Kafka assigns entire partitions exclusively to specific consumers in a group. |

---

## 2. Core Concepts: Core to Advanced

Let's break down the core architectural components of Kafka.

### A. Broker (The Storage Node)
A **Broker** is a single Kafka server running on a physical or virtual machine. Multiple brokers connect to form a **Kafka Cluster**.
* **Replication:** Each topic partition is duplicated across multiple brokers to prevent data loss. The configuration is called `replication-factor` (e.g., a factor of `3` means data is stored on 3 brokers).
* **Leader vs. Follower:** For every partition, one broker is designated as the **Leader**, and the others are **Followers**.
  * All writes (producers) and reads (consumers) go directly through the **Leader**.
  * Followers asynchronously pull data from the leader to keep their copies up to date.
* **ISR (In-Sync Replicas):** The set of followers that are caught up with the leader. If the leader broker crashes, one of the brokers in the ISR is automatically promoted to be the new leader.

```
       [ Client Producer ]
               │
               ▼ (Writes to Leader)
┌──────────────────────────────────────────────┐
│  Broker 1 (Leader for Partition 0)           │
└──────────────────────┬───────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼ (Followers replicate data)    ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│  Broker 2 (Follower)         ││  Broker 3 (Follower)         │
└──────────────────────────────┘└──────────────────────────────┘
```

### B. Topic (The Logical Channel)
A **Topic** is a logical stream of messages (similar to a database table or a folder). Topics are named and hold a category of messages (e.g., `order-events` or `user-signups`).

### C. Partition (The Scale-out Unit)
A topic is divided into **Partitions** distributed across brokers in the cluster.
* **Append-Only Log:** A partition is physically represented as directories on the broker's disk. Messages are written sequentially to the end of the log and are immutable.
* **Offset:** Every message inside a partition gets a sequential index number called an **offset** (e.g., 0, 1, 2, 3...). Offsets are local to the partition (Partition 0 has offset 5, Partition 1 has its own offset 5).
* **How Messages are Distributed:** When a producer publishes a message:
  * **Without a Key:** Messages are distributed round-robin or using sticky partitioning across all partitions.
  * **With a Key (e.g., `UserID` or `OrderID`):** Kafka hashes the key (`hash(key) % total_partitions`) to determine the target partition. All events with the same key are guaranteed to land on the *same partition*, securing **strict ordering** for that entity.

```
Topic: order-events
┌────────────────────────────────────────────────────────┐
│ Partition 0:  [Offset 0] -> [Offset 1] -> [Offset 2]   │
├────────────────────────────────────────────────────────┤
│ Partition 1:  [Offset 0] -> [Offset 1]                 │
├────────────────────────────────────────────────────────┤
│ Partition 2:  [Offset 0] -> [Offset 1] -> [Offset 2]   │
└────────────────────────────────────────────────────────┘
```

### D. Consumer Group (Scalability & Fault Tolerance)
A **Consumer Group** is a collection of consumers working together to process messages from one or more topics (identified by a `group.id`, e.g., `user-service-group`).
* **Exclusive Partition Assignment:** Inside a group, each partition is assigned to **exactly one** consumer instance.
* **Scaling Consumers:**
  * If a topic has 4 partitions and your consumer group has 2 instances, each instance processes 2 partitions.
  * If you scale the group to 4 instances, each instance gets exactly 1 partition.
  * If you add a 5th instance, it sits **idle** because there are no available partitions. To support higher consumer concurrency, you must increase the partition count of the topic.
* **Consumer Group Coordinator:** A designated broker that manages the group. Consumers send periodic **heartbeats** to the coordinator. If a consumer crashes and stops sending heartbeats, the coordinator triggers a **Rebalance**, reassigning its partitions to the remaining healthy consumers.

---

## 3. Advanced Concepts: EOS & KRaft Mode

### A. Exactly-Once Semantics (EOS)
In messaging systems, there are three types of delivery guarantees:
1. **At-Least-Once (Default):** Messages are guaranteed to be delivered, but duplicates may occur (e.g., consumer crashes after processing but before committing the offset).
2. **At-Most-Once:** Messages are never duplicated, but may be lost (e.g., consumer commits offset before processing, then crashes).
3. **Exactly-Once (EOS):** The message is processed exactly once, with zero duplicates and zero loss.

#### How Kafka Achieves EOS:
Kafka achieves EOS via two main mechanisms:
* **Idempotent Producers:** The broker assigns a unique Producer ID (`PID`) and sequence number to every batch of messages. If a network glitch occurs and the producer retries sending a batch the broker already saved, the broker detects the duplicate sequence number and discards it, preventing duplicates.
* **Transactional Writes (Read-Process-Write):** Under the hood, Kafka uses a **Transaction Coordinator** and transaction logs. This allows a consumer-producer application to bundle reading input messages, writing intermediate states, and publishing output messages in a single atomic transaction. Either all actions succeed, or none do (offset commits are marked as read only when the transaction commits).

---

### B. KRaft Mode (Kafka Raft Metadata Mode)
Yes! **We are using KRaft mode** in our docker-compose configuration.

Historically, Kafka required **Apache ZooKeeper** to manage cluster metadata, leader elections, and configuration. ZooKeeper added complexity, doubled network connections, and caused scalability bottlenecks.

**KRaft** replaces ZooKeeper entirely:
* **Self-Managed Metadata:** Metadata management is built directly inside Kafka.
* **Raft Consensus:** Designated brokers function as **Controllers** and run the Raft consensus algorithm to replicate metadata logs.
* **Key Benefits:**
  * **Ultra-fast metadata replication:** Leader elections that took minutes in ZooKeeper take milliseconds under KRaft.
  * **Simpler architecture:** You run and manage only one type of system (Kafka), instead of two separate systems (Kafka + ZooKeeper).
  * **Scalability:** Kafka clusters can scale past tens of thousands of partitions easily.

---

## 4. Crucial Kafka Features You Must Learn

Beyond the basics, here are the advanced concepts we will leverage or you should keep in mind:

1. **Log Compaction:**
   By default, Kafka deletes logs based on time (e.g., delete after 7 days) or size. However, with **Log Compaction**, Kafka guarantees that it will keep *at least the last known value* for each message key. This is perfect for maintaining the current state of database records (like current user profiles or account balances) over long periods.
2. **Zero-Copy Disk I/O:**
   How does Kafka achieve insane performance? When a consumer reads data, Kafka bypasses the application space entirely. It uses the OS kernel's `sendfile()` system call to transfer byte buffers directly from the disk's page cache to the network socket.
3. **Consumer Lag:**
   The difference between the latest offset written by the producer and the latest offset read by the consumer. **Consumer Lag is the primary operational metric** you monitor to determine if your service is bottlenecked or running slow.

---

## 5. Our Concrete Phase 3 Coding Steps

To bring these concepts to life in our monorepo:

### Step 1: Set Up `segmentio/kafka-go`
We will import `segmentio/kafka-go` in both `services/order` and `services/user`. We choose this library because it is pure Go, CGO-free, and handles context-driven asynchronous execution naturally.

### Step 2: Implement the Kafka Producer (Order Service)
* When an order is created, the Order Service will write an event to the `order-events` topic.
* We will use the `OrderID` or `UserID` as the **Message Key** to ensure all events related to a specific order/user are consistently routed to the same **Partition**, securing strict message ordering.

### Step 3: Implement the Kafka Consumer (User Service)
* The User Service will launch a background loop as part of a **Consumer Group** (`user-service-group`).
* It will listen for `order-events` on all partitions, decode the payload, and update user purchase statistics in the PostgreSQL database.

### Step 4: End-to-End Validation
* We will verify that placing an order automatically publishes a message to the leader broker, which persists it in a partition log. 
* The background consumer in the User Service will detect the message, read the offset, process it, and commit the offset back to the broker.
