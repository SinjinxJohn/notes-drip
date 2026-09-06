# Engineering Notes & Technical Decisions: Order Management System (OMS)

## 1. Core Domain Architecture & Database Design

### Decoupling Catalog from Inventory
* **The Problem:** Storing stock quantities directly inside a product catalog table creates significant transactional performance bottlenecks. Products are inherently read-heavy (catalog browsing, viewing details) while stock levels are intensely write-heavy due to frequent transactional updates. Keeping them in the same database row leads to severe row-locking issues and spikes API latency.
* **The Production Solution:** Extract stock management out of the main catalog and place it into a dedicated, isolated inventory table. This keeps the core product lookup queries clean, highly cacheable, and exceptionally fast.
* **Data Relationship:** The inventory table acts as an extended data structure of a product and maintains a rigid `@OneToOne` relationship with the product table.
* **JPA Best Practice:** Map this relationship explicitly using object-relational mappings (`@OneToOne`) instead of using a loose `Long productId` primitive field. This approach preserves full ORM benefits, allowing the application to utilize JPA's auto-joining capabilities instead of forcing developers to manually construct raw join queries.

### Inventory Metrics & Lifecycle
To robustly track and protect stock levels across multi-step order workflows, the inventory table must partition stock counts into two distinct fields:
1. `available_quantity`: The physical inventory currently sitting in the warehouse ready to be purchased.
2. `reserved_quantity`: Stock that is temporarily locked by customers who have placed an order but whose payments haven't fully cleared yet.

**The Stock Lifecycle Routine:**
* **Order Placed:** A customer places an order for 2 iPhones. If `available_quantity = 10` and `reserved_quantity = 0`, the system shifts the balance: `available_quantity` becomes **8**, and `reserved_quantity` becomes **2**.
* **Payment Success:** The payment clears successfully. The items are declared sold; `reserved_quantity` drops back to **0** and the stock is permanently deducted.
* **Payment Failure / Timeout:** If the payment fails or a checkout timeout occurs, the reservation is safely released and reverted back to the shelf: `available_quantity` returns to **10** and `reserved_quantity` resets to **0**.

---

## 2. Advanced Relational Data Modeling & JPA Rules

### Relationship Ownership & Bidirectional Navigation
* **The Ownership Rule:** In any relational database join mapping, the table containing the physical Foreign Key (FK) column **owns** the relationship.
* **The Order ↔ OrderItem Graph:** The physical foreign key column (`order_id`) resides entirely inside the child `order_items` table. Therefore, the `OrderItem` entity strictly owns the relationship and maps it using a `@ManyToOne` annotation.
* **Bidirectional Abstraction:** In the parent `Order` entity, a matching `@OneToMany(mappedBy = "order")` is defined. This exists purely for ease of navigation in the Java application layer.
* **Architectural Guardrail:** Do not map database relationships in your Java code simply because they exist in the database schema; **relationships must be added only because the application code specifically needs to navigate them**.

### JPA Memory Synchronization (Bidirectional Linkage)
* **The Gotcha:** When modifying bidirectional graphs in memory, Java requires you to explicitly update **both sides** of the relationship.
* **The Risk:** Failing to link a child `OrderItem` back to its parent `Order` in memory means the `OrderItem` object retains a `null` parent reference. When Hibernate attempts to cascade and persist the graph, it will fail to resolve the `order_id` column, throwing a database foreign key constraint violation or inserting orphaned rows.
* **The Abstraction Pattern:** Never handle this linkage directly in your business service layers. Always encapsulate this logic within a dedicated helper method directly inside your parent `Order` entity class to shield the service layer from underlying boilerplate:

```java
public void addOrderItem(OrderItem item) {
    this.orderItems.add(item);
    item.setOrder(this); // Syncs the child back to the parent in memory
}
```

### Lifecycle Rules & Domain Modeling Framework
* **`CascadeType`:** Dictates what happens to a child entity when its parent entity is modified or deleted (e.g., setting `CascadeType.ALL` ensures saving an `Order` automatically inserts its nested `OrderItems`).
* **`orphanRemoval`:** Specifies whether a child entity should be automatically deleted from the database if it is dropped from the parent's internal in-memory collection.
* **Association Tables:** Utilized to represent complex Many-to-Many relationships (e.g., a Customer renting multiple Movies and a Movie rented by multiple Customers). These tables are essential for relational databases and can be leveraged to house metadata specific to the relationship intersection, such as a `rental_date`.

**The Data Modeling Evaluation Framework:** Before defining any database relationship or mapping, answer these 7 structural questions:
1. What business concept am I representing?
2. Who owns the relationship?
3. Which table contains the physical foreign key?
4. Can the child entity exist independently outside the parent?
5. Do I genuinely need bidirectional navigation both ways?
6. Should lifecycle operations cascade down the graph?
7. Could this sub-collection become massive over time?

