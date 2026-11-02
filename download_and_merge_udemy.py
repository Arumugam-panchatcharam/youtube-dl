#!/usr/bin/env python3
"""Download a Udemy course and merge each chapter in lecture order."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def normalize_title(title):
    return ''.join(char.lower() for char in title if char.isalnum())


def run(command):
    return subprocess.run(command, check=True)


def chapter_directories(course_dir):
    directories = {}
    for path in course_dir.iterdir():
        match = re.match(r'^(\d+)[-_ ]', path.name)
        if path.is_dir() and match:
            chapter_number = int(match.group(1))
            if chapter_number in directories:
                raise RuntimeError(
                    'Multiple directories found for chapter %d: %s and %s'
                    % (chapter_number, directories[chapter_number], path))
            directories[chapter_number] = path
    return directories


def missing_playlist_items(entries, course_dir):
    directories = chapter_directories(course_dir)
    existing_titles = {}
    video_extensions = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.flv'}

    for chapter_number, chapter_dir in directories.items():
        existing_titles[chapter_number] = {
            normalize_title(path.stem)
            for path in chapter_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in video_extensions
            and not path.name.endswith('.part')
            and path.stat().st_size > 0
        }

    missing_items = []
    for playlist_index, entry in enumerate(entries, 1):
        try:
            chapter_number = int(entry['chapter_number'])
            title = entry['title']
        except (KeyError, TypeError, ValueError):
            raise RuntimeError(
                'A Udemy lecture is missing its chapter number or title')
        if normalize_title(title) not in existing_titles.get(chapter_number, set()):
            missing_items.append((playlist_index, chapter_number, title))
    return missing_items


def concat_quote(path):
    return str(path.resolve()).replace('\\', '\\\\').replace("'", "'\\''")


def merge_chapter(chapter_dir, lecture_titles, overwrite):
    videos = [
        path for path in chapter_dir.glob('*.mp4')
        if path.name not in ('merged.mp4', 'output.mp4')
    ]
    videos_by_title = {}
    duplicate_titles = set()
    for path in videos:
        title = normalize_title(path.stem)
        if title in videos_by_title:
            duplicate_titles.add(title)
        videos_by_title[title] = path

    ordered_videos = []
    missing_titles = []
    for title in lecture_titles:
        key = normalize_title(title)
        if key in duplicate_titles or key not in videos_by_title:
            missing_titles.append(title)
        else:
            ordered_videos.append(videos_by_title[key])

    if missing_titles:
        raise RuntimeError(
            '%s is missing or has ambiguous lecture files: %s'
            % (chapter_dir, ', '.join(missing_titles)))
    if len(ordered_videos) != len(videos):
        matched = set(ordered_videos)
        extras = sorted(path.name for path in videos if path not in matched)
        raise RuntimeError(
            '%s has MP4 files not present in the Udemy lecture list: %s'
            % (chapter_dir, ', '.join(extras)))
    if len(ordered_videos) < 2:
        print('Skipping %s: fewer than two lectures' % chapter_dir)
        return

    destination = chapter_dir / 'merged.mp4'
    if destination.exists() and not overwrite:
        print('Keeping existing %s (use --force to rebuild)' % destination)
        return

    manifest_path = None
    temporary_output = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', suffix='.txt', delete=False) as manifest:
            manifest_path = manifest.name
            for path in ordered_videos:
                manifest.write("file '%s'\n" % concat_quote(path))

        fd, temporary_output = tempfile.mkstemp(
            prefix='.merged-', suffix='.mp4', dir=str(chapter_dir))
        os.close(fd)
        run([
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0', '-i', manifest_path,
            '-c', 'copy', temporary_output,
        ])
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', temporary_output],
            check=True, stdout=subprocess.PIPE, universal_newlines=True)
        if not probe.stdout.strip() or float(probe.stdout) <= 0:
            raise RuntimeError('ffprobe reported an invalid merged video')

        os.replace(temporary_output, str(destination))
        temporary_output = None
        print('Created %s' % destination)
    finally:
        if manifest_path and os.path.exists(manifest_path):
            os.unlink(manifest_path)
        if temporary_output and os.path.exists(temporary_output):
            os.unlink(temporary_output)


def main():
    parser = argparse.ArgumentParser(
        description='Download a Udemy course and merge its chapters in Udemy order.')
    parser.add_argument('url', help='Udemy course URL')
    parser.add_argument(
        'course_dir',
        help='Directory to create/use for the course, for example 14-Yocto-Part-3')
    parser.add_argument(
        '--cookies-from-browser', default='chrome',
        help='yt-dlp browser cookie source (default: chrome)')
    parser.add_argument(
        '--force', action='store_true',
        help='replace existing merged.mp4 files after successful validation')
    parser.add_argument(
        '--merge-only', action='store_true',
        help='merge already-downloaded lectures without downloading them')
    args = parser.parse_args()

    for program in ('yt-dlp', 'ffmpeg', 'ffprobe'):
        if shutil.which(program) is None:
            parser.error('%s must be installed and available on PATH' % program)

    course_dir = Path(args.course_dir).expanduser().resolve()
    course_dir.mkdir(parents=True, exist_ok=True)

    metadata_result = subprocess.run(
        ['yt-dlp', '--cookies-from-browser', args.cookies_from_browser,
         '--flat-playlist', '--dump-single-json', args.url],
        check=True, stdout=subprocess.PIPE, universal_newlines=True)
    course = json.loads(metadata_result.stdout)
    entries = course.get('entries') or []
    if not entries:
        raise RuntimeError('No course lectures were returned by yt-dlp')

    download_returncode = 0
    lectures_by_chapter = {}
    for entry in entries:
        try:
            number = int(entry['chapter_number'])
            title = entry['title']
        except (KeyError, TypeError, ValueError):
            raise RuntimeError('A Udemy lecture is missing its chapter number or title')
        lectures_by_chapter.setdefault(number, []).append(title)

    download_returncode = 0
    if not args.merge_only:
        missing_items = missing_playlist_items(entries, course_dir)
        if missing_items:
            playlist_items = ','.join(str(item[0]) for item in missing_items)
            print(
                'Downloading %d missing lecture(s) out of %d: %s'
                % (len(missing_items), len(entries),
                   ', '.join('%d: %s' % (item[1], item[2])
                             for item in missing_items)),
                file=sys.stderr)
            download_result = subprocess.run([
                'yt-dlp', '--cookies-from-browser', args.cookies_from_browser,
                '--playlist-items', playlist_items,
                '--all-subs', '--merge-output-format', 'mp4',
                '--no-overwrites', '--ignore-errors',
                '--output', str(course_dir / '%(chapter_number)s-%(chapter)s' / '%(title)s.%(ext)s'),
                args.url,
            ])
            download_returncode = download_result.returncode
            if download_returncode:
                print(
                    'Warning: yt-dlp exited with status %d; checking downloaded '
                    'lectures and merging complete chapters.' % download_returncode,
                    file=sys.stderr)
        else:
            print('All %d course lectures are already downloaded.' % len(entries))

    directories = chapter_directories(course_dir)
    merge_errors = []
    for number, titles in sorted(lectures_by_chapter.items()):
        chapter_dir = directories.get(number)
        if chapter_dir is None:
            merge_errors.append(
                'No downloaded directory found for Udemy chapter %d' % number)
            continue
        try:
            merge_chapter(chapter_dir, titles, args.force)
        except RuntimeError as error:
            merge_errors.append(str(error))
    if merge_errors or download_returncode:
        details = list(merge_errors)
        if download_returncode:
            details.insert(
                0, 'yt-dlp exited with status %d; review its earlier output for '
                'the individual download errors' % download_returncode)
        raise RuntimeError(
            '%d issue(s) remain after checking the course:\n  %s'
            % (len(details), '\n  '.join(details)))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError,
            json.JSONDecodeError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            command = Path(error.cmd[0]).name if error.cmd else 'command'
            message = (
                'Error: %s exited with status %d. See its output above for the '
                'underlying error. Completed downloads were kept; rerun the '
                'same command to resume.' % (command, error.returncode))
        else:
            message = 'Error: %s' % error
        print(message, file=sys.stderr)
        sys.exit(1)
