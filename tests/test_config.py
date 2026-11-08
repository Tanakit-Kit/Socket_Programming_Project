"""Check configuration without relying on the developer's environment files."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class ConfigurationTests(unittest.TestCase):
    def run_isolated(self, overrides, assertion):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('CHAT_', 'GEMINI_', 'AGENT_'))}
        env.update(overrides)
        root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-c',
                f'import sys; sys.path.insert(0, {root!r}); import server, gemini_service; ' + assertion],
                cwd=directory, env=env, check=True, timeout=20)

    def test_defaults_without_env_file(self):
        self.run_isolated({}, "assert server.HOST == '0.0.0.0'; assert server.PORT == 5000; "
            "assert server.AGENT_MAX_STEPS == 5; assert gemini_service.GEMINI_API_KEY == ''; "
            "assert gemini_service.call_gemini_api('hello', [])")

    def test_exported_overrides(self):
        self.run_isolated({'CHAT_PORT': '5678', 'AGENT_MAX_STEPS': '3', 'GEMINI_MODELS': 'custom-model'},
            "assert server.PORT == 5678; assert server.AGENT_MAX_STEPS == 3; "
            "assert gemini_service.GEMINI_MODELS == ['custom-model']")
