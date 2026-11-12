"""Create a Windows release ZIP with portable, non-personal file metadata."""
from pathlib import Path
import shutil
import zipfile


def package(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.is_relative_to(source):
        raise ValueError('Place release ZIP outside the application directory')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Windows release must not contain symbolic links')
            if not path.is_file():
                continue
            # Git/source snapshots can use epoch 0; ZIP starts at 1980.
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open('rb') as input_file, archive.open(info, 'w', force_zip64=True) as output:
                shutil.copyfileobj(input_file, output)
    return destination


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(package(args.source, args.destination))
