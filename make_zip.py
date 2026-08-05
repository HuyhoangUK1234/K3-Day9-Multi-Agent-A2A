"""Build the submission archive.

README section 8 wants the zip to hold exactly the 50 rulings and nothing else,
so `output/.gitkeep` must not be swept in. Entry names are written with forward
slashes: Windows zip tooling emits backslashes, which a grader unpacking on
Linux sees as a single file literally named "output\\EC_001.json" rather than a
directory.

    python make_zip.py                       # from output/ -> output.zip
    python make_zip.py --src output_evidence --dest output_evidence.zip
"""

import argparse
import json
import pathlib
import sys
import zipfile

EXPECTED = ["EC_{:03}.json".format(i) for i in range(1, 51)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=pathlib.Path, default=pathlib.Path("output"))
    parser.add_argument("--dest", type=pathlib.Path, default=pathlib.Path("output.zip"))
    args = parser.parse_args()

    missing = [name for name in EXPECTED if not (args.src / name).exists()]
    if missing:
        print("missing rulings: {}".format(missing), file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in EXPECTED:
            path = args.src / name
            json.loads(path.read_text(encoding="utf-8"))  # refuse to ship an unparseable file
            archive.write(path, arcname="output/{}".format(name))

    with zipfile.ZipFile(args.dest) as archive:
        names = archive.namelist()
        corrupt = archive.testzip()
        problems = []
        if names != ["output/{}".format(n) for n in EXPECTED]:
            problems.append("entry list does not match EC_001..EC_050")
        if any(chr(92) in name for name in names):
            problems.append("an entry name contains a backslash")
        if corrupt:
            problems.append("corrupt entry: {}".format(corrupt))
        for name in names:
            json.loads(archive.read(name).decode("utf-8"))

    if problems:
        for problem in problems:
            print("FAIL: {}".format(problem), file=sys.stderr)
        return 1

    print("{} -> {}".format(args.src, args.dest))
    print("  entries   : {}".format(len(names)))
    print("  first/last: {} / {}".format(names[0], names[-1]))
    print("  size      : {} KB".format(round(args.dest.stat().st_size / 1024, 1)))
    print("  all parse : True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
