import os
import yacbi

DEFAULT_FLAGS = [
    '-x',
    'cpp',
    '-std=c++11',
]

THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def FlagsForFile(filename, **kwargs):
    flags = yacbi.query_compile_args(THIS_DIR, filename)
    if flags is None:
        flags = DEFAULT_FLAGS
    return {
        'flags': flags,
        'do_cache': True
    }
