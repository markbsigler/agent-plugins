# Java Upgrade, Rearchitecture & Target Migration Rules

Reference guidance for `java-analysis`.

## 1. Java 8 → 11 → 17 → 21 Upgrades

- **Removed JDK modules (Java 11+):** JAXB (`javax.xml.bind`), JAX-WS (`javax.xml.ws`), JAF (`javax.activation`), and CORBA were removed from the JDK. Add explicit `jakarta.xml.bind-api` and runtime dependencies where XML/SOAP bindings remain in scope.
- **Strong encapsulation (Java 16/17+):** Reflective access to JDK internals (`sun.misc.Unsafe`, private `java.lang.*` fields) fails without `--add-opens`. Upgrade bytecode libraries (Lombok, ASM, ByteBuddy, cglib, Mockito, Jackson, Gradle/Maven plugins) before bumping the target JDK.
- **Virtual threads (Java 21):** Before enabling virtual threads (`spring.threads.virtual.enabled=true`), audit `synchronized` blocks that wrap blocking I/O (which pin carrier threads) and replace them with `ReentrantLock` where appropriate, and review `ThreadLocal` pool assumptions.

## 2. Spring Boot 2.x → 3.x & `javax` → `jakarta`

- **Namespace boundary:** Jakarta EE 9/10 moves EE packages (`javax.servlet`, `javax.persistence`, `javax.validation`, `javax.annotation`, `javax.transaction`, `javax.jms`, `javax.ejb`, `javax.ws.rs`) to `jakarta.*`. Standard SE packages (`javax.sql`, `javax.crypto`, `javax.naming`, `javax.net`, `javax.swing`, `javax.xml.transform`) **stay** `javax.*`.
- **Spring Security 6:** Replace `WebSecurityConfigurerAdapter` and `antMatchers`/`mvcMatchers` with a `@Bean SecurityFilterChain` using `requestMatchers` and lambda DSL.
- **Spring Web & Jackson:** Trailing-slash URL matching (`matchOptionalTrailingSeparator`) is disabled by default in Spring Boot 3.0+; if external callers rely on `/api/items/` matching `/api/items`, preserve it explicitly or document it in the contract.
- **Hibernate 6:** Verify custom JPQL/HQL queries, sequence generator defaults (`_SEQ` naming), and `Instant`/`OffsetDateTime` column mappings against real database containers.

## 3. Legacy Java EE, WebSphere, and Struts Modernization

| Legacy Component | Spring Boot Target | Key Pitfall |
| --- | --- | --- |
| EJB `@Stateless` / `SessionBean` | `@Service` + `@Transactional` | EJB default transaction attribute is `REQUIRED` and rolls back on system exceptions; verify checked-exception rollback rules (`rollbackFor`) |
| EJB `@MessageDriven` (MDB) | `@JmsListener` / `@KafkaListener` | Preserve acknowledge mode, concurrency, dead-letter queue routing, and transaction participation |
| `ibm-web-bnd.xml` / `ibm-ejb-jar-bnd.xml` JNDI bindings | `application.yml` + Spring `@ConfigurationProperties` | Map every `resource-ref` and `env-entry` to an explicit property and document it in configuration inventory |
| Apache Struts `Action` + `ActionForm` + `struts.xml` | `@RestController` / `@Controller` + `@Valid` DTOs | ActionForms shared or mutated carelessly across requests; keep controller state stateless and match exact form field names and validation error keys |

## 4. Java as the Target of a Mainframe Migration

When `java-analysis` is loaded alongside `mainframe-analysis` for a COBOL/PL/I/CICS/IMS → Java modernization:

- **Arithmetic & `BigDecimal`:**
  - Map every `PIC 9(n)V9(m)` / `COMP-3` field to `BigDecimal` with fixed scale `m`.
  - COBOL truncates toward zero by default (`RoundingMode.DOWN`) unless `ROUNDED` is coded (`RoundingMode.HALF_UP` for positive/standard COBOL rounding). Never use `double` or default `HALF_EVEN` without checking the COBOL statement.
- **EBCDIC Collation:**
  - In EBCDIC, lowercase < uppercase < digits (`'a' < 'A' < '0'`); in ASCII/UTF-8, digits < uppercase < lowercase (`'0' < 'A' < 'a'`). Any `ORDER BY`, binary search, or range check on alphanumeric keys mixing letters and digits must use an explicit collation or comparator if exact ordering is required.
- **Transactional Boundaries:**
  - Map CICS `EXEC CICS SYNCPOINT` / `SYNCPOINT ROLLBACK` and batch checkpoint intervals to explicit Spring `@Transactional` boundaries or Spring Batch chunk boundaries.
