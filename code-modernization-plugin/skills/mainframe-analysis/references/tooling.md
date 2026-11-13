# Mainframe modernization tooling

Use the tools the organization already licenses and operates. The categories below help identify them and the artifacts they produce. Product names and ownership change often, so confirm current names, versions, and entitlements with the platform team.

| Need | Examples |
| --- | --- |
| Source control and promotion | Endevor; ChangeMan ZMF; BMC AMI DevX Code Pipeline (formerly ISPW); Git with IBM Dependency Based Build (DBB) and zAppBuild |
| Editors and IDEs | IBM Developer for z/OS; IBM Z Open Editor; BMC AMI DevX Workbench for Eclipse or VS Code; Broadcom Code4z |
| Remote access and automation | Zowe CLI and Zowe Explorer; Ansible collections for IBM z/OS |
| Application discovery and analysis | IBM Application Discovery and Delivery Intelligence (ADDI); BMC AMI DevX Code Insights; Enterprise Analyzer; CAST Imaging; compiler `XREF` and `MAP` listings |
| COBOL unit and integration testing | IBM zUnit; BMC AMI DevX Total Test; Broadcom Test4z; Galasa; cobol-check (Open Mainframe Project) with GnuCOBOL |
| Debugging, abend, and fault analysis | IBM z/OS Debugger; IBM Fault Analyzer; BMC AMI DevX Code Debug (formerly Xpediter); BMC AMI DevX Abend-AID; Broadcom InterTest |
| Data editing, comparison, and test data | IBM File Manager; BMC AMI DevX File-AID and Data Studio; Broadcom File Master Plus; test data masking and subsetting products |
| Performance analysis | IBM Application Performance Analyzer; BMC AMI Strobe; SMF reporting and capacity tools |
| Compiler and module optimization | IBM Enterprise COBOL for z/OS; IBM Automatic Binary Optimizer (ABO) |
| API enablement and integration | IBM z/OS Connect; CICS web services and Liberty; IMS Connect; IBM MQ and its Kafka connectors |
| Change data capture | IBM InfoSphere Data Replication; Precisely Connect; Qlik Replicate |
| Mainframe-compatible runtimes (rehost or replatform) | Rocket Software (formerly Micro Focus) Enterprise Server and Enterprise Developer; AWS Mainframe Modernization runtime options |
| AI-assisted understanding and conversion | IBM watsonx Code Assistant for Z; AWS Transform for mainframe; other vendors' assistants |
| Off-platform COBOL compilers | GnuCOBOL (dialect configurations such as `-std=ibm`); Rocket Visual COBOL and Enterprise Developer with IBM dialect settings |

Guidance:

- Outputs of AI assistants and automated converters pass through the same playbook gates and equivalence evidence as hand-written changes.
- When code runs off-platform for testing (for example with GnuCOBOL), configure the dialect, sign, binary byte order, and truncation options to match the z/OS compiler options, and still confirm results on z/OS before sign-off.
- Record which tool produced each piece of evidence so the gate review can trust and reproduce it.
