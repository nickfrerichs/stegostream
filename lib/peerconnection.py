import threading, queue
import time
import multiprocessing
from enum import Enum
import struct
import copy
from collections import OrderedDict
from .lockvar import LockVar
from .textmessage import IncomingTextMessage, OutgoingTextMessage


class PeerConnection:

    def __init__(self, videoStream):
        self.videoStream = videoStream
        self.recvMessagesThread = None
        self.conn_status = LockVar(Status.NONE)
        self.connected = False
        # 2 Channels so text and data transfers can happen simultaneously
        self.seq = LockVar({1:0, 2:0})
        self.ack = LockVar({1:0, 2:0})
        self.send_buffer = LockVar({1:Buffer(), 2:Buffer()})
        self.recv_buffer = LockVar({1:{}, 2:{}})
        self.buffer_threads = {}

    def initrecv(self):
        self.videoStream.initRecv()
        for attempt in range(30):
            print("Waiting for video stream... "+str(attempt))
            status = self.videoStream.getStatus()
            if status == "STREAM UP":
                self.recvMessagesThread = threading.Thread(target=self.__recvMessagesWorker, name="recvMessages")
                self.recvMessagesThread.start()
                return
            time.sleep(2)

    def initsend(self):
        if self.sendStreamUp():
            print("Send stream is already running.")
            return
        self.videoStream.initSend()
        time.sleep(1)
        self.initrecv()


    
    ## ============================================================================================================================
    ## Connection with peer methods
    ## ============================================================================================================================
    def __setConnStatus(self, newStatus):
        self.conn_status.set(newStatus)
        print(self.conn_status.get())

    # Method to check the flags and handle extablishing a connection
    def __checkFlags(self, flag):

        if self.conn_status.get() == Status.NONE and flag == Flags.SYN:
            self.__setConnStatus(Status.SYN_RECV)
            connectThread = threading.Thread(target=self.__connect, name="ServerConnect")
            connectThread.start()

        if self.conn_status.get() == Status.SYN_SEND and flag == Flags.SYN_ACK:
            self.__setConnStatus(Status.SYN_ACK_RECV)

        if self.conn_status.get() == Status.SYN_ACK_SEND and flag == Flags.ACK:
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
            bin_flag = Flags.set(Flags.SYN)
            self.__send_data(None, 0, bin_flag)
            self.__setConnStatus(Status.SYN_SEND)
            
            for attempt in range(30):
                if self.conn_status.get() == Status.SYN_ACK_RECV:
                    bin_flag = Flags.set(Flags.ACK)
                    self.__send_data(None, 0, bin_flag)
                    self.__setConnStatus(Status.ACK_SEND)
                    self.__setConnStatus(Status.CONNECTED)
                    break
                time.sleep(2)
        # This path is followed if a SYN flag was received to initialize a connection
        elif self.conn_status.get() == Status.SYN_RECV:
            bin_flag = Flags.set(Flags.SYN_ACK)
            self.__send_data(None, 0, bin_flag)
            # Mark as connected??
            self.__setConnStatus(Status.SYN_ACK_SEND)
            for attempt in range(30):
                if self.conn_status.get() == Status.ACK_RECV:
                    self.__setConnStatus(Status.CONNECTED)
                    break
                time.sleep(2)

        # Connected, start all buffer threads to handle in/out packets
        if self.conn_status.get() == Status.CONNECTED:
            self.buffer_threads[1] = threading.Thread(target=self.__processRecvBufferWorker, args=(1,), name="RecvBufferThread1")
            self.buffer_threads[2] = threading.Thread(target=self.__processRecvBufferWorker, args=(2,), name="RecvBufferThread2")
            self.buffer_threads["send"] = threading.Thread(target=self.__processSendBufferWorker, name="SendBufferThread")

            for b in self.buffer_threads:
                self.buffer_threads[b].start()
            


    ## ============================================================================================================================
    ## Recv messages methods
    ## ============================================================================================================================
    #
    # __recvMessagesWorker 
    # One worker for all channels
    #   - Channel 0 is handled by this thread directly, used for establishing a connection and health
    #   - Channel 1 is sent to a recvBuffer, text messages to be displayed on screen (work in progress)
    #   - Channel 2 is sent to a recvBuffer, data/files to be saved (TBD)
    #
    # __processRecvBuffer Worker
    # One worker for each channel (except 0)
    #   - Determine the ack to be used on next packet sent to peer to confirm received messages
    #   - Purge buffer of anything that has been received in order/ack sent
    #
    #

    def __recvMessagesWorker(self):

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
            
                channel, flag, ack, seq, data = struct.unpack(format_string, raw_message)
            except struct.error:
                print("Error unpacking stuct")
                print("Raw Message: "+str(raw_message))
                continue

            # Channel 0 is used for establishing a connection
            if channel == 0:
                self.__checkFlags(flag)

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

    def __processRecvBufferWorker(self, channel):

        def calculateAck(channel):
            # Thank you ChatGPT
            sorted_seq_numbers = sorted(self.recv_buffer.get()[channel])

            high_ack = sorted_seq_numbers[0]+1 if sorted_seq_numbers else 1  # Initialize with 0 if the buffer is empty

            # ack already aquired
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



    ## ============================================================================================================================
    ## Send messages methods
    ## ============================================================================================================================
    # __queue_message()
    # - Queue a single message to a channel's buffer
    #
    # __processSendBufferWorker()
    # One thread handles sending for all channels, each loop: 
    # - Send all messages in channel 1 buffer (text messages)
    # - Send one message in channel 2 buffer (data/files)
    #
    #
    def __processSendBufferWorker(self):
        while True:

            with self.send_buffer.lock:
                for channel, message in self.send_buffer.var.items():
                    try:
                        (message, seq, last) = channel.queue.get_nowait()
                        bin_flag = Flags.set(Flags.NONE)

                        if channel == 0:
                            data = channel.to_bytes(1, byteorder='big')+bin_flag + channel.to_bytes(2, byteorder='big') + channel.to_bytes(2, byteorder='big') + message
                        elif channel > 0:
                            with self.seq.lock, self.ack.lock:
                                data = channel.to_bytes(1, byteorder='big')+bin_flag + self.ack.var[channel].to_bytes(2, byteorder='big') + self.seq.var[channel].to_bytes(2, byteorder='big') + message
                        self.videoStream.send(data)
                    except queue.Empty:
                        pass

                    # Purge buffer up until last_ack by peer
            time.sleep(.1)


    def send_text(self, text):

        msg = OutgoingTextMessage(text,50)

        for index in range(msg.chunk_count):
            chunk = msg.get_next_chunk()
            flag = Flags.set(Flags.NONE)
            if index == msg.chunk_count - 1:
                flag = Flags.set(Flags.END_DATA)
            self.__queue_message(chunk,1,flag)
            

    # When messages are queued:
    # - Add to buffer
    def __queue_message(self, binary_data, channel, bin_flag = None):
        if binary_data is None:
            binary_data = "".encode("utf-8")

        if bin_flag is None:
            bin_flag = Flags.set(Flags.NONE)

        with self.send_buffer.lock, self.seq.lock:
            self.seq.var[channel] += 1
            self.send_buffer.var[channel].add_message(binary_data, 1, bin_flag)


    ## ===============================
    ## Status and misc methods
    ## ===============================

    def getStatus(self):
        text = "DISCONNECTED"
        if self.sendStreamUp() and self.recvStreamUp():
            text = "STREAM UP"
        if self.conn_status.get() == Status.CONNECTED:
            text ="CONNECTED"
        return text.ljust(12)

    def printStatus(self, verbose=False):

        print("recvMessagesThread: "+str(self.recvMessagesThread))
        print("conn_status: "+str(self.conn_status.get()))
        print("seq: "+str(self.seq.get()))
        print("ack: "+str(self.ack.get()))
        print("send_buffer: "+"1: "+str(len(self.send_buffer.get()[1].queue.qsize()))+" 2: "+str(len(self.send_buffer.get()[2].queue.qsize())))
        print("recv_buffer: "+"1: "+str(len(self.recv_buffer.get()[1]))+" 2: "+str(len(self.recv_buffer.get()[2])))

        if verbose:
            print(time.strftime("Last valid image: %Y-%m-%d %H:%M:%S", time.localtime(self.videoStream.last_valid_image_time.get())))
            print(time.strftime("Last new image: %Y-%m-%d %H:%M:%S", time.localtime(self.videoStream.last_new_image_time.get())))
            self.videoStream.displayLastImage()


    def sendStreamUp(self):
        if self.videoStream.sendThread and self.videoStream.sendThread.is_alive():
            return True
        return False
            
    def recvStreamUp(self):
        if self.videoStream.recvThread and self.videoStream.recvThread.is_alive() and self.videoStream.getStatus() == "STREAM UP":
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
    NONE = 0
    SYN = 1
    ACK = 2
    SYN_ACK = 3
    END_DATA = 4   
    FLAG_E = 5  
    FLAG_F = 6  
    FLAG_G = 7

    @staticmethod
    def set(flag):
        return flag.to_bytes(1, byteorder='big')



class Buffer:


    def __init__(self):
        self.buffer = {}
        self.queue = queue.Queue()
    
    def add_message(self, data, seq, last=False):
        self.queue.put((data, seq, last))
        self.buffer[seq] = data

    def get_message(self, index):
        return self.buffer[index]
    
    def get_next_message(self):
        return self.queue.get()
    
    def purge_buffer(self):
        pass
        