import setuptools
import subprocess
from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setuptools.setup(
    name='ccpbsa',
    version='0.1',
    description="A structure based method quantitive estimation of mutational \
    free energy",
    long_description=long_description,
    long_description_content_type='text/markdown',
    packages=setuptools.find_packages(),
    author='Tom Unterleiter',
    author_email='tom_unterleiter@gmail.com',
    scripts=['ccpbsa/ccpbsa', 'ccpbsa/ccpbsa-setup'],
    include_package_data=True,
    install_requires=["numpy","pymol", "pandas", "tqdm"],
    zip_safe = False
)

subprocess.call(['~/data/tom/CCPBSA/CC-PBSA/ccpbsa-setup'], shell=True)
