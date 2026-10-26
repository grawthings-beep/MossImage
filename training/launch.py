"""Receive, validate and run a detached MOSS training job. Linux / RunPod only."""
import argparse
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from common import digest, read_bundle, read_json, valid_name, validate_job, verify_dataset, verify_final, write_json
import runtime

HERE = Path(__file__).resolve().parent


def state(job_dir, value, **fields):
    write_json(job_dir / "status.json", {"state": value, "worker_pid": os.getpid(),
                                        "time": time.time(), **fields})
    print(value + (": " + str(fields) if fields else ""), flush=True)


def install_bundle(archive, sha, job_dir, name):
    job, files = read_bundle(archive, sha)
    if job["name"] != name:
        raise ValueError("Received job name differs from the requested name")
    manifest = job_dir / "job.json"
    if manifest.exists() and read_json(manifest) != job:
        raise ValueError("This job name already has a different dataset/recipe; nothing was overwritten")
    dataset = job_dir / "train"
    if dataset.exists() or dataset.is_symlink():
        verify_dataset(dataset, job)
    else:
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=job_dir) as tmp:
            staged = Path(tmp) / "train"
            staged.mkdir()
            for filename, data in files.items():
                (staged / filename).write_bytes(data)
            verify_dataset(staged, job)
            staged.rename(dataset)
    write_json(manifest, job)
    print(f"IMAGES={job['images']} TXT={job['images']} SHA256=OK", flush=True)
    return job


def child(command, locks, **kwargs):
    """Children keep the locks if the supervising worker dies unexpectedly."""
    p = subprocess.Popen(command, pass_fds=tuple(locks), stdin=subprocess.DEVNULL, **kwargs)
    try:
        code = p.wait()
    except BaseException:
        p.terminate()
        try:
            p.wait(timeout=120)  # Give the trainer time to save a checkpoint on SIGTERM.
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        raise
    if code:
        raise subprocess.CalledProcessError(code, command)


def gpu_processes():
    result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                            check=True, capture_output=True, text=True, timeout=20)
    return [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]


def cache_valid(job_dir, job, py, locks, env):
    marker = job_dir / "precache-complete.json"
    if not marker.exists() or read_json(marker).get("job_sha256") != digest(job_dir / "job.json"):
        return False
    try:
        child([py, str(HERE / "runtime.py"), "cache", "--job", str(job_dir)], locks, env=env)
        return True
    except subprocess.CalledProcessError:
        print("Cached tensors failed verification; stopping without overwriting them.", flush=True)
        raise


