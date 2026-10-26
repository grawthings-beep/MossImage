from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from restart import owns, targets, terminate, main


class RestartTests(unittest.TestCase):
    def test_stop_releases_runtime_lock_without_starting_generation_again(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_fcntl=SimpleNamespace(LOCK_EX=2,LOCK_NB=4,LOCK_UN=8,flock=Mock())
            with patch('restart.sys.platform','linux'), patch('restart.sys.argv',['restart.py','--stop']), \
                 patch.dict('os.environ',{'MOSS_HOME':directory}), patch.dict(sys.modules,{'fcntl':fake_fcntl}), \
                 patch('restart.targets',return_value={}), patch('restart.terminate') as stop, \
                 patch('restart.subprocess.call') as start:
                self.assertEqual(main(),0)
                stop.assert_called_once()
                start.assert_not_called()
                self.assertEqual(fake_fcntl.flock.call_args_list[-1].args[1],fake_fcntl.LOCK_UN)

    def test_only_this_kit_and_runtime_match(self):
        kit=Path('/kit').resolve(); runtime=Path('/runtime').resolve()
        server=['python','-u',str(kit/'launch_comfy.py'),'--runtime',str(runtime)]
        backend=['python','-u',str(runtime/'ComfyUI/main.py'),'--listen','127.0.0.1']
        self.assertTrue(owns(server,kit,runtime)); self.assertTrue(owns(backend,kit,runtime))
        self.assertTrue(owns(['python','-u',str(kit/'pod_boot.py'),'--runtime',str(runtime)],kit,runtime))
        for argv in ([*server[:-1],str(runtime/'other')],['python','training/train.py',str(kit/'launch_comfy.py')],
                     ['python',str(runtime/'other/ComfyUI/main.py')],['bash','-c',' '.join(server)]):
            self.assertFalse(owns(argv,kit,runtime))

    def test_scan_excludes_pid_one_and_reused_pid_is_not_signalled(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); kit=root/'kit'; runtime=root/'runtime'
            argv=['python','-u',str(runtime/'ComfyUI/main.py')]
            for pid in (1,12345):
                p=root/str(pid); p.mkdir()
                (p/'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv)+b'\0')
                (p/'stat').write_text(f'{pid} (python worker) S '+'0 '*18+'100 0')
            found=targets(root,kit,runtime)
            self.assertEqual(set(found),{12345})
            with patch('restart.os.kill') as kill:
                terminate(root,found,kit,runtime)
                self.assertEqual(kill.call_count,1)
                kill.reset_mock()
                (root/'12345/stat').write_text('12345 (python worker) S '+'0 '*18+'101 0')
                terminate(root,found,kit,runtime)
                kill.assert_not_called()


if __name__=='__main__': unittest.main()
