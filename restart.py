"""Restart this kit's generation server on Linux, without matching other Python jobs."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def process(proc, pid):
    try:
        folder = proc / str(pid)
        argv = [os.fsdecode(part) for part in (folder / 'cmdline').read_bytes().split(b'\0') if part]
        stat = (folder / 'stat').read_text()
        started = stat[stat.rfind(')') + 2:].split()[19]
        return argv, started
    except (OSError, IndexError):
        return None


def owns(argv, kit, runtime):
    script = argv[2] if len(argv) > 2 and argv[1] == '-u' else argv[1] if len(argv) > 1 else ''
    if script == str(runtime / 'ComfyUI/main.py'):
        return True
    if script not in (str(kit / 'launch_comfy.py'), str(kit / 'pod_boot.py')) or '--runtime' not in argv:
        return False
    index = argv.index('--runtime') + 1
    return index < len(argv) and Path(argv[index]).resolve() == runtime


def targets(proc, kit, runtime):
    found = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) in (1, os.getpid()):
            continue
        current = process(proc, int(entry.name))
        if current and owns(current[0], kit, runtime):
            found[int(entry.name)] = current
    return found


def terminate(proc, expected, kit, runtime):
    for pid, previous in expected.items():
        # Recheck the command and process start time, so a reused PID is never signalled.
        current = process(proc, pid)
        if current == previous and owns(current[0], kit, runtime):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def main():
    if sys.platform != 'linux':
        raise SystemExit('Run this restart command in the RunPod terminal.')
    import fcntl
    options = sys.argv[1:]
    stop_only = options == ['--stop']
    if '--stop' in options and not stop_only:
        raise SystemExit('--stop does not accept additional startup options.')
    kit = Path(__file__).resolve().parent
    runtime = Path(os.environ.get('MOSS_HOME', '/workspace/moss-image-runtime')).resolve()
    proc = Path('/proc')
    matching = targets(proc, kit, runtime)
    print(f'Stopping {len(matching)} generation processes for this MOSS runtime.', flush=True)
    terminate(proc, matching, kit, runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'runtime.lock').open('a') as lock:
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SystemExit('The runtime is still busy (possibly setup or another checkout). No other processes were stopped. Try after setup finishes.')
                time.sleep(.25)
        fcntl.flock(lock, fcntl.LOCK_UN)
    if stop_only:
        print('Generation server stopped. Models and projects remain saved; training can proceed when the GPU is free.', flush=True)
        return 0
    # Preserve the caller's HF_TOKEN/MOSS_HOME and forward start.sh options.
    return subprocess.call(['bash', str(kit / 'background.sh'), *options])


if __name__ == '__main__':
    raise SystemExit(main())
