# **Engineering Notes & Technical Decisions: Order Management System (OMS)**

## **1\. Core Domain Architecture & Database Design**

### **Decoupling Catalog from Inventory**

* **The Problem:** Storing stock quantities directly inside a product catalog table creates significant transactional performance bottlenecks. Products are inherently read-heavy (catalog browsing, viewing details) while stock levels are intensely write-heavy due to frequent transactional updates. Keeping them in the same database row leads to severe row-locking issues and spikes API latency.  
* **The Production Solution:** Extract stock management out of the main catalog and place it into a dedicated, isolated inventory table. This keeps the core product lookup queries clean, highly cacheable, and exceptionally fast.  
* **Data Relationship:** The inventory table acts as an extended data structure of a product and maintains a rigid OneToOne relationship with the product table.  
* **JPA Best Practice:** Map this relationship explicitly using object-relational mappings (@OneToOne) instead of using a loose Long productId primitive field. This approach preserves full ORM benefits, allowing the application to utilize JPA's auto-joining capabilities instead of forcing developers to manually construct raw join queries.

### **Inventory Metrics & Lifecycle**

To robustly track and protect stock levels across multi-step order workflows, the inventory table must partition stock counts into two distinct fields:

1. available\_quantity**:** The physical inventory currently sitting in the warehouse ready to be purchased.  
2. reserved\_quantity**:** Stock that is temporarily locked by customers who have placed an order but whose payments haven't fully cleared yet.

**The Stock Lifecycle Routine:**

* **Order Placed:** A customer places an order for 2 iPhones. If available\_quantity \= 10 and reserved\_quantity \= 0, the system shifts the balance: available\_quantity becomes **8**, and reserved\_quantity becomes **2**.  
* **Payment Success:** The payment clears successfully. The items are declared sold; reserved\_quantity drops back to **0** and the stock is permanently deducted. \* **Payment Failure/Timeout:** If the payment fails or a checkout timeout occurs, the reservation is safely released and reverted back to the shelf: available\_quantity returns to **10** and reserved\_quantity resets to **0**.

## **2\. Advanced Relational Data Modeling & JPA Rules**

### **Relationship Ownership & Bidirectional Navigation**

* **The Ownership Rule:** In any relational database join mapping, the table containing the physical Foreign Key (FK) column **owns** the relationship.  
* **The Order ↔ OrderItem Graph:** The physical foreign key column (order\_id) resides entirely inside the child order\_items table. Therefore, the OrderItem entity strictly owns the relationship and maps it using a @ManyToOne annotation.  
* **Bidirectional Abstraction:** In the parent Order entity, a matching @OneToMany(mappedBy \= "order") is defined. This exists purely for ease of navigation in the Java application layer.  
* **Architectural Guardrail:** Do not map database relationships in your Java code simply because they exist in the database schema; **relationships must be added only because the application code specifically needs to navigate them**.

### **JPA Memory Synchronization (Bi-directional Linkage)**

* **The Gotcha:** When modifying bidirectional graphs in memory, Java requires you to explicitly update **both sides** of the relationship.  
* **The Risk:** Failing to link a child OrderItem back to its parent Order in memory means the OrderItem object retains a null parent reference. When Hibernate attempts to cascade and persist the graph, it will fail to resolve the order\_id column, throwing a database foreign key constraint violation or inserting orphaned rows.  
* **The Abstraction Pattern:** Never handle this linkage directly in your business service layers. Always encapsulate this logic within a dedicated helper method directly inside your parent Order entity class to shield the service layer from underlying boilerplate:  
* Java

public void addOrderItem(OrderItem item) {  
    this.orderItems.add(item);  
    item.setOrder(this); // Synchs the child back to the parent in memory  
}

* 

### **Lifecycle Rules & Domain Modeling Framework**