def work(args, job_dir):
    import fcntl
    # This fd was inherited from the foreground launcher; never unlock it in the parent.
    os.fstat(args.lock_fd)
    locks = [args.lock_fd]
    root = args.root
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", TOKENIZERS_PARALLELISM="false",
               HF_HUB_DISABLE_TELEMETRY="1", HF_HOME=str(root / "hf-cache"),
               PIP_CACHE_DIR=str(root / "pip-cache"))
    # A resumed shell may carry offline settings from unrelated jobs.
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTHONPATH"):
        env.pop(key, None)
    if args.code:
        state(job_dir, "RECEIVING")
        receiver = runtime.receiver(root)
        with tempfile.TemporaryDirectory(prefix="receive-", dir=job_dir) as tmp:
            child([receiver, "receive", args.code], locks, cwd=tmp, env=env)
            archive = Path(tmp) / f"moss_{args.name}_run.tar.gz"
            job = install_bundle(archive, args.sha256, job_dir, args.name)
    elif args.bundle:
        job = install_bundle(args.bundle, args.sha256, job_dir, args.name)
    else:
        job = validate_job(read_json(job_dir / "job.json"))
        if job["name"] != args.name:
            raise ValueError("Manifest name mismatch")
        verify_dataset(job_dir / "train", job)
    final = root / "outputs" / f"mossimage_lora_{job['name']}.safetensors"
    if final.exists():
        verify_final(final, job)
        state(job_dir, "COMPLETE", output=str(final), message="Existing completed job; training not repeated")
        return
    state(job_dir, "QUEUED", images=job["images"], steps=job["recipe"]["total_steps"])
    with (root / "gpu.lock").open("a+") as gpu:
        try:
            fcntl.flock(gpu, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            state(job_dir, "WAITING", message="Another MOSS job owns the GPU lock")
            fcntl.flock(gpu, fcntl.LOCK_EX)
        locks.append(gpu.fileno())
        reported = False
        while gpu_processes():
            if not reported:
                state(job_dir, "WAITING", message="GPU is in use. Stop the generation server or let the other training finish.")
                reported = True
            time.sleep(10)
        verify_dataset(job_dir / "train", job)
        state(job_dir, "SETTING_UP")
        child([sys.executable, str(HERE / "runtime.py"), "setup", "--root", str(root)], locks, env=env)
        config = runtime.prepare_job(root, job_dir, job)
        py = config["python"]
        child([py, str(HERE / "runtime.py"), "images", "--job", str(job_dir)], locks, env=env)
        child([py, str(HERE / "runtime.py"), "models", "--root", str(root)], locks, env=env)
        # The source's downloader uses main. Everything was fetched above at a fixed revision.
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        scripts = job_dir / "scripts"
        if not cache_valid(job_dir, job, py, locks, env):
            state(job_dir, "PRECACHE")
            child([py, "-u", str(scripts / "1_pre_cache_mossimage.py")], locks, cwd=job_dir, env=env)
            child([py, str(HERE / "runtime.py"), "cache", "--job", str(job_dir)], locks, env=env)
            write_json(job_dir / "precache-complete.json", {"job_sha256": digest(job_dir / "job.json")})
        out = runtime.output_dir(job_dir, job)
        original = out / "MossImage_FINAL_LoRA.safetensors"
        if original.exists():
            verify_final(original, job)
        else:
            child([py, str(HERE / "runtime.py"), "resume", "--job", str(job_dir)], locks, env=env)
            state(job_dir, "TRAINING", steps=job["recipe"]["total_steps"])
            child([py, "-u", str(scripts / "2_train_lora_mossimage.py")], locks, cwd=job_dir, env=env)
            # Upstream can return exit code zero on a stop signal; require a real final export.
            verify_final(original, job)
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            raise ValueError("Final output appeared during training; refusing to overwrite")
        temporary = final.with_suffix(".safetensors.tmp")
        shutil.copyfile(original, temporary)
        verify_final(temporary, job)
        temporary.rename(final)
        state(job_dir, "COMPLETE", output=str(final), bytes=final.stat().st_size,
              sha256=digest(final), checkpoints=str(out))


def follow(job_dir):
    print(f"Log: {job_dir / 'train.log'}", flush=True)
    print("Ctrl+C / closing Safari stops only this log view. The worker continues.", flush=True)
    try:
        subprocess.run(["tail", "-n", "40", "-F", str(job_dir / "train.log")], check=True)
    except KeyboardInterrupt:
        pass


def start(args, job_dir):
    import fcntl
    with (job_dir / "job.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Already receiving/queued/running; showing the existing log.", flush=True)
        else:
            cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "worker", args.name,
                   "--root", str(args.root), "--lock-fd", str(lock.fileno())]
            for key in ("code", "sha256", "bundle"):
                value = getattr(args, key)
                if value:
                    cmd += ["--" + key, str(value)]
            with (job_dir / "train.log").open("ab", buffering=0) as log:
                process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True, pass_fds=(lock.fileno(),), cwd=job_dir)
            print(f"WORKER_PID={process.pid}; receipt/setup/training now run in the background.", flush=True)
    if not args.no_follow:
        follow(job_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["receive", "start", "resume", "logs", "status", "worker"])
    parser.add_argument("name", type=valid_name)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("MOSS_TRAIN_HOME", "/workspace/moss-training")))
    parser.add_argument("--code")
    parser.add_argument("--sha256")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--no-follow", action="store_true")
    parser.add_argument("--lock-fd", type=int)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Run train.sh on the Linux GPU Pod; use build_bundle.py / send_bundle.ps1 on Windows.")
    args.root = args.root.resolve()
    if args.bundle:
        args.bundle = args.bundle.resolve()
    if args.action == "receive":
        if not args.code or not re.fullmatch(r"[0-9]{4}-[a-z]+-[a-z]+-[a-z]+-[0-9]+", args.code):
            parser.error("--code must be a real runpodctl receive code")
    if args.action == "start" and not args.bundle:
        parser.error("start requires --bundle")
    if (args.code or args.bundle) and not re.fullmatch(r"[0-9a-f]{64}", args.sha256 or ""):
        parser.error("A verified --sha256 is required")
    if args.action not in ("worker", "receive", "start") and (args.code or args.bundle or args.sha256):
        parser.error("resume/logs/status use only the saved job name")
    job_dir = args.root / "jobs" / args.name
    if job_dir.is_symlink():
        parser.error("Job directory must not be a symlink")
    job_dir.mkdir(parents=True, exist_ok=True)
    if args.action == "status":
        print((job_dir / "status.json").read_text() if (job_dir / "status.json").exists() else "No status yet")
    elif args.action == "logs":
        follow(job_dir)
    elif args.action == "worker":
        def stop(signum, frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, stop)
        try:
            work(args, job_dir)
        except KeyboardInterrupt:
            state(job_dir, "STOPPED", message="Resume explicitly with train.sh resume NAME")
        except Exception as error:
            state(job_dir, "FAILED", error=str(error))
            raise
    else:
        if args.action == "resume" and not (job_dir / "job.json").is_file():
            parser.error("No received job found. Receive a bundle first.")
        start(args, job_dir)


if __name__ == "__main__":
    main()
