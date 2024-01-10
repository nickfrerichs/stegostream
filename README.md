# Stegostream
Connect and send data between two parties sharing live video streams. This is an early attempt at the concept of using video steganography as a medium to make a live connection between two peers.

This is just experimenting with an idea, not intended to be useful.

## Usage instructions
### Installation (Ubuntu 22.04)
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


#### Working
- Data link via YouTube live streams by both peers
  - Transfers binary data encoded by an stego encoder, currently a basic RGB grid with no cover image
- Basics of a "TCP-like" connection
  - Three way handshake
  - Sequence numbers with receive buffer
