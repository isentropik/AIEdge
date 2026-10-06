"""Source-level runtime COPY admission; does not substitute for a Docker build."""
import ast, pathlib, re, shlex, unittest
ROOT=pathlib.Path(__file__).resolve().parent

def missing_browser_assets(dockerfile,html=None):
    """Discover page asset dependencies, independent of a hand-maintained list."""
    from html.parser import HTMLParser
    from urllib.parse import urlsplit
    copied=set();final=dockerfile.split('\nFROM ')[-1].replace('\\\n',' ')
    for line in final.splitlines():
        tokens=shlex.split(line)
        if tokens and tokens[0]=='COPY' and not tokens[1].startswith('--from='):copied.update(tokens[1:-1])
    class Assets(HTMLParser):
        def __init__(self):super().__init__();self.names=set()
        def handle_starttag(self,tag,attributes):
            attributes=dict(attributes)
            value=attributes.get('src') if tag=='script' else attributes.get('href') if tag=='link' else None
            if value:
                url=urlsplit(value)
                if not url.scheme and not url.netloc and pathlib.PurePosixPath(url.path).suffix in ('.js','.css'):self.names.add(url.path.removeprefix('./'))
    parser=Assets();parser.feed((ROOT/'index.html').read_text() if html is None else html)
    return sorted(parser.names-copied)

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
    def test_a_missing_ambiguity_module_is_rejected(self):
        docker=(ROOT/'Dockerfile').read_text().replace(' reading_bounds.py ',' ')
        self.assertIn('reading_bounds.py',missing_runtime_modules(docker))
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
        from camera_auto import PROBE_SECONDS
        self.assertGreaterEqual(SHUTDOWN_TIMEOUT_SECONDS,PROBE_SECONDS+10)
        self.assertGreaterEqual(timeout,SHUTDOWN_TIMEOUT_SECONDS+10)
    def test_every_index_css_and_js_dependency_is_packaged(self):
        self.assertEqual(missing_browser_assets((ROOT/'Dockerfile').read_text()),[])
    def test_missing_event_helpers_rejected_by_transitive_import_gate(self):
        docker=(ROOT/'Dockerfile').read_text()
        for name in ('event_mode.py','ha_event_selection.py'):
            with self.subTest(name=name):self.assertIn(name,missing_runtime_modules(docker.replace(name+' ','')))
    def test_missing_event_ui_and_existing_dashboard_are_rejected(self):
        docker=(ROOT/'Dockerfile').read_text()
        for name in ('event-selection-ui.js','dashboard.js','parity.css'):
            with self.subTest(name=name):self.assertIn(name,missing_browser_assets(docker.replace(name+' ','')))
    def test_dependency_discovery_handles_new_assets_and_query_strings(self):
        docker=(ROOT/'Dockerfile').read_text()
        html='<script src="future-screen.js?v=2"></script><link rel="stylesheet" href="future.css#theme"><script src="https://example.invalid/external.js"></script>'
        self.assertEqual(missing_browser_assets(docker,html),['future-screen.js','future.css'])
