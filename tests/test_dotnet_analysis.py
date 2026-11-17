"""Tests for code-modernization-plugin: dotnet-analysis skill and dotnet_inventory.py."""

from __future__ import annotations

import json
from pathlib import Path

import dotnet_inventory
import pytest


def _write_dotnet_estate(root: Path) -> None:
    (root / "LegacyWeb").mkdir(parents=True)
    (root / "ModernWorker").mkdir(parents=True)

    (root / "Estate.sln").write_text("Microsoft Visual Studio Solution File\n", encoding="utf-8")
    (root / "Directory.Packages.props").write_text("<Project/>\n", encoding="utf-8")

    (root / "LegacyWeb" / "LegacyWeb.csproj").write_text(
        '<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
        "  <PropertyGroup>\n"
        "    <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>\n"
        "  </PropertyGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    (root / "LegacyWeb" / "packages.config").write_text(
        '<packages>\n  <package id="EntityFramework" version="6.4.4" />\n'
        '  <package id="Newtonsoft.Json" version="13.0.3" />\n</packages>\n',
        encoding="utf-8",
    )
    (root / "LegacyWeb" / "Web.config").write_text("<configuration/>\n", encoding="utf-8")
    (root / "LegacyWeb" / "OrderService.cs").write_text(
        "using System.Web;\n"
        "using System.ServiceModel;\n"
        "using System.Data.Entity;\n"
        "using Microsoft.Win32;\n"
        "namespace Acme.Legacy\n"
        "{\n"
        "    [ServiceContract]\n"
        '    [Table("ORDERS_HEADER")]\n'
        "    public class OrderService : ApiController\n"
        "    {\n"
        "        public DbSet<OrderLine> OrderLines { get; set; }\n"
        "        private double orderBalance = 0.0;\n"
        '        private string clientSecret = "hardcoded-secret-val";\n'
        "        public void Process(string id)\n"
        "        {\n"
        "            var ctx = HttpContext.Current;\n"
        "            var fmt = new BinaryFormatter();\n"
        '            var cmd = new SqlCommand("SELECT * FROM CUSTOMER_ACCT WHERE ID = " + id);\n'
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    (root / "ModernWorker" / "ModernWorker.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk.Worker">\n'
        "  <PropertyGroup>\n"
        "    <TargetFrameworks>net8.0;net9.0</TargetFrameworks>\n"
        "  </PropertyGroup>\n"
        "  <ItemGroup>\n"
        '    <PackageReference Include="Microsoft.Extensions.Hosting" Version="8.0.0" />\n'
        '    <PackageReference Include="Dapper">\n'
        "      <Version>2.1.35</Version>\n"
        "    </PackageReference>\n"
        "  </ItemGroup>\n"
        "</Project>\n",
        encoding="utf-8",
    )
    (root / "ModernWorker" / "appsettings.json").write_text("{}\n", encoding="utf-8")


def test_dotnet_inventory_scans_solutions_projects_packages_and_risks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_dotnet_estate(tmp_path)
    assert dotnet_inventory.main([str(tmp_path)]) == 0
    inv = json.loads(capsys.readouterr().out)

    summary = inv["summary"]
    assert summary["solutions"] == 1
    assert summary["projects"] == 2
    assert summary["legacy_projects"] == 1
    assert summary["central_package_management"] is True
    assert summary["packages_configs"] == 1
    assert "ORDERS_HEADER" in inv["db_tables"]
    assert "ORDERLINES" in inv["db_tables"]
    assert "CUSTOMER_ACCT" in inv["db_tables"]

    risks = summary["risk_totals"]
    for key in (
        "legacy_target_framework",
        "packages_config",
        "system_web",
        "wcf_service",
        "ef6_context",
        "binary_formatter",
        "float_currency",
        "sql_concatenation",
        "hardcoded_secret",
    ):
        assert risks.get(key, 0) >= 1, f"missing risk {key}"

    assert dotnet_inventory.main([str(tmp_path), "--format", "markdown"]) == 0
    md = capsys.readouterr().out
    assert "## Projects" in md
    assert "`LegacyWeb/LegacyWeb.csproj`" in md
    assert "`binary_formatter`" in md

    single = tmp_path / "LegacyWeb" / "OrderService.cs"
    assert dotnet_inventory.build_inventory(single)["summary"]["cs_files"] == 1

    bad_dir = tmp_path / "broken"
    bad_dir.mkdir()
    (bad_dir / "Bad.csproj").write_text("<Project><unclosed>", encoding="utf-8")
    (bad_dir / "packages.config").write_text("<packages><unclosed>", encoding="utf-8")
    assert dotnet_inventory.build_inventory(bad_dir)["summary"]["projects"] == 1

    assert dotnet_inventory.main([str(tmp_path / "missing")]) == 1
    assert "not found" in capsys.readouterr().err
