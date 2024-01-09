import cv2
import numpy as np
import subprocess
import time
import sys


# Video settings
width, height = 640, 480
frame_rate = 10
rtmp_url = 'rtmp://a.rtmp.youtube.com/live2/?????'

# FFmpeg command for RTMP streaming with filler audio
ffmpeg_cmd_stream = [
    'ffmpeg',
    '-r', str(frame_rate),
    '-s', f'{width}x{height}',
    '-f', 'rawvideo',
    '-pix_fmt', 'bgr24',
    '-i', 'pipe:0',
    '-f', 'lavfi',  # Use lavfi (audio filter) for audio input
    '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',  # Generate silent audio
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-c:a', 'aac',
    '-map', '0:v:0',
    '-map', '1:a:0',
    '-f', 'flv',
    '-g' , '60',
    rtmp_url
]

# OpenCV setup
gradient_start = np.array([0, 0, 0], dtype=np.uint8)
gradient_end = np.array([255, 255, 255], dtype=np.uint8)
transition_duration = 5.0  # in seconds

# FFmpeg process for streaming
ffmpeg_process_stream = subprocess.Popen(ffmpeg_cmd_stream, stdin=subprocess.PIPE)

try:
    start_time = time.time()

    while True:  # Loop indefinitely
        elapsed_time = time.time() - start_time
        alpha = min(elapsed_time / transition_duration, 1.0)

        # Gradually change colors for the entire frame
        current_color = ((1 - alpha) * gradient_start + alpha * gradient_end).astype(np.uint8)
        current_frame = np.full((height, width, 3), current_color, dtype=np.uint8)

        # Convert to bytes and write to FFmpeg stdin for RTMP streaming
        ffmpeg_process_stream.stdin.write(current_frame.tobytes())
        ffmpeg_process_stream.stdin.flush()

        # Pause for a short duration to control the frame rate
        time.sleep(1 / (frame_rate + 1))

        # Restart the transition if it completes
        if alpha == 1.0:
            start_time = time.time()

except BrokenPipeError:
    print("Error writing to FFmpeg stdin")
finally:
    # Terminate the FFmpeg process
    ffmpeg_process_stream.stdin.close()
    ffmpeg_process_stream.wait()
