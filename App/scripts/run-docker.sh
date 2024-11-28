#!/bin/bash
current_directory=$(pwd)
xhost +
docker run -it --rm --net=host --gpus all --entrypoint="" -e DISPLAY=$DISPLAY --device /dev/snd \
    -v /tmp/.X11-unix/:/tmp/.X11-unix \
    -v "$current_directory/config/:/usr/emotion-ds/config/" \
    -v "$current_directory/data/:/usr/emotion-ds/data/" \
    -v "$current_directory/testVideos/:/usr/emotion-ds/testVideos/" \
    -v "$current_directory/main.py:/usr/emotion-ds/main.py" \
    -p 8555:8554 \
    --name emotion-ds \
    emotion-ds-base \
    bash