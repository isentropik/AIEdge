"""Keep local workstation paths out of firmware __FILE__ diagnostics."""
from pathlib import Path
Import("env")

# Set flags before ESP-IDF clones component environments. Its CMake import
# drops @response options and splits direct options containing spaces.
source = Path(env.subst("$PROJECT_DIR")).resolve().as_posix()
build = Path(env.subst("$BUILD_DIR"))
build.mkdir(parents=True, exist_ok=True)
response = build / "aiedge-source-map.rsp"
response.write_text('"-ffile-prefix-map=' + source + '=."\n', encoding="utf-8")
env.Append(CCFLAGS=["@" + response.as_posix()])
