---
name: java-analysis
description: Java and JVM stack profile for the modernization playbooks. Analyzes Java estates (Maven, Gradle, Java 8 to 21, Spring Boot 2.x to 3.x, javax to jakarta, Java EE, EJB, Struts, JSP, WebSphere, WebLogic) and supplies the Java tasks for every Refactor and Rearchitect stage, both when modernizing a Java codebase in place and when targeting Java Spring Boot as the destination of a mainframe or legacy migration. Bundled script only reads files.
license: MIT
compatibility: Python 3.11+, standard library only; run with uv or python3.
metadata:
  author: markbsigler
  version: "1.0"
---

# Java Analysis (Java / Spring Boot / Jakarta EE)

The Java stack profile for `modernization-triage`, `playbook-refactor`, and `playbook-rearchitect`. Triage loads it when the scope contains Java or JVM artifacts, or when Java (for example Spring Boot 3.x on Java 21) is the target stack of a cross-stack rearchitecture or language conversion.

## Stack profile

| Profile part | Where in this skill |
| --- | --- |
| Detection signals | [Detection signals](#detection-signals) |
| Discovery and estate brief | [Workflow](#workflow), Steps 1 to 3 |
| Contract surface | Operating rule 3 |
| Elicitation addendum | [Elicitation addendum](#elicitation-addendum) |
| Classification examples | [Classification examples](#classification-examples) |
| Playbook stage tasks | [references/playbook-stages.md](references/playbook-stages.md): `Refactor Stage 1` to `4` and `Rearchitect Stage 1` to `4` |
| Equivalence evidence and NFR baselines | [references/upgrade-and-migration.md](references/upgrade-and-migration.md) |
| Target platforms and transition patterns | [references/upgrade-and-migration.md](references/upgrade-and-migration.md) |

### Detection signals

- Build manifests: `pom.xml`, `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`.
- Deployment descriptors: `web.xml`, `ejb-jar.xml`, `application.xml`, `struts.xml`, `struts-config.xml`, `ibm-web-bnd.xml`, `ibm-ejb-jar-bnd.xml`, `weblogic.xml`, `jboss-web.xml`.
- Mentions of Java 8/11/17/21, Spring Boot, Jakarta EE, Java EE, `javax` to `jakarta`, WebSphere, WebLogic, JBoss/WildFly, Struts, EJB, or Maven/Gradle.

### Elicitation addendum

Ask only what `scripts/java_inventory.py` and `.modernize/rulebook/` could not determine:
1. **Target JDK and framework release:** for example Java 21 LTS and Spring Boot 3.x, or an intermediate step (Java 17 first).
2. **Application server posture:** staying on an external servlet/EE container (WAR) or moving to a standalone executable JAR?
3. **Database and messaging test strategy:** Testcontainers (recommended for PostgreSQL, Db2, Kafka, Service Bus, Redis) or existing integration environments?

### Classification examples

| Request | Route |
| --- | --- |
| Upgrading Java 8 → 17/21, Spring Boot 2.x → 3.x, `javax.*` → `jakarta.*`, JUnit 4 → JUnit 5, or remediating Maven/Gradle CVEs without changing APIs or deployment topology | Refactor |
| Migrating a Spring Boot WAR on WebSphere Application Server to a standalone executable JAR with identical REST/MQ/JDBC contracts | Refactor |
| Converting Apache Struts 2 actions to Spring MVC controllers while keeping identical URLs, form parameters, and responses | Refactor |
| Decomposing a monolithic EAR/WAR into independent Spring Boot microservices, extracting a bounded context, or replacing shared database tables with event streams | Rearchitect |
| Extracting a mainframe CICS/COBOL or IMS slice into a new Java Spring Boot service | Rearchitect (load `mainframe-analysis` as legacy profile and `java-analysis` as target profile) |

## Operating rules

1. **Evidence from build files and source.** Run `./scripts/java_inventory.py` before proposing an upgrade order or seam split.
2. **Stepwise upgrades beat big jumps.** Separate build-plugin updates, JDK bumps, `javax` → `jakarta` namespace shifts, and framework major-version bumps into distinct, testable commits.
3. **Contracts are wider than controller signatures.** JSON field names and date formats (Jackson serialization), Bean Validation error payloads, HTTP status codes, JMS/Kafka headers, database schema/Flyway/Liquibase migrations, and JVM exit codes are all part of the external contract surface.
4. **`BigDecimal` for money and scaled quantities.** Never use `float` or `double` for currency, rates, or mainframe `COMP-3` / zoned-decimal fields; use `BigDecimal` with explicit scale and `RoundingMode`.
5. **Read-only discovery.** The bundled inventory script only reads files.

## Workflow

### Step 1: Inventory the Java estate

Run the inventory script on the repository root:

```bash
uv run --script ./scripts/java_inventory.py <project-dir> --format markdown
uv run --script ./scripts/java_inventory.py <project-dir> > .modernize/java-inventory.json
```

It reports build modules (`maven` or `gradle`), declared Java and Spring Boot versions, direct dependencies, `javax.*` vs. `jakarta.*` package usage, entry points (Spring MVC/REST, JAX-RS, Servlets, Struts actions, JMS/Kafka/RabbitMQ listeners, scheduled jobs), EJB and WebSphere/JNDI bindings, JPA entities and SQL tables, and modernization/security risks (`javax_namespace`, `ejb_component`, `jndi_lookup`, `struts_action`, `websphere_binding`, `float_currency`, `sql_concatenation`, `java_serialization`, `hardcoded_secret`).

### Step 2: Load the rules for the findings

Read [references/playbook-stages.md](references/playbook-stages.md) for the active playbook stage and [references/upgrade-and-migration.md](references/upgrade-and-migration.md) for Java 8→21, Spring Boot 2→3, Struts/EJB/WebSphere migration, Testcontainers verification, and mainframe-to-Java data rules.

### Step 3: Report the Java Estate Brief

```markdown
## Java Estate Brief: <scope>
- **Build & modules:** <Maven/Gradle, modules, packaging (JAR/WAR/EAR)>
- **Java & framework versions:** <current JDK, Spring Boot / Jakarta EE version, target versions>
- **Entry points & contracts:** <REST/MVC controllers, Servlets, Struts actions, message listeners, scheduled tasks>
- **App-server & legacy coupling:** <javax.* packages, EJBs, JNDI lookups, WebSphere descriptors, JSPs>
- **Data & messaging:** <JPA entities, SQL tables, JDBC/JTA, JMS/Kafka/RabbitMQ>
- **Risk hotspots:** <risk counts and top affected classes>
```
