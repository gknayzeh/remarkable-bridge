Consensus Algorithms

Raft Protocol

Raft separates consensus into three subproblems:
  - Leader election
  - Log replication
  - Safety

A cluster of 5 nodes can tolerate 2 failures.
The leader sends heartbeats every 150ms.

Key Terms
  - Term: a logical clock that increments on each election
  - Committed: an entry replicated to a majority of nodes
  - Applied: an entry executed by the state machine

Paxos vs Raft

Paxos is more general but harder to implement correctly.
Raft was designed for understandability.
Both guarantee safety under all non-Byzantine conditions.
