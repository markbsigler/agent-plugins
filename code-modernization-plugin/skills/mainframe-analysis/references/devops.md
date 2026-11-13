# DevOps on z/OS

Small, verifiable changes need a pipeline: source in Git, repeatable builds, automated tests, and promotion of the artifacts that were tested. Product names, packaging, and ownership change often; confirm current products, versions, and entitlements with the platform team.

## Git as the source of truth

- Store members as files with extensions (`.cbl`, `.cpy`, `.jcl`), one repository per application or bounded context, with the build and bind configuration next to the code.
- Declare encodings in `.gitattributes`. Git on z/OS uses the `zos-working-tree-encoding` attribute to tag and convert files (for example to `IBM-1047`) while developers work in UTF-8; mark binary content as binary.
- IBM Dependency Based Build (DBB) builds from Git on z/OS UNIX: it scans dependencies (copybooks, includes, called programs), keeps them in a metadata store, and supports full, impact, and user builds. zAppBuild is the Groovy-based sample framework; zBuilder (DBB 3) is configured in YAML.
- Existing SCMs stay in place during transition through bridges: Endevor Bridge for Git synchronizes Git branches with Endevor, and ChangeMan ZMF and BMC AMI DevX Code Pipeline (ISPW) offer their own Git integrations. Decide which side is authoritative and never edit both.

## Developer tools

| Need | Examples |
| --- | --- |
| Editors with COBOL, PL/I, HLASM, and JCL support | IBM Z Open Editor, BMC AMI DevX Workbench, Broadcom Code4z (VS Code); IBM Developer for z/OS (Eclipse) |
| Data sets, jobs, and z/OS UNIX from the workstation | The remote-system views of the shop's IDE, or ISPF and SDSF through a 3270 emulator |
| Development and test systems | IBM Wazi as a Service (z/OS virtual servers on IBM Cloud), Wazi Sandbox where licensed, IBM Z Development and Test Environment (ZD&T), shared development LPARs |

## Continuous integration

- Orchestrators: Jenkins (often with an agent on z/OS UNIX), GitLab CI, GitHub Actions, or Azure Pipelines, with runners that reach z/OS through SSH or the z/OSMF REST services.
- Pipeline for each change: build with DBB, run unit tests, bind to a test collection, deploy to a test environment, run regression and equivalence tests, then package.
- Unit tests in CI: IBM zUnit, BMC AMI DevX Total Test, Broadcom Test4z, or cobol-check (Open Mainframe Project). Keep tests and test data in the repository and fail the pipeline on any regression.

## Db2 bind and deployment

- Bind packages in the pipeline from the DBRMs the build produced, with `BIND` options kept in version-controlled configuration and one collection per environment. Rebind with `EXPLAIN(YES)` and `APCOMPARE` so access-path changes are visible (see [performance-cost.md](performance-cost.md)).
- Package once and deploy the same load modules and DBRMs to every environment with IBM Wazi Deploy (deployment manifest, Python or Ansible translators), IBM DevOps Deploy (formerly UrbanCode Deploy), or the SCM's promotion.
- Ansible for z/OS (the `ibm.ibm_zos_core` collection and related IBM Z collections) automates data set, job, and operator tasks; review playbooks like programs.
- Put CICS `NEWCOPY` or `PHASEIN`, IMS online change, and bind order in the deployment plan, together with rollback: previous load modules and package copies.

## Branching and promotion

- Prefer trunk-based development: short-lived feature branches merged to `main` through pull requests, release tags, and release maintenance branches. Do not create a branch per environment.
- Map the SCM promotion path (Endevor environments and stages, ChangeMan ZMF promotion levels, Code Pipeline levels) to deployment environments for one built package, not to branches.
- Branch production fixes from the release tag and merge them back to `main`.

## Small, verifiable commits for refactors

- One concern per commit: one program's restructuring, one copybook change with its impact list, or one compiler or `BIND` option change. Never mix option changes with source changes.
- Each commit builds (impact build), passes unit tests, and carries the evidence its playbook stage asks for: characterization results, equivalence comparisons, and CPU deltas where cost is the driver.
- Keep sequence numbers and change tags stable so diffs show only real changes; handle encodings and line endings in `.gitattributes`, not by hand.
- Tag the commit that is deployed so production modules trace back to source.
