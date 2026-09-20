# OmniSettlement: AWS Principal & Distributed Systems Interview Guide

This guide details the core distributed systems, cloud architecture, and AI safety concepts embodied in **OmniSettlement** to ace technical discussions with AWS Principal Engineers, Bar Raisers, and Hackathon Judges.

---

## 1. System Design & Cloud Primitives

### Q1: Why use DynamoDB TransactWriteItems instead of Amazon Aurora PostgreSQL for the ledger?
* **Answer**: In a multi-sided marketplace experiencing flash traffic (e.g. game nights, storm cancellations), connection pooling in relational databases like Aurora becomes a bottleneck for serverless Lambda execution (causing connection exhaustion). DynamoDB provides:
  1. **Single-digit millisecond latency** at arbitrary concurrency without connection overhead.
  2. **Atomic Multi-Item Transactions (`TransactWriteItems`)**: Commits up to 100 items (or 4MB of data) in an all-or-nothing two-phase commit across distinct partition keys (Customer, Merchant, Driver, Escrow).
  3. **Conditional Writes for Idempotency**: Atomic checks like `attribute_not_exists(idempotency_key)` prevent concurrent race conditions without distributed locks.

### Q2: Why decouple Ingestion with SQS FIFO instead of writing directly to Step Functions?
* **Answer**:
  1. **Rate Limiting & Shock Absorption**: Webhook bursts from Stripe or Uber Eats can spike to 50,000 req/sec. SQS FIFO buffers events without throttling upstream webhooks.
  2. **Strict Per-Order Ordering (`MessageGroupId = order_id`)**: Guarantees that a dispute update never processes before the original order creation event.
  3. **Content-Based Deduplication (`MessageDeduplicationId`)**: Enforces exactly-once message ingestion within a 5-minute deduplication interval.

---

## 2. Distributed Consistency & Resilience

### Q3: How does the Compensating Saga Pattern work in this system?
* **Answer**: Unlike a 2-Phase Commit (2PC) that holds database locks across microservices (unviable across external APIs like Stripe Connect), Step Functions executes a **Compensating Saga**:
  - **Forward Steps**: `AggregateTelemetry` $\rightarrow$ `BedrockExtractor` $\rightarrow$ `InvariantEngine` $\rightarrow$ `LedgerWriter` $\rightarrow$ `StripeDispatcher`.
  - **Compensating Rollback**: If `StripeDispatcher` fails (e.g. gateway timeout or insufficient platform account funds), Step Functions catches the error and executes `ExecuteCompensatingRollback`, which restores the platform escrow hold and logs the dispute for human arbitration.

### Q4: How is Distributed Idempotency guaranteed?
* **Answer**:
  - **Layer 1 (API Gateway/Lambda)**: Validates HMAC-SHA256 signature against webhook secret.
  - **Layer 2 (DynamoDB State Lock)**: Executes a conditional put `attribute_not_exists(idempotency_key)` in table `IdempotencyAndState`. If duplicate, returns `200 DUPLICATE_IGNORED` immediately.
  - **Layer 3 (SQS FIFO)**: Enforces message deduplication ID over 5-minute sliding windows.

---

## 3. AI Safety & Anti-Hallucination Architecture

### Q5: How do you guarantee the LLM does not hallucinate financial balances?
* **Answer**: **Architectural Separation of Concerns**:
  1. **Zero Math in LLM**: The prompt strictly prohibits Claude 3.5 Sonnet from calculating currency values or writing SQL/dynamodb queries.
  2. **Schema-Bound Fact Extraction**: Bedrock is constrained to extracting physical facts (e.g. `merchant_food_prepared: true`, `driver_dispatched_distance_km: 3.5`).
  3. **Deterministic Python Invariant Engine**: A pure Python module computes disbursements using arbitrary-precision `Decimal` and Banker's rounding (`ROUND_HALF_EVEN`), asserting:

$$\Delta_{\text{Customer}} + \Delta_{\text{Merchant}} + \Delta_{\text{Driver}} + \Delta_{\text{Platform}} \equiv 0.0000$$

  4. **Adversarial Prompt Injection Immunity**: Untrusted user chat text is isolated inside `<untrusted_evidence>` XML tags, and system prompts enforce data-only treatment.

---

## 4. Least-Privilege Security & Compliance

### Q6: What security controls are built into the CDK infrastructure?
* **Answer**:
  - **KMS Customer Managed Keys (CMK)** with automated key rotation encrypting S3, DynamoDB, and SQS at rest.
  - **S3 Object Lock (WORM - Write Once, Read Many)**: Ensures dispute audit records cannot be overwritten or deleted even by the AWS account root user (SEC Rule 17a-4 / SOC 2 compliance).
  - **Fine-Grained IAM**: The Ingestion Lambda has no DynamoDB delete or full table scan permissions (`dynamodb:PutItem` conditional only); the Bedrock Lambda has read-only invoke permissions; the Ledger Writer Lambda has transactional permissions scoped strictly to table ARNs.
