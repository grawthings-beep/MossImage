"""Contract tests; fake GPU processes are explicit and do not prove GPU training."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

TRAINING = Path(__file__).resolve().parents[1] / "training"
sys.path.insert(0, str(TRAINING))
from build_bundle import build
from common import digest, read_json, read_bundle, validate_pairs, verify_final, write_json
import runtime

spec = importlib.util.spec_from_file_location("moss_training_launch", TRAINING / "launch.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


class RuntimeSetupTests(unittest.TestCase):
    def test_vision_checked_before_trainer_imports_even_for_ready_venv(self):
        for already_ready in (False, True):
            with self.subTest(already_ready=already_ready), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                constraints = root / "cuda-constraints.txt"
                constraints.write_bytes(b"torch==2.9.1+cu128\n")
                identity = hashlib.sha256((TRAINING / "requirements.txt").read_bytes()
                    + constraints.read_bytes() + (TRAINING / "revisions.json").read_bytes()).hexdigest()[:16]
                venv = root / "venvs" / identity
                python = venv / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.touch()
                if already_ready:
                    (venv / "moss-ready.json").write_text("{}")
                with mock.patch.object(runtime.subprocess, "run") as run, \
                        mock.patch.object(runtime, "sources", return_value=root / "sources"):
                    runtime.setup(root)
                commands = [call.args[0] for call in run.call_args_list]
                vision_index = commands.index([str(python), str(TRAINING / "ensure_torchvision.py")])
                cuda_index = commands.index([str(python), str(runtime.KIT / "check_runtime.py")])
                imports_index = commands.index([str(python), str(Path(runtime.__file__)), "check"])
                self.assertLess(vision_index, cuda_index)
                self.assertLess(cuda_index, imports_index)
                installs = [i for i, cmd in enumerate(commands) if "install" in cmd]
                self.assertEqual(len(installs), 0 if already_ready else 1)
                if installs:
                    self.assertLess(installs[0], vision_index)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.dataset = self.base / "dataset"
        self.dataset.mkdir()
        # Dataset contract tests use signatures; runtime.validate_images tests real decoding.
        (self.dataset / "one.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"fixture")
        (self.dataset / "one.txt").write_text("t0ken, one woman, red dress", encoding="utf-8")
        report = build(self.dataset, "test_character", "t0ken", self.base / "bundles")
        self.report = read_json(report)
        self.archive = Path(self.report["bundle"])
        self.job, self.files = read_bundle(self.archive, self.report["sha256"])
        self.job_dir = self.base / "jobs/test_character"
        self.job_dir.mkdir(parents=True)

    def install(self):
        return launch.install_bundle(self.archive, self.report["sha256"], self.job_dir, "test_character")

    def test_round_trip_preserves_original_bytes_and_is_repeatable(self):
        self.install()
        for name, data in self.files.items():
            self.assertEqual((self.job_dir / "train" / name).read_bytes(), data)
        again = read_json(build(self.dataset, "test_character", "t0ken", self.base / "bundles"))
        self.assertEqual(self.report["sha256"], again["sha256"])
        self.install()

    def test_bundle_corruption_is_rejected_before_extraction(self):
        self.archive.write_bytes(self.archive.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.install()
        self.assertFalse((self.job_dir / "train").exists())

    def test_no_caption_missing_trigger_and_duplicate_stems_rejected(self):
        for files in [{"one.png": self.files["one.png"]},
                      {**self.files, "one.txt": b"a woman, no trigger"},
                      {**self.files, "one.jpg": b"\xff\xd8\xff"}]:
            with self.subTest(files=list(files)), self.assertRaises(ValueError):
                validate_pairs(files, "t0ken")

    def test_path_traversal_links_duplicate_and_code_members_rejected(self):
        for filename, member_type in [("../escaped", tarfile.REGTYPE), ("train/link.png", tarfile.SYMTYPE),
                                      ("launch.py", tarfile.REGTYPE), ("job.json", tarfile.REGTYPE)]:
            with self.subTest(name=filename):
                archive = self.base / "unsafe.tar.gz"
                with tarfile.open(self.archive) as original, tarfile.open(archive, "w:gz") as target:
                    for member in original:
                        target.addfile(member, original.extractfile(member))
                    extra = tarfile.TarInfo(filename)
                    extra.type, extra.size, extra.linkname = member_type, 1, "/etc/passwd"
                    target.addfile(extra, io.BytesIO(b"x"))
                with self.assertRaises(ValueError):
                    read_bundle(archive, digest(archive))

    def test_modified_received_data_is_preserved(self):
        self.install()
        caption = self.job_dir / "train/one.txt"
        caption.write_text("my edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.install()
        self.assertEqual(caption.read_text(), "my edit")

    def test_same_name_with_changed_recipe_is_refused(self):
        self.install()
        recipe = {**self.job["recipe"], "total_steps": 2500}
        other = read_json(build(self.dataset, "test_character", "t0ken", self.base / "other", recipe))
        with self.assertRaisesRegex(ValueError, "different dataset/recipe"):
            launch.install_bundle(Path(other["bundle"]), other["sha256"], self.job_dir, self.job["name"])

    def test_final_requires_expected_steps_identity_and_complete_tensor_data(self):
        path = self.base / "result.safetensors"
        def data(steps=2000, name="test_character"):
            header = {"__metadata__": {"ss_steps": str(steps), "project_name": name,
                       "trigger_word": "t0ken", "ss_sd_model_name": "MOSS-Image-Base", "ss_network_dim": "16"},
                      "diffusion_model.layers.0.proj.q.lora_A.weight":
                          {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
            raw = json.dumps(header).encode()
            return struct.pack("<Q", len(raw)) + raw + b"\0" * 4
        path.write_bytes(data())
        verify_final(path, self.job)
        for invalid in [data(250), data(name="wrong"), data()[:-1], b"<html>failure</html>"]:
            path.write_bytes(invalid)
            with self.assertRaises((ValueError, struct.error)):
                verify_final(path, self.job)

    def test_settings_use_isolated_job_paths_and_moss_recipe(self):
        cfg = runtime.configurations(self.base, self.job_dir, self.job)
        pre = cfg["settings/pre_cache_settings_mossimage.json"]
        train = cfg["settings/train_settings_mossimage.json"]
        self.assertEqual(pre["target_area"], 1024 ** 2)
        self.assertEqual(pre["dataset_path"], str(self.job_dir / "train"))
        self.assertEqual(pre["text_encoder"], "BF16_offload")
        self.assertEqual((train["base_model"], train["lora_rank"], train["lora_alpha"]), ("base", 16, 16))
        self.assertEqual(train["timestep_sampling"], "moss")

    def test_detached_launcher_and_duplicate_job_handling(self):
        fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=mock.Mock())
        args = argparse.Namespace(root=self.base, name=self.job["name"], code="1111-test-test-test-0",
                                  sha256=self.report["sha256"], bundle=None, no_follow=True)
        with mock.patch.dict(sys.modules, fcntl=fake_fcntl), mock.patch.object(launch.subprocess, "Popen") as popen:
            launch.start(args, self.job_dir)
            kwargs = popen.call_args.kwargs
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(len(kwargs["pass_fds"]), 1)
            fake_fcntl.flock.side_effect = BlockingIOError()
            launch.start(args, self.job_dir)
            self.assertEqual(popen.call_count, 1)

    def test_corrupt_cache_is_not_silently_replaced(self):
        self.install()
        write_json(self.job_dir / "precache-complete.json", {"job_sha256": digest(self.job_dir / "job.json")})
        with mock.patch.object(launch, "child", side_effect=subprocess.CalledProcessError(1, "cache")):
            with self.assertRaises(subprocess.CalledProcessError):
                launch.cache_valid(self.job_dir, self.job, "python", [], {})

    def test_zero_exit_without_final_does_not_report_success(self):
        self.install()
        args = argparse.Namespace(root=self.base, name=self.job["name"], code=None,
                                  bundle=None, lock_fd=1)
        fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=mock.Mock())
        with mock.patch.dict(sys.modules, fcntl=fake_fcntl), mock.patch.object(launch.os, "fstat"), \
                mock.patch.object(launch, "gpu_processes", return_value=[]), \
                mock.patch.object(launch, "child"), \
                mock.patch.object(runtime, "prepare_job", return_value={"python": "python"}), \
                mock.patch.object(launch, "cache_valid", return_value=True):
            with self.assertRaises(FileNotFoundError):
                launch.work(args, self.job_dir)
        self.assertNotEqual(read_json(self.job_dir / "status.json")["state"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
