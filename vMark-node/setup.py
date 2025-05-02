from setuptools import setup, find_packages
import os

# Ensure we can read requirements.txt
if os.path.exists('requirements.txt'):
    with open('requirements.txt') as f:
        requirements = [line.strip() for line in f.readlines() if line.strip()]
else:
    requirements = ['prompt_toolkit>=3.0.0', 'pyyaml>=6.0']

setup(
    name="vmark-node",
    version="0.3.5",
    packages=find_packages(include=["cli", "cli.*", "plugins", "plugins.*"]),
    py_modules=["main"],
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'vmark-node=main:start_cli',
        ],
    },
    include_package_data=True,  # Include non-Python files
    package_data={
        "plugins": ["*"],  # Include all files in the plugins directory
    },
    author="Pathgate",
    description="An Ethernet software-based open source demarcation NID",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/xmas-ar/vMark-node",
    license="GPL-3.0-only",  # Use SPDX identifier instead of classifier
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