---

## 3. Concurrency Strategy: Resolving Race Conditions

When multiple application threads read and update stock quantities concurrently, reading a value into application memory, modifying it, and writing it back will result in data corruption and overselling. Three production strategies solve this issue:

### Evaluation Matrix

| Concurrency Strategy | Database Mechanism | Operational Behavior & UX | Long-Term Evolvability Impact |
| :--- | :--- | :--- | :--- |
| **Pessimistic Locking** | `SELECT ... FOR UPDATE` | **Blocking:** Locks the selected database row immediately on read. Other incoming threads are forced into a blocking queue until the lock-holding transaction finishes. | **Poor:** If you later integrate slow external integrations (e.g., third-party payment gateways, fraud checks) inside the transaction, the row lock stays open, exhausting connection pools and grinding the system to a halt. |
| **Optimistic Locking** | `@Version` checking column | **Non-blocking:** Highly performant under low conflict. If a conflict occurs during a write, the database rejects the statement and throws an `OptimisticLockingFailureException`. | **Messy:** Forces the implementation of complex transaction retry loops (e.g., Spring Retry). The thread doesn’t know *why* the version changed—it must roll back, open a new transaction, and re-read the DB just to check if stock actually ran out. |
| **Atomic Database Updates** *(Recommended)* | Native database math operations | **Non-blocking / Fail-Fast:** Shifts business rule validation filters directly into the SQL query conditions. Returns an integer (1 for success, 0 for failure) instead of throwing a DB exception. | **Excellent:** Keeps Java code simple, highly readable, and insulated. It eliminates long row locks and completely removes the need for transaction retry blocks since you know definitively on the first attempt if stock was available. |

### Implementing the Atomic Update Pattern
Instead of reading an object, validating its getters in Java, and executing a standard `.save()`, the entire inventory check is handled in a single SQL step:

#### 1. Repository Layer Query (`InventoryRepository`)
```java
@Modifying
@Query("""
    UPDATE Inventory i 
    SET i.availableQuantity = i.availableQuantity - :quantity, 
        i.reservedQuantity = i.reservedQuantity + :quantity 
    WHERE i.product.id = :productId AND i.availableQuantity >= :quantity
""")
int reserveStock(@Param("productId") Long productId, @Param("quantity") int quantity);
```

#### 2. Service Layer Implementation (`OrderService`)
```java
// Inside the order placement loop:
int rowsUpdated = inventoryRepository.reserveStock(product.getId(), itemReq.quantity());

if (rowsUpdated == 0) {
    // The database naturally reports 0 rows changed if stock drops below requested quantity
    throw new InsufficientInventoryException("Not enough stock available.");
}
// Proceed with building out your OrderItem cascading graph...
```

---

## 4. Modern Enterprise Java Standards (21+)

### DTO Modernization: Java Records vs. POJOs
* Data Transfer Objects (DTOs) are meant purely for immutable request/response data transit.
* Use **Java Records** instead of classic mutable POJOs to drastically eliminate boilerplate code (removing the explicit need for Lombok on DTOs).
* Records are inherently thread-safe and immutable by default (no fields can be modified after instantiation).
* **Constraint:** Records are strictly not applicable for database Entities, as JPA/Hibernate change tracking inherently requires entity objects to be mutable.

### Object Mapping Strategy
* Avoid using `ModelMapper` in enterprise configurations. It relies completely on reflection to perform data mapping at runtime, which introduces significant latency, causes silent runtime failures, and is incompatible with modern immutable Java Records.
* **The Scalability Rule:** Use clear manual mapping constructors/methods for small-to-medium scale applications, and leverage **MapStruct** for compilation-safe, high-performance object translation in enterprise environments.

### Automated Data Auditing & API Standards
* **Auditing Fields:** Do not handle database tracking fields like `createdAt` and `updatedAt` manually. Register `AuditingEntityListener.class` directly on your entity classes alongside `@CreatedDate` and `@LastModifiedDate` to force Spring Data JPA to automatically populate timestamps.
* **Idiomatic Spring Responses:** Adhere strictly to clean REST structures. Use `ResponseEntity.ok()` for successful executions and standard success status codes.
* When business rules are violated (e.g., running out of stock), map custom domain exceptions using a global `@RestControllerAdvice` handler to return a `422 Unprocessable Entity` HTTP status code.

---

## 5. Architectural Principles & Query Optimization

**Senior Engineer's Creed:** Always build for today’s requirements and leave just enough room for tomorrow’s requirements. Never add premature architectural complexity, but do not compromise on foundational database integrity or clean separation of concerns.

