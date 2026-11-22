#!/usr/bin/env python3
"""Unit tests for tools/ci/windows_release.py (python3 -I tools/ci/test_windows_release.py)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import windows_release as wr  # noqa: E402


class WindowsReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="win-release-test-"))
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.com",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.tmp),
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    def _init_git(self):
        self._git("init")
        (self.tmp / "README.md").write_text("init\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-m", "initial commit")

    def _populate_valid_repo_files(self):
        (self.tmp / ".github" / "workflows").mkdir(parents=True)
        (self.tmp / "tools" / "ci").mkdir(parents=True)
        (self.tmp / "editor" / "resources" / "icons").mkdir(parents=True)
        (self.tmp / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (self.tmp / "editor" / "resources" / "icons" / "jasperengine-editor.ico").write_bytes(b"ICO")
        (self.tmp / "tools" / "ci" / "windows.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (self.tmp / "tools" / "ci" / "check-call-cli.py").write_text("print('ok')\n", encoding="utf-8")
        (self.tmp / "CMakePresets.json").write_text('{"configurePresets":[{"name":"windows-msvc-release"}]}', encoding="utf-8")
        (self.tmp / ".github" / "workflows" / "windows-release.yml").write_text(
            "name: Win\non: workflow_dispatch\njobs:\n  b:\n    steps:\n"
            "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
            encoding="utf-8",
        )
        (self.tmp / "tools" / "ci" / "windows-installer.iss").write_text(
            "[Setup]\nAppId={{1234}}\n[Languages]\n[Tasks]\n[Files]\n[Icons]\n[Run]\n[Code]\n"
            "function NeedsVCRedist: Boolean;\nbegin\nResult := False;\nend;\n",
            encoding="utf-8",
        )

    def test_resolve_version_defaults_and_bumps(self):
        self._init_git()
        info = wr.resolve_version(self.tmp, bump="patch")
        self.assertEqual(info, {"version": "v0.1.0", "numeric": "0.1.0.0", "previous_tag": ""})

        self._git("tag", "v0.1.0")
        self._git("tag", "build-cache-windows-msvc")
        self.assertEqual(
            wr.resolve_version(self.tmp, bump="patch"),
            {"version": "v0.1.1", "numeric": "0.1.1.0", "previous_tag": "v0.1.0"},
        )
        self.assertEqual(
            wr.resolve_version(self.tmp, bump="minor"),
            {"version": "v0.2.0", "numeric": "0.2.0.0", "previous_tag": "v0.1.0"},
        )
        self.assertEqual(
            wr.resolve_version(self.tmp, bump="major"),
            {"version": "v1.0.0", "numeric": "1.0.0.0", "previous_tag": "v0.1.0"},
        )
        self.assertEqual(
            wr.resolve_version(self.tmp, ref_type="tag", ref_name="win-20261122"),
            {"version": "win-20261122", "numeric": "0.0.0.0", "previous_tag": "v0.1.0"},
        )

    def test_resolve_version_rejects_bad_characters(self):
        self._init_git()
        with self.assertRaises(ValueError):
            wr.resolve_version(self.tmp, explicit="v1.0 bad")

    def test_validate_passes_and_catches_unpinned_action(self):
        self._populate_valid_repo_files()
        self.assertEqual(wr.validate_repo(self.tmp, version="v0.1.0", run_repo_lints=False), [])

        wf = self.tmp / ".github" / "workflows" / "windows-release.yml"
        wf.write_text("name: Win\njobs:\n  b:\n    steps:\n      - uses: actions/checkout@v4\n", encoding="utf-8")
        problems = wr.validate_repo(self.tmp, version="v0.1.0", run_repo_lints=False)
        self.assertTrue(any("40-hex commit SHA" in p for p in problems), problems)

    def test_validate_catches_unescaped_appid(self):
        self._populate_valid_repo_files()
        iss = self.tmp / "tools" / "ci" / "windows-installer.iss"
        iss.write_text(iss.read_text(encoding="utf-8").replace("AppId={{1234}}", "AppId={1234}"), encoding="utf-8")
        problems = wr.validate_repo(self.tmp, run_repo_lints=False)
        self.assertTrue(any("AppId={{" in p for p in problems), problems)

    def test_release_notes_includes_hashes_and_fallback_changelog(self):
        self._init_git()
        self._git("tag", "v0.1.0")
        (self.tmp / "feature.txt").write_text("hello\n", encoding="utf-8")
        self._git("add", "feature.txt")
        self._git("commit", "-m", "feat: add sample feature")
        head = self._git("rev-parse", "HEAD")

        setup = self.tmp / "JasperEngine-v0.1.1-windows-x64-setup.exe"
        setup.write_bytes(b"setup-binary")
        portable = self.tmp / "JasperEngine-v0.1.1-windows-x64.zip"
        portable.write_bytes(b"zip-binary")

        notes = wr.build_release_notes(
            self.tmp,
            version="v0.1.1",
            commit=head,
            previous_tag="v0.1.0",
            assets=[setup, portable],
            repo_url="https://github.com/example/repo",
            run_url="https://github.com/example/repo/actions/runs/123",
        )
        self.assertIn("JasperEngine v0.1.1 (Windows x64)", notes)
        self.assertIn("JasperEngine-v0.1.1-windows-x64-setup.exe", notes)
        self.assertIn("JasperEngine-v0.1.1-windows-x64.zip", notes)
        self.assertIn("feat: add sample feature", notes)
        self.assertIn("SmartScreen", notes)


if __name__ == "__main__":
    unittest.main()
