"""Exercise registry secret handling without real tokens, AWS or cluster writes."""

import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "registry_bootstrap", Path(__file__).resolve().parents[1] / "local/bootstrap.py"
)
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class RegistryBootstrap(unittest.TestCase):
    def test_private_read_token_only_goes_to_selected_narx_namespace_via_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("unit-test-read-only")
            token.chmod(0o600)
            argv = [
                "bootstrap.py",
                "refresh-registry",
                "--context",
                "kind-narx-commerce",
                "--environment",
                "production",
                "--registry-user",
                "operator",
                "--registry-token-file",
                str(token),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(b, "command", return_value="applied") as command,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                b.main()
            args = command.call_args.args
            self.assertEqual(args[:3], ("kubectl", "--context", "kind-narx-commerce"))
            self.assertNotIn("unit-test-read-only", " ".join(args) + output.getvalue())
            secret = json.loads(command.call_args.kwargs["input"])
            self.assertEqual(
                secret["metadata"],
                {"name": "ghcr-pull", "namespace": "commerce-production"},
            )
            self.assertEqual(secret["type"], "kubernetes.io/dockerconfigjson")
            config = json.loads(secret["stringData"][".dockerconfigjson"])
            self.assertEqual(
                base64.b64decode(config["auths"]["ghcr.io"]["auth"]).decode(),
                "operator:unit-test-read-only",
            )
            command.assert_called_once()

    def test_readable_token_file_is_rejected_before_any_cluster_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token"
            token.write_text("unit-test")
            token.chmod(0o644)
            argv = [
                "bootstrap.py",
                "refresh-registry",
                "--context",
                "kind-narx-commerce",
                "--environment",
                "dev",
                "--registry-user",
                "operator",
                "--registry-token-file",
                str(token),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(b, "command") as command,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                b.main()
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
