"""Install the bundled Skill in a selected client's user skill directory."""
import argparse
from pathlib import Path
from importlib.resources import files

ROOTS = {"claude": ".claude", "codex": ".codex", "deepseek": ".dsh"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", choices=ROOTS)
    args = parser.parse_args()
    target = Path.home() / ROOTS[args.client] / "skills/shared-context/SKILL.md"
    content = files("agent_context_kit").joinpath("SKILL.md").read_bytes()
    if target.exists() and target.read_bytes() == content:
        print(target)
        return
    if target.parent.is_symlink() or target.is_symlink():
        parser.exit(1, f"Existing linked skill at {target}; inspect it before installing.\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(content)
    print(target)
