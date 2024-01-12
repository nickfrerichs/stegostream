# Stegostream
Connect and send data between two parties sharing live video streams.
.

## Usage instructions


#### Print help
```bash
python3 stegostream_endpoint.py -h
```

#### Start the endpoint on both peers
This just starts the program, everything will be idle at start. No streams are established.
```bash
python3 stegostream_endpoint (use --basic_output to troubleshoot)
```

#### Init with nonce
Initialization starts with sending images to the configured video stream (blank payload with the configured nonce). A thread is immediately created to listen for the peers video. Both have a timeout period.
The nonce helps to make sure the peers match, both peers must use the same nonce value
```bash
init <0-255>
```

#### Connect to peer
Once video streams are established (you will see a message indicating so), data is being sent between both peers and passing CRC checks. Next a connection can begin in order to buffer data and ensure ordered and reliable delivery.
```bash
connect
```
A 3 way handshake will occur, it can take a minute or so depending on the video quality and configured fps

#### Send a text message to peer
Text messages are prioritized over file transfer chunks to ensure timely delivery.
```bash
text_message <enter text message>
```

#### Send a file to peer
A file send request will be sent to the peer. The peer will be prompted to specify a location to save the file. Then a ACK will be sent back to signal the file transfer to begin.
Files are split into segments which are compressed, then compressed data is split into chunks for transmission. Expect low bandwidth!
```bash
send_file <file_path>
```

#### Check status of things
This dumps out some raw data useful for troubleshooting
```bash
status
```

#### Verbose
If you want a quieter experience, set verbose to 0.
```bash
verbose <0 or 1>
```

## Installation instructions

### Ubuntu 22.04
- sudo apt install ffmpeg python3-pip python3-venv
- python3 -m venv env
- source env/bin/activate
- pip install -r requirements.txt

- cp config-example.json config.json
  - Edit config.json
    - SEND_VIDEO_URL - RTMP destination for outgoing video stream to be sent to peer
    - RECV_VIDEO_URL - Peer's incoming video source URL
- Set up a second peer just like this one to send data between them, you will need to send video to an intermediary like YouTube, or set up your own RTMP server


### (Optional) set up your own RTMP server to stream video between peers
- Ubuntu 22.04
- sudo apt install ffmpeg nginx libnginx-mod-rtmp
- sudo systemctl start nginx
- sudo systemctl enable nginx
- sudo nano /etc/nginx/nginx.conf
```
rtmp {
    server {
        listen 1935;
        chunk_size 4000;

        application live {
            live on;
            record off;

            # Specify the stream and its settings
            exec ffmpeg -i rtmp://localhost/live/$name -c:v libx264 -b:v 500k -c:a aac -strict -2 -f flv rtmp://localhost/live/stream;
        }
    }
}
```
- sudo systemctl restart nginx
- You can now write video to the stream at any key you wish and use a video player like VLC to view the live stream at rtmp://HOSTNAME/live/KEY


## What is working
- Data link via RTMP stream by both peers, including YouTube live streams
  - Transfers binary data encoded by an stego encoder, currently a basic RGB grid with no cover image
- Basics of a "TCP-like" connection
  - Three way handshake
  - Sequence numbers with receive buffer
  - Two channels, can send text messages while files are transferring:
    - 1 - text messages to peer
    - 2 - send files to peer


#### Known issues/limitations to be addressed
- Almost no graceful error handling (use --basic_output if something goes wrong)
- No error checking on path typed by peer receiving file, type carefully
- Channel 0 (maintenance channel) does not recover from missing packets. (therefore --simulate_packet_loss flag does not effect this channel)
- Stats may not be accurate, need to revisit
