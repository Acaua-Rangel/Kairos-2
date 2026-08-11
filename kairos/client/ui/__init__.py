import sys
from os.path import dirname, join, realpath

from kairos import root_path

sys.path.insert(0, str(root_path()))


with open(realpath(join(dirname(__file__), '../../VERSION'))) as version_file:
    version = version_file.read().strip()
