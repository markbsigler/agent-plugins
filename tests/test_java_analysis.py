"""Tests for code-modernization-plugin: java-analysis skill and java_inventory.py."""

from __future__ import annotations

import json
from pathlib import Path

import java_inventory
import pytest


def _write_java_estate(root: Path) -> None:
    (root / "src" / "main" / "java" / "com" / "acme" / "billing").mkdir(parents=True)
    (root / "src" / "main" / "webapp" / "WEB-INF").mkdir(parents=True)
    (root / "gradle-mod").mkdir(parents=True)

    (root / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <parent>\n"
        "    <groupId>org.springframework.boot</groupId>\n"
        "    <artifactId>spring-boot-starter-parent</artifactId>\n"
        "    <version>2.7.18</version>\n"
        "  </parent>\n"
        "  <packaging>war</packaging>\n"
        "  <properties>\n"
        "    <java.version>11</java.version>\n"
        "  </properties>\n"
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <groupId>org.springframework.boot</groupId>\n"
        "      <artifactId>spring-boot-starter-web</artifactId>\n"
        "    </dependency>\n"
        "    <dependency>\n"
        "      <groupId>javax.servlet</groupId>\n"
        "      <artifactId>javax.servlet-api</artifactId>\n"
        "      <version>4.0.1</version>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "</project>\n",
        encoding="utf-8",
    )
    (root / "gradle-mod" / "build.gradle.kts").write_text(
        'plugins {\n  id("org.springframework.boot") version "3.3.2"\n  id("war")\n}\n'
        "java {\n  toolchain {\n    languageVersion.set(JavaLanguageVersion.of(21))\n  }\n}\n"
        "dependencies {\n"
        '  implementation("org.springframework.boot:spring-boot-starter-data-jpa")\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "src" / "main" / "webapp" / "WEB-INF" / "ibm-web-bnd.xml").write_text(
        "<web-ext/>", encoding="utf-8"
    )
    (root / "src" / "main" / "webapp" / "WEB-INF" / "struts-config.xml").write_text(
        "<struts-config/>", encoding="utf-8"
    )
    (root / "src" / "main" / "webapp" / "WEB-INF" / "ejb-jar.xml").write_text(
        "<ejb-jar/>", encoding="utf-8"
    )
    (root / "src" / "main" / "webapp" / "index.jsp").write_text("<%@ page %>\n", encoding="utf-8")
    (
        root / "src" / "main" / "java" / "com" / "acme" / "billing" / "BillingService.java"
    ).write_text(
        "package com.acme.billing;\n"
        "import javax.persistence.Entity;\n"
        "import javax.persistence.Table;\n"
        "import javax.servlet.http.HttpServletRequest;\n"
        "import jakarta.validation.Valid;\n"
        "import com.ibm.websphere.rsadapter.WSCallHelper;\n"
        "@RestController\n"
        "@Stateless\n"
        '@Table(name = "BILLING_INVOICE")\n'
        "public class BillingService extends Action {\n"
        "    private double totalAmount = 0.0;\n"
        '    private String apiKey = "super-secret-value";\n'
        "    public void run(String id) throws Exception {\n"
        "        synchronized (this) {\n"
        '            new InitialContext().lookup("jdbc/BillingDS");\n'
        '            stmt.executeQuery("SELECT * FROM CUST_LEDGER WHERE ID = " + id);\n'
        "            new ObjectInputStream(stream).readObject();\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )


def test_java_inventory_scans_maven_gradle_descriptors_and_risks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_java_estate(tmp_path)
    assert java_inventory.main([str(tmp_path)]) == 0
    inv = json.loads(capsys.readouterr().out)

    summary = inv["summary"]
    assert summary["modules"] == 2
    assert summary["java_files"] == 1
    assert summary["jsp_files"] == 1
    assert summary["descriptors"] == 3
    assert "BILLING_INVOICE" in inv["db_tables"]
    assert "CUST_LEDGER" in inv["db_tables"]
    assert inv["javax_imports"] == {"javax.persistence": 2, "javax.servlet": 1}
    assert inv["jakarta_imports"] == {"jakarta.validation": 1}
    risks = summary["risk_totals"]
    for key in (
        "javax_namespace",
        "ejb_component",
        "jndi_lookup",
        "struts_action",
        "websphere_binding",
        "float_currency",
        "sql_concatenation",
        "java_serialization",
        "hardcoded_secret",
        "synchronized_io",
    ):
        assert risks.get(key, 0) >= 1, f"missing risk {key}"

    assert java_inventory.main([str(tmp_path), "--format", "markdown"]) == 0
    md = capsys.readouterr().out
    assert "## Build Modules" in md
    assert "`javax.persistence`" in md
    assert "`float_currency`" in md

    single = tmp_path / "src" / "main" / "java" / "com" / "acme" / "billing" / "BillingService.java"
    assert java_inventory.build_inventory(single)["summary"]["java_files"] == 1

    bad_pom = tmp_path / "broken" / "pom.xml"
    bad_pom.parent.mkdir()
    bad_pom.write_text("<project><unclosed>", encoding="utf-8")
    assert java_inventory.build_inventory(bad_pom.parent)["summary"]["modules"] == 1

    assert java_inventory.main([str(tmp_path / "missing")]) == 1
    assert "not found" in capsys.readouterr().err
