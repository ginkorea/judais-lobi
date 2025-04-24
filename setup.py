from setuptools import setup, find_packages

setup(
    name="lobi-cli",
    version="0.2.2",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "rich",
        "python-dotenv",
        "beautifulsoup4",
        "requests",
        "faiss-cpu",          # Added for vector search in LongTermMemory
        "numpy"               # Required for FAISS vector operations
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
