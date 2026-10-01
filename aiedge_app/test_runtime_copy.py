"""Source-level runtime COPY admission; does not substitute for a Docker build."""
import ast, pathlib, re, shlex, unittest
ROOT=pathlib.Path(__file__).resolve().parent

def missing_runtime_modules(dockerfile):
    copied=set()
    final=dockerfile.split('\nFROM ')[-1]
    for line in final.splitlines():
        tokens=shlex.split(line)
        if tokens and tokens[0]=='COPY' and not tokens[1].startswith('--from='):
            copied.update(token for token in tokens[1:-1] if token.endswith('.py'))
    missing=set()
    for name in copied:
        tree=ast.parse((ROOT/name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            modules=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) else []
            for module in modules:
                if not module:continue
                path=ROOT/(module.split('.')[0]+'.py')
                if path.is_file() and path.name not in copied:missing.add(path.name)
    return sorted(missing)

class RuntimeCopyTests(unittest.TestCase):
    def test_all_local_runtime_dependencies_are_copied(self):
        self.assertEqual(missing_runtime_modules((ROOT/'Dockerfile').read_text()),[])
    def test_a_missing_clock_module_is_rejected(self):
        docker=(ROOT/'Dockerfile').read_text().replace(' capture_clock.py ',' ')
        self.assertIn('capture_clock.py',missing_runtime_modules(docker))
    def test_a_missing_shutdown_module_is_rejected(self):
        docker=(ROOT/'Dockerfile').read_text().replace(' lifecycle.py ',' ')
        self.assertIn('lifecycle.py',missing_runtime_modules(docker))
    def test_supervisor_grace_exceeds_the_bounded_app_drain(self):
        from lifecycle import SHUTDOWN_TIMEOUT_SECONDS
        from capture import CAPTURE_IO_DEADLINE
        timeout=int(re.search(r'^timeout:\s*(\d+)\s*$',(ROOT/'config.yaml').read_text(),re.M)[1])
        # A camera call and SQLite's existing ten-second lock wait can occur
        # consecutively. This does not claim filesystem writes cannot stall.
        self.assertGreaterEqual(SHUTDOWN_TIMEOUT_SECONDS,CAPTURE_IO_DEADLINE+10+5)
        self.assertGreaterEqual(timeout,SHUTDOWN_TIMEOUT_SECONDS+10)
