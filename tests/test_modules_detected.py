import json
import subprocess
import sys

from conftest import LAUNCHER, REPO

LEGAL = ("Acme LLC (hereinafter the Supplier) shall sign the DPA in "
         "Schedule 1 under the GDPR, notwithstanding the foregoing "
         "and subject to Clause 4.")
PLAIN = ("The worker reads the queue and writes one line per event, and the "
         "canteen menu on the wall still offers the soup to anyone.")


def test_a_domain_is_detected_from_the_text(kv):
    assert [n for n, _ in kv.detect_modules(LEGAL)] == ["legal"]
    assert kv.detect_modules(PLAIN) == []


def test_plan_prints_the_modules_line(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Notes\n\n" + (LEGAL + " ") * 3 + "\n")
    r = subprocess.run([sys.executable, str(LAUNCHER), "plan", str(doc)],
                       capture_output=True, text=True)
    assert "modules: legal (" in r.stdout, r.stdout + r.stderr
    doc.write_text("# Notes\n\n" + PLAIN + "\n")
    r = subprocess.run([sys.executable, str(LAUNCHER), "plan", str(doc)],
                       capture_output=True, text=True)
    assert "modules: none detected" in r.stdout, r.stdout + r.stderr


def test_the_shipped_legal_sample_is_read_as_legal():
    r = subprocess.run([sys.executable, str(LAUNCHER), "plan",
                        str(REPO / "tests" / "fixtures" / "legal-sample.md")],
                       capture_output=True, text=True)
    assert "modules: legal (" in r.stdout, r.stdout + r.stderr
