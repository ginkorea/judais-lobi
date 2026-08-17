from setuptools import setup, find_packages

VERSION = "0.14.1"

setup(
    name="judais-lobi",
    version=VERSION,
    # tests/ is importable (it has an __init__.py) so a bare find_packages()
    # would ship a top-level `tests` module into every site-packages. 0.8.0's
    # wheel was caught doing exactly that at release time.
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    install_requires=[
        "openai>=1.0.0",
        "rich>=14.0.0",
        "python-dotenv>=1.1.0",
        "beautifulsoup4>=4.13.4",
        "requests>=2.32.3",
        "numpy>=1.26.4",
        "httpx>=0.28.1",
        "httpcore>=1.0.9",
        "h11>=0.16.0",
        "sniffio>=1.3.1",
        "pydantic>=2.11.0",
        "annotated-types>=0.7.0",
        "certifi>=2025.8.3",
        # `tomllib` is 3.11+. `python_requires` is 3.10, and
        # core/contracts/schemas.py reads a TOML personality by importing
        # `tomllib`, falling back to `tomli`, and raising ValueError when
        # neither is there. That is core, not an extra: the reference
        # deployment points ELF_PERSONALITY at a `tai.toml`, so on a clean
        # 3.10 install every turn dies before `mission_started` — the
        # silence the exit contract says a consumer must report as a
        # failure, caused by a wheel nobody declared.
        'tomli>=1.2; python_version < "3.11"',
    ],
    extras_require={
        "dev": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
        # The vector index, which core/memory/memory.py treats as
        # optional and always did: `_make_index` imports faiss inside a
        # try, falls back to the numpy inner-product index next to it,
        # and `JUDAIS_LOBI_FAISS_BACKEND=numpy` asks for the fallback
        # outright. A compiled wheel every install paid for and no code
        # path required. Install it when the long-term memory is large
        # enough for the difference to matter.
        "faiss": ["faiss-cpu>=1.11.0"],
        # An extra, not a hard dependency: the SDK pulls ~20 wheels including
        # compiled ones, and `judais --help` has to keep working without them.
        # core/tools/mcp_client.py is the only importer, and imports it lazily.
        "mcp": ["mcp>=1.25,<2"],
        # The Anthropic SDK, for `--provider anthropic` and for the
        # external critic's Anthropic tier — one client per provider, and
        # one extra that installs it. Soft-imported at both call sites so
        # `judais --help` works without it. The version floor is repeated
        # in `critic` below rather than referenced, because
        # `tests/test_packaging.py` reads `extras_require` with
        # `ast.literal_eval` and a shared name would not survive that.
        "anthropic": ["anthropic>=0.40"],
        # What a mission actually needs, as one name. `mcp` alone installs
        # half of it: `--skill` reads YAML frontmatter, and with no pyyaml
        # `load_skill` raises `SkillManifestError`, which `_load_skill`
        # turns into `SystemExit`. So the failure is loud and nothing runs
        # ungoverned — the extra exists to spare an operator discovering
        # that at the door and installing the second half by hand.
        #
        # `jsonschema` is the third: core/runtime/schema_check.py validates
        # a call's arguments against the tool's own schema before
        # dispatching it, and soft-imports this. Without it the check falls
        # back to `required`/`type`/`enum` at the top level and says nothing
        # about anything nested — a real floor rather than a crash, which is
        # why it is an extra and not a hard dependency, and why it is IN the
        # extra a platform installs rather than left to be discovered.
        "mission": ["mcp>=1.25,<2", "pyyaml>=6.0", "jsonschema>=4"],
        "critic": [
            "anthropic>=0.40",
            "google-generativeai>=0.7.0",
            "keyring>=25.0.0",
            "pyyaml>=6.0",
        ],
        "treesitter": [
            "tree-sitter>=0.23.0",
            "tree-sitter-c>=0.21.0",
            "tree-sitter-cpp>=0.22.0",
            "tree-sitter-rust>=0.23.0",
            "tree-sitter-go>=0.23.0",
            "tree-sitter-javascript>=0.23.0",
            "tree-sitter-typescript>=0.23.0",
            "tree-sitter-java>=0.23.0",
        ],
        "voice": [
            "simpleaudio>=1.0.4",
            "TTS>=0.22.0",
            "torch>=2.7.0",
            "torchaudio>=2.7.0",
            "soundfile>=0.13.1",
            "audioread>=3.0.1",
            "soxr>=0.5.0.post1",
            "transformers>=4.51.3",
            "huggingface-hub>=0.31.1",
            "tokenizers>=0.21.1",
            "safetensors>=0.5.3",
            "trainer>=0.0.36",
        ]
    },
    entry_points={
        "console_scripts": [
            "lobi = core.cli:main_lobi",
            "judais = core.cli:main_judais",
            # Same shape as the other two: no arguments, reads `sys.argv`
            # itself. A personality reachable only by asking for another
            # agent does not have a name.
            "tai = core.cli:main_tai",
        ],
    },
    author="Josh Gompert",
    # `Summary:` in the built metadata. The version belongs to VERSION
    # above; retyped here it agreed for exactly as long as whoever
    # bumped one remembered the other.
    description=f"JudAIs & Lobi v{VERSION} — Terminal agents and a governed mission runtime over OpenAI, Anthropic, Mistral and local backends, with memory and tools",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ginkorea/judais-lobi",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
)
