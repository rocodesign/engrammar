# Issue #7: Daemon Is Single-Threaded

- Severity: Medium
- Complexity: C3 (High complexity)
- Status: Open

## Problem
The daemon accepts one connection and handles it synchronously.

## Why It Matters
One slow request can delay all other hook requests and increase perceived latency.

## Suggested High-Level Solution
1. Keep a single listener, but process requests with a small worker pool.
2. Add per-request timeout and structured error responses.
3. Keep maintenance jobs single-flight, but isolate them from request handling.
4. Add basic metrics in daemon log: queue wait, request duration, failures.
