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
DEBUG_FILES_PATH = "./debug"

class VideoStream:

    def __init__(self, video_url, codec, msg):
        self.msg = msg
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
        self.stream_nonce = None
        self.stream_nonce_match = False
        self.send_fps = 1
        self.recv_fps = 2
        self.width, self.height = 1280, 720


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
            self.msg.print("yt_dlp not found: "+config.YT_DLP)
            return

        while True:
            try:
                source_url = subprocess.check_output(cmd,shell=True,encoding='UTF-8',stderr=subprocess.PIPE).strip()
                break
            except subprocess.CalledProcessError:
                self.msg.print("Failed to connect to live stream. Is it live?")
                time.sleep(1)
                continue
        

        cmd = FFMPEG + " -y -i '"+source_url+"' -vf fps="+str(self.recv_fps)+" ./"+BMP_FILES_PATH+"/out%d.bmp"
        self.ffmpeg_subprocess = subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE, shell=True)
        
        total = 0
        correct = 1

        while True:
            files = os.listdir(BMP_FILES_PATH)
            with self.stats.lock:
                self.stats.var.recv_backlog = len(files)
            for f in files:
                start_time = time.time()

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
                        self.stats.var.recv_crc_fail+=1

                    self.last_valid_image_time.set(time.time())

                # Get the stream_nonce from the packet
                try:
                    stream_nonce =(msg_data[:1])
                except IndexError:
                    self.__clean_up_recv_image(file_path, start_time)
                    continue
               
                if self.stream_nonce != stream_nonce:
                    with self.stats.lock:
                        self.stats.var.recv_nonce_fail+=1
                    self.__clean_up_recv_image(file_path, start_time)
                    continue
                elif self.stream_nonce_match == False:
                    self.stream_nonce_match = True
               
                if self.last_msg == msg_data:
                    self.__clean_up_recv_image(file_path, start_time)
                    continue
               
                self.last_msg = msg_data
                # Remove the stream nonce and the nonce that helps resends appear new
                msg_data = msg_data[2:]
                
                with self.stats.lock:
                    self.stats.var.recv_new+=1
                
                self.recv_q.put(msg_data)
                self.__clean_up_recv_image(file_path, start_time)
                self.write_debug_image(image, f)
                self.last_new_image.set(image)
                self.last_new_image_time.set(time.time())
                
                time.sleep(.05)
                self.__setStatus()
    def __clean_up_recv_image(self, file_path, start_time, out_file_path=None):
        if out_file_path:
            out_dir, f = os.path.split(out_file_path)
            if os.path.exists(out_dir) == False:
                os.makedirs(out_dir)
            shutil.move(file_path,out_file_path)
        else:
            os.remove(file_path)

        with self.stats.lock:
            self.stats.var.recv_time += time.time()-start_time



    # Perform everything needed to establish an outbound video stream
    def initSend(self, nonce_int, rtmp_url):
        self.stream_nonce = self.get_nonce(nonce_int)
        self.send_rtmp_url = rtmp_url
        self.sendThread = threading.Thread(target=self.__sendThread, name="Thread-1")
        self.sendThread.start()


    def __sendThread(self):
        raw_fps = 10
# FFmpeg command for RTMP streaming with filler audio
        ffmpeg_cmd_stream = [
            'ffmpeg',
            '-r', str(raw_fps),
            '-s', f'{self.width}x{self.height}',
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
            '-g' , str(raw_fps*4),
            self.send_rtmp_url
        ]

        ffmpeg_process_stream = subprocess.Popen(ffmpeg_cmd_stream, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

        last_image = None
        image = self.codec.encode(self.stream_nonce)
        next_update = time.time()
        while True:
            if time.time() >= next_update:
                # This is the rate of the image being updated with data
                next_update = time.time() + (1/self.send_fps)
                start = time.time()
                # Receive binary data from the queue, convert to encoded image
                try:
                    data = self.send_q.get_nowait()
                    image = self.codec.encode(self.stream_nonce+self.get_nonce()+data)

                    with self.stats.lock:
                        self.stats.var.send_total+=1
                except queue.Empty:
                    pass

                if image is None:
                    time.sleep(.25)
                    continue
    #            if image is not last_image:
                # ffmpeg_process_stream.stdin.write(image.tobytes())
                # ffmpeg_process_stream.stdin.flush()
                #cv2.imshow("Sending", image)
                last_image = image
                with self.stats.lock:
                    self.stats.var.send_time+=time.time()-start
                #cv2.waitKey(self.send_fps*1000)
                

            ffmpeg_process_stream.stdin.write(image.tobytes())
            ffmpeg_process_stream.stdin.flush()
            # This is the stream rate of the underlying video stream
            time.sleep(1/(raw_fps+(raw_fps*.1)))

        cv2.destroyAllWindows()    

    def send(self, data):
        self.send_q.put(data)


    def __setStatus(self):

        nonce_int = None
        if self.stream_nonce:
            nonce_int = int.from_bytes(self.stream_nonce, byteorder='big')

        if (self.recvThread and self.recvThread.is_alive() and self.ffmpeg_subprocess 
                and self.sendThread and self.sendThread.is_alive() and self.last_msg != None and self.stream_nonce_match):
            self.status = "STREAM UP"
        elif (self.recvThread and self.recvThread.is_alive() and self.ffmpeg_subprocess 
                and self.sendThread and self.sendThread.is_alive()):
            self.status = "Send Stream initialized with nonce "+str(nonce_int)+", recv stream initalizing"
        elif self.sendThread and self.sendThread.is_alive():
            self.status = "Send Stream initialized with nonce "+str(nonce_int)+", no recv stream"
        else:
            self.status = "IDLE"
        self.msg.set_status("stream",self.status)
        if self.status == "STREAM UP":
            rate = (self.stats.var.recv_valid / self.stats.var.recv_total) * 100
            rate_string = "{:.2f}%".format(rate)
            stats = "Send: {}, Recv: {} (CRC: {}/{:.0f} - {})".format(
            self.stats.var.send_total, self.stats.var.recv_new, self.stats.var.recv_valid, self.stats.var.recv_total, rate_string)
            self.msg.set_status("stream","STREAM UP ("+str(nonce_int)+") - "+stats)

    def getStatus(self):
        self.__setStatus()
        return self.status
    
    def write_debug_image(self, image, name):
        if os.path.exists(DEBUG_FILES_PATH) == False:
            os.makedirs(DEBUG_FILES_PATH)
        cv2.imwrite(os.path.join(DEBUG_FILES_PATH, name), image)

    def displayLastImage(self):
        image = self.last_new_image.get()

        if image is not None:
            # Save the image to a temporary file
            temp_image_path = os.path.join(tempfile.gettempdir(), 'temp_image.jpg')
            cv2.imwrite(temp_image_path, image)
            self.msg.print("Displaying image from last valid packet")
            subprocess.run(['xdg-open', temp_image_path])

    def get_nonce(self, val=None):
        if val is None:
            val = random.randint(0, 255)
        return val.to_bytes(1, byteorder='big')

class VideoStreamStats:
    def __init__(self):
        self.send_total = 0
        self.send_time = 0
        self.recv_total = 0
        self.recv_time = 0
        self.recv_valid = 0
        self.recv_crc_fail = 0
        self.recv_new = 0
        self.recv_backlog = 0
        self.recv_nonce_fail = 0
