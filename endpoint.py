import os, sys, glob, shutil
import lib.stegocodecs.rgb_grid
import lib.peerconnection
import lib.videostream
import time
import threading
import curses
import argparse
from lib.config import Config
import lib.lockvar
from datetime import datetime
import logging


# Configure logging, used for debugging at times
log_file_path = './error.log'
logging.basicConfig(filename=log_file_path, level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

config = Config()
msg = None
stdscr = None

def curses_main(_stdscr):

    global stdscr  # Access the global stdscr variable
    stdscr = _stdscr  # Assign _stdscr to the global stdscr variable
    # Turn on keypad input and disable cursor display
    stdscr.keypad(1)
    curses.curs_set(0)

    # Set timeout for getch() to make it non-blocking
    stdscr.timeout(100)



    while True:
        status = conn.getStatus()
        display_status(stdscr)

        # Get user input
        key = stdscr.getch()

        # Exit the loop if the user presses 'q'
        if key == ord('q'):
            break

        # Handle Enter key
        elif key == 10:  # 10 is the ASCII code for Enter
            prompt_thread = threading.Thread(target=process_user_input)
            prompt_thread.start()
            msg.user_input = ""  # Clear user input after processing

        # Handle backspace
        elif key == curses.KEY_BACKSPACE or key == 127:
            msg.user_input = msg.user_input[:-1]

        # Update user input based on key
        elif key != -1 and key < 256:
            msg.user_input += chr(key)



def main():
    while True:
        status = conn.getStatus()
        user_input = input(status+"> ")
        # if user_input.startswith("initrecv "):
        #     conn.initrecv()

        if user_input != "":
            msg.user_input = user_input
            process_user_input()
            msg.user_input = ""

        time.sleep(.1)

def process_user_input():

    user_input = msg.user_input

    # A thread is waiting on user input, gather it here
    if msg.input_prompt != None and msg.user_response == None:
        msg.put_response(user_input)
        return

    # Handle standard input
    if user_input.startswith("init"):
        try:
            nonce = user_input.split(" ",1)[1]
        except:
            msg.print("You must specify a numeric value 0-255")
            return
        if nonce.isdigit() == False:
            msg.print("You must specify a numeric value 0-255")
            return
        conn.initsend(int(nonce),config.SEND_VIDEO_URL)
        time.sleep(2)
        msg.print("\n\n")
        return

    if user_input.startswith("send_message "):
        data = user_input.split(" ",1)[1]
        conn.send_text(data)
        return

    if user_input.startswith("connect"):
        conn.connect()
        return

    if user_input.startswith("status"):
        conn.printStatus(True)
        return
    
    if user_input.startswith("verbose "):
        try:
            level = int(user_input.split(" ",1)[1])
        except ValueError:
            msg.print("You must specify 0 or 1")
            return
        if level < 0 or level > 1:
            msg.print("You must specify 0 or 1")
            return
        msg.set_verbose(level)
        return

    if user_input.startswith("send_file "):
        filepath = user_input.split(" ",1)[1]
        conn.send_file(filepath,2)
        msg.print("send_file called with "+filepath)
        return
                     
    msg.print(" ")
    msg.print_line()
    msg.print(" Valid commands:")
    msg.print("   verbose <0,1>        - send more output to the screen (default 0)")
    msg.print("   init <0-255>         - initialize the video streams with peer, nonce must match peer")
    msg.print("   connect              - begin connection handshake to establish a connection")
    msg.print("   status               - print some stats to the screen")
    msg.print("   send_message <text>  - send a text message to the connected peer")
    msg.print("   send_file <path>     - send a file to the connected peer")
    msg.print_line()
    msg.print(" ")

def display_status(stdscr):
    msg.update_statuses()
    msg.update_video_stream_stats()
    stdscr.clear()

    # Display user input area
    prompt = "Input: {}"

    stdscr.addstr(1, 0, prompt.format(msg.user_input))
    stdscr.hline(2, 0, '-', curses.COLS)

    if msg.input_prompt:
        stdscr.addstr(3, 0, prompt.format(msg.input_prompt))
    else:
        stdscr.addstr(3, 0,"")


    stdscr.hline(4, 0, '-', curses.COLS)

    # Display last 5 messages
    messages_y = 5
    num_channels = msg.channel_count+1


    for i, message in enumerate(reversed(msg.last_messages)):
        stdscr.addstr(messages_y + i, 0, str(message))


    # Draw a line above the statuses
    stdscr.hline(curses.LINES - (4+num_channels), 0, '-', curses.COLS)

    # Display statuses in the left bottom corner, left-justified
    width = 13
    status1_y, status2_y = curses.LINES - (2+num_channels) , curses.LINES - (1+num_channels)
    backlog_text = ""

    if msg.video_stream_stats and msg.video_stream_stats.recv_backlog > 10:        
        backlog_text = ("==> Recv Backlog: "+str(msg.video_stream_stats.recv_backlog)+" <==").upper()

    try:
        stdscr.addstr(status1_y, 0, "Video Stream: ".ljust(width)+msg.status["stream"] +"  "+backlog_text)
        stdscr.addstr(status2_y, 0, "Peer Conn:    ".ljust(width)+msg.status["conn"])
        # Iterate through channel statuses
        for channel in range(num_channels):
            line_y = curses.LINES - 1 - abs(channel - num_channels +1)
            stdscr.addstr(line_y, 0, f"Channel {channel}:".ljust(width) + f"{msg.status[channel]}")
    except curses.error:
        pass


    stdscr.refresh()


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

class AppMessages:
    def __init__(self):
        self.video_stream_stats = None
        self.video_stream_stats_update_time = 0
        self.channel_count = 2
        self.text_message_wrap = 90
        self.input_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.msg_lines = 25
        self.input_prompt = None
        self.user_input = ""
        self.user_response = None
        self.response1 = ""
        self.response2 = ""
        self.verbose = 1
        self.status = {"stream" : "IDLE", "conn" : "IDLE"}
        for i in range(self.channel_count+1):
            self.status[i] = "" 
        self.last_messages = [""] * self.msg_lines
        


    def print(self, text, verbose=0):

        if verbose > self.verbose:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        text = str(text)

        if args.basic_output:
            message_with_timestamp = "{}: {}".format(timestamp, text)
            print(message_with_timestamp)
        else:
            # Split the message into lines if it's longer than 50 characters
            if len(text) > self.text_message_wrap:
                lines = [text[i:i+self.text_message_wrap] for i in range(0, len(text), self.text_message_wrap)]

                # Prepend timestamp to each line
                lines = ["{}: {}".format(timestamp, line) for line in reversed(lines)]
            else:
                lines = ["{}: {}".format(timestamp, text)]

            # Insert new messages at the beginning of the list
            self.last_messages = lines + self.last_messages

            # Trim the list to keep only the last `msg_lines` messages
            self.last_messages = self.last_messages[:self.msg_lines]
    def print_line(self, char="=", text=None):
        if text:
            pad = char * ((self.text_message_wrap-2 - len(text)) // 2)
            line = f"{pad} {text} {pad}"
        else:
            line = char*(self.text_message_wrap-2)
        self.print(line)

    def print_banner(self, text, char="=", title=None):
        if title:
            title = title.upper()
        self.print_line(char, title)
        self.print(text)
        self.print_line(char)

    def request_input(self, prompt):
        with self.input_lock:
            if self.input_prompt == None:
                self.input_prompt = prompt
                if args.basic_output:
                    self.print_line()
                    self.print(self.input_prompt)
                    self.print_line()
                return True
        return False
    
    def get_input(self, prompt):
        with self.input_lock:
            if prompt != self.input_prompt:
                return False
            if self.user_response:
                return_input = self.user_response
                self.user_input = ""
                self.user_response = None
                self.input_prompt = None
                return return_input
            return False
    
    def put_response(self, response):
        with self.input_lock:
            self.user_response = response


    def set_status(self, index, text):
        with self.status_lock:
            self.status[index] = text

    def set_verbose(self, level):
        self.verbose = level
        self.print("Verbose level set to "+str(level))

    def update_statuses(self):
        self.status[0] = str(conn.conn_status.var)
        for i in range(1,self.channel_count+1):
            text = str(conn.channel_status.var[i][0])
            text += " | S:"+str(len(conn.send_buffer.var[i].buffer))
           # text += " Resend: "+str(conn.resend_queue.var[i].qsize())
            text += " R:"+str(len(conn.recv_buffer.var[i]))
            text += " |" 
            text += " S:"+str(conn.seq.var[i])
            text += " A:"+str(conn.ack.var[i])
            text += " P:"+str(conn.peer_ack.var[i])
           # text += " Resend: "+str(len(conn.resend.var[i]))
           # text += " Missing: "+str(len(conn.missing.var[i]))

            self.status[i]= text
    def update_video_stream_stats(self):
        if time.time() > self.video_stream_stats_update_time:
            self.video_stream_stats = conn.videoStream.stats.get()
            self.video_stream_stats_update_time = time.time()+2



def check_terminal_size():
    width, height = shutil.get_terminal_size()

    # Check if the terminal size is too small
    if height < 35 or width < 100:  # Adjust the minimum size as needed
        return False
    return True


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Stegostream endpoint to connect to a peer and send data over video stream')
    parser.add_argument('--basic_output', action='store_true', help='Run with basic output')  
    parser.add_argument('--debug', type=int, default=0, help='Debug mode 1 or 2')
    parser.add_argument('--simulate_packet_loss', type=int, default=0, help='Simulate packet loss, specify a percentage to randomly drop')
    args = parser.parse_args()

    msg = AppMessages()
    shared_input = lib.lockvar.LockVar({"id":None, "prompt":None, "response":None})
    videoStream = lib.videostream.VideoStream(config.RECV_VIDEO_URL,lib.stegocodecs.rgb_grid.Codec,msg,args)
    conn = lib.peerconnection.PeerConnection(videoStream, shared_input,msg,args)

    if args.basic_output:
        purge_temp_files()
        main()
    else:
        if check_terminal_size() == False:
            sys.exit("Terminal window is not large enough, make it bigger or use --basic_output")
        os.system('clear')
        purge_temp_files()
        curses.wrapper(curses_main)
    







