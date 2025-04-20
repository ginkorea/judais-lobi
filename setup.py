from setuptools import setup, find_packages

setup(
    name="lobi-cli",
    version="0.1.3",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "rich",
        "python-dotenv",
        "beautifulsoup4",   # new for --search tool
        "requests"          # also required for web fetching
    ],
    entry_points={
        "console_scripts": [
            "lobi = lobi.cli:main",
        ],
    },
    author="Josh Gompert",
    description="Lobi: a terminal-based AI assistant with personality and tools",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ginkorea/lobi",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
