from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from restart import owns, targets, terminate


class RestartTests(unittest.TestCase):
    def test_only_this_kit_and_runtime_match(self):
        kit=Path('/kit').resolve(); runtime=Path('/runtime').resolve()
        server=['python','-u',str(kit/'launch_comfy.py'),'--runtime',str(runtime)]
        backend=['python','-u',str(runtime/'ComfyUI/main.py'),'--listen','127.0.0.1']
        self.assertTrue(owns(server,kit,runtime)); self.assertTrue(owns(backend,kit,runtime))
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
