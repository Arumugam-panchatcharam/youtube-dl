## Useful yt-dlp commands

Install `yt-dlp` and `ffmpeg` first. The commands below use Chrome cookies to
access courses available to your Udemy account.

### Download a course and merge its chapters

Use the helper to download all lectures and subtitles, then create a
`merged.mp4` in each multi-lecture chapter folder. It looks up the course's
current Udemy lecture order, preserves the original clips, and merges without
re-encoding:

```sh
python3 download_and_merge_udemy.py \
  'https://www.udemy.com/course/embedded-linux-using-yocto-part-3/' \
  '14-Embedded-Linux-using-Yocto-Part-3'
```

The second argument is the local course directory to create or use. Existing
`merged.mp4` files are kept by default; pass `--force` to rebuild them after
downloading updates:

```sh
python3 download_and_merge_udemy.py --force \
  'https://www.udemy.com/course/embedded-linux-using-yocto-part-3/' \
  '14-Embedded-Linux-using-Yocto-Part-3'
```

The downloader keeps completed files and continues past individual lecture
download errors. The merge step then checks every chapter against the Udemy
lecture list, reports all chapters with missing clips, and merges only chapters
whose clips are complete. Rerunning the same command resumes without
overwriting completed downloads. yt-dlp can still exit with status 1 when an
individual lecture fails; the helper will check and merge complete chapters
before reporting the remaining download errors.
Before downloading, the helper compares the course playlist with existing
video filenames and requests only missing playlist items, so a retry does not
revisit all lectures.

If the lectures are already downloaded, skip the download step and merge only:

```sh
python3 download_and_merge_udemy.py --merge-only \
  'https://www.udemy.com/course/embedded-linux-using-yocto-part-3/' \
  '14-Embedded-Linux-using-Yocto-Part-3'
```

To use cookies from a different browser, add for example
`--cookies-from-browser firefox`.

### Download without merging

The equivalent direct yt-dlp command downloads all subtitles and stores each
lecture in a numbered chapter directory:

```sh
yt-dlp --cookies-from-browser chrome --all-subs \
  --merge-output-format mp4 \
  -o '14-Embedded-Linux-using-Yocto-Part-3/%(chapter_number)s-%(chapter)s/%(title)s.%(ext)s' \
  'https://www.udemy.com/course/embedded-linux-using-yocto-part-3/'
```

### List the course lecture order

```sh
yt-dlp --cookies-from-browser chrome --flat-playlist \
  --print '%(playlist_index)s | chapter %(chapter_number)s | %(chapter)s | %(title)s' \
  'https://www.udemy.com/course/embedded-linux-using-yocto-part-3/'
```

`playlist_index` is the overall lecture order; `chapter_number` identifies the
chapter. To list only one chapter, pipe the output through `awk`, for example:

```sh
yt-dlp --cookies-from-browser chrome --flat-playlist \
  --print '%(chapter_number)s | %(title)s' \
  'https://www.udemy.com/course/embedded-linux-using-yocto-part-3/' |
  awk -F '|' '$1 + 0 == 3'
```

The merge helper stops with an error if a listed lecture is missing locally, if
an unexpected MP4 is present in a chapter, or if ffmpeg/ffprobe cannot validate
the result. This helps avoid silently creating a merged file with an incorrect
order or missing clips.
