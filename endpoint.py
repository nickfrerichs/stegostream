import os, sys, glob
import cv2
import lib.stegocodecs.rgb_grid
import lib.stegostream
import time
import threading
import config

videoStream = lib.stegostream.VideoStream(lib.stegocodecs.rgb_grid.Codec, config)
conn = lib.stegostream.PeerConnection(videoStream)

def main():
    
    purge_temp_files()

    # Create a daemon thread
    input_thread = threading.Thread(target=user_input_thread, daemon=True)

    # Start the thread
    input_thread.start()

    while True:
        pass


def user_input_thread():
    while True:

        status = conn.getStatus()
        user_input = input(status+"> ")
        if user_input.startswith("initrecv "):
            video_url = user_input.split(" ",1)[1]
            video_url = config.video_url
            conn.initrecv(video_url)

        if user_input.startswith("initsend"):
            conn.initsend()

        if user_input.startswith("send "):
            data = user_input.split(" ",1)[1]
            conn.send_text(data)

        if user_input.startswith("connect"):
            conn.connect()

        if user_input.startswith("status"):
            conn.printStatus()


def purge_temp_files():
    locations = ["./temp/*.bmp", "./temp/debug_images/*.bmp", "./temp/done/*.bmp"]

    for location in locations:
        bmp_files = glob.glob(location)
        if not bmp_files:
            continue
        confirm = input("Do you want to delete temp files "+location+"? (Y/n): ").lower()
        if confirm != "" and confirm[0].lower() != "y":
            continue
        for file_path in bmp_files:
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

    # i = 0
    # while True:
    #     txt = str(i)+str(i*3)+str(i*2)
    #     videoStream.queueSend(str(txt))
    #     i += 1
    #     input()


main()