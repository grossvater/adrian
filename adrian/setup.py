from distutils.command.build_scripts import build_scripts as _build_py
from setuptools import setup
import os.path

version = '0.6'
scripts = [ 'adrian.py' ]

class build_py(_build_py):
    def preprocess_all(self):
        for s in scripts:
            outFile = os.path.join(self.build_dir, s)
            _build_py.make_file(self, 
                                    [ s ], 
                                    outFile, 
                                    self.preprocess, [ s, outFile ])
    
    def preprocess(self, inFile, outFile):
        self.run_command('egg_info')
        egg_version = str(self.distribution.get_command_obj('egg_info').egg_version)
        with open(inFile, 'r') as i:
            with open(outFile, "w") as o:
                for l in i:
                    if (l.startswith('__version__')):
                        l = l.replace('$version', egg_version)
                    o.write(l)
        
    def run(self):
        print(self.build_dir)
        _build_py.mkpath(self, self.build_dir)
        self.preprocess_all()
        
        _build_py.run(self)
        
def get_version(filename):
    import re

    here = os.path.dirname(os.path.abspath(__file__))
    f = open(os.path.join(here, filename))
    version_file = f.read()
    f.close()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if not version_match:
        raise RuntimeError("Unable to find version string.")
    
    return version_match.group(1)
    
setup(
    cmdclass = {
        'build_scripts': build_py,
    },
    name = "Adrian",
    version = version,
    requires = ['suds'],
    scripts = scripts,
)