* **CascadeType:** Dictates what happens to a child entity when its parent entity is modified or deleted (e.g., setting CascadeType.ALL ensures saving an Order automatically inserts its nested OrderItems).  
* **orphanRemoval:** Specifies whether a child entity should be automatically deleted from the database if it is dropped from the parent's internal in-memory collection.  
* **Association Tables:** Utilized to represent complex Many-to-Many relationships (e.g., a Customer renting multiple Movies and a Movie rented by multiple Customers). These tables are essential for relational databases and can be leveraged to house metadata specific to the relationship intersection, such as a rental\_date.

**The Data Modeling Evaluation Framework:** Before defining any database relationship or mapping, answer these 7 structural questions: 1\. What business concept am I representing? 2\. Who owns the relationship? 3\. Which table contains the physical foreign key? 4\. Can the child entity exist independently outside the parent? 5\. Do I genuinely need bidirectional navigation both ways? 6\. Should lifecycle operations cascade down the graph? 7\. Could this sub-collection become massive over time?

## **3\. Concurrency Strategy: Resolving Race Conditions**

When multiple application threads read and update stock quantities concurrently, reading a value into application memory, modifying it, and writing it back will result in data corruption and overselling. Three production strategies solve this issue:

### **Evaluation Matrix**

| Concurrency Strategy | Database Mechanism | Operational Behavior & UX | Long-Term Evolvability Impact |
| :---- | :---- | :---- | :---- |
| **Pessimistic Locking** | SELECT ... FOR UPDATE | **Blocking:** Locks the selected database row immediately on read. Other incoming threads are forced into a blocking queue until the lock-holding transaction finishes. | **Poor:** If you later integrate slow external integrations (e.g., third-party payment gateways, fraud checks) inside the transaction, the row lock stays open, exhausting connection pools and grinding the system to a halt. |
| **Optimistic Locking** | @Version checking column | **Non-blocking:** Highly performant under low conflict. If a conflict occurs during a write, MySQL rejects the statement and throws an OptimisticLockingFailureException. | **Messy:** Forces the implementation of complex transaction retry loops (e.g., Spring Retry). The thread doesn’t know *why* the version changed—it must roll back, open a new transaction, and re-read the DB just to check if stock actually ran out. |
| **Atomic Database Updates** *(Recommended)* | Native database math operations | **Non-blocking / Fail-Fast:** Shifts business rule validation filters directly into the SQL query conditions. Returns an integer (1 for success, 0 for failure) instead of throwing a DB exception. | **Excellent:** Keeps Java code simple, highly readable, and insulated. It eliminates long row locks and completely removes the need for transaction retry blocks since you know definitively on the first attempt if stock was available. |

### 

### **Implementing the Atomic Update Pattern**

Instead of reading an object, validating its getters in Java, and executing a standard .save(), the entire inventory check is handled in a single SQL step:

#### **1\. Repository Layer Query (**InventoryRepository**)**

Java  
@Modifying  
@Query("""  
    UPDATE Inventory i   
    SET i.availableQuantity \= i.availableQuantity \- :quantity,   
        i.reservedQuantity \= i.reservedQuantity \+ :quantity   
    WHERE i.product.id \= :productId AND i.availableQuantity \>= :quantity  
""")  
int reserveStock(@Param("productId") Long productId, @Param("quantity") int quantity);

#### **2\. Service Layer Implementation (**OrderService**)**

Java  
// Inside the order placement loop:  
int rowsUpdated \= inventoryRepository.reserveStock(product.getId(), itemReq.quantity());

if (rowsUpdated \== 0) {  
    // The database naturally reports 0 rows changed if stock drops below requested quantity  
    throw new InsufficientInventoryException("Not enough stock available.");  
}  
// Proceed with building out your OrderItem cascading graph...

## **4\. Modern Enterprise Java Standards (21+)**

### **DTO Modernization: Java Records vs. POJOs**

