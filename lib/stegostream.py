import os, sys, shutil
import cv2
import threading, queue
import time
import subprocess
import multiprocessing
from enum import Enum
import struct
import copy

#YT_DLP = "./env/bin/yt-dlp"
FFMPEG = "/usr/bin/ffmpeg"
BMP_FILES_PATH = "./temp"
OBS = "/var/lib/flatpak/exports/bin/com.obsproject.Studio --startstreaming --profile stegstream"
FIREFOX = "firefox --new-tab https://studio.youtube.com/channel/UC/livestreaming"

class PeerConnection:

    def __init__(self, videoStream):
        self.videoStream = videoStream
        self.recvMessagesThread = None
        self.conn_status = LockVar(Status.NONE)
        self.connected = False
        # 2 Channels so text and data transfers can happen simultaneously
        self.seq = LockVar({1:0, 2:0})
        self.ack = LockVar({1:0, 2:0})
        self.send_buffer = LockVar({1:{}, 2:{}})
        self.recv_buffer = LockVar({1:{}, 2:{}})
        self.buffer_threads = {}

    def initrecv(self, video_url):
        self.videoStream.initRecv(video_url)
        for attempt in range(7):
            print("Waiting for video stream... "+str(attempt))
            status = self.videoStream.getStatus()
            if status == "LINK UP":
                self.recvMessagesThread = threading.Thread(target=self.__recvMessages, name="recvMessages")
                self.recvMessagesThread.start()
                return
            time.sleep(2)

    def initsend(self):
        if self.sendStreamUp():
            print("Send stream is already running.")
            return
        self.videoStream.initSend()

    def __recvMessages(self):

        # one byte for channel, one byte for flags, two bytes for ack, two bytes for seq, and the rest for binary_data
        header_length = 6
        while True:
            # Get binary data
            try:
                raw_message = self.videoStream.recv_q.get(timeout=1)
            except queue.Empty:
                continue
            format_string = '>BBHH{}s'.format(len(raw_message)-header_length)
           # if len(raw_message) < 6: continue
            try:
            # Unpack binary data into headers and data
            
                channel, flags, ack, seq, data = struct.unpack(format_string, raw_message)
            except struct.error:
                print("Error unpacking stuct")
                print("Raw Message: "+str(raw_message))
                continue

            # Channel 0 is used for establishing a connection
            if channel == 0:
                self.__checkFlags(flags)

            if self.conn_status.get() != Status.CONNECTED:
                continue

            # with self.ack.lock:
            #     self.ack.var[channel] = ack

            if channel > 0:
                # Save the received data to the buffer
                with self.recv_buffer.lock:
                    self.recv_buffer.var[channel][seq] = data

            
            #except struct.error:
             #   print("Struct Error")
              #  continue

            # print("RECIEVED")
            # print("Channel:", channel)
            # print("Flags:", flags)
            # print("Ack:", ack)
            # print("Seq:", seq)
            # print("Binary Data:", data)

    def __processRecvBuffer(self, channel):

        def calculateAck(channel):
            # Thank you ChatGPT
            sorted_seq_numbers = sorted(self.recv_buffer.get()[channel])

            high_ack = sorted_seq_numbers[0]+1 if sorted_seq_numbers else 1  # Initialize with 0 if the buffer is empty

            # Lack already aquired
            ack = max(high_ack, self.ack.var[channel])

            for seq in sorted_seq_numbers[1:]:
                if seq == ack + 1:
                    ack = seq  # Update ack if the sequence numbers are contiguous
                else:
                    break  # Exit the loop if a non-contiguous sequence number is encountered
            # The 'ack' now represents the highest contiguous sequence number
            return ack

        while True:
            purge_buffer = False
            # Determine what the "ack" should be set to based on how many contiguous packets are in the recv_buffer
            with self.ack.lock:
                self.ack.var[channel] = calculateAck(channel)

            with self.recv_buffer.lock, self.ack.lock:
                for b in self.recv_buffer.var[channel]:
                    # Skip if out of order
                    if b > self.ack.var[channel]:
                        continue

                    if channel == 1:
                        text = self.recv_buffer.var[channel][b].decode('utf-8')
                        print(text)
                    purge_buffer = True
            time.sleep(1)



            # Clear buffer for this channel up to the ack number, thank ChatGPT for the one-liner
            if purge_buffer:
                with self.recv_buffer.lock, self.ack.lock:
                    self.recv_buffer.var[channel] = {key: value for key, value in self.recv_buffer.var[channel].items() if key >= self.ack.var[channel]}
            
            time.sleep(.1)

                
    def __processSendBuffer(self):
        while True:
            with self.send_buffer.lock:
                for b in self.send_buffer.var[1]:
                    self.send_q.put(self.send_buffer.var[1][b], 1)
            time.sleep(.1)
                        
    def __setConnStatus(self, newStatus):
        self.conn_status.set(newStatus)
        print(self.conn_status.get())

    # Method to check the flags and handle extablishing a connection
    def __checkFlags(self, flags):

        if self.conn_status.get() == Status.NONE and Flags.check(flags, Flags.SYN):
            self.__setConnStatus(Status.SYN_RECV)
            connectThread = threading.Thread(target=self.__connect, name="ServerConnect")
            connectThread.start()

        if self.conn_status.get() == Status.SYN_SEND and Flags.check(flags, Flags.ACK) and Flags.check(flags, Flags.SYN):
            self.__setConnStatus(Status.SYN_ACK_RECV)

        if self.conn_status.get() == Status.SYN_ACK_SEND and Flags.check(flags, Flags.ACK):
            self.__setConnStatus(Status.ACK_RECV)



    def connect(self):
        threading.Thread(target=self.__connect, name="ClientConnect").start()

    def __connect(self):
        if self.sendStreamUp() == False:
            print("Cannot connect, no send stream active")
            return
        if self.recvStreamUp() == False:
            print("Cannot connect, no recv stream")
            return

        # This path is followed if initiating the connection
        if self.conn_status.get() == Status.NONE:
            print("BEGIN HANDSHAKE")
            
            # Send SYN flag, wait for SYN ACK
            flags = Flags.set(SYN=True)
            self.__send_data(None, 0, flags)
            self.__setConnStatus(Status.SYN_SEND)
            
            for attempt in range(30):
                if self.conn_status.get() == Status.SYN_ACK_RECV:
                    flags = Flags.set(SYN=False, ACK=True)
                    self.__send_data(None, 0, flags)
                    self.__setConnStatus(Status.ACK_SEND)
                    self.__setConnStatus(Status.CONNECTED)
                    break
                time.sleep(2)
        # This path is followed if a receiving a connection initalization
        elif self.conn_status.get() == Status.SYN_RECV:
            flags = Flags.set(SYN=True, ACK=True)
            self.__send_data(None, 0, flags)
            # Mark as connected??
            self.__setConnStatus(Status.SYN_ACK_SEND)
            for attempt in range(30):
                if self.conn_status.get() == Status.ACK_RECV:
                    self.__setConnStatus(Status.CONNECTED)
                    break
                time.sleep(2)

        # Connected, start all buffer threads to handle in/out packets
        if self.conn_status.get() == Status.CONNECTED:
            self.buffer_threads[1] = threading.Thread(target=self.__processRecvBuffer, args=(1,), name="RecvBufferThread1")
            self.buffer_threads[2] = threading.Thread(target=self.__processRecvBuffer, args=(2,), name="RecvBufferThread2")
            self.buffer_threads["send"] = threading.Thread(target=self.__processSendBuffer, name="SendBufferThread")

            for b in self.buffer_threads:
                self.buffer_threads[b].start()
            

    def send_text(self, text):
        self.__send_data(text.encode('utf-8'),1)

    def __send_data(self, binary_data, channel, flags = None):
        if binary_data is None:
            binary_data = "".encode("utf-8")

        if flags is None:
            flags = Flags.set()

        # print("SENDING DATA")
        # print("Channel:", channel)
        # print("Flags:", flags)

        if channel == 0:
            data = channel.to_bytes(1, byteorder='big')+flags + channel.to_bytes(2, byteorder='big') + channel.to_bytes(2, byteorder='big') + binary_data
        elif channel > 0:
            with self.seq.lock, self.ack.lock:
                self.seq.var[channel] += 1
                data = channel.to_bytes(1, byteorder='big')+flags + self.ack.var[channel].to_bytes(2, byteorder='big') + self.seq.var[channel].to_bytes(2, byteorder='big') + binary_data

        self.videoStream.queueSend(data)

    def getStatus(self):
        text = "DISCONNECTED"
        if self.sendStreamUp() and self.recvStreamUp():
            text = "LINK UP"
        if self.conn_status.get() == Status.CONNECTED:
            text ="CONNECTED"
        return text.ljust(12)

    def printStatus(self):

        print("recvMessagesThread: "+str(self.recvMessagesThread))
        print("conn_status: "+str(self.conn_status.get()))
        print("seq: "+str(self.seq.get()))
        print("ack: "+str(self.ack.get()))
        print("send_buffer: "+"1: "+str(len(self.send_buffer.get()[1]))+" 2: "+str(len(self.send_buffer.get()[2])))
        print("recv_buffer: "+"1: "+str(len(self.recv_buffer.get()[1]))+" 2: "+str(len(self.recv_buffer.get()[2])))


        # if self.sendStreamUp():
        #     print("Send stream: alive")
        # else:
        #     print("Send stream: not alive")

        # if self.recvStreamUp():
        #     print("Receive stream: alive")
        # else:
        #     print("Receive stream: not alive")


    def sendStreamUp(self):
        if self.videoStream.sendThread and self.videoStream.sendThread.is_alive():
            return True
        return False
            
    def recvStreamUp(self):
        if self.videoStream.recvThread and self.videoStream.recvThread.is_alive():
            return True
        return False
    
    def connected(self):
        if self.sendStreamUp() and self.recvStreamUp() and self.connected:
            return True
        return False
    

