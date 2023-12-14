import os, shutil
import threading, queue
import subprocess
import time
import cv2
import copy, tempfile
import random
from .lockvar import LockVar
from .config import Config
config = Config()


FFMPEG = "/usr/bin/ffmpeg"
BMP_FILES_PATH = "./temp"

class VideoStream:

    def __init__(self, video_url, codec):
        self.local_seq = 0
        self.remote_seq = 0
        self.codec = codec()
        self.video_url = video_url
        self.sendThread = None
        self.recvThread = None
        self.send_q = queue.Queue()
        self.recv_q = queue.Queue()
        self.max_recv_q = 10
        self.ffmpeg_subprocess = None
        self.last_msg = None
        self.last_new_image = LockVar(None)
        self.last_new_image_time = LockVar(0)
        self.last_valid_image_time = LockVar(0)
        self.status = "INITALIZING"
        self.stats = LockVar(VideoStreamStats())


    # Perform everything needed to connect to an inbound video stream
    def initRecv(self):
        self.recvThread = threading.Thread(target=self.__recvThread, name="Thread-2")
        self.recvThread.start()
 

    def __recvThread(self):

        def ffmpeg_worker(source_url):
            cmd = FFMPEG + " -y -i '"+source_url+"' -vf fps=1 ./"+BMP_FILES_PATH+"/out%d.bmp"
            self.ffmpeg_subprocess = subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE, shell=True)

        # Start ffmpeg process to capture frames as .bmp files
        cmd = config.YT_DLP+ " -f best -g "+self.video_url

        if os.path.isfile(config.YT_DLP) == False:
            print("yt_dlp not found: "+config.YT_DLP)
            return

        while True:
            try:
                source_url = subprocess.check_output(cmd,shell=True,encoding='UTF-8',stderr=subprocess.PIPE).strip()
                break
            except subprocess.CalledProcessError:
                print("Failed to connect to live stream. Is it live?")
                time.sleep(1)
                continue
        

        cmd = FFMPEG + " -y -i '"+source_url+"' -vf fps=1/2 ./"+BMP_FILES_PATH+"/out%d.bmp"
        self.ffmpeg_subprocess = subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE, shell=True)
        
        total = 0
        correct = 1

        while True:
            files = os.listdir(BMP_FILES_PATH)
            with self.stats.lock:
                self.stats.var.recv_backlog = len(files)
            for f in files:
                start = time.time()
                new_data = True
                if ".bmp" not in f:
                    continue
                time.sleep(.1)
                file_path = os.path.join(BMP_FILES_PATH,f)
                image = cv2.imread(file_path)

                # Try to decode the image, msg_data will be binary data
                is_valid, msg_data, data = self.codec.decode(image,f)
                with self.stats.lock:
                    self.stats.var.recv_total+=1
                    if is_valid:
                        self.stats.var.recv_valid+=1

                    else:
                        self.stats.var.recv_invalid+=1

                    self.last_valid_image_time.set(time.time())
                #self.codec.debug(is_valid, msg_data, data, image, total)
                # os.remove(file_path)

                if self.last_msg == msg_data:
                    new_data = False

                
                if new_data:
                    # Remove the nonce that helps resends appear new
                    msg_data = msg_data[1:]

                    with self.stats.lock:
                        self.stats.var.recv_new+=1
                    if os.path.exists(os.path.join(BMP_FILES_PATH,"done")) == False:
                        os.makedirs(os.path.join(BMP_FILES_PATH,"done"))
                    shutil.move(file_path,os.path.join(BMP_FILES_PATH,"done",f))

                    self.recv_q.put(msg_data)

                    self.last_msg = msg_data
                    self.last_new_image.set(image)
                    self.last_new_image_time.set(time.time())
                    
                else:
                    os.remove(file_path)
                with self.stats.lock:
                    self.stats.var.recv_time += time.time()-start
            #   print("Accuracy: "+str(round((correct/total)*100,2))+" - "+str(correct)+"/"+str(total)+"          Duration: "+str(duration)+"s")
                time.sleep(.05)
                self.__setStatus()


    # Perform everything needed to establish an outbound video stream
    def initSend(self):
        self.sendThread = threading.Thread(target=self.__sendThread, name="Thread-1")
        self.sendThread.start()


    def __sendThread(self):
        last_image = None
        image = self.codec.encode(str(self.get_nonce()).encode('utf-8'))
        while True:
            start = time.time()
            # Receive binary data from the queue, convert to encoded image
            try:
                data = self.send_q.get_nowait()
                
                image = self.codec.encode(self.get_nonce()+data)
                with self.stats.lock:
                    self.stats.var.send_total+=1
            except queue.Empty:
                pass

            if image is None:
                time.sleep(.25)
                continue
#            if image is not last_image:
            cv2.imshow("Sending", image)
            last_image = image
            with self.stats.lock:
                self.stats.var.send_time+=time.time()-start
            cv2.waitKey(2000)
        cv2.destroyAllWindows()    

    def send(self, data):
        self.send_q.put(data)


    def __setStatus(self):
        if (self.recvThread and self.recvThread.is_alive() and self.ffmpeg_subprocess 
                and self.sendThread and self.sendThread.is_alive() and self.last_msg != None):
            self.status = "STREAM UP"

    def getStatus(self):
        self.__setStatus()
        return self.status
    
    def displayLastImage(self):
        image = self.last_new_image.get()

        if image is not None:
            # Save the image to a temporary file
            temp_image_path = os.path.join(tempfile.gettempdir(), 'temp_image.jpg')
            cv2.imwrite(temp_image_path, image)
            print("Displaying image from last valid packet")
            subprocess.run(['xdg-open', temp_image_path])

    def get_nonce(self):
        return random.randint(0, 255).to_bytes(1, byteorder='big')

class VideoStreamStats:
    def __init__(self):
        self.send_total = 0
        self.send_time = 0
        self.recv_total = 0
        self.recv_time = 0
        self.recv_valid = 0
        self.recv_invalid = 0
        self.recv_new = 0
        self.recv_backlog = 0
