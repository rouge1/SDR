"""Finding media in the media folder, for every app's picker.

Ten pickers across eight apps used to list the media folder each in their
own way, and they disagreed:

- **None of them looked in subfolders.** A clip filed under
  ``media/Prelinger/`` was invisible to every app.
- **Five matched ``.wav`` case-sensitively and the rest did not.** Those
  five - AM Audio, FM Audio, FM Subcarrier, PPM-OOK and FM + RDS - used
  ``glob('*.wav')``, which on Linux misses ``SONG.WAV``; the NTSC and FM
  video transmitters lower-cased the name first and found it. So one file
  could be offered by one transmitter and not by the next, and only on
  Linux, since Windows filenames are not case-sensitive at all.
- **Two of them did not sort**, so their lists came out in whatever order
  the filesystem happened to return.

Everything goes through :func:`media_files` now. Standard library only, so
the modules that are deliberately free of Qt - ``ntsc_source`` - can use it
too.
"""

import os

WAV = ('.wav',)

#: What the audio pickers offer. WAV comes first on purpose: where a song is
#: kept both ways, :func:`choices` lists it once and keeps the WAV, which
#: plays without being decoded. An MP3 is decoded by ffmpeg as it plays -
#: see ``apps/audio_file.py``.
AUDIO = ('.wav', '.mp3')


def media_files(directory, extensions):
    """Every file under ``directory`` with one of ``extensions``.

    Subfolders are searched, to any depth. Extensions match whatever their
    case - ``extensions`` is given in lower case, dot included. Returns
    ``(relative path, full path)`` pairs, the relative path with forward
    slashes on every platform so that a label reads the same on Windows.

    The files at the top of the folder come first and each subfolder's
    follow, grouped by folder; within that, alphabetical ignoring case.
    Top-level files keep the relative path they always had - their own
    name - which is what keeps a choice saved before subfolders were
    searched pointing at the same file.

    Hidden folders and files are skipped. The ``._song.wav`` that macOS
    leaves beside every file it copies to a foreign disk has the right
    extension and is not audio at all; offered in a picker it fails only
    once someone presses OK. Symbolic links to folders are not followed,
    so a link back up the tree cannot make this walk forever.
    """
    if not directory or not os.path.isdir(directory):
        return []
    wanted = tuple(e.lower() for e in extensions)
    found = []
    for folder, subfolders, names in os.walk(directory):
        subfolders[:] = [d for d in subfolders if not d.startswith('.')]
        here = os.path.relpath(folder, directory)
        for name in names:
            if name.startswith('.'):
                continue
            if os.path.splitext(name)[1].lower() not in wanted:
                continue
            relative = name if here == '.' else \
                here.replace(os.sep, '/') + '/' + name
            found.append((relative, os.path.join(folder, name)))
    found.sort(key=lambda pair: ('/' in pair[0], pair[0].lower()))
    return found


def picker_name(relative, stem=None):
    """What a picker shows for a file: its folder, then its name.

    ``Prelinger/Chevrolet 1955 Heres Looking`` for a clip in a subfolder,
    and exactly what it always was for one at the top - the name without
    its extension, dashes turned to spaces. ``stem`` replaces the name
    part, for a picker that tidies names further (the ``.dat`` stills).
    """
    folder, _slash, name = relative.rpartition('/')
    if stem is None:
        stem = os.path.splitext(name)[0]
    stem = stem.replace('-', ' ')
    return f"{folder}/{stem}" if folder else stem


def choices(directory, extensions):
    """``(label, full path)`` for every matching file - a picker's items.

    One entry per name within a folder. A song kept as both ``song.wav``
    and ``song.mp3`` would otherwise be listed twice under the one label
    ``song``, with nothing on screen to say which is which - the trap the
    video picker fell into with its ``.mp4`` and ``.ts`` twins. The file
    kept is the one whose extension comes earliest in ``extensions``.
    """
    ranks = [e.lower() for e in extensions]
    kept, order = {}, []
    for relative, full in media_files(directory, extensions):
        stem, ext = os.path.splitext(relative)
        key, rank = stem.lower(), ranks.index(ext.lower())
        if key not in kept:
            order.append(key)
        if key not in kept or rank < kept[key][0]:
            kept[key] = (rank, relative, full)
    return [(picker_name(kept[k][1]), kept[k][2]) for k in order]
