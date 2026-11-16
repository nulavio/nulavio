# Media fixtures

`sine-aac.mp4`: three seconds of a 440 Hz tone, AAC-LC, mono, 13.5 kB. Made for
`tests/integration/test_media_codecs.py` (#377) with FFmpeg's own encoder; it holds nobody else's work:

    ffmpeg -f lavfi -i sine=frequency=440:duration=3 -c:a aac -b:a 32k -ac 1 -map_metadata -1 \
        -fflags +bitexact -flags:a +bitexact -movflags +faststart sine-aac.mp4
