---
title: "Test Note — Simple"
tags: [type/reference, topic/testing]
---

# Distributed Systems Overview

Distributed systems are programs that run across multiple networked computers.

## Key Concepts

The CAP theorem states that a distributed system can provide at most two of
three guarantees: consistency, availability, and partition tolerance.

See also: [[consensus-algorithms]] and [[raft-protocol]]

> "A distributed system is one in which the failure of a computer you didn't
> even know existed can render your own computer unusable." — Leslie Lamport

---

---
title: "Test Note — Code Heavy"
tags: [type/reference, topic/python]
---

# Python Async Patterns

## Basic coroutine

```python
import asyncio

async def fetch_data(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def main():
    tasks = [fetch_data(f"https://api.example.com/{i}") for i in range(10)]
    results = await asyncio.gather(*tasks)
    for result in results:
        print(result["status"])
```

Inline code: use `asyncio.run(main())` to start the event loop.

## Error handling

```python
async def safe_fetch(url: str) -> dict | None:
    try:
        return await fetch_data(url)
    except aiohttp.ClientError as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None
```

---

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
