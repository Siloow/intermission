"""Release Intermission: one version number, one tag, one section in the changelog.

    python3 release.py              which version this is, and what changed since
    python3 release.py 0.2.0        release it: VERSION, CHANGELOG.md, a commit, the tag v0.2.0, a push
    python3 release.py 0.2.0 -y     the same without asking before the push

The version is VERSION (major.minor.patch). CHANGELOG.md gets a section per
release: one you wrote yourself (## 0.2.0 …) is kept as it is; otherwise the
commit subjects since the last release go in, and you can edit them into
sentences before pushing — the push is the last step and asks first. The other
Mac picks a release up with Update.command.

Standard library only.
"""
import datetime, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = os.path.join(HERE, "VERSION")
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"[release] git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def current():
    try:
        return open(VERSION).read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def last_tag():
    return git("describe", "--tags", "--abbrev=0", check=False) or None


def since(tag):
    """Commit subjects since the last release (all of them before the first)."""
    out = git("log", f"{tag}..HEAD" if tag else "HEAD", "--format=%s", "--no-merges", check=False)
    return [s for s in out.splitlines() if s.strip()]


def parts(v):
    m = SEMVER.match(v)
    return tuple(int(x) for x in m.groups()) if m else None


def main(argv):
    yes = "-y" in argv
    argv = [a for a in argv if a != "-y"]
    cur, tag = current(), last_tag()
    if not argv:
        print(f"Intermission {cur}" + (f"  (tag {tag})" if tag else "  (no tag yet)"))
        items = since(tag)
        print(f"\n{len(items)} commit(s) since then:" if items else "\nnothing since then")
        for s in items:
            print(f"  - {s}")
        return 0

    new = argv[0].lstrip("v")
    if not parts(new):
        sys.exit(f"[release] {new!r} is not major.minor.patch")
    if parts(new) <= parts(cur):
        sys.exit(f"[release] {new} is not after {cur}")
    if git("status", "--porcelain", "--", ".", ":!VERSION", ":!CHANGELOG.md"):   # its own two files may wait
        sys.exit("[release] the working tree isn't clean: commit or stash first, so the release is what's committed")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit(f"[release] on {branch}; releases are cut from main")

    today = datetime.date.today().isoformat()
    try:
        log = open(CHANGELOG).read()
    except OSError:
        log = "# Changelog\n\nWhat changed in Intermission, newest first.\n\n"
    if not re.search(rf"^## {re.escape(new)}\b", log, re.M):
        items = since(tag) or ["(no commits since the last release)"]
        section = f"## {new} — {today}\n\n" + "".join(f"- {s}\n" for s in items) + "\n"
        m = re.search(r"^## ", log, re.M)
        log = (log[:m.start()] + section + log[m.start():]) if m else log.rstrip() + "\n\n" + section
        open(CHANGELOG, "w").write(log)
        print(f"[release] CHANGELOG.md: {len(items)} line(s) under {new}, from the commits since "
              f"{tag or 'the beginning'} — edit them into sentences if you like")
    else:
        print(f"[release] CHANGELOG.md already has a section for {new}: kept")
    open(VERSION, "w").write(new + "\n")

    git("add", "VERSION", "CHANGELOG.md")
    git("commit", "-q", "-m", f"Intermission {new}")
    git("tag", "-a", f"v{new}", "-m", f"Intermission {new}")
    print(f"[release] Intermission {new}: committed and tagged v{new}")
    if not yes:
        try:
            yes = input("push it now? [Y/n] ").strip().lower() in ("", "y", "yes")
        except EOFError:
            yes = False
    if yes:
        git("push")
        git("push", "--tags")
        print("[release] pushed — Update.command on the other Mac brings it in")
    else:
        print("[release] not pushed. When ready:  git push && git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