* Data Transfer Objects (DTOs) are meant purely for immutable request/response data transit.  
* Use **Java Records** instead of classic mutable POJOs to drastically eliminate boilerplate code (removing the explicit need for Lombok on DTOs).  
* Records are inherently thread-safe and immutable by default (no fields can be set after instantiation).  
* **Constraint:** Records are strictly not applicable for database Entities, as JPA/Hibernate tracking inherently requires entity objects to be mutable.

### **Object Mapping Strategy**

* Avoid using ModelMapper in enterprise configurations. It relies completely on reflection to perform data mapping at runtime, which introduces significant latency, causes silent runtime failures, and is incompatible with modern immutable Java Records.  
* **The Scalability Rule:** Use clear manual mapping constructors/methods for small-to-medium scale applications, and leverage MapStruct for compilation-safe, high-performance object translation in enterprise environments.

### **Automated Data Auditing & API Standards**

* **Auditing Fields:** Do not handle database tracking fields like createdAt and updatedAt manually. Register an EntityListener(AuditingEntityListener.class) directly on your entity classes alongside @CreatedDate and @LastModifiedDate to force Spring Data JPA to automatically populate timestamps.  
* **Idiomatic Spring Responses:** Adhere strictly to clean REST structures. Use ResponseEntity.ok() for successful executions and standard success status codes.  
* When business rules are violated (e.g., running out of stock), map custom domain exceptions using a global handler to return a 422 Unprocessable Entity REST HTTP status code.

## **5\. Architectural Principles & Core Best Practices**

**Senior Engineer's Creed:** Always build for today’s requirements and leave just enough room for tomorrow’s requirements. Never add premature architectural complexity, but do not compromise on foundational database integrity or clean separation of concerns.

### **Action-Driven DTO Design**

Enforce strict context-driven naming rules for your data carriers. Never build a generic, multi-purpose OrderRequestDTO. Each transactional endpoint requires entirely unique data representations:

* For a CreateOrder action, the payload should only accept a minimal list of requested item identifiers and quantities.  
* For an UpdateOrderStatus action, the payload must demand a specific order identifier and an operational status string. Name your objects explicitly according to their exact business operation (e.g., CreateOrderRequest, UpdateOrderStatusRequest).

**27th June 2026**

So while planning to add the getAllOrders resource, I came across an interesting case-  
To implement the getAllOrders resource \- the Order Section has a field called OrderItems, so each order can have N number of orderItems.   
By default the field has set fetchType as lazyloading to prevent fetching orderItems in memory by hibernate. But this introduces a classic N+1 query problem since while responding to the client the code maps entity to DTO and the DTO can call order.getOrderItems which causes the hibernate to add an additional query to fetch orderItems for each order \- which can make the query unnecessarily slow.

To prevent this there is a method called “Join fetch” or join in sql which can fetch the orderItems while fetching the orders and keep it in memory \- this is a silver bullet technique to avoid N+1 query problems. 

There is one critical case though  \- now since we have optimized the performance of the query there still comes the case \- at scale join fetch could result to a cartesian product trap that is to show the orderItems it has to show the orderId column as well and hence a lot of duplicate row for the same parent may be created and if order has a lot of columns let’s say 50 \- it could lead to too much information being fetched and kept in memory.

So when this issue arises we need to use batchSize instead to both solve N+1 query problem as well as the cartesian product basically this leads to more number of network round trips  \- but may reduce random crash due to fetching too much data upfront in memory  
In join fetch  \- only one network round trip is needed to fetch data.

The cartesian product trap is not an issue at the DB level but when DB has to send the whole flattened data across the network into the app’s memory. Basically to show the result set for each orderItem even though in db it shows just orderId duplication but when it is sent over the internet each and every column of order is duplicated for each orderItem \- this is what causes the memory of the application to explode.

