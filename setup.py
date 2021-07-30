# Author: Panchumarti Jaswant EXT
# Description: Install iplotlib on any system with pip.
# Changelog:
#   19/07/2021: Add boilerplate
# Note For changes to this file, please add the author to the list of PR reviewers

import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="iplotlib",
    setup_requires=[
        "setuptools-git-versioning"
    ],
    version_config={
        "starting_version": "0.0.0",
        "template": "{tag}",
        "dirty_template": "{tag}.{ccount}.{sha}",
    },
    author="Lana Abadie",
    author_email="lana.abadie@iter.org",
    description="ITER plotting library",
    long_description=long_description,
    url="https://git.iter.org/scm/vis/iplotlib.git",
    project_urls={
        "Bug Tracker": "https://jira.iter.org/issues/?jql=project+%3D+IDV+AND+component+%3D+iplotlib",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        # "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    package_dir={"": "."},
    packages=setuptools.find_packages(where="."),
    python_requires=">=3.8",
    install_requires=[
        "iplotProcessing >= 0.6.0",
        "matplotlib >= 3.3.3",
        "pandas >= 1.2.0",
        "qtpy >= 1.9.0"
    ],
    package_data = {
        "iplotlib.qt": ["icons/*.png"]
    }
)
