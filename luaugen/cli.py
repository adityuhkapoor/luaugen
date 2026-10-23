import argparse
import sys

from . import __version__
from .accept import run
from .build import BuildError, build, check


def main(argv=None):
    parser = argparse.ArgumentParser(prog="luaugen", description="Compile JSON data to deterministic Luau modules and verify them.")
    parser.add_argument("--version", action="version", version="luaugen " + __version__)
    sub = parser.add_subparsers(dest="command")
    p_build = sub.add_parser("build", help="generate every target in the manifest")
    p_build.add_argument("manifest", nargs="?", default="luaugen.json")
    p_check = sub.add_parser("check", help="fail if any generated file is missing or stale")
    p_check.add_argument("manifest", nargs="?", default="luaugen.json")
    p_accept = sub.add_parser("accept", help="run reference cases through generated data + evaluator")
    p_accept.add_argument("fixtures", nargs="+")
    p_accept.add_argument("--luau", default="luau", help="path to the luau CLI")
    p_accept.add_argument("--manifest", help="run `check` first so stale data cannot pass")
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            for path in build(args.manifest):
                print("wrote", path)
            return 0
        if args.command == "check":
            stale = check(args.manifest)
            for path in stale:
                print("stale:", path)
            return 1 if stale else 0
        if args.command == "accept":
            if args.manifest:
                stale = check(args.manifest)
                if stale:
                    for path in stale:
                        print("stale:", path)
                    return 1
            failed = False
            for fixture in args.fixtures:
                result = run(fixture, luau=args.luau)
                print("%s: %s" % (fixture, result.summary()))
                for name, msg in result.failed[:20] + result.errors[:20]:
                    print("  %s: %s" % (name, msg))
                for name in result.missing[:20]:
                    print("  missing: %s" % name)
                failed = failed or not result.ok
            return 1 if failed else 0
    except BuildError as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
