"""Exercise actual curses key decoding and terminal restoration on Linux."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux PTY and curses')
class TerminalTests(unittest.TestCase):
    def test_down_and_right_arrows_and_terminal_restoration(self):
        import pty
        import select
        import termios
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        path = Path(__file__).resolve().parents[1] / 'src/campus-network'
        code = "import runpy,sys,json; m=runpy.run_path(sys.argv[1]); print('RESULT='+json.dumps(m['select_menu']('test-menu', ['first','second'])))"
        child = subprocess.Popen([sys.executable, '-c', code, str(path)], stdin=slave,
                                 stdout=slave, stderr=slave,
                                 env=dict(os.environ, TERM='xterm-256color', LC_ALL='C.UTF-8'))
        output, sent = b'', False
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    output += os.read(master, 65536)
                if b'test-menu' in output and not sent:
                    os.write(master, b'\x1bOB\x1bOC')
                    sent = True
                if b'RESULT=' in output:
                    break
            child.wait(timeout=2)
            match = re.search(rb'RESULT=(\[.*?\])', output)
            self.assertIsNotNone(match, output.decode(errors='replace'))
            self.assertEqual(json.loads(match[1]), [1, 'enable'])
            self.assertEqual(termios.tcgetattr(slave), original)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    unittest.main()
