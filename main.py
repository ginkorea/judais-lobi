# main.py

import sys

from core.cli import main_judais, main_lobi, main_tai

#: The agents this entry point can start, and one line each for `--help`.
#:
#: `tai` is here because a personality you can only reach by asking for a
#: different agent does not have a name. Tai shipped as a TOML file in the
#: deployment that operates it (TAIPAN, where this was learned) plus
#: `--personality` in `core.cli`, which made it *loadable* — but the only
#: way to run it was `python main.py lobi --personality .../tai.toml`, so the
#: mission agent had to impersonate Lobi to start, its debug banner said Lobi,
#: and nobody reading this file would learn Tai existed. `main_tai` finds the
#: file itself; see `core.cli.tai_personality_path`.
AGENTS = {
    "lobi": (main_lobi, "the mischievous one — a general assistant"),
    "judais": (main_judais, "the sharp one — a general assistant"),
    "tai": (main_tai, "the mission-agent personality — governed tools over "
                      "MCP, cites every claim, never sees source "
                      "(TAIPAN's deployment of judais-lobi uses this name)"),
}


def _usage(stream=sys.stdout):
    print("Usage: python main.py [lobi|judais|tai] <message> [flags]\n",
          file=stream)
    print("Agents:", file=stream)
    for name, (_, blurb) in AGENTS.items():
        print(f"  {name:8} {blurb}", file=stream)
    print("\nFlags belong to the agent, not to this dispatcher, so ask it:",
          file=stream)
    print("  python main.py tai --help", file=stream)
    print("\nExample:", file=stream)
    # A placeholder URL and an env var, not a real one of either. An
    # example is copied before it is read, so a live internal hostname in
    # `--help` is a hostname published to everyone who ever runs `--help`,
    # and a token named in argv is a token visible in `ps`.
    print("  python main.py tai 'What governed corpora exist?' \\\n"
          "      --mission --mcp-url http://<mcp-host>:<port>/mcp \\\n"
          "      --mcp-token \"$MCP_TOKEN\"", file=stream)


def main():
    argv = sys.argv[1:]

    # `--help` before a command is a question about THIS file, and it used to
    # be answered with `Unknown command: --help` and exit 1. An entry point
    # that treats the universal request for help as an error teaches every
    # caller — human or agent — that it cannot be asked anything.
    if not argv or argv[0] in ("-h", "--help", "help"):
        _usage()
        sys.exit(0)

    command = argv[0]
    if command not in AGENTS:
        print(f"Unknown agent: {command!r}\n", file=sys.stderr)
        _usage(sys.stderr)
        sys.exit(2)  # 2 is "you used me wrong", which is what argparse says

    sys.argv = [sys.argv[0]] + argv[1:]  # strip the agent name
    AGENTS[command][0]()


if __name__ == "__main__":
    main()
