# main.py

import sys
from core.cli import main_lobi, main_judais

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [lobi|judais] <message and flags>")
        sys.exit(1)

    command = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Strip the 'lobi' or 'judais' flag

    if command == "lobi":
        main_lobi()
    elif command == "judais":
        main_judais()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
