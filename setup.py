# Author: Panchumarti Jaswant EXT
# Description: Install iplotlib on any system with pip.
# Changelog:
#   19/07/2021: Add boilerplate
# Note For changes to this file, please add the author to the list of PR reviewers

import setuptools
import os
import sys

sys.path.append(os.getcwd())
import versioneer

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
)
