from setuptools import setup, find_packages
import os

# Load dependencies
if os.path.exists('requirements.txt'):
    with open('requirements.txt') as f:
        requirements = [line.strip() for line in f if line.strip()]
else:
    # Fallbacks for basic operation
    requirements = [
        "prompt_toolkit>=3.0.0,<4.0.0",
        "pyroute2>=0.6.9,<0.7.0",
        "ethtool==0.15"
    ]

setup(
    name="vmark-node",
    version="0.3.7",
    packages=find_packages(include=["cli", "cli.*", "plugins", "plugins.*"]),
    py_modules=["main"],
    install_requires=requirements,
    python_requires=">=3.9",
    entry_points={
        'console_scripts': [
            'vmark-node=main:start_cli',
        ],
    },
    include_package_data=True,
    package_data={
        "plugins": ["*"],
    },
    author="Pathgate",
    description="An Ethernet software-based open source demarcation NID",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/xmas-ar/vMark-node",
    license="GPL-3.0-only",
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
)
