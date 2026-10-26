"""Missing-vision repair must preserve the Pod's working PyTorch installation."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
import ensure_torchvision as vision


class TorchvisionTests(unittest.TestCase):
    def test_exact_official_build_selected_for_existing_torch(self):
        self.assertEqual(vision.wheel_for("2.9.1+cu128", "12.8"), (
            "torchvision==0.24.1+cu128", "https://download.pytorch.org/whl/cu128"))
        self.assertEqual(vision.wheel_for("2.9.1+cpu", None), (
            "torchvision==0.24.1+cpu", "https://download.pytorch.org/whl/cpu"))

    def test_unknown_prerelease_and_inconsistent_builds_are_rejected(self):
        for version, cuda in [("2.99.0+cu128", "12.8"), ("2.9.1rc1+cu128", "12.8"),
                              ("2.9.1+cu128", "12.6"), ("2.9.1+cpu", "12.8"),
                              ("2.9.1+rocm6.4", None), ("2.9.1", "12.4")]:
            with self.subTest(version=version, cuda=cuda):
                with self.assertRaisesRegex(RuntimeError, "was not changed"):
                    vision.wheel_for(version, cuda)

    @mock.patch.object(vision.subprocess, "run")
    @mock.patch.object(vision.importlib.util, "find_spec", return_value=None)
    def test_missing_vision_installs_only_the_matching_binary_then_checks_it(self, spec, run):
        with mock.patch.object(sys, "prefix", "/training/venv"), \
                mock.patch.object(sys, "base_prefix", "/system"):
            vision.ensure("2.9.1+cu128", "12.8")
        self.assertEqual(run.call_count, 2)
        install = run.call_args_list[0]
        self.assertEqual(install.args[0], [
            sys.executable, "-m", "pip", "install", "--no-deps", "--only-binary=:all:",
            "--index-url", "https://download.pytorch.org/whl/cu128", "torchvision==0.24.1+cu128"])
        self.assertTrue(install.kwargs["check"])
        self.assertEqual(run.call_args_list[1].args[0], [sys.executable, "-c", vision.VERIFY])

    @mock.patch.object(vision.subprocess, "run")
    @mock.patch.object(vision.importlib.util, "find_spec", return_value=None)
    def test_missing_vision_never_installs_in_system_python(self, spec, run):
        with mock.patch.object(sys, "prefix", "/system"), \
                mock.patch.object(sys, "base_prefix", "/system"):
            with self.assertRaisesRegex(RuntimeError, "requires a training venv"):
                vision.ensure("2.9.1+cu128", "12.8")
        run.assert_not_called()

    @mock.patch.object(vision.subprocess, "run")
    @mock.patch.object(vision.importlib.util, "find_spec", return_value=object())
    def test_existing_installation_is_verified_without_pip_or_version_selection(self, spec, run):
        # A custom but working preinstalled pair need not be in our repair table.
        vision.ensure("custom", "custom")
        run.assert_called_once_with([sys.executable, "-c", vision.VERIFY], check=True)

    @mock.patch.object(vision.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "check"))
    @mock.patch.object(vision.importlib.util, "find_spec", return_value=object())
    def test_broken_existing_installation_stops_without_replacing_it(self, spec, run):
        with self.assertRaises(subprocess.CalledProcessError):
            vision.ensure("2.9.1+cu128", "12.8")
        run.assert_called_once_with([sys.executable, "-c", vision.VERIFY], check=True)


if __name__ == "__main__":
    unittest.main()
