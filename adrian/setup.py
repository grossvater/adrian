from setuptools import setup, find_packages


def get_version(filename):
    import os
    import re

    here = os.path.dirname(os.path.abspath(__file__))
    f = open(os.path.join(here, filename))
    version_file = f.read()
    f.close()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")

setup(
    name = "Adrian",
    version = get_version('adrian.py'),
    install_requires = ['suds'],
    scripts = ['adrian.py'],
)

