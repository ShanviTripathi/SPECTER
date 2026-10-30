r"""
SPECTER - backup script. Zips your project folders into one timestamped archive, adds a
SHA-256 manifest, and verifies the archive. Point --dest at a USB stick or at your
Google Drive / OneDrive sync folder (the sync client uploads it for you).

Examples:
  python C:\specter\backup_specter.py --dest E:\backups
  python C:\specter\backup_specter.py --src C:\specter C:\esp\esp-csi-master --dest "G:\My Drive\SPECTER"
  python C:\specter\backup_specter.py --dest E:\backups --no-data      (code only, no recordings)

By default it backs up the folder this script lives in. Build output (build/, __pycache__)
is skipped because it can be regenerated (also venv/, which is large and not portable); recordings in data/ are included.
"""
import argparse
import hashlib
import os
import sys
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"build", "__pycache__", ".pytest_cache", ".git", ".idea", ".vscode", "venv", ".venv"}
SKIP_SUFFIXES = (".pyc", ".pyo")

ap = argparse.ArgumentParser()
ap.add_argument("--src", nargs="+", default=[HERE], help="folders to back up (default: this script's folder)")
ap.add_argument("--dest", required=True, help="folder to put the zip in (USB / Drive sync folder)")
ap.add_argument("--name", default="specter_backup", help="archive name prefix")
ap.add_argument("--no-data", action="store_true", help="skip folders named 'data' (the CSV recordings)")
ap.add_argument("--keep-build", action="store_true", help="do not skip build/ folders")
args = ap.parse_args()

skip_dirs = set(SKIP_DIRS)
if args.keep_build:
    skip_dirs.discard("build")
if args.no_data:
    skip_dirs.add("data")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


files = []   # (full path, arcname)
for src in args.src:
    src = os.path.abspath(src)
    if not os.path.isdir(src):
        print(f"WARNING: not a folder, skipped: {src}")
        continue
    top = os.path.basename(src.rstrip("\\/")) or "root"
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if fn.endswith(SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, fn)
            files.append((full, os.path.join(top, os.path.relpath(full, src))))

if not files:
    sys.exit("Nothing to back up (check --src).")

try:
    os.makedirs(args.dest, exist_ok=True)
except OSError as e:
    sys.exit(f"Cannot use destination '{args.dest}': {e}\n"
             "Is the USB stick plugged in / is the drive letter right? Check with: Get-PSDrive -PSProvider FileSystem")
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
zip_path = os.path.join(args.dest, f"{args.name}_{stamp}.zip")
print(f"Backing up {len(files)} file(s) from {len(args.src)} folder(s) -> {zip_path}")

manifest = []
try:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (full, arc) in enumerate(files, 1):
            zf.write(full, arc)
            manifest.append(f"{sha256(full)}  {arc.replace(os.sep, '/')}")
            if i % 50 == 0 or i == len(files):
                print(f"  {i}/{len(files)}", end="\r", flush=True)
        zf.writestr("MANIFEST.sha256", "\n".join(manifest) + "\n")
except OSError as e:
    sys.exit(f"\nBackup failed ({e}). Is the destination full or unplugged? Partial file: {zip_path}")

print("\nVerifying...")
with zipfile.ZipFile(zip_path) as zf:
    bad = zf.testzip()
    n_in_zip = len([n for n in zf.namelist() if n != "MANIFEST.sha256"])
if bad or n_in_zip != len(files):
    sys.exit(f"VERIFY FAILED (bad member: {bad}, files in zip {n_in_zip} vs {len(files)}). Run it again.")

size_mb = os.path.getsize(zip_path) / 1e6
print(f"OK: {n_in_zip} files, {size_mb:.1f} MB, archive passes integrity test.")
print(f"Archive: {zip_path}")
print("Tip: keep a second copy elsewhere (USB AND Drive), not just one.")
