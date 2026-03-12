Section 3.2 — Memory Consistency Models

Sequential consistency requires that the result of any execution is the same
as if the operations of all processors were executed in some sequential order,
and the operations of each individual processor appear in this sequence in the
order specified by its program.

Relaxed consistency models allow reordering of memory operations for
performance. Common relaxations include:

  Total Store Order (TSO): Allows read-after-write reordering
  Partial Store Order (PSO): Also allows write-after-write reordering
  Release Consistency (RC): Most relaxed, requires explicit acquire/release

This is what x86 gives you (mostly)

= x86/SPARC default

ARM and RISC-V use this!
Need explicit barriers:
dmb / dsb / isb

Q: Does Zephyr abstract the memory barriers?
Check: arch/arm/core/barrier.h
