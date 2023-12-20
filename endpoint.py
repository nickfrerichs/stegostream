import os, sys, glob
import lib.stegocodecs.rgb_grid
import lib.peerconnection
import lib.videostream
import time
import threading
from lib.config import Config
import lib.lockvar

config = Config()
shared_input = lib.lockvar.LockVar({"id":None, "prompt":None, "response":None})
videoStream = lib.videostream.VideoStream(config.video_url, lib.stegocodecs.rgb_grid.Codec)
conn = lib.peerconnection.PeerConnection(videoStream, shared_input)


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

        if user_input.startswith("send_file "):
            filepath = user_input.split(" ",1)[1]
            conn.send_file(filepath,2)
            print("send_file called with "+filepath)


        # If a child thread needs user input, it is asked here. N exits canceling the request
        if shared_input.get()["id"] is not None and shared_input.get()["prompt"] is not None:
            prompt = shared_input.get_index("prompt")
            response = ""
            print("Prompt: "+prompt)
            while True:
                response = input(prompt)
                if len(response) > 0 and response.lower()[0] == "n":
                    with shared_input.lock:
                        shared_input.var = {"id":None, "prompt":None, "response":None}
                    break

                dir_path = os.path.dirname(response)
                if response != "" and os.path.exists(dir_path):
                    with shared_input.lock:
                        shared_input.var["response"] = response
                    break

        time.sleep(.1)



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