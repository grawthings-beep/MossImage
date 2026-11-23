"""Train verified bundles dropped in the RunPod volume, including at boot."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

from common import digest, valid_name
from runtime import receiver


FILENAME = re.compile(r"moss_([a-z0-9][a-z0-9_]{0,63})\.([0-9a-f]{64})\.tar\.gz")
LAUNCH = Path(__file__).with_name("launch.py")


def receive(inbox, root, name, sha, code):
    destination = inbox / f"moss_{name}.{sha}.tar.gz"
    try:
        if destination.is_file() and digest(destination) == sha:
            return
        print(f"{name}: receiving the bundle from the PC", flush=True)
        with tempfile.TemporaryDirectory(dir=inbox) as tmp:
            result = subprocess.run([receiver(root), "receive", code], cwd=tmp,
                                    stdin=subprocess.DEVNULL)
            if result.returncode:
                raise ValueError(f"runpodctl exited with status {result.returncode}")
            archive = Path(tmp) / f"moss_{name}_run.tar.gz"
            if not archive.is_file() or archive.is_symlink() or digest(archive) != sha:
                raise ValueError("Received file missing or SHA256 mismatch")
            archive.replace(destination)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"{name}: transfer failed ({exc}). You can upload the prepared bundle to {inbox}.", flush=True)


def scan(inbox, root, observed, dispatched):
    for path in sorted(inbox.glob("moss_*.tar.gz")):
        match = FILENAME.fullmatch(path.name)
        if not match or path.is_symlink():
            continue
        name, sha = match.groups()
        if dispatched.get(name) == sha:
            continue
        try:
            stat = path.stat()
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if observed.get(path) == signature:
                continue
            observed[path] = signature
            if not path.is_file() or digest(path) != sha:
                print(f"{name}: waiting for upload to match SHA256", flush=True)
                continue
            if name in dispatched:
                print(f"{name}: another bundle with this job name was submitted; choose a new job name.", flush=True)
                continue
            subprocess.run([sys.executable, "-u", str(LAUNCH), "start", name,
                            "--root", str(root), "--bundle", str(path), "--sha256", sha,
                            "--no-follow"], check=True)
            dispatched[name] = sha
            print(f"{name}: see {root / 'jobs' / name / 'train.log'}", flush=True)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"{path.name}: {exc}", flush=True)
            observed.pop(path, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receive", nargs=3, metavar=("NAME", "SHA256", "CODE"))
    args = parser.parse_args()
    inbox = Path("/workspace/LoRA-inbox")
    root = Path(os.environ.get("MOSS_TRAIN_HOME", "/workspace/moss-training")).resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    if args.receive:
        name, sha, code = args.receive
        valid_name(name)
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(r"[0-9]{4}-(?:[a-z]+-){3}[0-9]+", code):
            parser.error("Invalid transfer parameters")
        threading.Thread(target=receive, args=(inbox, root, name, sha, code), daemon=True).start()
    print(f"Training mode ready. Upload a checksum-named MOSS bundle to {inbox}.", flush=True)
    observed, dispatched = {}, {}
    while True:
        scan(inbox, root, observed, dispatched)
        time.sleep(5)


if __name__ == "__main__":
    main()
