"""Tests for code-modernization-plugin: mainframe-analysis seam_report.py."""

from __future__ import annotations

import json
from pathlib import Path

import mainframe_inventory
import pytest
import seam_report
from mainframe_fixtures import write_rich_estate


def test_seam_report_finds_owners_clusters_footprints_and_interfaces(tmp_path: Path) -> None:
    write_rich_estate(tmp_path)
    report = seam_report.build_report(mainframe_inventory.build_inventory([tmp_path]))

    master = report["resources"]["dataset:PROD.ACCT.KSDS"]
    assert master["actors"] == {
        "ACCTBAT": {"ops": "RU", "via": ["ACCTJOB.STEP010 DD ACCTDD"]},
        "ACCTJOB.STEP020": {"ops": "R", "via": ["SORT"]},
        "ACCTPLI": {"ops": "R", "via": ["ACCTJOB.STEP015 DD ACCTDD"]},
        "ACCTUPD": {"ops": "RU", "via": ["CICS file ACCTFIL"]},
    }
    assert master["writers"] == ["ACCTBAT", "ACCTUPD"]
    assert report["multiple_writers"] == ["dataset:PROD.ACCT.KSDS"]
    assert report["resources"]["dataset:PROD.RATES.TABLE"]["actors"] == {
        "ACCTJOB.STEP010": {"ops": "R", "via": ["ACCTBAT"]}
    }

    cluster = report["write_clusters"][0]
    assert cluster == {
        "writers": ["ACCTBAT", "ACCTUPD"],
        "resources": [
            "cics-file:ACCTFIL",
            "cics-queue:ACCTQ",
            "dataset:PROD.ACCT.KSDS",
            "db2-table:ACCT.BALANCE",
            "db2-table:ACCT.HISTORY",
            "ims-segment:ACCOUNT",
            "mq-queue:ACCT.EVENTS",
        ],
        "outside_readers": ["ACCTAPI", "ACCTJOB.STEP020", "ACCTPLI"],
    }

    footprint = report["transactions"]["AUPD"]
    assert footprint["programs"] == ["ACCTUPD", "ACCTVAL"]
    assert footprint["calls"] == [{"from": "ACCTUPD", "type": "cics-link", "to": "ACCTVAL"}]
    assert footprint["updates_in_unit_of_work"] == [
        "cics-file:ACCTFIL",
        "cics-queue:ACCTQ",
        "db2-table:ACCT.BALANCE",
        "db2-table:ACCT.HISTORY",
        "mq-queue:ACCT.EVENTS",
    ]
    assert (footprint["links"], footprint["syncpoints"], footprint["resource_accesses"]) == (
        1,
        1,
        6,
    )
    assert footprint["next_transactions"] == ["APRT", "AUPD"]

    found = report["interfaces"]
    assert found["inbound_datasets"] == ["PROD.RATES.TABLE"]
    assert found["outbound_datasets"] == ["PROD.ACCT.EXTRACT", "PROD.ACCT.PLIOUT", "PROD.OLD.FILE"]
    assert found["mq_put_only"] == ["ACCT.EVENTS"]
    assert found["mq_get_only"] == []
    assert found["remote_db2_locations"] == ["DB2B"]
    assert found["screens"] == ["ACCTSET"]
    assert found["web_endpoints"]["ACCTURI"]["program"] == "ACCTAPI"
    assert found["reports"] == [
        {"job": "ACCTJOB", "step": "STEP010", "dd": "RPTOUT", "class": "A", "dest": "RMT1"}
    ]


def test_seam_report_cli_reads_json_and_jsonl_and_draws_mermaid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "estate"
    write_rich_estate(root)
    assert mainframe_inventory.main([str(root), "--format", "jsonl"]) == 0
    jsonl = tmp_path / "inventory.jsonl"
    jsonl.write_text(capsys.readouterr().out, encoding="utf-8")
    inventory_json = tmp_path / "inventory.json"
    inventory_json.write_text(json.dumps(seam_report.load_inventory(jsonl)), encoding="utf-8")

    assert seam_report.main([str(jsonl), "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert (
        "| dataset | PROD.ACCT.KSDS | ACCTBAT RU, ACCTJOB.STEP020 R, ACCTPLI R, ACCTUPD RU | yes |"
        in markdown
    )
    assert "## Transaction footprints" in markdown
    assert "| AUPD | ACCTUPD, ACCTVAL |" in markdown
    assert "| Resource accesses | SYNCPOINTs | Next transactions |" in markdown
    assert (
        "- **Transfer:** ACCTJOB.STEP030 send PROD.ACCT.EXTRACT to FTP.EXAMPLE.COM acct.csv"
        in markdown
    )
    assert "- **Web endpoint:** ACCTURI /acct/* -> ACCTAPI" in markdown
    assert "- **Report:** ACCTJOB.STEP010 RPTOUT class A to RMT1" in markdown

    assert seam_report.main([str(inventory_json)]) == 0
    assert json.loads(capsys.readouterr().out)["multiple_writers"] == ["dataset:PROD.ACCT.KSDS"]

    arguments = ["--scan", str(root), "--transaction", "aupd", "--format", "mermaid"]
    assert seam_report.main(arguments) == 0
    mermaid = capsys.readouterr().out
    assert 't_AUPD(["AUPD"]) --> p_ACCTUPD' in mermaid
    assert "p_ACCTUPD -->|cics-link| p_ACCTVAL" in mermaid
    assert "p_ACCTUPD -->|RU| r_cics_file_ACCTFIL" in mermaid
    assert "REMT" not in mermaid

    inventory = seam_report.load_inventory(jsonl)
    inventory["cics_transactions"] = {}
    clusters = seam_report.to_mermaid(seam_report.build_report(inventory))
    assert 'subgraph cluster1["Write cluster 1"]' in clusters
    assert "p_ACCTBAT -->|RU| r_dataset_PROD_ACCT_KSDS" in clusters
    assert "r_dataset_PROD_ACCT_KSDS -.->|R| p_ACCTPLI" in clusters


def test_data_sets_that_are_read_are_not_outbound_feeds() -> None:
    inventory = {
        "members": [],
        "edges": [
            {"from": "ACCTUPD", "to": "ACCTFIL", "type": "cics-file", "access": "RU"},
            {"from": "ACCTEXT", "to": "EXTFIL", "type": "cics-file", "access": "C"},
        ],
        "cics": {
            "files": {
                "ACCTFIL": {"dsname": "PROD.ACCT.KSDS"},
                "EXTFIL": {"dsname": "PROD.ACCT.EXTRACT"},
            }
        },
    }
    found = seam_report.build_report(inventory)["interfaces"]
    assert found["outbound_datasets"] == ["PROD.ACCT.EXTRACT"]
    assert found["inbound_datasets"] == []


def test_seam_report_cli_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert seam_report.main(["--scan", str(tmp_path / "missing")]) == 1
    assert "not found" in capsys.readouterr().err
    assert seam_report.main([str(tmp_path / "missing.json")]) == 1
    assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        seam_report.main([str(tmp_path / "inventory.json"), "--scan", str(tmp_path)])
    with pytest.raises(SystemExit):
        seam_report.main([])