class Status(Enum):
    NONE = 0
    SYN_SEND = 1
    SYN_RECV = 2
    SYN_ACK_SEND = 3
    SYN_ACK_RECV = 4
    ACK_SEND = 5
    ACK_RECV = 6
    CONNECTED = 7

class Flags:
    SYN = 0b00000001
    ACK = 0b00000010
    FLAG_C = 0b00000100
    FLAG_D = 0b00001000
    FLAG_E = 0b00010000
    FLAG_F = 0b00100000
    FLAG_G = 0b01000000
    
    def set(SYN=False, ACK=False):
        flags = 0b00000000
        if SYN:
            flags |= Flags.SYN
        if ACK:
            flags |= Flags.ACK

        return flags.to_bytes(1, byteorder='big')
    
    def check(flags_byte, flag):
        return (flags_byte & flag) != 0



class VideoStream:

    def __init__(self, codec, config):
        self.config = config
        self.local_seq = 0
        self.remote_seq = 0
        self.codec = codec()
        self.sendThread = None
        self.recvThread = None
        self.send_q = queue.Queue()
        self.recv_q = queue.Queue()
        self.max_recv_q = 10
        self.ffmpeg_subprocess = None
        self.last_msg = None
        self.status = "INITALIZING"
#        self.manager = multiprocessing.Manager()
#        self.shared = self.manager.dict()




    # Perform everything needed to connect to an inbound video stream
    def initRecv(self, video_url):
        self.recvThread = threading.Thread(target=self.__recvThread, args=(video_url,), name="Thread-2")
        self.recvThread.start()
 

    def __recvThread(self, video_url):

        def ffmpeg_worker(source_url):
            cmd = FFMPEG + " -y -i '"+source_url+"' -vf fps=1 ./"+BMP_FILES_PATH+"/out%d.bmp"
            self.ffmpeg_subprocess = subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE, shell=True)

        # Start ffmpeg process to capture frames as .bmp files
        cmd = self.config.YT_DLP+ " -f best -g "+video_url

        if os.path.isfile(self.config.YT_DLP) == False:
            print("yt_dlp not found: "+self.config.YT_DLP)
            return

        try:
            source_url = subprocess.check_output(cmd,shell=True,encoding='UTF-8',stderr=subprocess.PIPE).strip()
        except subprocess.CalledProcessError:
            print("Failed to connect to live stream. Is it live?")
            return
        

        cmd = FFMPEG + " -y -i '"+source_url+"' -vf fps=1/2 ./"+BMP_FILES_PATH+"/out%d.bmp"
        self.ffmpeg_subprocess = subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE, shell=True)
        
        # Using multiprocessing is probably not needed
        # ffmpeg_process = multiprocessing.Process(target=ffmpeg_worker, args=(source_url,))
        # ffmpeg_process.start()
        
        total = 0
        correct = 1

        while True:
            files = os.listdir(BMP_FILES_PATH)

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

                total+=1
                if is_valid:
                    correct+=1
                else:
                    pass
                #self.codec.debug(is_valid, msg_data, data, image, total)
                # os.remove(file_path)

                if self.last_msg == msg_data:
                    new_data = False

                if new_data:
                    if os.path.exists(os.path.join(BMP_FILES_PATH,"done")) == False:
                        os.makedirs(os.path.join(BMP_FILES_PATH,"done"))
                    shutil.move(file_path,os.path.join(BMP_FILES_PATH,"done",f))

                    self.recv_q.put(msg_data)

                    self.last_msg = msg_data
                    duration = time.time()-start
                else:
                    os.remove(file_path)

            #    print("Accuracy: "+str(round((correct/total)*100,2))+" - "+str(correct)+"/"+str(total)+"          Duration: "+str(duration)+"s")
                time.sleep(.05)
                self.__setStatus()





    # Perform everything needed to establish an outbound video stream
    def initSend(self):
        self.sendThread = threading.Thread(target=self.__sendThread, name="Thread-1")
        self.sendThread.start()


    def __sendThread(self):
        last_image = None
        image = self.codec.encode("".encode('utf-8'))
        while True:

            # Receive binary data from the queue, convert to encoded image
            try:
                data = self.send_q.get_nowait()
                image = self.codec.encode(data)
                #self.local_seq += 1
               # print("new image "+data+"_"+str(sendData_q.qsize()))
            except queue.Empty:
                pass

            if image is None:
                time.sleep(.25)
                continue
