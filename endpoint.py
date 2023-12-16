import os, sys, glob
import lib.stegocodecs.rgb_grid
import lib.peerconnection
import lib.videostream
import time
import threading
from lib.config import Config

config = Config()
videoStream = lib.videostream.VideoStream(config.video_url, lib.stegocodecs.rgb_grid.Codec)
conn = lib.peerconnection.PeerConnection(videoStream)

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
        # if user_input.startswith("initrecv "):
        #     conn.initrecv()

        if user_input.startswith("init"):
            try:
                nonce = user_input.split(" ",1)[1]
            except:
                print("You must specify a numeric value 0-255")
                continue
            if nonce.isdigit() == False:
                print("You must specify a numeric value 0-255")
                continue
            conn.initsend(int(nonce))
            time.sleep(2)
            print("\n\n")

        if user_input.startswith("send "):
            data = user_input.split(" ",1)[1]
            conn.send_text(data)

        if user_input.startswith("connect"):
            conn.connect()

        if user_input.startswith("status"):
            conn.printStatus(True)

        if user_input.startswith("last_image"):
            conn.displayLastImage()


def purge_temp_files():
    locations = ["./temp/*.bmp", "./temp/debug_images/*.bmp", "./temp/done/*.bmp", "./debug/*.bmp"]

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