**In the DB Storage:** The foreign key keeps everything perfect and normalized. No duplication.  
**On the Network Wire:** A `JOIN` forces the database to flatten the data into a grid, introducing data duplication.  
**In Java Memory (JVM Heap):** Your Spring Boot application has to download this massive duplicated grid into RAM first. Only *after* it's inside your RAM does Hibernate look at the foreign key IDs and deduplicate them back into a neat, single Java `Order` object with an array of items.

Dilemma : Right now we are returning only orderItemId in order, but later if we want to show more data we can create a DTO like OrderItemSummaryDTO in which we can show some information apart from the whole entity graph which can show order \- orderItem \- product \- category \- which is like too much info.

**Concurrency case \-**   
Why do we need Optimistic locking for creating order resources apart from the atomic update sol implemented in DB. This is because at scale considering the example of two threads creating an order.  
Thread A \- loads the product info and the inventory info  
Thread B \- loads the same product info and the inventory info

Let’s say by the time thread A completes it’s transaction thread b is halfway in it’s transaction and let’s say thread A updates one of the parameters which is used as a business validation in create order, then it could affect thread B’s transaction since thread A has modified one or more fields which thread B does not know about. This could lead to data corruption which is why it is necessary to have optimistic locking, as in this case since the version would have been changed even if thread B reaches the db level \- the version would have changed and hibernate would throw an exception. Ensuring data integrity. Checking the version ensures the db row was exactly how it was in the beginning of the transaction.

In **Java LLD** there is a way to enforce that threads are executing a method one by one only using the **synchronised** keyword in method which slows the operation but ensures only one thread is processed at a time.

**Fault Tolerance Case:**  
**Let’s say user clicks on order now button and his order is processed, status is marked as PAID and money is deducted from his acc but before the success response is sent back to the customer his network connection goes or a packet in his network drops which looks like his request failed and out of frustration they might click the order now button again.** 

**This could lead to double deduction for a single order for the customer.**

To handle this we will use a pattern called Idempotency Pattern. In this pattern what necessarily happens is when the user opens the checkout page, the client generates a unique UUID which is sent with the request. The DB will check if any response has been cached for the same UUID(Idempotency Key). If it finds any cached response it simply returns the response. If idempotency key not found in db then the request is processed completely from start

**Case \#:**  
**We encountered a case when let’s say the customer presses the checkout button several backend processes occur such as generating invoice, sending an email etc, which if done in a synchronous way could act as a huge delay for the customer in terms of UX.**  
**To handle this there is a pattern of using something called asynchronous messaging.**  
What kafka does here is instead of keeping the logic to generate pdfs, send email in the controller or the service, we introduce  Kafka which is a high speed append only transaction log (Called a topic) wherein we append logs, let’s say customer clicks on order now button and then the stock is reserved and status has been changed to PENDING, then later a tiny notification event is created and published in kafka,   
Which is later processed by individual workers (consumers) who consume each notification event. There could be a worker for each task like sending notification, generating pdf, shipping worker etc.

With Kafka even if let’s say something fails in between after a payment is processed like the third party shipping service fails, Kafka still stores the events in hard drive and then once the service is available, a tracking pointer flag called offset helps continue from where the processes stopped.

Low Level Design related to Asynchronous messaging.  
By default Spring processes events synchronously.

Kafka is basically like a append on the tail log book  
Whenever a new event is registered the event is given a sequential number called an offset

Kafka helps handle millions of concurrent events because of a mechanism called a partition 

Let;s say for a single topic it can divide it into multiple partitions  
Let;s say there are three partitions of order-event then kafka can distribute it to upto three physical machines.

When an event gets published kafka runs a hashing strategy on a routing data such as orderId to place the event in the correct partition.

While implementing kafka we faced an issue wherein it was silently failing internally. This was because Kafka broker looks for 3 nodes 1 wherein it saves the event and other two contains the replicate to prevent from any failures. Since our broker is a single node setup and is not a cluster, kafka failed silently, so it is necessary to manually define configuration to use a single node only locally. This would not happen in a production setup.