#            if image is not last_image:
            cv2.imshow("Sending", image)
            last_image = image
            cv2.waitKey(2)
        cv2.destroyAllWindows()    

    def queueSend(self, data):
        self.send_q.put(data)


    def __setStatus(self):
        if (self.recvThread and self.recvThread.is_alive() and self.ffmpeg_subprocess 
                and self.sendThread and self.sendThread.is_alive() and self.last_msg != None):
            self.status = "LINK UP"

    def getStatus(self):
        self.__setStatus()
        return self.status


class LockVar():
    def __init__(self,var):
        self.var = var
        self.lock = threading.Lock()

    def set(self, val):
        with self.lock:
            self.var = val

    def get(self):
        with self.lock:
            return copy.deepcopy(self.var)


# class SharedVar():
#     def __init__(self, var):
#         self.var = var
#         self.lock = threading.Lock()

#     def get(self):
#         with self.lock:
#             return self.var

#     def set(self, newVar):
#         with self.lock:
#             self.var = newVar

# class SharedDict():
#     def __init__(self, var):
#         self.var = var
#         self.lock = threading.Lock()

#     def get(self, key):
#         with self.lock:
#             self.var[key]

#     def set(self, key, val):
#         with self.lock:
#             self.var[key] = val


# class SharedDict2():
#     def __init__(self, var):
#         self.var = var
#         self.lock = threading.Lock()

#     def get(self, key, key2):
#         with self.lock:
#             self.var[key][key2]

#     def set(self, key, key2, val):
#         with self.lock:
#             self.var[key][key2] = val

#     def getDict(self):
#         with self.
        

