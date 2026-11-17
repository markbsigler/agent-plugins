# Playbook stage tasks (Java / Spring Boot / Jakarta EE)

Stack profile tasks for the `playbook-refactor` and `playbook-rearchitect` skills. Complete the matching section below alongside the playbook's generic tasks and include the results in that stage's gate review.

## Refactor

### Refactor Stage 1: Tech Debt, Security & Dependency Audit

- Run `scripts/java_inventory.py` across the repository and record every build module, current JDK and Spring Boot / Java EE version, packaging (`jar`, `war`, `ear`), and direct dependency list.
- Inventory `javax.*` packages that require migration to `jakarta.*` (Servlet, Persistence, Validation, Annotation, Transaction, EJB, JMS, JAX-RS) and third-party libraries that must be upgraded to Jakarta-compatible releases.
- Identify container coupling (`ejb-jar.xml`, `ibm-web-bnd.xml`, `@Stateless`/`@Stateful`/`@MessageDriven`, `InitialContext` JNDI lookups) and legacy web frameworks (Struts actions, JSPs).
- Flag security and precision hazards reported by `java_inventory.py`: SQL string concatenation (`sql_concatenation`), unsafe Java deserialization (`java_serialization`), hardcoded secrets (`hardcoded_secret`), and binary floating-point currency fields (`float_currency`).
- Check `.modernize/rulebook/` for mandatory target JDK, Spring Boot version, build tool, and dependency policies.

### Refactor Stage 2: Characterization & Nonfunctional Baseline

- Use the `behavioral-baseline` skill to freeze `.modernize/baseline/test-cases.md` and `.modernize/baseline/infra-decision-table.md` covering every controller, servlet, Struts action, message listener, and scheduled job in scope.
- Prefer Testcontainers (PostgreSQL, Db2, MySQL, Kafka, RabbitMQ, Redis, Azurite) over in-memory H2 mocks when database dialect or broker semantics matter.
- Capture Jackson JSON serialization snapshots (date/time formatting, null handling, enum representation, `BigDecimal` formatting) and Bean Validation error responses so upgrades do not silently alter wire payloads.
- Record baseline build time, test execution time, startup time, and memory footprint.

### Refactor Stage 3: Incremental Code Transformation

- Sequence changes in small, compilable commits:
  1. Upgrade Maven/Gradle wrapper and build plugins (`maven-compiler-plugin`, `maven-surefire-plugin`, Spring Boot plugin).
  2. Upgrade to the latest patch of Spring Boot 2.7.x (if starting on 2.x) and resolve deprecations before moving to Spring Boot 3.x.
  3. Migrate `javax.*` imports and configuration properties to `jakarta.*` (note that `javax.sql.*`, `javax.crypto.*`, and `javax.naming.*` remain in the JDK under `javax.*`).
  4. Migrate Spring Security (`WebSecurityConfigurerAdapter` → `SecurityFilterChain` bean), Hibernate/JPA queries, and actuator properties.
  5. For WebSphere/EJB-to-Spring Boot refactors, replace `@Stateless` with `@Service`, `@EJB` with constructor injection, JNDI data sources/queues with Spring configuration, and `ibm-*-bnd.xml` bindings with externalized `application.yml` properties.
- Run `./mvnw test` or `./gradlew test` after each step.

### Refactor Stage 4: Equivalence & NFR Verification

- Run the full unit and integration test suite (`./mvnw verify` or `./gradlew check`) and `baseline_gate.py verify` to confirm 100% pass rate and 1:1 `TC-XXX` coverage.
- Verify that JSON payloads, HTTP status codes, headers, database migrations, and decimal rounding match the Stage 2 baseline with zero drift.
- Compare startup time, latency, and test duration against the Stage 2 baseline.

## Rearchitect

### Rearchitect Stage 1: Domain Seam Analysis & ADR Generation

- Run `scripts/java_inventory.py` to map controllers/listeners, service classes, JPA entities, and SQL tables (`db_tables`) per package or module.
- Identify shared tables accessed by multiple domain packages, cross-domain synchronous calls, distributed JTA/XA transactions, and shared session state (`HttpSession`).
- In the ADR, specify the target service boundaries, how shared JPA entities/tables are split (Database-per-Service, schema separation, or outbox/CDC), how JTA transactions are replaced (transactional outbox or saga), and any target cloud/platform rules from `.modernize/rulebook/`.

### Rearchitect Stage 2: Seam Isolation & Interface Contract Definition

- Define explicit OpenAPI 3.x, AsyncAPI, or gRPC/Protobuf contracts for the extracted slice. When the legacy side is a mainframe copybook (`mainframe-analysis` + `copybook-data`), generate the schema from the copybook and map all `COMP-3` / zoned-decimal fields to `BigDecimal` (serialized as strings or exact decimals).
- Introduce a Java interface seam and anti-corruption layer (ACL) in the monolith (for example a Spring interface wired via `@ConditionalOnProperty` or a feature-flag router between the legacy in-process implementation and the remote client).
- Lock consumer/provider contract tests and freeze `.modernize/baseline/test-cases.md` via `behavioral-baseline`.

### Rearchitect Stage 3: Strangler Slice Implementation & Dual-Run

- Scaffold and implement the new Spring Boot service following the Stage 2 contract, constructor dependency injection, externalized configuration (`application.yml` / environment variables), and structured observability (OpenTelemetry / Micrometer).
- When migrating from mainframe COBOL/CICS/IMS to Java:
  - Preserve fixed-point scale and rounding (`BigDecimal` with `RoundingMode.DOWN` for COBOL truncation or `RoundingMode.HALF_UP` for `ROUNDED`).
  - Isolate EBCDIC/ASCII translation and copybook byte marshaling inside the ACL adapter.
- Route a controlled slice of traffic or events through the toggle or gateway and run Testcontainers integration tests.

### Rearchitect Stage 4: Parity Validation, Cutover & Legacy Decommissioning

- Run shadow/parallel comparisons and `baseline_gate.py verify` + `baseline_gate.py gate --type completeness` to prove behavioral parity across all `TC-XXX` test cases and `REQ-XXX` / `BR-XXX` requirements.
- Shift 100% traffic, remove the legacy Java packages, EJB descriptors, Struts mappings, or monolith adapter classes, and update the ADR status to `Accepted & Implemented`.
