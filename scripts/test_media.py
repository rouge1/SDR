#!/usr/bin/env python3
"""Check how the pickers find media: subfolders, capitals, hidden files.

Builds a throwaway media folder with every case that matters and checks
what ``apps/media.py`` - and the video and still-frame lists built on it in
``apps/ntsc_source.py`` - make of it. No radio, no display, and nothing in
the real media folder is touched. Runs on Windows as well as Linux.

    python scripts/test_media.py
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apps.media import WAV, choices, media_files, picker_name  # noqa: E402

FAILURES = []


def check(condition, message):
    print(('  ok   ' if condition else '  FAIL ') + message)
    if not condition:
        FAILURES.append(message)


def touch(root, relative):
    path = os.path.join(root, *relative.split('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').close()


def main():
    root = tempfile.mkdtemp(prefix='media-test-')
    try:
        for name in ('Zebra-Song.wav', 'apple.WAV', 'Mixed.Wav', 'notes.txt',
                     'Music/Artist/Album/Track-One.wav', 'Music/Top.wav',
                     'Effects/boom.WAV',
                     '._Zebra-Song.wav', '.cache/hidden.wav',
                     'Prelinger/clip.mp4', 'Prelinger/clip.ts',
                     'NASA/clip.mp4', 'Moonwalk.mp4', 'Moonwalk.TS',
                     'Stills/Test-Card-946x486-18M0FS.DAT'):
            touch(root, name)

        print('capitals')
        names = [rel for rel, _ in media_files(root, WAV)]
        check('apple.WAV' in names and 'Mixed.Wav' in names,
              '.WAV and .Wav are found as well as .wav')
        check('notes.txt' not in names, 'other extensions are not')

        print('\nsubfolders')
        check('Music/Artist/Album/Track-One.wav' in names,
              'found three folders down')
        check('Effects/boom.WAV' in names, 'found in a sibling folder, capitals and all')
        labels = dict(choices(root, WAV))
        check('Music/Artist/Album/Track One' in labels,
              "labelled with its folder: 'Music/Artist/Album/Track One'")
        check('Zebra Song' in labels,
              "a top-level file keeps the label it always had: 'Zebra Song'")

        print('\nordering')
        top = [n for n in names if '/' not in n]
        check(names[:len(top)] == top, 'top-level files come before any subfolder')
        check(top == sorted(top, key=str.lower),
              'alphabetical ignoring case: ' + ', '.join(top))
        deep = [n for n in names if '/' in n]
        check(deep == sorted(deep, key=str.lower),
              'subfolders grouped: ' + ', '.join(deep))

        print('\nwhat is skipped')
        check(not any(n.startswith('._') for n in names),
              "macOS's ._ files are not offered")
        check(not any(n.startswith('.cache') for n in names),
              'hidden folders are not searched')

        print('\npaths')
        for rel, full in media_files(root, WAV):
            if not os.path.isfile(full):
                check(False, f'{rel} resolves to a real file')
                break
        else:
            check(True, 'every full path is a real file')
        check(all('\\' not in rel for rel, _ in media_files(root, WAV)),
              'labels use / on every platform')

        print('\nthe video list')
        from apps.ntsc_source import dat_files, video_files
        from apps.atsc_source import ATSC_EXTENSIONS
        clips = video_files(root)
        by_label = {label: os.path.basename(full) for label, full in clips}
        check('Prelinger/clip' in by_label and by_label['Prelinger/clip'] == 'clip.mp4',
              'a folder holding clip.mp4 and clip.ts offers it once, as the .mp4')
        check('NASA/clip' in by_label,
              'a clip of the same name in another folder is offered too')
        check(by_label.get('Moonwalk') == 'Moonwalk.mp4',
              'at the top level .mp4 still beats .TS, capitals and all')
        ts_first = dict(video_files(root, ATSC_EXTENSIONS))
        check(os.path.basename(ts_first.get('Moonwalk', '')) == 'Moonwalk.TS',
              'asked for the .ts first, as the ATSC transmitter does, it gets it')
        stills = dict(dat_files(root))
        check('Stills/Test Card' in stills,
              "a .DAT still is found and tidied: 'Stills/Test Card'")

        print('\na link back up the tree')
        try:
            os.symlink(root, os.path.join(root, 'Music', 'loop'),
                       target_is_directory=True)
        except (OSError, NotImplementedError):
            print('  skip no permission to make a symbolic link here')
        else:
            again = media_files(root, WAV)
            check(len(again) == len(names) and not any('/loop/' in r for r, _ in again),
                  'is not followed, so the walk ends and nothing is listed twice')

        print('\nnothing to scan')
        check(media_files('', WAV) == [] and media_files(
            os.path.join(root, 'absent'), WAV) == [],
            'an empty or missing folder gives an empty list, not an error')
        check(picker_name('Top-Level.wav') == 'Top Level',
              'picker_name keeps a top-level name as it was')
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{len(FAILURES)} failed" if FAILURES else '\nall checks passed')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