### Action-Driven DTO Design
Enforce strict context-driven naming rules for your data carriers. Never build a generic, multi-purpose `OrderRequestDTO`. Each transactional endpoint requires entirely unique data representations:
* For a `CreateOrder` action, the payload should only accept a minimal list of requested item identifiers and quantities (e.g., `CreateOrderRequest`).
* For an `UpdateOrderStatus` action, the payload must demand a specific order identifier and an operational status string (e.g., `UpdateOrderStatusRequest`).

### Resolving the N+1 Query Problem & The Cartesian Product Trap
When implementing `getAllOrders`, each `Order` contains a collection of `OrderItems`. By default, `fetchType = FetchType.LAZY` prevents loading items into memory prematurely, but accessing `order.getOrderItems()` during DTO serialization causes Hibernate to execute an additional query per order (the classic **N+1 Problem**).

#### Solutions & Tradeoffs:
1. **`JOIN FETCH`**:
   * Fetches the order and all nested items in a single query (1 network round trip).
   * **The Cartesian Product Trap:** At scale, `JOIN` flattens the parent and child into a duplicated grid. If an order has 50 columns and 10 items, all 50 order columns are repeated 10 times across the wire.
2. **`@BatchSize`**:
   * Hibernate loads collections in batches (e.g., `@BatchSize(size = 25)`), converting N queries into `ceil(N / 25)` queries.
   * Eliminates the Cartesian memory explosion while keeping network round trips minimal and predictable.

#### Where the Cartesian Product Overhead Happens:
* **In DB Storage:** Foreign keys keep everything normalized without duplication.
* **On the Network Wire:** A SQL `JOIN` flattens data into a grid, introducing duplicate parent columns per child row.
* **In JVM Heap:** Spring Boot downloads the entire flattened grid into RAM. Only after it resides in memory does Hibernate deduplicate rows back into distinct Java entity graphs.

---

## 6. Advanced Concurrency & Multi-Tenant Race Conditions

### Why Combine Optimistic Locking with Atomic Updates?
While Atomic Updates solve inventory overselling, Optimistic Locking (`@Version`) remains essential for multi-step transactional workflows:
* **Scenario:** Thread A and Thread B load the same Order and Customer data simultaneously. Thread A updates order payment status. If Thread B completes later without version validation, it could overwrite Thread A's changes without knowing they occurred.
* `@Version` ensures that if another thread modified the row during your transaction, Hibernate immediately throws an `OptimisticLockException`, protecting cross-field data integrity.
* In Java Low-Level Design (LLD), the `synchronized` keyword can enforce single-threaded execution on critical code blocks, but distributed systems require database-level or distributed locks (Redis/Redlock).

---

## 7. System Reliability & Fault Tolerance

### Preventing Double-Charging: The Idempotency Pattern
* **The Problem:** A customer clicks "Place Order". Payment is deducted and the order is marked `PAID`, but the customer's network drops before receiving the HTTP 200 response. Thinking the request failed, they click "Place Order" again, resulting in double deduction.
* **The Production Solution:** Implement the **Idempotency Key Pattern**:
  1. When opening the checkout page, the client generates a unique UUID (`Idempotency-Key`).
  2. The backend stores the idempotency key alongside the processed result.
  3. If a retry arrives with the same key, the server returns the cached response immediately without re-executing payment or inventory deduction.

---

## 8. Event-Driven Architecture with Apache Kafka

### Asynchronous Decoupling for High-Throughput Checkout
Executing ancillary tasks (generating invoice PDFs, sending confirmation emails, notifying third-party logistics) synchronously in the checkout HTTP request drastically degrades user experience and creates cascading points of failure.

* **Kafka Architecture:**
  1. Once stock is reserved and order status is marked `PENDING`, the service publishes a lightweight event to a Kafka topic.
  2. Independent consumer workers (Notification Worker, PDF Worker, Shipping Worker) process events asynchronously.
  3. **Fault Tolerance via Offsets:** If a downstream service (e.g. shipping partner) goes down, Kafka retains events in persistent storage. Once the service recovers, consumer offsets resume exactly where they left off without losing data.

### Partitioning & Broker Configuration Gotchas
* **Partition Distribution:** Kafka topics are partitioned across broker nodes. Publishing with a routing key (e.g., `orderId`) hashes events to the same partition, guaranteeing strict in-order processing per order.
* **Local vs. Production Broker Gotcha:** In local development on a single-node Kafka setup, Kafka may silently fail or refuse topics if `offsets.topic.replication.factor` or `transaction.state.log.replication.factor` default to `3`. For local development, replication factor must be explicitly configured to `1`.

