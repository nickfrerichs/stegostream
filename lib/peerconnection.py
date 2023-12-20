import sys
import threading, queue
import time
import multiprocessing
from enum import Enum
import struct
import copy
import random
from .lockvar import LockVar
from .sendtext import IncomingTextMessage, OutgoingTextMessage
from .sendfile import IncomingFile, OutgoingFile
from .flags import Flags


class PeerConnection:

    def __init__(self, videoStream, shared_input):
        self.shared_input = shared_input
        self.videoStream = videoStream
        self.recvMessagesThread = None
        self.conn_status = LockVar(Status.NONE)
        self.connected = False
        # 2 Channels so text and data transfers can happen simultaneously
        self.seq = LockVar({1:1, 2:1})
        self.ack = LockVar({1:1, 2:1})
        self.peer_ack = LockVar({1:0, 2:0})
        self.resend = LockVar({1:list(),2:list()})
        self.missing = LockVar({1:set(),2:set()})
        self.send_buffer = LockVar({1:Buffer(1), 2:Buffer(2, 10)})
        self.resend_queue = LockVar({1:queue.Queue(), 2:queue.Queue()})
        self.recv_buffer = LockVar({1:{}, 2:{}})
        self.channel_status = LockVar({1:[Status.NONE,None], 2:[Status.NONE,None]})
        self.buffer_threads = {}

    def initrecv(self):
        self.videoStream.initRecv()
        for attempt in range(60):
            print("Waiting for video stream... "+str(attempt))
            status = self.videoStream.getStatus()
            if status == "STREAM UP":
                self.recvMessagesThread = threading.Thread(target=self.__recvMessagesWorker, name="recvMessages")
                self.recvMessagesThread.start()
                return
            time.sleep(5)

    def initsend(self, nonce):
        if self.sendStreamUp():
            print("Send stream is already running.")
            return
        self.videoStream.initSend(nonce)
        time.sleep(1)
        self.initrecv()

    
    ## ============================================================================================================================
    ## Connection with peer methods
    ## ============================================================================================================================
    def __setConnStatus(self, newStatus):
        self.conn_status.set(newStatus)
        print(self.conn_status.get())

    # Method to check the flags and handle extablishing a connection
    def __check_handshake_flags(self, flags):
        print(self.conn_status.get())
        if self.conn_status.get() == Status.NONE and Flags.is_only_set(flags,Flags.SYN):
            self.__setConnStatus(Status.SYN_RECV)
            connectThread = threading.Thread(target=self.__connect, name="ServerConnect")
            connectThread.start()

        if self.conn_status.get() == Status.SYN_SEND and Flags.is_set(flags, (Flags.SYN, Flags.ACK)):
            self.__setConnStatus(Status.SYN_ACK_RECV)

        if self.conn_status.get() == Status.SYN_ACK_SEND and Flags.is_only_set(flags, Flags.ACK):
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
            bin_flag = Flags.get_bin(Flags.SYN)
            self.__send_control_message(bin_flag)
            self.__setConnStatus(Status.SYN_SEND)
            
            for attempt in range(30):
                if self.conn_status.get() == Status.SYN_ACK_RECV:
                    bin_flag = Flags.get_bin(Flags.ACK)
                    self.__send_control_message(bin_flag)
                    self.__setConnStatus(Status.ACK_SEND)
                    self.__setConnStatus(Status.CONNECTED)
                    break
                time.sleep(2)
        # This path is followed if a SYN flag was received to initialize a connection
        elif self.conn_status.get() == Status.SYN_RECV:
            bin_flag = Flags.get_bin((Flags.SYN, Flags.ACK))
            self.__send_control_message(bin_flag)
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
        # For now, add some time to avoid reading images from previous session
        
        time.sleep(20)
        print("Starting connection listener")
        while True:
            # Get binary data
            try:
                raw_message = self.videoStream.recv_q.get(timeout=1)
            except queue.Empty:
                time.sleep(.1)
                continue
            
            # Skip messages that contain no headers
            if len(raw_message) == 0:
                continue

            format_string = '>BBHH{}s'.format(len(raw_message)-header_length)

            try:
            # Unpack binary data into headers and data
            
                channel, flags, ack, seq, data = struct.unpack(format_string, raw_message)
                flags = flags.to_bytes(1,byteorder='big')
            except struct.error:
                print("Error unpacking stuct")
                print("Raw Message: "+str(raw_message))
                print("Length: "+str(len(raw_message)))
                continue
            with self.peer_ack.lock:
                self.peer_ack.var[channel] = ack

            # Channel 0 is used for establishing a connection
            if channel == 0 and self.conn_status.get() != Status.CONNECTED:
                self.__check_handshake_flags(flags)
                continue

            if self.conn_status.get() != Status.CONNECTED:
                continue

            # If any resends are requested with the maintenance packet, they will be processed by the send buffer thread
            if channel == 0 and Flags.is_set(flags,Flags.MAINT):
                with self.resend.lock:
                    # format_string = '>BH{}i'.format((len(data) - 1) // 4)
                    format_string = '>BH{}i'.format((len(data) - 1) // struct.calcsize('i'))
                    channel, ack, *resend_list = struct.unpack(format_string, data)
                    with self.peer_ack.lock:
                        self.peer_ack.var[channel] =  ack
                    if len(resend_list) > 0:
                        print ("Got MAINT packet with resends - channel: "+str(channel)+", ack "+str(ack)+" resend: "+str(resend_list))
                    if not resend_list:  # Check if resend_list is empty
                        resend_list = []  # Assign an empty list if it's empty
                    elif isinstance(resend_list, int):
                        resend_list = [resend_list]  # Convert to a list if it's a single integer

                    self.resend.var[channel] = resend_list

                
                # If the ack specified is less than the current syn, it means the peer never received that, but may not know it was sent. Resend it
                with self.ack.lock,  self.seq.lock, self.resend.lock:
                    last_seq = self.seq.var[channel]-1
                ###    print ("Got MAINT packet - channel: "+str(channel)+", ack "+str(ack)+" resend: "+str(resend_list)+", last_seq: "+str(last_seq))
                    if ack <= last_seq and len(self.resend.var[channel]) == 0:
                        # Could resend everything from ack to seq incase they missed multiple
                        self.resend.var[channel].append(last_seq)

                continue
            
            # This should not happen, but I'd like to know if it does
            if channel == 0:
                print("An unexpected Channel 0 packet was received: "+str(raw_message))
                continue

            # FOR TESTING - Randomly miss an incoming packet to test resending
            # if random.random() < .25:
            #     print("Whoops, "+str(seq)+" was dropped.")
            #     continue

            
            # Ignore things where we already have the ack
            if channel > 0 and seq >= self.ack.get()[channel]:
                # Save the received data to the buffer, if we don't already have it
                with self.recv_buffer.lock:
                    if self.recv_buffer.var[channel].get(seq) is None:
                        self.recv_buffer.var[channel][seq] = (data, flags)
                        print("Added "+str(seq)+" to buffer.")
            elif channel > 0 and seq < self.ack.get()[channel]:
                print("Packet "+str(seq)+" arrived but is not needed, not added to buffer.")



    def __processRecvBufferWorker(self, channel):

        # def calculateAck(channel):
        #     # Thank you ChatGPT
        #     sorted_seq_numbers = sorted(self.recv_buffer.get()[channel])

        #     high_ack = sorted_seq_numbers[0]+1 if sorted_seq_numbers else 1  # Initialize with 0 if the buffer is empty

        #     # ack already aquired
        #     ack = max(high_ack, self.ack.var[channel])

        #     for seq in sorted_seq_numbers[1:]:
        #         if seq == ack + 1:
        #             ack = seq  # Update ack if the sequence numbers are contiguous
        #         else:
        #             break  # Exit the loop if a non-contiguous sequence number is encountered
        #     # The 'ack' now represents the highest contiguous sequence number
        #     return ack

        # Initialize the ack to 1
        with self.ack.lock:
            self.ack.var[channel] = 1

        maint_interval = 20
        maint_timer = time.time()+maint_interval

        while True:
            purge_buffer = False
            # Determine what the "ack" should be set to based on how many contiguous packets are in the recv_buffer
            # with self.ack.lock:
            #     max_ack = calculateAck(channel)

            with self.recv_buffer.lock, self.ack.lock:
                buffered_seq = sorted(self.recv_buffer.var[channel])
                for seq in buffered_seq:
                    
                    # If the seq is less than the ack, we've already processed it
                    if seq < self.ack.var[channel]:
                        print(str(seq)+" is less than "+str(self.ack.var[channel]))
                        continue

                    # If out of order, add seq numbers in the gap to the resend set and continue to next
                    if seq > self.ack.var[channel]:
                       # print(str(seq)+" is greater than "+str(self.ack.var[channel]))
                        with self.missing.lock:
                          #  missing_set = set([seq - i for i in range(1, seq - self.ack.var[channel])])
                            missing_set = set([seq - i for i in range(0, seq - self.ack.var[channel] + 1)])
                            missing_set -= set(buffered_seq)
                            self.missing.var[channel].update(missing_set)
                        continue
                    
                    # If not out of order, update the ack and continue processing the data
                    # with self.missing.lock:
                    #     self.missing.var[channel].discard(seq)
                    self.ack.var[channel] += 1
                    print(str(seq)+" is being processed. Ack increased to "+str(self.ack.var[channel]))
                    data, flags = self.recv_buffer.var[channel][seq]
                    purge_buffer = True
                    # Channel 1 is for text messages to be displayed to the screen
                    if channel == 1:
                        # If this is a new textmessage, create a new incoming message
                        if Flags.is_set(flags,Flags.START_DATA):
                            msg = IncomingTextMessage()
                        msg.receive_chunk(data)

                        if Flags.is_set(flags,Flags.END_DATA):
                            print("\n*******************************************************\n")
                            print(msg.decompress_message())
                            print("\n*******************************************************\n")
                            msg = None

                        # text = self.recv_buffer.var[channel][seq].decode('utf-8')
                        # print(text)
                            
                    # Channel 2 is for receiving files and writing to disk
                    if channel == 2:
                        print("Channel 2 packet arrived: "+str(data))
                        # File send request is received from peer, handle request and send ack, IncomingFile returned if success
                        if self.channel_status.get()[channel][0] == Status.NONE and Flags.is_only_set(flags,Flags.SYN):
                            print("Incoming File initiated")
                            incoming_file = self.__handle_file_request_from_peer(data, channel)
                            if incoming_file == None:
                                continue


                        # Ack is received for a running __send_file thread
                        if self.channel_status.get()[channel][0] == Status.SYN_SEND and Flags.is_only_set(flags,Flags.ACK):
                            print("ACK received for file send")
                            file_id, size = struct.unpack(f'!HQ', data)
                            with self.channel_status.lock:
                                self.channel_status.var[channel] = [Status.ACK_RECV, file_id]

                        # If status is NONE at this point, the user canceled or declined to receive the file
                        # if self.channel_status.get()[channel][0] == Status.NONE:
                        #     incoming_file = None
                        #     continue

                        # If SYN_RECV, an out_path was provided, send an ACK


                        # Somewhere, need to check if the file timer has expired and reset the whole thing

                        if self.channel_status.get()[channel][0] == Status.FILE_RECV and Flags.is_set(flags,Flags.SYN):
                            self.__handle_file_recv_from_peer(data, incoming_file, flags)

                

                    
            time.sleep(.25)


            if maint_timer < time.time():
                # check for resends and process
                with self.missing.lock, self.ack.lock:
                    binary_data = struct.pack('>BH', channel, self.ack.var[channel])
                    if len(self.missing.var[channel]) > 0:
                        # Make sure all missing seq #s are greater than the ack
                        missing_list = [x for x in list(self.missing.var[channel]) if x >= self.ack.var[channel]]
                        if len(missing_list) > 0:
                            print("Sending MAINT packet for channel:"+str(channel)+", ack "+str(self.ack.var[channel])+", missing "+str(missing_list))
                            # Channel + List of missing syn #s
                            binary_data += struct.pack('>{}i'.format(len(missing_list)), *missing_list)
                            self.missing.var[channel] = set()                    
                    print("Sending MAINT packet for channel:"+str(channel)+", ack "+str(self.ack.var[channel]))
                    self.__send_control_message(Flags.get_bin(Flags.MAINT),binary_data)
                # reset timer
                maint_timer = time.time()+maint_interval


            # Clear buffer for this channel up to the ack number, thank ChatGPT for the one-liner
            if purge_buffer:
                print("Purging buffer")
                with self.recv_buffer.lock, self.ack.lock:
                    self.recv_buffer.var[channel] = {key: value for key, value in self.recv_buffer.var[channel].items() if key >= self.ack.var[channel]}
                print("Buffer contains: "+str(self.recv_buffer.var[channel].keys()))
            
            time.sleep(.1)



    def __handle_file_request_from_peer(self, data, channel):

        file_id, size, in_name = struct.unpack(f'!HQ{len(data)-10}s', data)
        # Request input from the user
        incoming_file = None
        input_id = random.randint(0, sys.maxsize)
        self.shared_input.set_index("id",input_id)
        self.shared_input.set_index("prompt", "Receive file from peer? Size: "+str(size/1024/1024)+" MB: "+", Name: "+str(in_name)+ "\nEnter valid path to receive file, or -N- to decline.\nPath: ")
        print("Prompt added to shared_input")
        # Wait for response by user
        for attempt in range(30):
            # Canceled by user
          #  print("Waiting for user respnse: id "+str(self.shared_input.get()["id"])+" response: "+str(self.shared_input.get()["response"]))
            if self.shared_input.get()["id"] is None:
                with self.channel_status.lock:
                    self.channel_status.var[channel][0] = Status.NONE
                return None

            # Input received, continue to send ack
            if self.shared_input.get()["id"] == input_id and self.shared_input.get()["response"] is not None:
                with self.channel_status.lock:
                    self.channel_status.var[channel][0] = Status.SYN_RECV
                out_path = self.shared_input.get_index("response")
                incoming_file = IncomingFile(out_path, file_id, 60)
                break
                
            time.sleep(2)

        if self.channel_status.get()[channel][0] == Status.SYN_RECV and incoming_file is not None:
    
            # Resend back an ACK packet with the file ID
            bin_flags = Flags.get_bin(Flags.ACK)                           
            file_binary_data = struct.pack(f'!HQ', file_id, size)
            self.__queue_message(file_binary_data, channel, bin_flags)
            with self.channel_status.lock:
                self.channel_status.var[channel][0] = Status.FILE_RECV
        return incoming_file


    def __handle_file_recv_from_peer(self, data, incoming_file, flags):
        # It is the start of a new compressed segment, flag = 1 for start of new segment
        if  Flags.is_set(flags, [Flags.SYN, Flags.START_DATA]):
            incoming_file.process_incoming_chunk(data, 1)
        # It is the end of a compressed segment, flag = 2 for end of segment 
        elif Flags.is_set(flags, [Flags.SYN, Flags.END_DATA]):
            incoming_file.process_incoming_chunk(data, 2)
        elif Flags.is_set(flags, [Flags.SYN, Flags.MOD]):
            incoming_file.process_incoming_chunk(data, 0)
            
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


            # channel1_q = self.send_buffer.var[1].queue
            # channel = 1
            

            self.__process_channel_send_buffer(1)
            self.__process_channel_send_buffer(2,2)

            for channel in (1,2):
                # Purge buffer up until last_ack by peer
                with self.peer_ack.lock, self.send_buffer.lock:
                    self.send_buffer.var[channel].purge_buffer(self.peer_ack.var[channel])
                    
            time.sleep(.1)


    def __process_channel_send_buffer(self, channel, max_items=sys.maxsize):
        channel_q = self.send_buffer.var[channel].queue
        count = 0
        with self.send_buffer.lock:
            while not channel_q.empty() and count < max_items:
                message, seq, bin_flags = channel_q.get()
                with self.seq.lock, self.ack.lock:
                    data = channel.to_bytes(1, byteorder='big')+bin_flags + self.ack.var[channel].to_bytes(2, byteorder='big') + seq.to_bytes(2, byteorder='big') + message
                # videoStream will queue sending, one goes out every 2 seconds
                self.videoStream.send(data)
                print("Send: "+str(seq))
                count+=1

            # Send out any requested missing packets and empty the resend list
            resend_count = 0

            with self.resend.lock, self.peer_ack.lock:
                if len(self.resend.var[channel]) > 0:
                    for syn in self.resend.var[channel]:
                        if syn < self.peer_ack.var[channel]:
                            continue
                        print(self.send_buffer.var[channel].buffer)
                        buffer_data = self.send_buffer.var[channel].buffer[syn]
                        self.videoStream.send(buffer_data)
                        print("Resend "+str(syn))
                        resend_count+=1

                    self.resend.var[channel] = list()
                    print("Emptied resend list")

    def send_text(self, text):

        msg = OutgoingTextMessage(text,100)
        print("Chunk Count: "+str(msg.chunk_count))
        for index in range(msg.chunk_count):
            print("Chunk index: "+str(index))
            bin_chunk = msg.get_next_chunk()
            bin_flags = Flags.get_bin(Flags.NONE)
            if index == 0:
                print("Start_Data")
                bin_flags = Flags.get_bin(Flags.START_DATA, bin_flags)
            if index == msg.chunk_count - 1:
                print("End_Data")
                bin_flags = Flags.get_bin(Flags.END_DATA, bin_flags)
            self.__queue_message(bin_chunk,1,bin_flags)

    def send_file(self, file_path, channel):
        # Start __send_file thread and pass sendfile object
        outgoing_file = OutgoingFile(file_path)
        if outgoing_file.exists() == False:
            print("File not found: "+str(file_path))
            return
        threading.Thread(target=self.__send_file, args=(2,outgoing_file), name="sendFileThread").start()
        with self.channel_status.lock:
            self.channel_status.var[channel][0] = Status.SYN_SEND

        print("Thread started for file "+file_path)


    def __send_file(self, channel, file):
        # Send a SYN flag packet to peer with filename and size on Channel 2
        if self.channel_status.get()[channel][0] == Status.NONE:
            print("In channel status == None")
            bin_flags = Flags.get_bin(Flags.SYN)
            filename_bytes = file.name.encode("utf-8")
            # Pack the values into a binary object using struct
            binary_data = struct.pack(f'!HQ{len(filename_bytes)}s', file.id, file.size, filename_bytes)

            self.__queue_message(binary_data, channel, bin_flags)
            print("Queued message to request send")
            for attempt in range(30):
                print(self.channel_status.get()[channel][0])
                print(self.channel_status.get()[channel][1])
                print(file.id)
                print(str(type(self.channel_status.get()[channel][1])))
                print(str(type(file.id)))

                if self.channel_status.get()[channel][0] == Status.ACK_RECV and self.channel_status.get()[channel][1] == file.id:
                    with self.channel_status.lock:
                        self.channel_status.var[channel][0] = Status.FILE_SEND
                        break
                print("Waiting for ACK_RECV")
                time.sleep(2)

            if self.channel_status.get()[channel][0] == Status.FILE_SEND:
                for flag, chunk in file.get_file_chunks():
                    bin_flags = Flags.get_bin(Flags.NONE)
                    if flag == 1:
                        bin_flags = Flags.get_bin([Flags.SYN, Flags.START_DATA])
                        # New segment
                    elif flag == 2:
                        bin_flags = Flags.get_bin([Flags.SYN, Flags.END_DATA])
                        # End of segment
                    else:
                        bin_flags = Flags.get_bin((Flags.SYN, Flags.MOD))
                        # Middle of segment
                    
                    self.__queue_message(chunk, channel, bin_flags)

                    time.sleep(2)


        #       # It is the start of a new compressed segment, flag = 1 for start of new segment
        # if  Flags.is_set(flags, [Flags.SYN, Flags.START_DATA]):
        #     incoming_file.process_incoming_chunk(data, 1)
        # # It is the end of a compressed segment, flag = 2 for end of segment 
        # elif Flags.is_set(flags, [Flags.SYN, Flags.END_DATA]):
        #     incoming_file.process_incoming_chunk(data, 2)
        # else:
        #     incoming_file.process_incoming_chunk(data, 0)
            
        # pass
            

    # When messages are queued:
    # - Add to buffer
    def __queue_message(self, binary_data, channel, bin_flags = None):
        if binary_data is None:
            binary_data = "".encode("utf-8")

        if bin_flags is None:
            bin_flags = Flags.get_bin(Flags.NONE)

        with self.send_buffer.lock, self.seq.lock:
            self.send_buffer.var[channel].add(binary_data, self.seq.var[channel], bin_flags)
            self.seq.var[channel] += 1


    # Control messages always on channel 1, are not buffered
    def __send_control_message(self, bin_flag, message=None):
        if message is None:
            message = "".encode("utf-8")
        channel = 0
        data = channel.to_bytes(1, byteorder='big')+bin_flag + channel.to_bytes(2, byteorder='big') + channel.to_bytes(2, byteorder='big') + message
        self.videoStream.send(data)
        

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

    def set_channel_status(self,channel, status, msg=None):
        with self.channel_status.lock:
            self.channel_status.var[channel] = (status, msg)

    def printStatus(self, verbose=False):

        video_stream_stats = self.videoStream.stats.get()
        print("recvMessagesThread: "+str(self.recvMessagesThread))
        print("conn_status: "+str(self.conn_status.get()))
        print("seq: "+str(self.seq.get()))
        print("ack: "+str(self.ack.get()))
        print("send_buffer: "+"1: "+str(self.send_buffer.var[1].queue.qsize())+" 2: "+str(self.send_buffer.var[2].queue.qsize()))
        print("recv_buffer: "+"1: "+str(len(self.recv_buffer.get()[1]))+" 2: "+str(len(self.recv_buffer.get()[2])))
        print("recv image backlog: "+str(video_stream_stats.recv_backlog))
        for attr_name, attr_value in video_stream_stats.__dict__.items():
            print(f"{attr_name}: {attr_value}")

        if verbose:
            print(time.strftime("Last valid image: %Y-%m-%d %H:%M:%S", time.localtime(self.videoStream.last_valid_image_time.get())))
            print(time.strftime("Last new image: %Y-%m-%d %H:%M:%S", time.localtime(self.videoStream.last_new_image_time.get())))
            print("Sent total: "+str(video_stream_stats.send_total))
            print("Sent avg time: "+str(video_stream_stats.send_time / video_stream_stats.send_total) if video_stream_stats.send_total != 0 else "Sent avg time: 0")
            print("Recv total: "+str(video_stream_stats.recv_total))
            print("Recv avg time: "+str(video_stream_stats.recv_time / video_stream_stats.recv_total) if video_stream_stats.recv_total != 0 else "Recv avg time: 0")
            print("Recv valid: "+str(video_stream_stats.recv_valid))
            print("Recv invalid: "+str(video_stream_stats.recv_nonce_fail))
            print("Recv new: "+str(video_stream_stats.recv_new))
            print("Send buffer: "+str(self.send_buffer.var[1].buffer))
            

    def displayLastImage(self):
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
    FILE_RECV = 8
    FILE_SEND = 9


class Buffer:

    def __init__(self, channel, queue_size=None):
        self.buffer = {}
        if queue_size:
            self.queue = queue.Queue(maxsize=queue_size)
        else:
            self.queue = queue.Queue()
        self.channel = channel
        self.no_ack = 0
    
    def add(self, bin_data, seq, bin_flags):
        self.queue.put((bin_data, seq, bin_flags))
        self.buffer[seq] = self.channel.to_bytes(1, byteorder='big')+bin_flags + self.no_ack.to_bytes(2, byteorder='big') + seq.to_bytes(2, byteorder='big') + bin_data

    def get_message(self, index):
        return self.buffer[index]
    
    def get_next_message(self):
        return self.queue.get()
    
    def purge_buffer(self, ack):
        self.buffer = {key: value for key, value in self.buffer.items() if key >= ack}
        