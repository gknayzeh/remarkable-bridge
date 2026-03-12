---
title: "Test Note — Tables and Lists"
tags: [type/reference, topic/comparison]
---

# Protocol Comparison

## Summary Table

| Protocol | Consistency | Availability | Partition Tolerant | Use Case |
|----------|------------|--------------|-------------------|----------|
| Raft     | Strong     | Moderate     | Yes               | Metadata stores |
| Paxos    | Strong     | Moderate     | Yes               | Distributed locks |
| Gossip   | Eventual   | High         | Yes               | Membership |
| 2PC      | Strong     | Low          | No                | Transactions |

## Selection Criteria

1. **Latency requirements** — if sub-millisecond, avoid consensus protocols
2. **Failure tolerance** — how many nodes can fail?
3. **Data model** — key-value vs. relational vs. document
   - Key-value: Raft or gossip depending on consistency needs
   - Relational: 2PC for cross-shard transactions
   - Document: application-level conflict resolution

### Checklist

- [ ] Define SLA for consistency
- [ ] Benchmark network partition frequency
- [ ] Measure write amplification under load
