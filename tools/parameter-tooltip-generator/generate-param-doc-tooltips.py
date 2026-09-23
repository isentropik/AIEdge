"""Generate configuration tooltips from any working directory, without shell cp."""
from pathlib import Path
import re
import shutil
import markdown

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'param-docs/parameter-pages'
HTML = ROOT / 'sd-card/html'
PREFIX = '<div class="rst-content"><div class="tooltip"><img src="help.png" width="32px"><span class="tooltiptext">'
SUFFIX = '</span></div></div>'


def generate():
    pages = {
        HTML / 'edit_config.html': (HTML / 'edit_config_template.html').read_text(encoding='utf-8'),
        HTML / 'edit_reference.html': (HTML / 'edit_reference.html').read_text(encoding='utf-8'),
    }
    for source in sorted(DOCS.glob('*/*.md')):
        section = source.parent.name
        parameter = source.stem.replace('<', '').replace('>', '')
        rendered = markdown.markdown(source.read_text(encoding='utf-8').replace('# ', '### '), extensions=['admonition'])
        rendered = rendered.replace('a href', 'a target="_blank" rel="noopener" href')
        rendered = rendered.replace('href="../', 'href="https://jomjol.github.io/AI-on-the-edge-device-docs/')
        rendered = rendered.replace('<h3>', '<h3 style="margin: 0">').replace('../img/', '/')
        token = '<td>$TOOLTIP_' + section + '_' + parameter + '</td>'
        for path in pages:
            pages[path] = pages[path].replace(token, '<td>' + PREFIX + rendered + SUFFIX + '</td>')
    for path, text in pages.items():
        visible = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        unresolved = re.findall(r'\$TOOLTIP_[A-Za-z0-9_.]+', visible)
        if unresolved:
            raise ValueError(f'{path.name}: unresolved tooltip references: {unresolved}')
    for path, text in pages.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    for source in sorted((DOCS / 'img').glob('*')):
        if source.is_file():
            shutil.copyfile(source, HTML / source.name)
    print('Generated configuration and reference tooltips')


if __name__ == '__main__':
    generate()
