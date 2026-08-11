"""Poetry build hook: compiles the Cython extensions in-place.

Referenced by `[tool.poetry.build] script = "build.py"` in pyproject.toml. Poetry calls
`build(setup_kwargs)` during `poetry install`/`poetry build`, passing it the setuptools kwargs
it's about to build with; adding `ext_modules` here is the documented way to ship compiled
extensions from a Poetry-managed project. See:
https://python-poetry.org/docs/main/building-extension-modules/
"""
import os
import subprocess

import numpy as np
from Cython.Build import cythonize
from setuptools.command.build_ext import build_ext

is_posix = (os.name == "posix")


# Avoid a gcc warning below:
# cc1plus: warning: command line option ???-Wstrict-prototypes??? is valid
# for C/ObjC but not for C++
class BuildExt(build_ext):
    def build_extensions(self):
        if os.name != "nt" and "-Wstrict-prototypes" in self.compiler.compiler_so:
            self.compiler.compiler_so.remove("-Wstrict-prototypes")
        super().build_extensions()


def build(setup_kwargs):
    cpu_count = os.cpu_count() or 8

    extra_compile_args = []
    extra_link_args = []
    if is_posix:
        os_name = subprocess.check_output("uname").decode("utf8")
        if "Darwin" in os_name:
            extra_compile_args.extend(["-stdlib=libc++", "-std=c++11"])
            extra_link_args.extend(["-stdlib=libc++", "-std=c++11"])
        else:
            extra_compile_args.append("-std=c++11")
            extra_link_args.append("-std=c++11")
    if os.environ.get("WITHOUT_CYTHON_OPTIMIZATIONS"):
        extra_compile_args.append("-O0")

    cython_kwargs = {"language": "c++", "language_level": 3}
    if is_posix:
        cython_kwargs["nthreads"] = cpu_count

    compiler_directives = {"annotation_typing": False}
    if os.environ.get("WITHOUT_CYTHON_OPTIMIZATIONS"):
        compiler_directives.update({
            "optimize.use_switch": False,
            "optimize.unpack_method_calls": False,
        })

    extensions = cythonize(
        ["kairos/**/*.pyx"],
        compiler_directives=compiler_directives,
        **cython_kwargs,
    )
    for ext in extensions:
        ext.extra_compile_args = extra_compile_args
        ext.extra_link_args = extra_link_args

    setup_kwargs.update({
        "ext_modules": extensions,
        "include_dirs": [np.get_include()],
        "cmdclass": {"build_ext": BuildExt},
    })


if __name__ == "__main__":
    # Poetry invokes this script as a bare subprocess (`python build.py`, no args) during
    # `poetry install`/`poetry build`. `hbot update` invokes it directly with explicit setuptools
    # args (`python build.py build_ext --inplace -j 8`) to rebuild just the extensions after a
    # git pull, without a full `poetry install`. Only inject the default verb when none was
    # given, so the two callers don't collide.
    #
    # The repo root is a flat layout with several top-level directories (conf/, logs/,
    # controllers/, kairos/...), so setuptools' auto package-discovery must be short-circuited
    # with an explicit `packages` list — otherwise it refuses to guess and fails.
    import sys

    from setuptools import setup
    kwargs = {"packages": ["kairos"], "include_package_data": True}
    build(kwargs)
    if len(sys.argv) == 1:
        sys.argv = [sys.argv[0], "build_ext", "--inplace"]
    setup(**kwargs)
